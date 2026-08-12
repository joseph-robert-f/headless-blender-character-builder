"""Bounded caller-safe diagnostics for non-passing geometry QA.

The full QA report is private until a build passes.  Failure output therefore
uses only fixed, allowlisted phrases derived from the validated report.  It
never reflects request values, filesystem paths, QA notes, or verifier output.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Sequence, Tuple

from shared.quality_report import (
    CHECK_FIELDS,
    MEASUREMENT_FIELDS,
    QualityReport,
    dimensions_within_reimport_tolerance,
    value_within_geometry_tolerance,
)


MAX_FAILURE_DETAILS = 6
MAX_FAILURE_SUMMARY_CHARACTERS = 512
SAFE_DIAGNOSTIC_PREFIX = "safe diagnostics: "

_UNKNOWN_MEASUREMENTS: Tuple[Tuple[str, str], ...] = (
    ("requested_height_mm", "requested-height evidence unavailable"),
    ("dimensions_mm", "evaluated geometry bounds unavailable"),
    ("glb_dimensions_mm", "GLB bounds unavailable"),
    ("stl_dimensions_mm", "STL bounds unavailable"),
    ("triangle_count", "triangle-count evidence unavailable"),
    ("object_count", "object-count evidence unavailable"),
    ("material_count", "material-count evidence unavailable"),
    ("non_manifold_edges", "manifold-edge evidence unavailable"),
    ("zero_area_faces", "zero-area-face evidence unavailable"),
    ("minimum_wall_mm", "minimum wall measurement unavailable"),
    ("minimum_feature_mm", "minimum feature measurement unavailable"),
    ("connected_shells", "connected-shell evidence unavailable"),
)
_UNKNOWN_CHECKS: Tuple[Tuple[str, str], ...] = (
    ("manifold", "manifold check unavailable"),
    ("finite_geometry", "finite-geometry check unavailable"),
    ("outward_normals", "normal-direction check unavailable"),
    ("positive_volume", "positive-volume check unavailable"),
    ("height_within_tolerance", "height-tolerance check unavailable"),
    ("fresh_reload", "fresh Blender reload check unavailable"),
    ("glb_reimport", "GLB reimport check unavailable"),
    ("stl_reimport", "STL reimport check unavailable"),
)
_FAILED_CHECKS: Tuple[Tuple[str, str], ...] = (
    ("manifold", "manifold check failed"),
    ("finite_geometry", "geometry contains non-finite coordinates"),
    ("outward_normals", "face normals are not consistently outward"),
    ("positive_volume", "printable volume is not positive"),
    ("height_within_tolerance", "evaluated height is outside tolerance"),
    ("fresh_reload", "saved Blender file failed fresh reload"),
    ("glb_reimport", "GLB failed fresh-process reimport"),
    ("stl_reimport", "STL failed fresh-process reimport"),
)


if tuple(field for field, _ in _UNKNOWN_MEASUREMENTS) != MEASUREMENT_FIELDS:
    raise RuntimeError("QA failure-summary measurement allowlist is out of date")
if tuple(field for field, _ in _UNKNOWN_CHECKS) != CHECK_FIELDS:
    raise RuntimeError("QA failure-summary check allowlist is out of date")
if tuple(field for field, _ in _FAILED_CHECKS) != CHECK_FIELDS:
    raise RuntimeError("QA failure-summary failed-check allowlist is out of date")


def _bounded_summary(reasons: Sequence[str]) -> str:
    selected = list(reasons[:MAX_FAILURE_DETAILS])
    if not selected:
        selected.append("mandatory geometry evidence did not pass")
    if len(reasons) > MAX_FAILURE_DETAILS:
        selected.append("additional mandatory checks did not pass")
    summary = SAFE_DIAGNOSTIC_PREFIX + "; ".join(selected)

    # All reasons above are fixed literals.  Keep a fail-safe fallback anyway so
    # a future wording change cannot turn the diagnostic boundary into unbounded
    # or non-printable output.
    if len(summary) > MAX_FAILURE_SUMMARY_CHARACTERS or any(
        ord(character) < 32 or ord(character) > 126 for character in summary
    ):
        return SAFE_DIAGNOSTIC_PREFIX + "mandatory geometry QA did not pass"
    return summary


def geometry_qa_failure_summary(quality: QualityReport) -> str:
    """Return a deterministic safe summary for a validated non-passing report."""

    if quality.status == "passed":
        raise ValueError("a passing QA report has no failure summary")

    if quality.status == "needs_review":
        unknown = [
            phrase
            for field, phrase in _UNKNOWN_MEASUREMENTS
            if quality.measurements[field] is None
        ]
        unknown.extend(
            phrase for field, phrase in _UNKNOWN_CHECKS if quality.checks[field] is None
        )
        return _bounded_summary(unknown)

    if quality.status != "failed":
        raise ValueError("unsupported QA status")

    measurements = quality.measurements
    checks = quality.checks
    failures: List[str] = [
        phrase for field, phrase in _FAILED_CHECKS if checks[field] is False
    ]

    dimensions = measurements["dimensions_mm"]
    glb_dimensions = measurements["glb_dimensions_mm"]
    stl_dimensions = measurements["stl_dimensions_mm"]
    requested_height = measurements["requested_height_mm"]

    # A failed report cannot contain unknown evidence, as enforced by
    # QualityReport.  The guards keep this boundary fail-closed if that invariant
    # is ever weakened without reflecting any unexpected value.
    if dimensions is not None and glb_dimensions is not None:
        if not dimensions_within_reimport_tolerance(dimensions, glb_dimensions):
            failures.append("GLB bounds differ from evaluated geometry")
    if dimensions is not None and stl_dimensions is not None:
        if not dimensions_within_reimport_tolerance(dimensions, stl_dimensions):
            failures.append("STL bounds differ from evaluated geometry")
    if dimensions is not None and requested_height is not None:
        if checks["height_within_tolerance"] is not False and not value_within_geometry_tolerance(
            requested_height, dimensions[2]
        ):
            failures.append("evaluated height differs from requested height")

    triangle_count = measurements["triangle_count"]
    if triangle_count is not None and not 4 <= triangle_count <= 500_000:
        failures.append("triangle count is outside the supported range")
    object_count = measurements["object_count"]
    if object_count is not None and not 1 <= object_count <= 256:
        failures.append("object count is outside the supported range")
    material_count = measurements["material_count"]
    if material_count is not None and not 1 <= material_count <= 64:
        failures.append("material count is outside the supported range")

    non_manifold_edges = measurements["non_manifold_edges"]
    if checks["manifold"] is not False and non_manifold_edges not in (None, 0):
        failures.append("non-manifold edges were found")
    zero_area_faces = measurements["zero_area_faces"]
    if zero_area_faces not in (None, 0):
        failures.append("zero-area faces were found")

    minimum_wall = measurements["minimum_wall_mm"]
    if minimum_wall is not None and minimum_wall < Decimal("1.2"):
        failures.append("minimum wall is below the 1.2 mm requirement")
    minimum_feature = measurements["minimum_feature_mm"]
    if minimum_feature is not None and minimum_feature < Decimal("2.0"):
        failures.append("minimum feature is below the 2.0 mm requirement")
    connected_shells = measurements["connected_shells"]
    if connected_shells is not None and connected_shells != 1:
        failures.append("printable mesh does not contain exactly one connected shell")

    return _bounded_summary(failures)


__all__ = [
    "MAX_FAILURE_DETAILS",
    "MAX_FAILURE_SUMMARY_CHARACTERS",
    "SAFE_DIAGNOSTIC_PREFIX",
    "geometry_qa_failure_summary",
]
