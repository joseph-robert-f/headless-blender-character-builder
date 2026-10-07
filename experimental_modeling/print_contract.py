# SPDX-License-Identifier: GPL-3.0-or-later
"""Provisional, offline contract for the anime-cat print experiment.

This module does not enable the controller's reserved ``profile=print``. The
geometry input must come from an independent reimport of the final STL, not
from the source scene or a low-resolution construction mesh.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import MAX_JSON
from .platform_io import safe_path


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISIONS = ("r0", "r1", "r2")
_PROFILE_JSON = '''{"schema_version":1,"profile_id":"anime-cat-fdm-provisional-v1",
"status":"provisional","source_unit":"meter","source_scale_length":1.0,
"export_unit":"millimeter","reference_height_m":3.15,"reference_height_mm":100.0,
"revision_heights_mm":{"r0":92.2,"r1":100.0,"r2":92.2},
"height_tolerance_mm":1.5,"maximum_dimension_mm":120.0,
"nozzle_diameter_mm":0.4,"layer_height_mm":0.2,"material":"PLA",
"minimum_feature_mm":1.35,"maximum_triangles":500000}'''
_PROFILE_CANONICAL = json.dumps(json.loads(_PROFILE_JSON), sort_keys=True,
                                separators=(",", ":"), allow_nan=False).encode("utf-8")
DEFAULT_PROFILE_ID = "anime-cat-fdm-provisional-v1"
X1C_PROFILE_ID = "anime-cat-x1c-pla-04-bare100-v2"
X1C_BAMBU_PROFILE_ID = "anime-cat-x1c-pla-04-bare100-v3"
# Frozen against the repaired dd5c8b4 bare-cat geometry, never a fresh revision's
# bounds. This modeling policy is separate from Bambu's machine/process presets.
BARE_REFERENCE_MM = 92.1265640258789
X1C_FINAL_SCALE = 100.0 / BARE_REFERENCE_MM
_X1C_CANONICAL = json.dumps(json.loads(_PROFILE_JSON) | {
    "profile_id": X1C_PROFILE_ID,
    "reference_height_m": 2.901986766815185,
    "revision_heights_mm": {"r0": 100.0, "r1": 108.54632543541882, "r2": 100.0},
}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
_X1C_BAMBU_CANONICAL = json.dumps(json.loads(_X1C_CANONICAL) | {"profile_id": X1C_BAMBU_PROFILE_ID},
    sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
_REVIEWED_PROFILES = {DEFAULT_PROFILE_ID: _PROFILE_CANONICAL, X1C_PROFILE_ID: _X1C_CANONICAL,
                      X1C_BAMBU_PROFILE_ID: _X1C_BAMBU_CANONICAL}
_CHECKS = {"self_intersections", "feature_coverage", "roundtrip_surface", "protected_regions", "visual_fidelity"}
_PROFILE_FIELDS = {
    "schema_version", "profile_id", "status", "source_unit", "export_unit",
    "reference_height_m", "reference_height_mm", "revision_heights_mm",
    "height_tolerance_mm", "maximum_dimension_mm", "nozzle_diameter_mm",
    "layer_height_mm", "material", "minimum_feature_mm", "maximum_triangles", "source_scale_length",
}
_EVIDENCE_FIELDS = {
    "schema_version", "profile_sha256", "revision", "measurement_source", "units",
    "stl_sha256", "source_observation_sha256", "triangle_count", "connected_shells",
    "boundary_edges", "nonmanifold_edges", "noncontiguous_edges",
    "degenerate_triangles", "signed_volume_mm3", "bounds_min_mm", "bounds_max_mm",
    "measured_minimum_feature_mm", "feature_sample_count", "checks",
    "evaluated_triangle_count", "measured_triangle_count", "evaluated_mesh_sha256",
    "observer_sha256", "derivation_sha256", "nonmanifold_vertices", "loose_vertices",
}


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} exceeds its permitted range") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} is outside its permitted range")
    return result


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in range")
    return value


def _digest(raw: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate print profile field: " + key)
        result[key] = value
    return result


@dataclass(frozen=True)
class PrintProfile:
    """Fixed scale and provisional FDM design limits for all three revisions."""

    _json: bytes

    def __post_init__(self) -> None:
        if type(self._json) is not bytes or self._json not in _REVIEWED_PROFILES.values():
            raise ValueError("Only the reviewed canonical profile is supported")

    @property
    def raw(self) -> dict[str, Any]:
        """Return a fresh copy; mutation cannot change the reviewed profile."""
        return json.loads(self._json)

    @classmethod
    def load(cls, path: Path) -> "PrintProfile":
        path = safe_path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
            raise ValueError("JSON must be a bounded regular non-symlink file")
        with path.open("rb") as stream:
            data = stream.read(MAX_JSON + 1)
        if len(data) > MAX_JSON:
            raise ValueError("JSON must be bounded")
        return cls.parse(json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields,
                                    parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))))

    @classmethod
    def parse(cls, raw: Any) -> "PrintProfile":
        if not isinstance(raw, dict) or set(raw) != _PROFILE_FIELDS:
            raise ValueError("print profile fields mismatch")
        if raw["schema_version"] != 1 or type(raw["schema_version"]) is not int:
            raise ValueError("unsupported print profile version")
        if (not isinstance(raw["profile_id"], str) or raw["profile_id"] not in _REVIEWED_PROFILES
                or raw["status"] != "provisional"):
            raise ValueError("unknown print profile or status")
        canonical = _REVIEWED_PROFILES[raw["profile_id"]]
        expected = json.loads(canonical)
        if (raw["source_unit"], raw["export_unit"], raw["material"]) != ("meter", "millimeter", "PLA"):
            raise ValueError("unexpected print profile units or material")
        _number(raw["source_scale_length"], "source_scale_length", 1, 1)
        source_height = _number(raw["reference_height_m"], "reference_height_m", 0.1, 10)
        target_height = _number(raw["reference_height_mm"], "reference_height_mm", 10, 300)
        heights = raw["revision_heights_mm"]
        if not isinstance(heights, dict) or set(heights) != set(_REVISIONS):
            raise ValueError("revision height targets mismatch")
        for revision in _REVISIONS:
            _number(heights[revision], revision + " height", 10,
                    max(expected["revision_heights_mm"].values()))
        reference_revision = "r1" if raw["profile_id"] == DEFAULT_PROFILE_ID else "r0"
        if heights[reference_revision] != target_height or heights["r0"] != heights["r2"]:
            raise ValueError("shared scale and accessory height targets mismatch")
        tolerance = _number(raw["height_tolerance_mm"], "height_tolerance_mm", 0.01, 5)
        maximum = _number(raw["maximum_dimension_mm"], "maximum_dimension_mm", target_height, 300)
        nozzle = _number(raw["nozzle_diameter_mm"], "nozzle_diameter_mm", 0.2, 1.2)
        _number(raw["layer_height_mm"], "layer_height_mm", 0.05, nozzle * 0.8)
        _number(raw["minimum_feature_mm"], "minimum_feature_mm", nozzle, 10)
        _integer(raw["maximum_triangles"], "maximum_triangles", 1000, 2_000_000)
        if source_height * target_height * tolerance * maximum <= 0:
            raise ValueError("invalid print dimensions")
        if raw != expected:
            raise ValueError("Preset changes require a new reviewed profile version")
        return cls(canonical)

    @property
    def profile_id(self) -> str:
        return self.raw["profile_id"]

    @property
    def fixture_name(self) -> str:
        return {DEFAULT_PROFILE_ID:"provisional_fdm_v1.json", X1C_PROFILE_ID:"x1c_pla_bare100_v2.json",
                X1C_BAMBU_PROFILE_ID:"x1c_pla_bare100_v3.json"}[self.profile_id]

    @property
    def author_entry(self) -> str:
        return {DEFAULT_PROFILE_ID:"builder.py", X1C_PROFILE_ID:"builder_x1c.py",
                X1C_BAMBU_PROFILE_ID:"builder_x1c_v3.py"}[self.profile_id]

    @property
    def derivation_entry(self) -> str:
        return {DEFAULT_PROFILE_ID:"solids.py", X1C_PROFILE_ID:"x1c_solids.py",
                X1C_BAMBU_PROFILE_ID:"x1c_bambu_solids.py"}[self.profile_id]

    @property
    def final_scale(self) -> float:
        return 1.0 if self.profile_id == DEFAULT_PROFILE_ID else X1C_FINAL_SCALE

    @classmethod
    def reviewed(cls, profile_id: str = DEFAULT_PROFILE_ID) -> "PrintProfile":
        if not isinstance(profile_id, str) or profile_id not in _REVIEWED_PROFILES:
            raise ValueError("unknown print profile")
        return cls(_REVIEWED_PROFILES[profile_id])

    @property
    def mm_per_source_meter(self) -> float:
        return self.raw["reference_height_mm"] / self.raw["reference_height_m"]

    @property
    def sha256(self) -> str:
        return _digest(self.raw)


def assess_final_stl(profile: PrintProfile, evidence: Any) -> dict[str, Any]:
    """Assess bounded measurements of the *reimported final STL*.

    A caller must independently measure the STL and verify its SHA-256. This
    function only checks that report against the contract; it cannot prove
    the origin of a caller-supplied dictionary or physical print success.
    Every result is ineligible for promotion until a trusted observer and
    preservation gate are connected to the controller in a later sprint.
    """
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_FIELDS:
        raise ValueError("final STL evidence fields mismatch")
    if evidence["schema_version"] != 1 or type(evidence["schema_version"]) is not int:
        raise ValueError("unsupported print evidence version")
    if not isinstance(evidence["revision"], str) or evidence["revision"] not in _REVISIONS:
        raise ValueError("unknown print revision")
    if evidence["measurement_source"] != "reimported_final_stl" or evidence["units"] != "millimeter":
        raise ValueError("measure final STL geometry in millimeters")
    for key in ("profile_sha256", "stl_sha256", "source_observation_sha256",
                "evaluated_mesh_sha256", "observer_sha256", "derivation_sha256"):
        if not isinstance(evidence[key], str) or not _SHA256.fullmatch(evidence[key]):
            raise ValueError("invalid " + key)
    if evidence["profile_sha256"] != profile.sha256:
        raise ValueError("print evidence uses a different profile")

    for key in ("triangle_count", "connected_shells", "boundary_edges", "nonmanifold_edges",
                "noncontiguous_edges", "degenerate_triangles", "feature_sample_count",
                "evaluated_triangle_count", "measured_triangle_count",
                "nonmanifold_vertices", "loose_vertices"):
        _integer(evidence[key], key, 0, 10_000_000)
    _number(evidence["signed_volume_mm3"], "signed_volume_mm3", -1e9, 1e9)
    _number(evidence["measured_minimum_feature_mm"], "measured_minimum_feature_mm", 0, 300)
    for key in ("bounds_min_mm", "bounds_max_mm"):
        bounds = evidence[key]
        if not isinstance(bounds, list) or len(bounds) != 3:
            raise ValueError(key + " must be a three-vector")
        for coordinate in bounds:
            _number(coordinate, key, -1000, 1000)

    checks = evidence["checks"]
    if not isinstance(checks, dict) or set(checks) != _CHECKS:
        raise ValueError("final STL checks mismatch")
    if any(not isinstance(value, str) or value not in ("passed", "failed", "unknown")
           for value in checks.values()):
        raise ValueError("invalid final STL check status")
    dimensions = [hi - lo for lo, hi in zip(evidence["bounds_min_mm"], evidence["bounds_max_mm"])]
    failures = []
    if not 4 <= evidence["triangle_count"] <= profile.raw["maximum_triangles"]:
        failures.append("triangle_budget")
    if (evidence["evaluated_triangle_count"] != evidence["triangle_count"] or
            evidence["measured_triangle_count"] != evidence["triangle_count"]):
        failures.append("complete_final_geometry")
    if evidence["connected_shells"] != 1:
        failures.append("connected_shells")
    for key in ("boundary_edges", "nonmanifold_edges", "noncontiguous_edges", "degenerate_triangles",
                "nonmanifold_vertices", "loose_vertices"):
        if evidence[key] != 0:
            failures.append(key)
    if evidence["signed_volume_mm3"] <= 0:
        failures.append("positive_volume")
    if any(not 0 < length <= profile.raw["maximum_dimension_mm"] for length in dimensions):
        failures.append("dimensions_mm")
    if abs(dimensions[2] - profile.raw["revision_heights_mm"][evidence["revision"]]) > profile.raw["height_tolerance_mm"]:
        failures.append("fixed_scale_height")
    if abs(evidence["bounds_min_mm"][2]) > 0.25:
        failures.append("ground_z_mm")
    if (evidence["feature_sample_count"] == 0 or
            evidence["measured_minimum_feature_mm"] < profile.raw["minimum_feature_mm"]):
        failures.append("minimum_feature_mm")
    failures.extend(sorted(key for key, value in checks.items() if value == "failed"))
    unknowns = sorted(key for key, value in checks.items() if value == "unknown")
    return {
        "schema_version": 1, "revision": evidence["revision"],
        "measurement_gate": "rejected" if failures else "needs_review" if unknowns else "passed",
        "failures": failures, "unknowns": unknowns, "dimensions_mm": dimensions,
        "profile_sha256": profile.sha256, "evidence_sha256": _digest(evidence),
        "promotion_eligible": False, "physical_validation": "pending",
    }
