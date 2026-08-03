#!/usr/bin/env python3
"""Outer standard-library gate for the G2 Blender generator milestone.

This module deliberately is not a ``test_*.py`` file: ordinary unittest
discovery must not require Blender.  A caller supplies both the exact Blender
executable and a temporary evidence directory.  The gate starts four isolated
Blender processes (two examples, twice each) and compares only declared stable
structural evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("g2_probe.py")
EXAMPLES = (
    ("facet-bot", ROOT / "examples" / "requests" / "facet-bot.json"),
    ("moss-hopper", ROOT / "examples" / "requests" / "moss-hopper.json"),
)
OUTER_GATE_VERSION = "g2-blender-integration/v1"
INNER_GATE_VERSION = "g2-probe/v1"
REQUIRED_STABLE_KEYS = {
    "base_dimensions",
    "character_topology_totals",
    "engine_report",
    "fixture_role_counts",
    "geometry_signature_sha256",
    "material_assignments",
    "mesh_inventory",
    "object_count",
    "request_sha256",
    "spec_sha256",
    "topology_totals",
    "used_material_count",
}
REQUIRED_CHECK_KEYS = {
    "caps",
    "finite_nonempty_actual_meshes",
    "height_tolerance_mm",
    "observed_height_mm",
    "one_printable_object",
    "printable_topology",
    "required_collections",
    "requested_height_mm",
    "semantic_rejection_before_scene_creation",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BLENDER_VERSION = "4.5.12 LTS"
PATH_LIKE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")


class GateFailure(RuntimeError):
    """A concise integration-gate failure safe to display to the caller."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_blender_path(raw: str) -> Path:
    supplied = Path(raw).expanduser()
    _require(supplied.is_absolute(), "--blender must be an explicit absolute path")
    blender = supplied.resolve()
    _require(blender.is_file(), "--blender does not identify a regular file")
    if os.name != "nt":
        _require(os.access(str(blender), os.X_OK), "--blender is not executable")
    return blender


def _validate_evidence_dir(raw: str) -> Path:
    evidence_dir = Path(raw).expanduser().resolve()
    _require(
        not _is_within(evidence_dir, ROOT),
        "--evidence-dir must be a caller-owned temporary directory outside the workspace",
    )
    if evidence_dir.exists():
        _require(evidence_dir.is_dir(), "--evidence-dir exists but is not a directory")
    else:
        evidence_dir.mkdir(parents=True, exist_ok=False)
    return evidence_dir


def _target_paths(evidence_dir: Path) -> Dict[Tuple[str, int], Path]:
    targets: Dict[Tuple[str, int], Path] = {}
    for slug, _request in EXAMPLES:
        for repeat in (1, 2):
            targets[(slug, repeat)] = evidence_dir / f"{slug}-run-{repeat}.json"
    targets[("summary", 0)] = evidence_dir / "g2-summary.json"
    for path in targets.values():
        _require(not path.exists(), f"refusing to overwrite existing evidence file: {path.name}")
    return targets


