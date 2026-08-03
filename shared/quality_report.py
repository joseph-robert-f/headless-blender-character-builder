"""QA v1 validation and terminal-state mapping.

Mandatory checks may be ``null`` only when they genuinely cannot be measured.
Any such unknown maps to ``needs_review``.  Both ``failed`` and
``needs_review`` map to application exit 11 and prohibit publication of a
success manifest; only ``passed`` maps to ``succeeded`` and permits one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple, Union

from .json_contract import (
    ContractValidationError,
    bounded_decimal_value,
    canonical_json_bytes,
    decode_json_document,
    reject_extra_fields,
    require_fields,
    require_object,
)


QA_VERSION = "qa/v1"
QA_STATUSES = ("passed", "failed", "needs_review")

MEASUREMENT_FIELDS = (
    "requested_height_mm",
    "dimensions_mm",
    "glb_dimensions_mm",
    "stl_dimensions_mm",
    "triangle_count",
    "object_count",
    "material_count",
    "non_manifold_edges",
    "zero_area_faces",
    "minimum_wall_mm",
    "minimum_feature_mm",
    "connected_shells",
)
CHECK_FIELDS = (
    "manifold",
    "finite_geometry",
    "outward_normals",
    "positive_volume",
    "height_within_tolerance",
    "fresh_reload",
    "glb_reimport",
    "stl_reimport",
)

QA_STATUS_BUILD_MAPPING = MappingProxyType({
    "passed": MappingProxyType({
        "build_status": "succeeded",
        "exit_code": 0,
        "publish_success_manifest": True,
        "note": "All mandatory geometry-v1 evidence is measurable and passes.",
    }),
    "failed": MappingProxyType({
        "build_status": "failed",
        "exit_code": 11,
        "publish_success_manifest": False,
        "note": "A mandatory measurable check failed; keep partial output private.",
    }),
    "needs_review": MappingProxyType({
        "build_status": "needs_review",
        "exit_code": 11,
        "publish_success_manifest": False,
        "note": "Mandatory evidence is unmeasurable; no success manifest may be published.",
    }),
})


def dimensions_within_reimport_tolerance(
    evaluated: Tuple[Decimal, Decimal, Decimal],
    reimported: Tuple[Decimal, Decimal, Decimal],
) -> bool:
    """Apply Section 8's per-axis max(0.2 mm, 0.5%) tolerance."""

    for expected, observed in zip(evaluated, reimported):
        tolerance = max(Decimal("0.2"), abs(expected) * Decimal("0.005"))
        if abs(observed - expected) > tolerance:
            return False
    return True


def value_within_geometry_tolerance(expected: Decimal, observed: Decimal) -> bool:
    tolerance = max(Decimal("0.2"), abs(expected) * Decimal("0.005"))
    return abs(observed - expected) <= tolerance


def _nullable_decimal(
    value: Any, path: str, minimum: Decimal, maximum: Decimal
) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ContractValidationError("expected_number", "value must be a number or null", path)
    result = bounded_decimal_value(value, path)
    if result < minimum or result > maximum:
        raise ContractValidationError(
            "number_out_of_range", f"number must be between {minimum} and {maximum}", path
        )
    return result


def _nullable_int(value: Any, path: str, minimum: int, maximum: int) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ContractValidationError("expected_integer", "value must be an integer or null", path)
    number = bounded_decimal_value(value, path)
    if number != number.to_integral_value():
        raise ContractValidationError("expected_integer", "value must be an integer or null", path)
    integer = int(number)
    if integer < minimum or integer > maximum:
        raise ContractValidationError(
            "integer_out_of_range", f"integer must be between {minimum} and {maximum}", path
        )
    return integer


def _nullable_bool(value: Any, path: str) -> Optional[bool]:
    if value is None or isinstance(value, bool):
        return value
    raise ContractValidationError("expected_boolean", "value must be a boolean or null", path)


