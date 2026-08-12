#!/usr/bin/env python3
"""Independent end-to-end gate for the complete-v1 Blender artifact set.

This is intentionally not a ``test_*.py`` module.  A caller must opt in with
an explicit Blender executable and a caller-owned temporary work directory.
The gate invokes the public runner in clean processes, validates every
published byte, then uses additional clean Blender processes to reload the
blend and independently import the GLB and STL.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only by a misconfigured caller
    Draft202012Validator = None  # type: ignore[assignment,misc]

from shared.build_manifest import (
    MAX_PUBLISHED_ARTIFACT_BYTES,
    REQUIRED_ARTIFACTS,
    BuildManifest,
)
from shared.character_spec import BuildRequest
from shared.json_contract import (
    MAX_BUILD_REQUEST_BYTES,
    ContractValidationError,
    canonical_json_bytes,
    canonical_sha256,
    decode_json_document,
)
from shared.quality_report import (
    QualityReport,
    dimensions_within_reimport_tolerance,
    value_within_geometry_tolerance,
)


RUNNER = ROOT / "blender" / "runner.py"
VERIFIER = ROOT / "blender" / "verifier.py"
PROBE = Path(__file__).with_name("g3_artifact_probe.py")
QA_REGRESSION = Path(__file__).with_name("g3_qa_regression.py")
MANIFEST_SCHEMA = ROOT / "schemas" / "manifest-v1.schema.json"
QA_SCHEMA = ROOT / "schemas" / "qa-v1.schema.json"
INVALID_REQUEST = ROOT / "tests" / "fixtures" / "rejected" / "outer-extra-property.json"
EXAMPLES = {
    "facet-bot": ROOT / "examples" / "requests" / "facet-bot.json",
    "moss-hopper": ROOT / "examples" / "requests" / "moss-hopper.json",
}

BLENDER_VERSION = "4.5.12 LTS"
GATE_VERSION = "g3-blender-integration/v1"
PROBE_VERSION = "g3-artifact-probe/v1"
VERIFICATION_VERSION = "artifact-verifier/v1"
EXACT_FILES = set(REQUIRED_ARTIFACTS) | {"manifest.json"}
EXACT_DIRECTORIES = {"diagnostics"}
PNG_FILES = (
    "preview.png",
    "diagnostics/front.png",
    "diagnostics/side.png",
    "diagnostics/back.png",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_FORBIDDEN_METADATA = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PATH_LIKE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_TRIANGLES = 500_000


class GateFailure(RuntimeError):
    """A bounded, caller-safe G3 gate failure."""


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


def _validate_work_dir(raw: str) -> Path:
    work_dir = Path(raw).expanduser().resolve()
    broad_roots = {
        Path(work_dir.anchor).resolve(),
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    _require(
        work_dir not in broad_roots,
        "--work-dir must be a dedicated temporary subdirectory, not a broad root",
    )
    _require(
        not _is_within(work_dir, ROOT),
        "--work-dir must be a caller-owned temporary directory outside the workspace",
    )
    if work_dir.exists():
        _require(work_dir.is_dir() and not work_dir.is_symlink(), "--work-dir is not a real directory")
    else:
        work_dir.mkdir(parents=True, mode=0o700)
    return work_dir


def _subprocess_environment() -> Dict[str, str]:
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


def _redact_output(text: str, blender: Path, work_dir: Path) -> str:
    redacted = text
    replacements = (
        (str(work_dir), "<work-dir>"),
        (str(ROOT), "<workspace>"),
        (str(blender), "<blender>"),
        (str(Path.home()), "<home>"),
        (tempfile.gettempdir(), "<temp>"),
    )
    for original, replacement in replacements:
        if original:
            redacted = redacted.replace(original, replacement)
    return "\n".join(redacted.splitlines()[-50:])


def _assert_path_free(value: Any, label: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_path_free(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_path_free(item, f"{label}[{index}]")
    elif isinstance(value, str):
        _require(not PATH_LIKE.match(value), f"{label} contains a local path")
        _require("file://" not in value.lower(), f"{label} contains a file URI")
        for local_root in (str(ROOT), str(Path.home()), tempfile.gettempdir()):
            _require(local_root not in value, f"{label} embeds a local path")


def _run_process(
    command: Sequence[str],
    *,
    blender: Path,
    work_dir: Path,
    timeout_seconds: int,
    label: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
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
        raw = exc.stdout if isinstance(exc.stdout, str) else ""
        detail = _redact_output(raw, blender, work_dir)
        raise GateFailure(f"{label}: process timed out\n{detail}".rstrip()) from exc
    except OSError as exc:
        raise GateFailure(f"{label}: process could not start: {type(exc).__name__}") from exc


def _check_blender_version(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    completed = _run_process(
        (str(blender), "--version"),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=min(timeout_seconds, 60),
        label="Blender version preflight",
    )
    _require(completed.returncode == 0, "Blender version preflight failed")
    first_line = completed.stdout.splitlines()[0] if completed.stdout.splitlines() else ""
    _require(first_line == f"Blender {BLENDER_VERSION}", f"gate requires Blender {BLENDER_VERSION}")


def _runner_command(blender: Path, request: Path, output: Path) -> List[str]:
    return [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        "--python-exit-code",
        "12",
        "--python",
        str(RUNNER),
        "--",
        "--request",
        str(request),
        "--output",
        str(output),
    ]


def _run_invalid_cli(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    output = work_dir / "invalid-cli-output"
    completed = _run_process(
        (*_runner_command(blender, EXAMPLES["facet-bot"], output), "--unsupported"),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="invalid CLI",
    )
    if completed.returncode != 2:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(
            f"invalid CLI: expected exit 2, observed {completed.returncode}\n{detail}".rstrip()
        )
    _require(not output.exists(), "invalid CLI published an output directory")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        "invalid CLI left a private staging directory",
    )
    _require("BLENDER_BUILDER: PASS" not in completed.stdout, "invalid CLI reported success")


def _run_existing_output(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    output = work_dir / "existing-output"
    output.mkdir(mode=0o700)
    marker = output / "caller-owned.txt"
    marker.write_text("preserve\n", encoding="utf-8")
    completed = _run_process(
        _runner_command(blender, EXAMPLES["facet-bot"], output),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="existing output",
    )
    if completed.returncode != 4:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(
            f"existing output: expected exit 4, observed {completed.returncode}\n{detail}".rstrip()
        )
    _require(marker.read_text(encoding="utf-8") == "preserve\n", "existing output was modified")
    _require(tuple(output.iterdir()) == (marker,), "existing output gained unexpected files")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        "existing output left a private staging directory",
    )
    _require("BLENDER_BUILDER: PASS" not in completed.stdout, "existing output reported success")


def _run_oversized_request(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    request = work_dir / "oversized-request.json"
    request.write_bytes(b" " * (MAX_BUILD_REQUEST_BYTES + 1))
    output = work_dir / "oversized-request-output"
    completed = _run_process(
        _runner_command(blender, request, output),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="oversized request",
    )
    if completed.returncode != 3:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(
            f"oversized request: expected exit 3, observed {completed.returncode}\n{detail}".rstrip()
        )
    _require(not output.exists(), "oversized request published an output directory")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        "oversized request left a private staging directory",
    )
    _require("BLENDER_BUILDER: PASS" not in completed.stdout, "oversized request reported success")


def _run_unresolvable_request_path(
    blender: Path, work_dir: Path, timeout_seconds: int
) -> None:
    output = work_dir / "unresolvable-request-path-output"
    command = _runner_command(
        blender,
        Path("~hbcc-user-that-must-not-exist-4f2c91/request.json"),
        output,
    )
    completed = _run_process(
        command,
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="unresolvable request path",
    )
    if completed.returncode != 4:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(
            f"unresolvable request path: expected exit 4, observed {completed.returncode}\n{detail}".rstrip()
        )
    _require(not output.exists(), "unresolvable request path published an output directory")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        "unresolvable request path left a private staging directory",
    )
    _require(
        "BLENDER_BUILDER: PASS" not in completed.stdout,
        "unresolvable request path reported success",
    )


def _run_qa_regression(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(QA_REGRESSION),
    ]
    completed = _run_process(
        command,
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="production QA regression",
    )
    if completed.returncode != 0:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(f"production QA regression failed\n{detail}".rstrip())
    _require(
        "G3_QA_REGRESSION: PASS" in completed.stdout,
        "production QA regression omitted its pass marker",
    )


def _run_invalid_request(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    output = work_dir / "invalid-request-output"
    _require(not output.exists(), "refusing to overwrite invalid-request output")
    completed = _run_process(
        _runner_command(blender, INVALID_REQUEST, output),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="invalid request",
    )
    if completed.returncode != 3:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(
            f"invalid request: expected exit 3, observed {completed.returncode}\n{detail}".rstrip()
        )
    _require(not output.exists(), "invalid request published a partial output directory")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        "invalid request left a private staging directory",
    )
    _require("BLENDER_BUILDER: PASS" not in completed.stdout, "invalid request reported success")


def _run_moss_needs_review(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    output = work_dir / "moss-hopper-needs-review-output"
    _require(not output.exists(), "refusing to overwrite Moss Hopper negative output")
    completed = _run_process(
        _runner_command(blender, EXAMPLES["moss-hopper"], output),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="moss-hopper needs_review",
    )
    if completed.returncode != 11:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(
            f"moss-hopper needs_review: expected exit 11, observed {completed.returncode}\n{detail}".rstrip()
        )
    _require(
        "mandatory geometry QA status is needs_review; "
        "safe diagnostics: minimum wall measurement unavailable" in completed.stdout,
        "moss-hopper: exit 11 omitted its safe mandatory-unknown QA diagnostic",
    )
    _require(
        "short strict candidates" not in completed.stdout and "ray misses" not in completed.stdout,
        "moss-hopper: exit 11 exposed private detailed QA notes",
    )
    _require(not output.exists(), "moss-hopper needs_review published partial output")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        "moss-hopper needs_review left a private staging directory",
    )
    _require("BLENDER_BUILDER: PASS" not in completed.stdout, "moss-hopper needs_review reported success")


def _run_success(
    blender: Path,
    request: Path,
    output: Path,
    work_dir: Path,
    timeout_seconds: int,
    label: str,
) -> None:
    _require(not output.exists(), f"{label}: refusing to overwrite output")
    completed = _run_process(
        _runner_command(blender, request, output),
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label=label,
    )
    if completed.returncode != 0:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(f"{label}: runner exited {completed.returncode}\n{detail}".rstrip())
    _require("BLENDER_BUILDER: PASS" in completed.stdout, f"{label}: runner omitted success marker")
    _require(output.is_dir() and not output.is_symlink(), f"{label}: output was not atomically published")
    _require(
        not tuple(work_dir.glob(f".{output.name}.staging-*")),
        f"{label}: success left a private staging directory",
    )


def _regular_file(path: Path, label: str) -> None:
    _require(not path.is_symlink(), f"{label}: symbolic links are forbidden")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise GateFailure(f"{label}: could not stat artifact") from exc
    _require(stat.S_ISREG(mode), f"{label}: artifact is not a regular file")
    _require(path.stat().st_size > 0, f"{label}: artifact is empty")


def _assert_exact_tree(output: Path, label: str) -> None:
    files: set[str] = set()
    directories: set[str] = set()
    for path in output.rglob("*"):
        relative = path.relative_to(output).as_posix()
        _require(not path.is_symlink(), f"{label}: output tree contains a symlink")
        if path.is_dir():
            directories.add(relative)
        else:
            _regular_file(path, f"{label}/{relative}")
            files.add(relative)
    _require(files == EXACT_FILES, f"{label}: published file tree differs from complete-v1")
    _require(directories == EXACT_DIRECTORIES, f"{label}: published directory tree is invalid")
    manifest_mtime = (output / "manifest.json").stat().st_mtime_ns
    _require(
        manifest_mtime >= max((output / name).stat().st_mtime_ns for name in REQUIRED_ARTIFACTS),
        f"{label}: manifest was not written last",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_revision() -> str:
    digest = hashlib.sha256()
    files = sorted(
        (*ROOT.joinpath("blender").rglob("*.py"), *ROOT.joinpath("shared").rglob("*.py")),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    for path in files:
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _load_contract_json(path: Path, label: str) -> Tuple[bytes, Mapping[str, Any]]:
    try:
        payload = path.read_bytes()
        _require(len(payload) <= MAX_JSON_BYTES, f"{label}: JSON exceeds gate size limit")
        # The project decoder first enforces duplicate-key, non-finite, nesting,
        # and numeric bounds.  Reparse the already-vetted document with the
        # standard numeric types expected by jsonschema and evidence checks.
        decode_json_document(payload, max_bytes=MAX_JSON_BYTES)
        raw = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ContractValidationError) as exc:
        raise GateFailure(f"{label}: invalid strict UTF-8 JSON") from exc
    _require(isinstance(raw, Mapping), f"{label}: JSON root must be an object")
    return payload, raw


def _load_schema(path: Path, label: str) -> Mapping[str, Any]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateFailure(f"{label}: could not load schema") from exc
    _require(isinstance(schema, Mapping), f"{label}: schema root is not an object")
    return schema


def _draft_validate(instance: Mapping[str, Any], schema_path: Path, label: str) -> None:
    _require(Draft202012Validator is not None, "G3 gate requires jsonschema==4.26.0")
    schema = _load_schema(schema_path, label)
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
    except Exception as exc:
        raise GateFailure(f"{label}: Draft 2020-12 validation could not run") from exc
    if errors:
        path = ".".join(str(item) for item in errors[0].absolute_path) or "$"
        raise GateFailure(f"{label}: Draft 2020-12 failure at {path}: {errors[0].message}")


def _within_tolerance(expected: Sequence[Any], observed: Sequence[Any]) -> bool:
    if len(expected) != 3 or len(observed) != 3:
        return False
    for baseline, actual in zip(expected, observed):
        baseline_float = float(baseline)
        actual_float = float(actual)
        tolerance = max(0.2, abs(baseline_float) * 0.005)
        if not math.isfinite(actual_float) or abs(actual_float - baseline_float) > tolerance:
            return False
    return True


def _validate_contracts(
    output: Path,
    request_path: Path,
    blender: Path,
    label: str,
) -> Dict[str, Any]:
    request = BuildRequest.from_json(request_path.read_bytes())
    manifest_payload, manifest_raw = _load_contract_json(output / "manifest.json", f"{label}/manifest")
    qa_payload, qa_raw = _load_contract_json(output / "qa.json", f"{label}/qa")
    _draft_validate(manifest_raw, MANIFEST_SCHEMA, f"{label}/manifest")
    _draft_validate(qa_raw, QA_SCHEMA, f"{label}/qa")
    try:
        manifest = BuildManifest.from_json(manifest_payload)
        quality = QualityReport.from_json(qa_payload)
    except ContractValidationError as exc:
        raise GateFailure(f"{label}: runtime contract rejection: {exc.code} at {exc.path}") from exc

    _require(manifest_payload == manifest.canonical_bytes + b"\n", f"{label}: manifest is not canonical JSON")
    _require(qa_payload == quality.canonical_bytes + b"\n", f"{label}: QA is not canonical JSON")
    _require(manifest.request_sha256 == request.request_sha256, f"{label}: request hash mismatch")
    _require(manifest.spec_sha256 == request.spec_sha256, f"{label}: spec hash mismatch")
    _require(quality.status == "passed", f"{label}: QA did not pass")
    _require(all(value is True for value in quality.checks.values()), f"{label}: QA check is not true")
    _require(
        quality.measurements["requested_height_mm"] == request.spec.height_mm,
        f"{label}: requested height evidence mismatch",
    )
    _require(manifest.dimensions_mm == quality.measurements["dimensions_mm"], f"{label}: dimensions disagree")
    _require(
        dimensions_within_reimport_tolerance(
            quality.measurements["dimensions_mm"], quality.measurements["glb_dimensions_mm"]
        )
        and dimensions_within_reimport_tolerance(
            quality.measurements["dimensions_mm"], quality.measurements["stl_dimensions_mm"]
        ),
        f"{label}: reimport dimensions exceed tolerance",
    )
    _require(
        value_within_geometry_tolerance(request.spec.height_mm, manifest.dimensions_mm[2]),
        f"{label}: printable height exceeds tolerance",
    )

    expected_summary = {
        "connected_shells": quality.measurements["connected_shells"],
        "fresh_reload": quality.checks["fresh_reload"],
        "glb_reimport": quality.checks["glb_reimport"],
        "manifold": quality.checks["manifold"],
        "minimum_feature_mm": quality.measurements["minimum_feature_mm"],
        "minimum_wall_mm": quality.measurements["minimum_wall_mm"],
        "non_manifold_edges": quality.measurements["non_manifold_edges"],
        "positive_volume": quality.checks["positive_volume"],
        "status": quality.status,
        "stl_reimport": quality.checks["stl_reimport"],
    }
    _require(dict(manifest.qa) == expected_summary, f"{label}: manifest QA summary disagrees with qa.json")

    total_bytes = 0
    recomputed_artifacts: Dict[str, Dict[str, Any]] = {}
    for name in REQUIRED_ARTIFACTS:
        artifact = output / name
        _regular_file(artifact, f"{label}/{name}")
        size = artifact.stat().st_size
        digest = _sha256_file(artifact)
        entry = manifest.artifacts[name]
        _require(entry["bytes"] == size, f"{label}/{name}: byte count mismatch")
        _require(entry["sha256"] == digest, f"{label}/{name}: SHA-256 mismatch")
        total_bytes += size
        recomputed_artifacts[name] = {"bytes": size, "sha256": digest}
    _require(total_bytes <= MAX_PUBLISHED_ARTIFACT_BYTES, f"{label}: artifact budget exceeded")

    execution = manifest.execution
    _require(execution["mode"] == "native", f"{label}: execution mode is not native")
    _require(execution["blender_version"] == BLENDER_VERSION, f"{label}: Blender version mismatch")
    _require(
        execution["blender_binary_sha256"] == _sha256_file(blender),
        f"{label}: Blender binary provenance mismatch",
    )
    _require(execution["project_revision"] == _source_revision(), f"{label}: source revision mismatch")
    _assert_path_free(manifest_raw, f"{label}.manifest")
    _assert_path_free(qa_raw, f"{label}.qa")
    return {
        "manifest": manifest,
        "manifest_raw": manifest_raw,
        "qa": quality,
        "qa_raw": qa_raw,
        "request": request,
        "artifacts": recomputed_artifacts,
        "total_bytes": total_bytes,
    }


def _paeth(left: int, above: int, upper_left: int) -> int:
    predictor = left + above - upper_left
    left_distance = abs(predictor - left)
    above_distance = abs(predictor - above)
    upper_left_distance = abs(predictor - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _inspect_png(path: Path, label: str) -> Dict[str, Any]:
    data = path.read_bytes()
    _require(data.startswith(PNG_SIGNATURE), f"{label}: invalid PNG signature")
    position = len(PNG_SIGNATURE)
    chunks: List[Tuple[bytes, bytes]] = []
    while position < len(data):
        _require(position + 12 <= len(data), f"{label}: truncated PNG chunk")
        length = struct.unpack_from(">I", data, position)[0]
        chunk_type = data[position + 4 : position + 8]
        end = position + 12 + length
        _require(length <= 16 * 1024 * 1024 and end <= len(data), f"{label}: invalid PNG chunk length")
        payload = data[position + 8 : position + 8 + length]
        expected_crc = struct.unpack_from(">I", data, position + 8 + length)[0]
        observed_crc = binascii.crc32(chunk_type)
        observed_crc = binascii.crc32(payload, observed_crc) & 0xFFFFFFFF
        _require(observed_crc == expected_crc, f"{label}: PNG CRC mismatch")
        chunks.append((chunk_type, payload))
        position = end
        if chunk_type == b"IEND":
            break
    _require(position == len(data), f"{label}: trailing data after PNG IEND")
    _require(chunks and chunks[0][0] == b"IHDR", f"{label}: PNG IHDR is not first")
    _require(chunks[-1] == (b"IEND", b""), f"{label}: invalid PNG IEND")
    _require(sum(1 for chunk_type, _payload in chunks if chunk_type == b"IHDR") == 1, f"{label}: duplicate IHDR")
    _require(not ({chunk_type for chunk_type, _payload in chunks} & PNG_FORBIDDEN_METADATA), f"{label}: PNG metadata was not stripped")

    ihdr = chunks[0][1]
    _require(len(ihdr) == 13, f"{label}: invalid IHDR length")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
    _require((width, height) == (512, 512), f"{label}: PNG dimensions are not 512x512")
    _require(bit_depth == 8 and color_type in (2, 6), f"{label}: PNG is not 8-bit RGB/RGBA")
    _require((compression, filtering, interlace) == (0, 0, 0), f"{label}: unsupported PNG encoding")
    channels = 3 if color_type == 2 else 4
    compressed = b"".join(payload for chunk_type, payload in chunks if chunk_type == b"IDAT")
    _require(bool(compressed), f"{label}: PNG has no IDAT data")
    try:
        filtered = zlib.decompress(compressed)
    except zlib.error as exc:
        raise GateFailure(f"{label}: PNG IDAT does not decompress") from exc
    stride = width * channels
    _require(len(filtered) == height * (stride + 1), f"{label}: PNG scanline length mismatch")
    pixels = bytearray(height * stride)
    source_position = 0
    previous = bytearray(stride)
    for row_index in range(height):
        filter_type = filtered[source_position]
        source_position += 1
        _require(filter_type <= 4, f"{label}: unsupported PNG filter")
        raw = filtered[source_position : source_position + stride]
        source_position += stride
        reconstructed = bytearray(stride)
        for index, value in enumerate(raw):
            left = reconstructed[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            else:
                predictor = _paeth(left, above, upper_left)
            reconstructed[index] = (value + predictor) & 0xFF
        pixels[row_index * stride : (row_index + 1) * stride] = reconstructed
        previous = reconstructed

    colors = set()
    luma_min = 255
    luma_max = 0
    visible_pixels = 0
    for offset in range(0, len(pixels), channels):
        red, green, blue = pixels[offset], pixels[offset + 1], pixels[offset + 2]
        alpha = pixels[offset + 3] if channels == 4 else 255
        if alpha:
            visible_pixels += 1
            luma = (red * 54 + green * 183 + blue * 19) // 256
            luma_min = min(luma_min, luma)
            luma_max = max(luma_max, luma)
            if len(colors) <= 4096:
                colors.add((red, green, blue, alpha))
    _require(visible_pixels > 0, f"{label}: PNG is fully transparent")
    _require(luma_max - luma_min >= 8 and len(colors) >= 16, f"{label}: PNG lacks rendered image variation")
    return {
        "bytes": len(data),
        "channels": channels,
        "content_sha256": hashlib.sha256(pixels).hexdigest(),
        "dimensions": [width, height],
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "luma_range": [luma_min, luma_max],
    }


def _strict_json_bytes(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        decode_json_document(payload, max_bytes=MAX_JSON_BYTES)
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ContractValidationError) as exc:
        raise GateFailure(f"{label}: invalid strict JSON") from exc
    _require(isinstance(value, Mapping), f"{label}: JSON root must be an object")
    return value


def _collect_uri_fields(value: Any, found: List[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "uri":
                found.append(str(item))
            _collect_uri_fields(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_uri_fields(item, found)


def _inspect_glb(path: Path, label: str) -> Dict[str, Any]:
    data = path.read_bytes()
    _require(len(data) >= 20, f"{label}: GLB is too short")
    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    _require(magic == b"glTF" and version == 2, f"{label}: invalid GLB header")
    _require(declared_length == len(data), f"{label}: GLB declared length mismatch")
    position = 12
    chunks: List[Tuple[int, bytes]] = []
    while position < len(data):
        _require(position + 8 <= len(data), f"{label}: truncated GLB chunk header")
        length, chunk_type = struct.unpack_from("<II", data, position)
        position += 8
        _require(length % 4 == 0 and position + length <= len(data), f"{label}: invalid GLB chunk framing")
        chunks.append((chunk_type, data[position : position + length]))
        position += length
    _require(position == len(data) and len(chunks) == 2, f"{label}: GLB must contain JSON and BIN chunks")
    _require(chunks[0][0] == 0x4E4F534A and chunks[1][0] == 0x004E4942, f"{label}: GLB chunk order is invalid")
    document = _strict_json_bytes(chunks[0][1].rstrip(b" \t\r\n\x00"), f"{label}/JSON")
    _require(document.get("asset", {}).get("version") == "2.0", f"{label}: glTF asset version mismatch")
    buffers = document.get("buffers")
    _require(isinstance(buffers, list) and len(buffers) == 1, f"{label}: GLB buffer inventory is invalid")
    byte_length = buffers[0].get("byteLength") if isinstance(buffers[0], Mapping) else None
    _require(isinstance(byte_length, (int, float)) and not isinstance(byte_length, bool), f"{label}: invalid GLB byteLength")
    _require(0 < int(byte_length) <= len(chunks[1][1]) <= int(byte_length) + 3, f"{label}: GLB BIN length mismatch")
    uri_fields: List[str] = []
    _collect_uri_fields(document, uri_fields)
    _require(not uri_fields, f"{label}: GLB contains external resource URIs")
    _require(not document.get("images") and not document.get("textures"), f"{label}: GLB contains image textures")
    _require(not document.get("cameras"), f"{label}: GLB contains cameras")
    extensions = document.get("extensionsUsed", [])
    _require("KHR_lights_punctual" not in extensions, f"{label}: GLB contains lights")

    accessors = document.get("accessors")
    meshes = document.get("meshes")
    materials = document.get("materials")
    _require(isinstance(accessors, list) and accessors, f"{label}: GLB has no accessors")
    _require(isinstance(meshes, list) and meshes, f"{label}: GLB has no meshes")
    _require(isinstance(materials, list) and 1 <= len(materials) <= 64, f"{label}: GLB material cap violated")
    primitive_count = 0
    position_vertices = 0
    for mesh in meshes:
        _require(isinstance(mesh, Mapping), f"{label}: invalid GLB mesh")
        primitives = mesh.get("primitives")
        _require(isinstance(primitives, list) and primitives, f"{label}: GLB mesh has no primitives")
        for primitive in primitives:
            _require(isinstance(primitive, Mapping), f"{label}: invalid GLB primitive")
            attributes = primitive.get("attributes")
            _require(isinstance(attributes, Mapping), f"{label}: GLB primitive lacks attributes")
            position_accessor = attributes.get("POSITION")
            _require(isinstance(position_accessor, int) and not isinstance(position_accessor, bool), f"{label}: GLB primitive lacks POSITION")
            _require(0 <= position_accessor < len(accessors), f"{label}: GLB POSITION accessor is out of range")
            accessor = accessors[position_accessor]
            count = accessor.get("count") if isinstance(accessor, Mapping) else None
            _require(isinstance(count, int) and count > 0, f"{label}: GLB POSITION accessor is empty")
            position_vertices += count
            primitive_count += 1
    _require(position_vertices > 0, f"{label}: GLB contains no position vertices")
    return {
        "accessor_count": len(accessors),
        "bytes": len(data),
        "material_count": len(materials),
        "mesh_count": len(meshes),
        "position_vertex_count": position_vertices,
        "primitive_count": primitive_count,
    }


class _DisjointSet:
    def __init__(self, count: int = 0) -> None:
        self.parent = list(range(count))
        self.rank = [0] * count

    def add(self) -> int:
        index = len(self.parent)
        self.parent.append(index)
        self.rank.append(0)
        return index

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first: int, second: int) -> None:
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return
        if self.rank[first_root] < self.rank[second_root]:
            first_root, second_root = second_root, first_root
        self.parent[second_root] = first_root
        if self.rank[first_root] == self.rank[second_root]:
            self.rank[first_root] += 1


def _cross(first: Sequence[float], second: Sequence[float]) -> Tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _inspect_stl(path: Path, requested_height_mm: float, label: str) -> Dict[str, Any]:
    data = path.read_bytes()
    _require(len(data) >= 84, f"{label}: STL is shorter than its binary header")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    _require(4 <= triangle_count <= MAX_TRIANGLES, f"{label}: STL triangle cap violated")
    _require(len(data) == 84 + triangle_count * 50, f"{label}: binary STL framing mismatch")

    vertices: Dict[Tuple[float, float, float], int] = {}
    vertex_sets = _DisjointSet()
    face_sets = _DisjointSet(triangle_count)
    # A value of None means the closed edge already has its two incident faces.
    edge_uses: MutableMapping[Tuple[int, int], Optional[Tuple[int, int]]] = {}
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    volume_terms: List[float] = []
    smallest_double_area = math.inf
    aligned_normals = 0

    for face_index in range(triangle_count):
        values = struct.unpack_from("<12fH", data, 84 + face_index * 50)
        normal = tuple(float(value) for value in values[0:3])
        coordinates = [
            tuple(float(value) for value in values[offset : offset + 3])
            for offset in (3, 6, 9)
        ]
        _require(
            all(math.isfinite(value) for vertex in coordinates for value in vertex)
            and all(math.isfinite(value) for value in normal),
            f"{label}: STL contains non-finite values",
        )
        ids: List[int] = []
        for vertex in coordinates:
            index = vertices.get(vertex)
            if index is None:
                index = vertex_sets.add()
                vertices[vertex] = index
            ids.append(index)
            for axis in range(3):
                minimum[axis] = min(minimum[axis], vertex[axis])
                maximum[axis] = max(maximum[axis], vertex[axis])
        _require(len(set(ids)) == 3, f"{label}: STL contains a collapsed triangle")
        vertex_sets.union(ids[0], ids[1])
        vertex_sets.union(ids[1], ids[2])

        edge_a = tuple(coordinates[1][axis] - coordinates[0][axis] for axis in range(3))
        edge_b = tuple(coordinates[2][axis] - coordinates[0][axis] for axis in range(3))
        geometric_normal = _cross(edge_a, edge_b)
        double_area = math.sqrt(sum(value * value for value in geometric_normal))
        _require(double_area > 1.0e-10, f"{label}: STL contains a zero-area triangle")
        smallest_double_area = min(smallest_double_area, double_area)
        normal_length = math.sqrt(sum(value * value for value in normal))
        _require(normal_length > 0, f"{label}: STL stores a zero normal")
        cosine = sum(normal[axis] * geometric_normal[axis] for axis in range(3)) / (
            normal_length * double_area
        )
        _require(cosine >= 0.99, f"{label}: STL stored normal opposes triangle winding")
        aligned_normals += 1
        cross_v1_v2 = _cross(coordinates[1], coordinates[2])
        volume_terms.append(
            sum(coordinates[0][axis] * cross_v1_v2[axis] for axis in range(3)) / 6.0
        )

        for first, second in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])):
            key = (min(first, second), max(first, second))
            orientation = 1 if first < second else -1
            if key not in edge_uses:
                edge_uses[key] = (face_index, orientation)
                continue
            previous = edge_uses[key]
            _require(previous is not None, f"{label}: STL edge has more than two incident faces")
            previous_face, previous_orientation = previous
            _require(previous_orientation == -orientation, f"{label}: STL edge winding is inconsistent")
            face_sets.union(previous_face, face_index)
            edge_uses[key] = None

    _require(all(value is None for value in edge_uses.values()), f"{label}: STL has boundary edges")
    vertex_components = len({vertex_sets.find(index) for index in range(len(vertex_sets.parent))})
    face_components = len({face_sets.find(index) for index in range(triangle_count)})
    _require(vertex_components == 1, f"{label}: STL has multiple vertex-connected components")
    _require(face_components == 1, f"{label}: STL has multiple face-connected shells")
    signed_volume = math.fsum(volume_terms)
    _require(math.isfinite(signed_volume) and signed_volume > 0, f"{label}: STL shell volume is not positive")
    dimensions = [maximum[index] - minimum[index] for index in range(3)]
    _require(all(math.isfinite(value) and value > 0 for value in dimensions), f"{label}: STL bounds are invalid")
    tolerance = max(0.2, abs(requested_height_mm) * 0.005)
    _require(abs(dimensions[2] - requested_height_mm) <= tolerance, f"{label}: raw-mm STL height mismatch")
    return {
        "aligned_normal_count": aligned_normals,
        "dimensions_mm": [round(value, 6) for value in dimensions],
        "edge_count": len(edge_uses),
        "face_components": face_components,
        "signed_volume_mm3": round(signed_volume, 6),
        "smallest_double_area_mm2": round(smallest_double_area, 12),
        "triangle_count": triangle_count,
        "unique_vertex_count": len(vertices),
        "vertex_components": vertex_components,
    }


def _run_probe(
    blender: Path,
    output: Path,
    request: Path,
    result: Path,
    work_dir: Path,
    timeout_seconds: int,
    label: str,
) -> None:
    _require(not result.exists(), f"{label}: refusing to overwrite probe evidence")
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        str(output / "model.blend"),
        "--python-exit-code",
        "1",
        "--python",
        str(PROBE),
        "--",
        "--blend",
        str(output / "model.blend"),
        "--glb",
        str(output / "model.glb"),
        "--stl",
        str(output / "model.stl"),
        "--request",
        str(request),
        "--result",
        str(result),
    ]
    completed = _run_process(
        command,
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label=f"{label}/independent probe",
    )
    if completed.returncode != 0:
        detail = _redact_output(completed.stdout, blender, work_dir)
        raise GateFailure(f"{label}: independent probe exited {completed.returncode}\n{detail}".rstrip())
    _require("G3_ARTIFACT_PROBE: PASS" in completed.stdout, f"{label}: probe omitted pass marker")


def _assert_closed_topology(topology: Any, label: str) -> None:
    _require(isinstance(topology, Mapping), f"{label}: topology evidence is not an object")
    _require(topology.get("face_components") == 1, f"{label}: face component count is not one")
    _require(topology.get("vertex_components") == 1, f"{label}: vertex component count is not one")
    for field in (
        "boundary_edges",
        "near_zero_faces",
        "non_contiguous_edges",
        "non_manifold_edges",
        "non_manifold_vertices",
    ):
        _require(topology.get(field) == 0, f"{label}: {field} is nonzero")
    volume = topology.get("signed_volume_mm3")
    _require(isinstance(volume, (int, float)) and not isinstance(volume, bool) and volume > 0, f"{label}: volume is not positive")


def _validate_probe(
    result: Path,
    slug: str,
    contracts: Mapping[str, Any],
) -> Mapping[str, Any]:
    _payload, evidence = _load_contract_json(result, f"{slug}/probe")
    expected_fields = {
        "blender_version",
        "checks",
        "example_slug",
        "gate_version",
        "stable",
        "stable_sha256",
        "status",
        "verifier_expected",
    }
    _require(set(evidence) == expected_fields, f"{slug}: probe evidence fields are invalid")
    _require(evidence["status"] == "passed", f"{slug}: probe did not pass")
    _require(evidence["gate_version"] == PROBE_VERSION, f"{slug}: probe version mismatch")
    _require(evidence["blender_version"] == BLENDER_VERSION, f"{slug}: probe Blender mismatch")
    _require(evidence["example_slug"] == slug, f"{slug}: probe slug mismatch")
    checks = evidence["checks"]
    _require(
        isinstance(checks, Mapping)
        and set(checks)
        == {"fresh_blend_reload", "glb_clean_reimport", "no_external_resources", "stl_clean_reimport"}
        and all(value is True for value in checks.values()),
        f"{slug}: independent probe checks did not all pass",
    )
    stable = evidence["stable"]
    _require(isinstance(stable, Mapping) and set(stable) == {"blend", "glb", "stl"}, f"{slug}: invalid stable probe evidence")
    _require(
        isinstance(evidence["stable_sha256"], str)
        and SHA256.fullmatch(evidence["stable_sha256"]) is not None
        and evidence["stable_sha256"] == canonical_sha256(stable),
        f"{slug}: probe stable hash mismatch",
    )
    blend = stable["blend"]
    glb = stable["glb"]
    stl = stable["stl"]
    _require(isinstance(blend, Mapping) and isinstance(glb, Mapping) and isinstance(stl, Mapping), f"{slug}: probe sections are invalid")
    _assert_closed_topology(blend.get("printable_topology"), f"{slug}/saved printable")
    _assert_closed_topology(stl.get("topology"), f"{slug}/reimported STL")
    quality: QualityReport = contracts["qa"]
    _require(
        _within_tolerance(
            quality.measurements["dimensions_mm"], blend["printable_bounds_mm"]["dimensions"]
        ),
        f"{slug}: saved blend dimensions disagree with QA",
    )
    _require(
        _within_tolerance(quality.measurements["glb_dimensions_mm"], glb["bounds_mm"]["dimensions"]),
        f"{slug}: reimported GLB dimensions disagree with QA",
    )
    _require(
        _within_tolerance(quality.measurements["stl_dimensions_mm"], stl["bounds_mm"]["dimensions"]),
        f"{slug}: reimported STL dimensions disagree with QA",
    )
    for section_name, section in (("blend", blend), ("glb", glb), ("stl", stl)):
        _require(1 <= section["object_count"] <= 256, f"{slug}/{section_name}: object cap violated")
        _require(4 <= section["triangle_count"] <= MAX_TRIANGLES, f"{slug}/{section_name}: triangle cap violated")
        _require(isinstance(section["mesh_inventory"], list) and section["mesh_inventory"], f"{slug}/{section_name}: mesh inventory is empty")

    expected = evidence["verifier_expected"]
    _require(
        isinstance(expected, Mapping)
        and set(expected)
        == {"dimensions_mm", "generation_result", "request", "structural_fingerprint_sha256"},
        f"{slug}: verifier expectation fields are invalid",
    )
    generation = expected["generation_result"]
    generation_fields = {
        "collection_names",
        "designed_minimum_feature_mm",
        "display_object_names",
        "generator_id",
        "printable_object_name",
        "request_sha256",
        "spec_sha256",
        "voxel_size_mm",
    }
    _require(isinstance(generation, Mapping) and set(generation) == generation_fields, f"{slug}: verifier generation fields are invalid")
    request: BuildRequest = contracts["request"]
    expected_request = BuildRequest.from_mapping(expected["request"])
    _require(expected_request.request_sha256 == request.request_sha256, f"{slug}: verifier request mismatch")
    _require(generation["request_sha256"] == request.request_sha256, f"{slug}: verifier generation request mismatch")
    _require(generation["spec_sha256"] == request.spec_sha256, f"{slug}: verifier generation spec mismatch")
    _require(generation["printable_object_name"] == "PrintableShell", f"{slug}: verifier printable name mismatch")
    fingerprint = expected["structural_fingerprint_sha256"]
    _require(isinstance(fingerprint, str) and SHA256.fullmatch(fingerprint) is not None, f"{slug}: invalid verifier fingerprint")
    _require(_within_tolerance(quality.measurements["dimensions_mm"], expected["dimensions_mm"]), f"{slug}: verifier dimensions mismatch")
    _assert_path_free(evidence, f"{slug}.probe")
    return evidence


def _host_artifact_inspection(output: Path, contracts: Mapping[str, Any], label: str) -> Dict[str, Any]:
    png = {name: _inspect_png(output / name, f"{label}/{name}") for name in PNG_FILES}
    diagnostic_hashes = {png[name]["file_sha256"] for name in PNG_FILES[1:]}
    _require(len(diagnostic_hashes) == 3, f"{label}: diagnostic renders are not view-distinct")
    glb = _inspect_glb(output / "model.glb", f"{label}/model.glb")
    request: BuildRequest = contracts["request"]
    stl = _inspect_stl(output / "model.stl", float(request.spec.height_mm), f"{label}/model.stl")
    quality: QualityReport = contracts["qa"]
    _require(
        _within_tolerance(quality.measurements["stl_dimensions_mm"], stl["dimensions_mm"]),
        f"{label}: raw STL dimensions disagree with QA",
    )
    return {"glb": glb, "png": png, "stl": stl}


def _corrupt_stl_verifier_test(
    blender: Path,
    source_output: Path,
    verifier_expected: Mapping[str, Any],
    work_dir: Path,
    timeout_seconds: int,
) -> None:
    corrupt = work_dir / "corrupt-private-stage"
    _require(not corrupt.exists(), "refusing to overwrite corrupt verifier stage")
    shutil.copytree(source_output, corrupt)
    manifest = corrupt / "manifest.json"
    manifest.unlink()
    stl = corrupt / "model.stl"
    with stl.open("r+b") as stream:
        stream.truncate(84)
    expected = corrupt / "_expected.json"
    result = corrupt / "_verification.json"
    expected.write_bytes(canonical_json_bytes(verifier_expected) + b"\n")
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        "--python-exit-code",
        "1",
        "--python",
        str(VERIFIER),
        "--",
        "--blend",
        str(corrupt / "model.blend"),
        "--glb",
        str(corrupt / "model.glb"),
        "--stl",
        str(stl),
        "--expected",
        str(expected),
        "--result",
        str(result),
    ]
    completed = _run_process(
        command,
        blender=blender,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        label="corrupted STL verifier",
    )
    _require(completed.returncode != 0, "corrupted STL unexpectedly passed the fresh verifier")
    _require("STL framing or triangle count is invalid" in completed.stdout, "corrupt test did not reach STL framing rejection")
    _require(not manifest.exists(), "corrupt private stage contains a success manifest")
    _require(not result.exists(), "failed verifier published success evidence")
    _require("ARTIFACT_VERIFIER: PASS" not in completed.stdout, "failed verifier reported success")


def _stable_manifest(manifest: BuildManifest) -> Mapping[str, Any]:
    raw = manifest.to_dict()
    return {
        key: raw[key]
        for key in (
            "dimensions_mm",
            "execution",
            "generator_version",
            "input_sha256",
            "manifest_version",
            "qa",
            "request_sha256",
            "spec_sha256",
        )
    }


def _stable_glb_structure(inspection: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        key: inspection[key]
        for key in (
            "material_count",
            "mesh_count",
            "position_vertex_count",
            "primitive_count",
        )
    }


def _compare_repeat(first: Mapping[str, Any], second: Mapping[str, Any]) -> None:
    _require(first["qa"].to_dict() == second["qa"].to_dict(), "facet-bot: repeat QA fields differ")
    _require(
        _stable_manifest(first["manifest"]) == _stable_manifest(second["manifest"]),
        "facet-bot: repeat manifest stable fields differ",
    )
    _require(first["probe"]["stable"] == second["probe"]["stable"], "facet-bot: repeat probe geometry differs")
    _require(
        first["probe"]["verifier_expected"] == second["probe"]["verifier_expected"],
        "facet-bot: repeat verifier expectation differs",
    )
    _require(
        _stable_glb_structure(first["host"]["glb"])
        == _stable_glb_structure(second["host"]["glb"]),
        "facet-bot: repeat GLB structural counts differ",
    )
    _require(first["host"]["stl"] == second["host"]["stl"], "facet-bot: repeat STL structure differs")


def _write_summary(path: Path, reports: Mapping[str, Mapping[str, Any]]) -> None:
    _require(not path.exists(), "refusing to overwrite G3 summary")
    examples: Dict[str, Any] = {}
    for key, report in reports.items():
        request: BuildRequest = report["request"]
        examples[key] = {
            "artifact_bytes": report["total_bytes"],
            "glb_mesh_count": report["host"]["glb"]["mesh_count"],
            "probe_stable_sha256": report["probe"]["stable_sha256"],
            "request_sha256": request.request_sha256,
            "spec_sha256": request.spec_sha256,
            "stl_triangle_count": report["host"]["stl"]["triangle_count"],
        }
    summary = {
        "blender_version": BLENDER_VERSION,
        "examples": examples,
        "failure_paths": {
            "corrupt_stl_no_manifest": True,
            "existing_output_exit_4_preserved": True,
            "invalid_cli_exit_2_no_output": True,
            "invalid_request_exit_3_no_output": True,
            "moss_hopper_needs_review_exit_11_no_output": True,
            "oversized_request_exit_3_no_output": True,
            "unresolvable_request_path_exit_4_no_output": True,
        },
        "gate_version": GATE_VERSION,
        "isolation": {
            "autoexec_disabled": True,
            "factory_startup": True,
            "network_offline": True,
            "public_runner_success_processes": 2,
        },
        "repeat_stable": True,
        "regressions": {"vertex_pinched_shell_rejected": True},
        "status": "passed",
    }
    _assert_path_free(summary)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def run_gate(blender: Path, work_dir: Path, timeout_seconds: int) -> None:
    _require(1 <= timeout_seconds <= 7200, "--timeout-seconds must be between 1 and 7200")
    _require(Draft202012Validator is not None, "G3 gate requires jsonschema==4.26.0")
    for required in (
        RUNNER,
        VERIFIER,
        PROBE,
        QA_REGRESSION,
        MANIFEST_SCHEMA,
        QA_SCHEMA,
        INVALID_REQUEST,
        *EXAMPLES.values(),
    ):
        _require(required.is_file(), f"required gate input is missing: {required.name}")

    targets = {
        "facet-bot-run-1": work_dir / "facet-bot-run-1",
        "facet-bot-run-2": work_dir / "facet-bot-run-2",
    }
    probes = {key: work_dir / f"{key}-probe.json" for key in targets}
    reserved = (
        *targets.values(),
        *probes.values(),
        work_dir / "g3-summary.json",
        work_dir / "corrupt-private-stage",
        work_dir / "existing-output",
        work_dir / "invalid-cli-output",
        work_dir / "invalid-request-output",
        work_dir / "moss-hopper-needs-review-output",
        work_dir / "oversized-request.json",
        work_dir / "oversized-request-output",
        work_dir / "unresolvable-request-path-output",
    )
    _require(not any(path.exists() for path in reserved), "work directory contains a reserved G3 target")

    _check_blender_version(blender, work_dir, timeout_seconds)
    _run_qa_regression(blender, work_dir, timeout_seconds)
    _run_invalid_cli(blender, work_dir, timeout_seconds)
    _run_existing_output(blender, work_dir, timeout_seconds)
    _run_oversized_request(blender, work_dir, timeout_seconds)
    _run_unresolvable_request_path(blender, work_dir, timeout_seconds)
    _run_invalid_request(blender, work_dir, timeout_seconds)
    _run_moss_needs_review(blender, work_dir, timeout_seconds)
    requests = {
        "facet-bot-run-1": EXAMPLES["facet-bot"],
        "facet-bot-run-2": EXAMPLES["facet-bot"],
    }
    reports: Dict[str, Dict[str, Any]] = {}
    for key, output in targets.items():
        request_path = requests[key]
        slug = "facet-bot"
        _run_success(blender, request_path, output, work_dir, timeout_seconds, key)
        _assert_exact_tree(output, key)
        report = _validate_contracts(output, request_path, blender, key)
        report["host"] = _host_artifact_inspection(output, report, key)
        _run_probe(blender, output, request_path, probes[key], work_dir, timeout_seconds, key)
        report["probe"] = _validate_probe(probes[key], slug, report)
        reports[key] = report

    _compare_repeat(reports["facet-bot-run-1"], reports["facet-bot-run-2"])
    _corrupt_stl_verifier_test(
        blender,
        targets["facet-bot-run-1"],
        reports["facet-bot-run-1"]["probe"]["verifier_expected"],
        work_dir,
        timeout_seconds,
    )
    _write_summary(work_dir / "g3-summary.json", reports)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the explicit G3 Blender artifact gate")
    parser.add_argument(
        "--blender",
        required=True,
        help="absolute path to the Blender 4.5.12 executable; no discovery is performed",
    )
    parser.add_argument(
        "--work-dir",
        required=True,
        help="caller-owned temporary output/evidence directory outside the repository",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="per-process timeout (default: 1800)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        blender = _validate_blender_path(args.blender)
        work_dir = _validate_work_dir(args.work_dir)
        run_gate(blender, work_dir, args.timeout_seconds)
    except (GateFailure, ContractValidationError) as exc:
        print(f"G3_BLENDER_INTEGRATION: FAIL: {exc}", file=sys.stderr)
        return 1
    print("G3_BLENDER_INTEGRATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