def _subprocess_environment() -> Dict[str, str]:
    """Pass only basic OS/runtime state, never arbitrary caller credentials."""

    allowed = (
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _redact_output(text: str, blender: Path, evidence_dir: Path) -> str:
    replacements = (
        (str(evidence_dir), "<evidence-dir>"),
        (str(ROOT), "<workspace>"),
        (str(blender), "<blender>"),
        (str(Path.home()), "<home>"),
        (tempfile.gettempdir(), "<temp>"),
    )
    redacted = text
    for original, replacement in replacements:
        if original:
            redacted = redacted.replace(original, replacement)
    lines = redacted.splitlines()
    return "\n".join(lines[-40:])


def _assert_path_free(value: Any, label: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_path_free(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_path_free(item, f"{label}[{index}]")
    elif isinstance(value, str):
        _require(not PATH_LIKE.match(value), f"{label} contains a local path")
        _require("file://" not in value.lower(), f"{label} contains a file URI")


def _load_probe_result(path: Path, expected_slug: str) -> Dict[str, Any]:
    _require(path.is_file(), f"{expected_slug}: Blender produced no evidence file")
    _require(path.stat().st_size <= 4 * 1024 * 1024, f"{expected_slug}: evidence is unexpectedly large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure(f"{expected_slug}: evidence is not valid UTF-8 JSON") from exc

    _require(isinstance(payload, dict), f"{expected_slug}: probe evidence must be an object")
    expected_top_level = {
        "blender_version",
        "checks",
        "example_slug",
        "gate_version",
        "stable",
        "status",
    }
    _require(set(payload) == expected_top_level, f"{expected_slug}: unexpected probe evidence fields")
    _require(payload["status"] == "passed", f"{expected_slug}: inner probe did not pass")
    _require(payload["gate_version"] == INNER_GATE_VERSION, f"{expected_slug}: inner gate version mismatch")
    _require(payload["example_slug"] == expected_slug, f"{expected_slug}: result slug mismatch")
    _require(
        payload["blender_version"] == BLENDER_VERSION,
        f"{expected_slug}: gate requires Blender {BLENDER_VERSION}",
    )

    checks = payload["checks"]
    _require(isinstance(checks, dict) and set(checks) == REQUIRED_CHECK_KEYS, f"{expected_slug}: invalid checks")
    for check in (
        "caps",
        "finite_nonempty_actual_meshes",
        "one_printable_object",
        "semantic_rejection_before_scene_creation",
    ):
        _require(checks[check] is True, f"{expected_slug}: check failed: {check}")
    _require(checks["printable_topology"] is True, f"{expected_slug}: printable topology failed")
    _require(
        checks["required_collections"]
        == ["CAMERAS", "CHARACTER", "LIGHTS", "PRINT", "SET"],
        f"{expected_slug}: required collection evidence mismatch",
    )
    _require(
        isinstance(checks["height_tolerance_mm"], (int, float))
        and not isinstance(checks["height_tolerance_mm"], bool)
        and checks["height_tolerance_mm"] > 0,
        f"{expected_slug}: invalid height tolerance evidence",
    )
    for field in ("observed_height_mm", "requested_height_mm"):
        _require(
            isinstance(checks[field], (int, float))
            and not isinstance(checks[field], bool)
            and checks[field] > 0,
            f"{expected_slug}: invalid {field}",
        )
    _require(
        abs(checks["observed_height_mm"] - checks["requested_height_mm"])
        <= checks["height_tolerance_mm"],
        f"{expected_slug}: requested height tolerance failed",
    )

    stable = payload["stable"]
    _require(isinstance(stable, dict) and set(stable) == REQUIRED_STABLE_KEYS, f"{expected_slug}: invalid stable fields")
    for field in ("geometry_signature_sha256", "request_sha256", "spec_sha256"):
        _require(
            isinstance(stable[field], str) and SHA256.fullmatch(stable[field]) is not None,
            f"{expected_slug}: invalid {field}",
        )
    engine_report = stable["engine_report"]
    _require(isinstance(engine_report, dict), f"{expected_slug}: invalid engine report")
    fingerprint = engine_report.get("fingerprint_sha256")
    _require(
        isinstance(fingerprint, str) and SHA256.fullmatch(fingerprint) is not None,
        f"{expected_slug}: invalid structural fingerprint",
    )
    printable_report = engine_report.get("printable")
    _require(
        isinstance(printable_report, dict),
        f"{expected_slug}: invalid engine printable report",
    )
    report_topology = printable_report.get("topology")
    _require(
        isinstance(report_topology, dict),
        f"{expected_slug}: invalid engine printable topology report",
    )
    _require(
        report_topology.get("connected_shells") == 1
        and report_topology.get("boundary_edges") == 0
        and report_topology.get("non_manifold_edges") == 0
        and report_topology.get("zero_area_faces") == 0
        and report_topology.get("finite_coordinates") is True
        and report_topology.get("positive_volume") is True,
        f"{expected_slug}: engine report does not prove one closed positive shell",
    )
    base = stable["base_dimensions"]
    _require(isinstance(base, dict), f"{expected_slug}: invalid base dimension evidence")
    _require(
        set(base)
        == {
            "maximum_error_mm",
            "observed_dimensions_mm",
            "preset",
            "requested_dimensions_mm",
        },
        f"{expected_slug}: unexpected base dimension evidence fields",
    )
    _require(
        isinstance(base["maximum_error_mm"], (int, float))
        and not isinstance(base["maximum_error_mm"], bool)
        and 0 <= base["maximum_error_mm"] <= 0.001,
        f"{expected_slug}: base dimension tolerance failed",
    )
    _require(
        isinstance(base["requested_dimensions_mm"], list)
        and len(base["requested_dimensions_mm"]) == 3,
        f"{expected_slug}: invalid requested base dimensions",
    )
    _require(
        base["preset"] in {"none", "round", "square", "hexagonal"},
        f"{expected_slug}: invalid base preset evidence",
    )
    requested_base = base["requested_dimensions_mm"]
    _require(
        all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
            for value in requested_base
        ),
        f"{expected_slug}: nonnumeric requested base dimensions",
    )
    if base["preset"] == "none":
        _require(
            base["observed_dimensions_mm"] is None
            and requested_base == [0.0, 0.0, 0.0],
            f"{expected_slug}: base preset none has observed geometry",
        )
    else:
        observed_base = base["observed_dimensions_mm"]
        _require(
            isinstance(observed_base, list)
            and len(observed_base) == 3
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and value > 0
                for value in observed_base
            ),
            f"{expected_slug}: invalid observed base dimensions",
        )
        recomputed_error = max(
            abs(observed_base[index] - requested_base[index]) for index in range(3)
        )
        _require(
            recomputed_error <= 0.001
            and abs(recomputed_error - base["maximum_error_mm"]) <= 0.000001,
            f"{expected_slug}: base dimension evidence is inconsistent",
        )
    topology = stable["topology_totals"]
    _require(isinstance(topology, dict), f"{expected_slug}: invalid topology totals")
    for field in ("edge_count", "polygon_count", "triangle_count", "vertex_count"):
        _require(
            isinstance(topology.get(field), int) and not isinstance(topology.get(field), bool),
            f"{expected_slug}: invalid topology total {field}",
        )
    _require(4 <= topology["triangle_count"] <= 500_000, f"{expected_slug}: triangle cap violated")
    _require(
        isinstance(stable["object_count"], int) and 1 <= stable["object_count"] <= 256,
        f"{expected_slug}: object cap violated",
    )
    _require(
        isinstance(stable["used_material_count"], int)
        and 1 <= stable["used_material_count"] <= 64,
        f"{expected_slug}: material cap violated",
    )
    _require(isinstance(stable["mesh_inventory"], list) and stable["mesh_inventory"], f"{expected_slug}: empty mesh inventory")
    _require(isinstance(stable["material_assignments"], list) and stable["material_assignments"], f"{expected_slug}: empty material assignments")
    printable_topology = [
        item.get("printable_topology")
        for item in stable["mesh_inventory"]
        if isinstance(item, dict) and "printable_topology" in item
    ]
    _require(len(printable_topology) == 1, f"{expected_slug}: printable topology evidence must be unique")
    shell = printable_topology[0]
    _require(
        shell.get("boundary_edges") == 0
        and shell.get("connected_face_components") == 1
        and shell.get("connected_vertex_components") == 1
        and shell.get("near_zero_faces") == 0
        and shell.get("non_contiguous_edges") == 0
        and shell.get("non_manifold_edges") == 0
        and shell.get("non_manifold_vertices") == 0
        and isinstance(shell.get("signed_volume_mm3"), (int, float))
        and not isinstance(shell.get("signed_volume_mm3"), bool)
        and shell.get("signed_volume_mm3") > 0,
        f"{expected_slug}: invalid printable topology evidence",
    )
    _assert_path_free(payload)
    return payload


def _run_blender(
    blender: Path,
    request_path: Path,
    result_path: Path,
    timeout_seconds: int,
    evidence_dir: Path,
) -> Dict[str, Any]:
    expected_slug = request_path.stem
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(PROBE),
        "--",
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=_subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        detail = _redact_output(output, blender, evidence_dir)
        raise GateFailure(
            f"{expected_slug}: Blender probe timed out\n{detail}".rstrip()
        ) from exc
    except OSError as exc:
        raise GateFailure(
            f"{expected_slug}: could not start Blender: {exc.__class__.__name__}"
        ) from exc

    if completed.returncode != 0:
        detail = _redact_output(completed.stdout, blender, evidence_dir)
        raise GateFailure(
            f"{expected_slug}: Blender probe exited {completed.returncode}\n{detail}".rstrip()
        )
    return _load_probe_result(result_path, expected_slug)


def _compare_repeats(slug: str, first: Mapping[str, Any], second: Mapping[str, Any]) -> None:
    _require(
        first["blender_version"] == second["blender_version"],
        f"{slug}: Blender version changed between fresh processes",
    )
    if first["stable"] != second["stable"]:
        first_stable = first["stable"]
        second_stable = second["stable"]
        changed = sorted(
            key for key in REQUIRED_STABLE_KEYS if first_stable.get(key) != second_stable.get(key)
        )
        raise GateFailure(f"{slug}: repeat-stable fields differ: {', '.join(changed)}")


def _compare_examples(facet: Mapping[str, Any], moss: Mapping[str, Any]) -> None:
    facet_stable = facet["stable"]
    moss_stable = moss["stable"]
    _require(
        facet_stable["engine_report"]["fingerprint_sha256"]
        != moss_stable["engine_report"]["fingerprint_sha256"],
        "examples have identical structural fingerprints",
    )
    _require(
        facet_stable["geometry_signature_sha256"]
        != moss_stable["geometry_signature_sha256"],
        "examples have identical palette-independent geometry signatures",
    )
    _require(
        facet_stable["character_topology_totals"]
        != moss_stable["character_topology_totals"],
        "examples differ only in non-topological fields",
    )


def _summary(reports: Mapping[Tuple[str, int], Mapping[str, Any]]) -> Dict[str, Any]:
    versions = {report["blender_version"] for report in reports.values()}
    _require(len(versions) == 1, "all four processes must use one Blender version")
    examples: Dict[str, Any] = {}
    for slug, _request in EXAMPLES:
        stable = reports[(slug, 1)]["stable"]
        examples[slug] = {
            "fingerprint_sha256": stable["engine_report"]["fingerprint_sha256"],
            "geometry_signature_sha256": stable["geometry_signature_sha256"],
            "observed_height_mm": reports[(slug, 1)]["checks"]["observed_height_mm"],
            "repeat_stable": True,
            "request_sha256": stable["request_sha256"],
            "spec_sha256": stable["spec_sha256"],
            "topology_totals": stable["character_topology_totals"],
            "requested_height_mm": reports[(slug, 1)]["checks"]["requested_height_mm"],
        }
    summary = {
        "blender_version": next(iter(versions)),
        "cross_example": {
            "different_palette_independent_geometry": True,
            "different_structural_fingerprint": True,
            "different_topology": True,
        },
        "examples": examples,
        "gate_version": OUTER_GATE_VERSION,
        "isolation": {
            "autoexec_disabled": True,
            "factory_startup": True,
            "network_offline": True,
            "process_count": 4,
        },
        "status": "passed",
    }
    _assert_path_free(summary)
    return summary


def _write_summary(path: Path, summary: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the explicit four-process G2 Blender integration gate"
    )
    parser.add_argument(
        "--blender",
        required=True,
        help="absolute path to the Blender 4.5 executable; no auto-discovery is performed",
    )
    parser.add_argument(
        "--evidence-dir",
        required=True,
        help="caller-owned temporary directory outside the repository",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=900,
        help="per-process timeout (default: 900)",
    )
    return parser


def run_gate(blender: Path, evidence_dir: Path, timeout_seconds: int) -> None:
    _require(1 <= timeout_seconds <= 3600, "--timeout-seconds must be between 1 and 3600")
    _require(PROBE.is_file(), "inner Blender probe is missing")
    for _slug, request_path in EXAMPLES:
        _require(request_path.is_file(), f"bundled request is missing: {request_path.name}")

    targets = _target_paths(evidence_dir)
    reports: Dict[Tuple[str, int], Mapping[str, Any]] = {}
    for slug, request_path in EXAMPLES:
        for repeat in (1, 2):
            reports[(slug, repeat)] = _run_blender(
                blender,
                request_path,
                targets[(slug, repeat)],
                timeout_seconds,
                evidence_dir,
            )
        _compare_repeats(slug, reports[(slug, 1)], reports[(slug, 2)])

    _compare_examples(reports[("facet-bot", 1)], reports[("moss-hopper", 1)])
    _write_summary(targets[("summary", 0)], _summary(reports))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        blender = _validate_blender_path(args.blender)
        evidence_dir = _validate_evidence_dir(args.evidence_dir)
        run_gate(blender, evidence_dir, args.timeout_seconds)
    except GateFailure as exc:
        print(f"G2_BLENDER_INTEGRATION: FAIL: {exc}", file=sys.stderr)
        return 1
    print("G2_BLENDER_INTEGRATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