def _dimensions(value: Any, path: str) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 3:
        raise ContractValidationError(
            "invalid_dimensions", "dimensions must be a three-number array or null", path
        )
    dimensions = tuple(
        _nullable_decimal(item, f"{path}[{index}]", Decimal("0.001"), Decimal("1000"))
        for index, item in enumerate(value)
    )
    if any(item is None for item in dimensions):
        raise ContractValidationError(
            "invalid_dimensions",
            "a dimensions array cannot contain null coordinates; use null for the whole measurement",
            path,
        )
    return dimensions  # type: ignore[return-value]


def derive_qa_status(measurements: Mapping[str, Any], checks: Mapping[str, Any]) -> str:
    """Derive the only permitted QA status from validated evidence.

    Unknown mandatory evidence takes precedence and always yields
    ``needs_review``.  This ensures a failed check cannot accidentally conceal an
    unmeasurable print-safety criterion behind an ordinary failure state.
    """

    if any(measurements.get(key) is None for key in MEASUREMENT_FIELDS):
        return "needs_review"
    if any(checks.get(key) is None for key in CHECK_FIELDS):
        return "needs_review"

    assert measurements["triangle_count"] is not None
    assert measurements["object_count"] is not None
    assert measurements["material_count"] is not None
    assert measurements["non_manifold_edges"] is not None
    assert measurements["zero_area_faces"] is not None
    assert measurements["minimum_wall_mm"] is not None
    assert measurements["minimum_feature_mm"] is not None
    assert measurements["connected_shells"] is not None
    assert measurements["requested_height_mm"] is not None
    assert measurements["dimensions_mm"] is not None
    assert measurements["glb_dimensions_mm"] is not None
    assert measurements["stl_dimensions_mm"] is not None

    failed = (
        any(checks[key] is False for key in CHECK_FIELDS)
        or not dimensions_within_reimport_tolerance(
            measurements["dimensions_mm"], measurements["glb_dimensions_mm"]
        )
        or not dimensions_within_reimport_tolerance(
            measurements["dimensions_mm"], measurements["stl_dimensions_mm"]
        )
        or not value_within_geometry_tolerance(
            measurements["requested_height_mm"], measurements["dimensions_mm"][2]
        )
        or measurements["triangle_count"] > 500_000
        # Four triangles are the smallest possible closed triangular shell.
        or measurements["triangle_count"] < 4
        or measurements["object_count"] > 256
        or measurements["object_count"] < 1
        or measurements["material_count"] > 64
        or measurements["material_count"] < 1
        or measurements["non_manifold_edges"] != 0
        or measurements["zero_area_faces"] != 0
        or measurements["minimum_wall_mm"] < Decimal("1.2")
        or measurements["minimum_feature_mm"] < Decimal("2.0")
        or measurements["connected_shells"] != 1
    )
    return "failed" if failed else "passed"


