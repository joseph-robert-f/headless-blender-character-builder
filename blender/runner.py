"""Narrow one-shot Blender runner for the complete-v1 artifact profile."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import bpy

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.build_manifest import BuildManifest, REQUIRED_ARTIFACTS
from shared.character_spec import BuildRequest
from shared.json_contract import (
    MAX_BUILD_REQUEST_BYTES,
    ContractValidationError,
    canonical_json_bytes,
    decode_json_document,
)
from shared.quality_report import QualityReport, derive_qa_status

from blender.core.camera import setup_render_scene
from blender.core.fingerprint import structural_report
from blender.exporters.model import export_glb, export_stl, inspect_binary_stl, save_model
from blender.generators.registry import generate_character, preflight_character
from blender.qa.geometry import analyze_generated_scene
from blender.render.diagnostics import render_diagnostics


BLENDER_VERSION = "4.5.12 LTS"
VERIFIER_TIMEOUT_SECONDS = 300
VERIFICATION_VERSION = "artifact-verifier/v1"
EXACT_OUTPUT_TREE = set(REQUIRED_ARTIFACTS) | {"manifest.json"}


class RunnerFailure(RuntimeError):
    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.message = message


def _script_args() -> Sequence[str]:
    try:
        boundary = sys.argv.index("--")
    except ValueError as exc:
        raise RunnerFailure(2, "missing Blender '--' script-argument boundary") from exc
    return sys.argv[boundary + 1 :]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    try:
        args, extras = parser.parse_known_args(argv)
    except (argparse.ArgumentError, SystemExit) as exc:
        raise RunnerFailure(2, "invalid runner command") from exc
    if extras:
        raise RunnerFailure(2, "unsupported runner option or positional argument")
    return args


def _read_request(path: Path) -> BuildRequest:
    try:
        # Bound the filesystem read itself.  The contract decoder repeats the
        # size check, but reading an attacker-sized file in full would defeat
        # that limit before validation gets a chance to reject it.
        with path.open("rb") as stream:
            payload = stream.read(MAX_BUILD_REQUEST_BYTES + 1)
    except OSError as exc:
        raise RunnerFailure(4, "could not read request file") from exc
    try:
        request = BuildRequest.from_json(payload)
        preflight_character(request)
        return request
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise RunnerFailure(3, "BuildRequest was rejected before scene creation") from exc


def _resolve_output(raw: str) -> Path:
    try:
        output = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RunnerFailure(4, "output path could not be resolved") from exc
    if output.exists():
        raise RunnerFailure(4, "output directory must not already exist")
    parent = output.parent
    if not parent.is_dir():
        raise RunnerFailure(4, "output parent directory does not exist")
    return output


def _resolve_request(raw: str) -> Path:
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RunnerFailure(4, "request path could not be resolved") from exc


def _private_stage(output: Path) -> Path:
    try:
        stage = Path(
            tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=str(output.parent))
        )
        stage.chmod(0o700)
        (stage / "diagnostics").mkdir(mode=0o700)
        return stage
    except OSError as exc:
        raise RunnerFailure(4, "could not create private staging directory") from exc


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    files = sorted(
        (*root.joinpath("blender").rglob("*.py"), *root.joinpath("shared").rglob("*.py")),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _write_expected(
    path: Path,
    request: BuildRequest,
    result: Any,
    fingerprint: Mapping[str, Any],
    dimensions_mm: list[float],
) -> None:
    payload = {
        "dimensions_mm": dimensions_mm,
        "generation_result": asdict(result),
        "request": request.to_dict(),
        "structural_fingerprint_sha256": fingerprint["fingerprint_sha256"],
    }
    path.write_bytes(canonical_json_bytes(payload) + b"\n")
    path.chmod(0o600)


def _child_environment() -> dict[str, str]:
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


def _run_verifier(stage: Path, expected_path: Path) -> Mapping[str, Any]:
    verifier_path = Path(__file__).with_name("verifier.py")
    result_path = stage / "_verification.json"
    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(verifier_path),
        "--",
        "--blend",
        str(stage / "model.blend"),
        "--glb",
        str(stage / "model.glb"),
        "--stl",
        str(stage / "model.stl"),
        "--expected",
        str(expected_path),
        "--result",
        str(result_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            env=_child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERIFIER_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerFailure(124, "fresh-process verifier timed out") from exc
    except OSError as exc:
        raise RunnerFailure(11, "fresh-process verifier could not start") from exc
    if completed.returncode != 0 or not result_path.is_file():
        lines = completed.stdout.splitlines() if completed.stdout else []
        candidates = [
            line
            for line in lines
            if "Error" in line or "RuntimeError" in line or "Traceback" in line
        ]
        detail = (candidates[-1] if candidates else (lines[-1] if lines else "no verifier output"))
        raise RunnerFailure(11, f"fresh-process artifact verification failed: {detail[:160]}")
    try:
        evidence = decode_json_document(result_path.read_bytes(), max_bytes=4 * 1024 * 1024)
    except (OSError, ContractValidationError) as exc:
        raise RunnerFailure(11, "fresh-process verifier evidence is invalid") from exc
    if not isinstance(evidence, Mapping):
        raise RunnerFailure(11, "fresh-process verifier evidence must be an object")
    required = {
        "verification_version",
        "fresh_reload",
        "glb_reimport",
        "stl_reimport",
        "blend",
        "glb",
        "stl",
    }
    if set(evidence) != required or evidence["verification_version"] != VERIFICATION_VERSION:
        raise RunnerFailure(11, "fresh-process verifier evidence contract mismatch")
    if not all(evidence[field] is True for field in ("fresh_reload", "glb_reimport", "stl_reimport")):
        raise RunnerFailure(11, "fresh-process verifier did not pass all reimports")
    return evidence


def _quality_report(
    request: BuildRequest,
    live: Mapping[str, Any],
    verified: Mapping[str, Any],
) -> QualityReport:
    printable = live["printable"]
    stl_topology = verified["stl"]["topology"]
    minimum_wall = printable["minimum_wall_mm"]
    minimum_feature = live["minimum_feature_mm"]
    measurements = {
        "requested_height_mm": request.spec.height_mm,
        "dimensions_mm": printable["dimensions_mm"],
        "glb_dimensions_mm": verified["glb"]["dimensions_mm"],
        "stl_dimensions_mm": verified["stl"]["dimensions_mm"],
        "triangle_count": live["triangle_count"],
        "object_count": live["object_count"],
        "material_count": live["material_count"],
        "non_manifold_edges": max(
            int(printable["non_manifold_edges"]),
            int(stl_topology["non_manifold_edges"]),
        ),
        "zero_area_faces": max(
            int(printable["zero_area_faces"]), int(stl_topology["zero_area_faces"])
        ),
        "minimum_wall_mm": minimum_wall,
        "minimum_feature_mm": minimum_feature,
        "connected_shells": int(stl_topology["connected_shells"]),
    }
    height_tolerance = max(0.2, float(request.spec.height_mm) * 0.005)
    checks = {
        "manifold": (
            measurements["non_manifold_edges"] == 0
            and int(printable["non_manifold_vertices"]) == 0
            and int(stl_topology["non_manifold_vertices"]) == 0
        ),
        "finite_geometry": bool(printable["finite_geometry"] and stl_topology["finite_geometry"]),
        "outward_normals": bool(printable["outward_normals"] and stl_topology["outward_normals"]),
        "positive_volume": bool(printable["positive_volume"] and stl_topology["positive_volume"]),
        "height_within_tolerance": abs(
            float(printable["dimensions_mm"][2]) - float(request.spec.height_mm)
        )
        <= height_tolerance,
        "fresh_reload": bool(verified["fresh_reload"]),
        "glb_reimport": bool(verified["glb_reimport"]),
        "stl_reimport": bool(verified["stl_reimport"]),
    }
    notes = [
        f"Wall lower bound uses all {printable['wall_sample_count']} final-shell triangle centroids, opposing and reciprocal rays, a short-candidate conflict gate, and a two-voxel deduction.",
        f"Feature lower bound uses actual PrintableShell cross-sections for {len(live['feature_measurements'])} generator-specific semantic parts and a two-voxel deduction.",
        "Source component dimensions are construction evidence only; joined regions are independently guarded by the global wall conflict gate.",
    ]
    if minimum_wall is None:
        notes.append(
            f"Wall evidence is unresolved: {printable['wall_strict_conflict_count']} short strict candidates and {printable['wall_ray_misses']} ray misses."
        )
    if minimum_feature is None:
        notes.append("Freestanding feature size could not be measured reliably.")
    derived_measurements = dict(measurements)
    for field in (
        "requested_height_mm",
        "minimum_wall_mm",
        "minimum_feature_mm",
    ):
        if derived_measurements[field] is not None:
            derived_measurements[field] = Decimal(str(derived_measurements[field]))
    for field in ("dimensions_mm", "glb_dimensions_mm", "stl_dimensions_mm"):
        if derived_measurements[field] is not None:
            derived_measurements[field] = tuple(
                Decimal(str(value)) for value in derived_measurements[field]
            )
    status = derive_qa_status(derived_measurements, checks)
    return QualityReport.from_mapping(
        {
            "qa_version": "qa/v1",
            "status": status,
            "measurements": measurements,
            "checks": checks,
            "notes": notes,
        }
    )


def _artifact_entries(stage: Path) -> dict[str, dict[str, Any]]:
    entries = {}
    for relative_name in REQUIRED_ARTIFACTS:
        path = stage / relative_name
        if not path.is_file() or path.stat().st_size <= 0:
            raise RunnerFailure(10, f"required artifact is missing: {relative_name}")
        entries[relative_name] = {
            "sha256": _hash_file(path),
            "bytes": path.stat().st_size,
        }
    return entries


def _manifest(
    request: BuildRequest,
    quality: QualityReport,
    stage: Path,
) -> BuildManifest:
    measurements = quality.measurements
    checks = quality.checks
    printable_qa = {
        "status": quality.status,
        "manifold": checks["manifold"],
        "non_manifold_edges": measurements["non_manifold_edges"],
        "minimum_wall_mm": measurements["minimum_wall_mm"],
        "minimum_feature_mm": measurements["minimum_feature_mm"],
        "connected_shells": measurements["connected_shells"],
        "positive_volume": checks["positive_volume"],
        "fresh_reload": checks["fresh_reload"],
        "glb_reimport": checks["glb_reimport"],
        "stl_reimport": checks["stl_reimport"],
    }
    binary_path = Path(bpy.app.binary_path)
    return BuildManifest.from_mapping(
        {
            "manifest_version": "manifest/v1",
            "request_sha256": request.request_sha256,
            "spec_sha256": request.spec_sha256,
            "input_sha256": {},
            "generator_version": "1.0.0",
            "execution": {
                "mode": "native",
                "project_revision": _source_revision(),
                "blender_version": bpy.app.version_string,
                "blender_binary_sha256": _hash_file(binary_path),
                "worker_image_reference": None,
                "worker_image_digest": None,
                "worker_image_id": None,
            },
            "dimensions_mm": list(measurements["dimensions_mm"]),
            "artifacts": _artifact_entries(stage),
            "qa": printable_qa,
        }
    )


def _publish(stage: Path, output: Path) -> None:
    private_names = {"_expected.json", "_verification.json"}
    try:
        for name in private_names:
            path = stage / name
            if path.exists():
                path.unlink()
    except OSError as exc:
        raise RunnerFailure(4, "could not remove private verifier evidence") from exc
    actual = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
    }
    if actual != EXACT_OUTPUT_TREE:
        raise RunnerFailure(12, "staged artifact tree differs from complete-v1")
    if output.exists():
        raise RunnerFailure(4, "output directory appeared during the build")
    try:
        os.rename(stage, output)
    except OSError as exc:
        raise RunnerFailure(4, "atomic artifact publication failed") from exc


def build(request_path: Path, output: Path) -> None:
    request = _read_request(request_path)
    if bpy.app.version_string != BLENDER_VERSION:
        raise RunnerFailure(10, f"builder requires Blender {BLENDER_VERSION}")
    stage = _private_stage(output)
    published = False
    try:
        try:
            result = generate_character(request)
            display_objects = tuple(bpy.data.objects[name] for name in result.display_object_names)
            printable = bpy.data.objects[result.printable_object_name]
            setup_render_scene(display_objects)
            fingerprint = structural_report(request, result)
            live = analyze_generated_scene(result)
            save_model(stage / "model.blend")
            export_glb(stage / "model.glb", display_objects)
            export_stl(stage / "model.stl", printable)
            inspect_binary_stl(stage / "model.stl")
            render_diagnostics(stage)
        except RunnerFailure:
            raise
        except OSError as exc:
            raise RunnerFailure(4, "artifact staging filesystem failure") from exc
        except Exception as exc:
            raise RunnerFailure(10, f"Blender generation/render/export failed: {type(exc).__name__}") from exc

        expected_path = stage / "_expected.json"
        try:
            _write_expected(
                expected_path,
                request,
                result,
                fingerprint,
                list(live["printable"]["dimensions_mm"]),
            )
        except OSError as exc:
            raise RunnerFailure(4, "could not write private verifier expectation") from exc
        verified = _run_verifier(stage, expected_path)
        quality = _quality_report(request, live, verified)
        try:
            (stage / "qa.json").write_bytes(quality.canonical_bytes + b"\n")
        except OSError as exc:
            raise RunnerFailure(4, "could not write qa.json") from exc
        if quality.status != "passed":
            raise RunnerFailure(11, f"mandatory geometry QA status is {quality.status}")
        manifest = _manifest(request, quality, stage)
        # Success manifest is deliberately the final staged artifact written.
        try:
            (stage / "manifest.json").write_bytes(manifest.canonical_bytes + b"\n")
        except OSError as exc:
            raise RunnerFailure(4, "could not write manifest.json") from exc
        _publish(stage, output)
        published = True
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(_script_args() if argv is None else argv)
    request_path = _resolve_request(args.request)
    output = _resolve_output(args.output)
    build(request_path, output)
    print("BLENDER_BUILDER: PASS")
    return 0


def _entrypoint() -> None:
    try:
        exit_code = main()
    except RunnerFailure as exc:
        print(f"BLENDER_BUILDER: FAIL[{exc.exit_code}]: {exc.message}", file=sys.stderr)
        exit_code = exc.exit_code
    except Exception as exc:
        print(f"BLENDER_BUILDER: FAIL[12]: unexpected {type(exc).__name__}", file=sys.stderr)
        exit_code = 12
    if exit_code:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)


if __name__ == "__main__":
    _entrypoint()