@dataclass(frozen=True)
class QualityReport:
    qa_version: str
    status: str
    measurements: Mapping[str, Any]
    checks: Mapping[str, Optional[bool]]
    notes: Tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Any) -> "QualityReport":
        value = require_object(raw, "$")
        fields = ("qa_version", "status", "measurements", "checks", "notes")
        reject_extra_fields(value, fields, "$")
        require_fields(value, fields, "$")
        if value["qa_version"] != QA_VERSION:
            raise ContractValidationError(
                "unsupported_version", f"qa_version must be {QA_VERSION!r}", "$.qa_version"
            )
        status = value["status"]
        if status not in QA_STATUSES:
            raise ContractValidationError(
                "invalid_enum", "status must be passed, failed, or needs_review", "$.status"
            )

        measurements_raw = require_object(value["measurements"], "$.measurements")
        reject_extra_fields(measurements_raw, MEASUREMENT_FIELDS, "$.measurements")
        require_fields(measurements_raw, MEASUREMENT_FIELDS, "$.measurements")
        measurements = {
            "requested_height_mm": _nullable_decimal(measurements_raw["requested_height_mm"], "$.measurements.requested_height_mm", Decimal("25"), Decimal("250")),
            "dimensions_mm": _dimensions(measurements_raw["dimensions_mm"], "$.measurements.dimensions_mm"),
            "glb_dimensions_mm": _dimensions(measurements_raw["glb_dimensions_mm"], "$.measurements.glb_dimensions_mm"),
            "stl_dimensions_mm": _dimensions(measurements_raw["stl_dimensions_mm"], "$.measurements.stl_dimensions_mm"),
            "triangle_count": _nullable_int(measurements_raw["triangle_count"], "$.measurements.triangle_count", 0, 10_000_000),
            "object_count": _nullable_int(measurements_raw["object_count"], "$.measurements.object_count", 0, 10_000),
            "material_count": _nullable_int(measurements_raw["material_count"], "$.measurements.material_count", 0, 10_000),
            "non_manifold_edges": _nullable_int(measurements_raw["non_manifold_edges"], "$.measurements.non_manifold_edges", 0, 100_000_000),
            "zero_area_faces": _nullable_int(measurements_raw["zero_area_faces"], "$.measurements.zero_area_faces", 0, 100_000_000),
            "minimum_wall_mm": _nullable_decimal(measurements_raw["minimum_wall_mm"], "$.measurements.minimum_wall_mm", Decimal("0"), Decimal("1000")),
            "minimum_feature_mm": _nullable_decimal(measurements_raw["minimum_feature_mm"], "$.measurements.minimum_feature_mm", Decimal("0"), Decimal("1000")),
            "connected_shells": _nullable_int(measurements_raw["connected_shells"], "$.measurements.connected_shells", 0, 10_000),
        }

        checks_raw = require_object(value["checks"], "$.checks")
        reject_extra_fields(checks_raw, CHECK_FIELDS, "$.checks")
        require_fields(checks_raw, CHECK_FIELDS, "$.checks")
        checks = {
            key: _nullable_bool(checks_raw[key], "$.checks." + key) for key in CHECK_FIELDS
        }

        notes_raw = value["notes"]
        if not isinstance(notes_raw, list) or len(notes_raw) > 32:
            raise ContractValidationError("invalid_notes", "notes must contain at most 32 entries", "$.notes")
        notes = []
        for index, note in enumerate(notes_raw):
            if (
                not isinstance(note, str)
                or not 1 <= len(note) <= 256
                or any(ord(character) < 32 or ord(character) > 126 for character in note)
            ):
                raise ContractValidationError(
                    "invalid_note", "notes must be 1-256 printable ASCII characters", f"$.notes[{index}]"
                )
            notes.append(note)

        derived = derive_qa_status(measurements, checks)
        if status != derived:
            raise ContractValidationError(
                "qa_status_mismatch", f"status must be {derived!r} for the supplied evidence", "$.status"
            )
        if derived == "needs_review" and not notes:
            raise ContractValidationError(
                "review_note_required", "needs_review reports must explain missing evidence", "$.notes"
            )
        return cls(
            QA_VERSION,
            status,
            MappingProxyType(measurements),
            MappingProxyType(checks),
            tuple(notes),
        )

    @classmethod
    def from_json(
        cls, payload: Union[str, bytes, bytearray, memoryview]
    ) -> "QualityReport":
        return cls.from_mapping(decode_json_document(payload))

    def to_dict(self) -> Mapping[str, Any]:
        measurements = dict(self.measurements)
        for field in ("dimensions_mm", "glb_dimensions_mm", "stl_dimensions_mm"):
            if measurements[field] is not None:
                measurements[field] = list(measurements[field])
        return {
            "checks": dict(self.checks),
            "measurements": measurements,
            "notes": list(self.notes),
            "qa_version": self.qa_version,
            "status": self.status,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def build_mapping(self) -> Mapping[str, Any]:
        return QA_STATUS_BUILD_MAPPING[self.status]


def validate_quality_report(
    payload: Union[QualityReport, Mapping[str, Any], str, bytes, bytearray, memoryview]
) -> QualityReport:
    if isinstance(payload, QualityReport):
        return QualityReport.from_mapping(payload.to_dict())
    if isinstance(payload, Mapping):
        return QualityReport.from_mapping(payload)
    return QualityReport.from_json(payload)
