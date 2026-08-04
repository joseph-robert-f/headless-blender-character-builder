#!/usr/bin/env python3
"""Explicit G4 clean-source, container-hardening, and parity gate.

This file is intentionally named ``g4_gate.py`` rather than ``test_*.py``.
It performs real Docker and Blender work only when a reviewer opts in with a
new caller-owned work directory and an explicit native Blender executable.

The gate exports the Git index with ``git checkout-index``, builds a uniquely
tagged image from that export, transparently records the Docker argv expanded
by GNU Make, and validates the produced artifacts independently.  It never
uses a worktree-only production file as build input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.security.g4_runtime_policy import (  # noqa: E402
    RuntimePolicyFailure,
    assert_hardened_run,
    assert_image_policy,
    assert_no_sensitive_mount_text,
)


GATE_VERSION = "g4-container-gate/v1"
BLENDER_VERSION = "4.5.12 LTS"
BLENDER_DOWNLOAD_SHA256 = "95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25"
DEFAULT_PLATFORM = "linux/amd64"
MAX_ARTIFACT_BYTES = 2 * 1024**3
MAX_TRIANGLES = 500_000
REQUIRED_FILES = {
    "diagnostics/back.png",
    "diagnostics/front.png",
    "diagnostics/side.png",
    "manifest.json",
    "model.blend",
    "model.glb",
    "model.stl",
    "preview.png",
    "qa.json",
}
REQUIRED_DIRECTORIES = {"diagnostics"}
HASHED_ARTIFACTS = REQUIRED_FILES - {"manifest.json"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
PATH_LIKE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PROVENANCE_ENV = {
    "HBCB_EXECUTION_MODE",
    "HBCB_WORKER_IMAGE_DIGEST",
    "HBCB_WORKER_IMAGE_ID",
    "HBCB_WORKER_IMAGE_REFERENCE",
}


class GateFailure(RuntimeError):
    """A bounded G4 release-gate failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _executable(raw: str, label: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        resolved = shutil.which(raw)
        _require(resolved is not None, "%s executable was not found" % label)
        candidate = Path(resolved)
    path = candidate.resolve()
    _require(path.is_file() and os.access(str(path), os.X_OK), "%s is not executable" % label)
    return path


def _work_dir(raw: str) -> Path:
    supplied = Path(raw).expanduser()
    _require(supplied.is_absolute(), "--work-dir must be an absolute caller-owned path")
    path = supplied.resolve(strict=False)
    broad = {
        Path(path.anchor).resolve(),
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }
    _require(path not in broad, "--work-dir must be a dedicated subdirectory, not a broad root")
    _require(not _is_within(path, ROOT), "--work-dir must be outside the development workspace")
    _require("," not in str(path), "--work-dir may not contain a comma because Docker mount syntax is CSV")
    if path.exists():
        _require(path.is_dir() and not path.is_symlink(), "--work-dir is not a real directory")
        _require(not any(path.iterdir()), "--work-dir must be new and empty")
    else:
        path.mkdir(parents=True, mode=0o700)
    return path


def _base_environment() -> Dict[str, str]:
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
    result = {name: os.environ[name] for name in allowed if name in os.environ}
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def _redact(text: str, work_dir: Path, extra_paths: Sequence[Path] = ()) -> str:
    redacted = text
    replacements = [
        (str(work_dir), "<work-dir>"),
        (str(ROOT), "<workspace>"),
        (str(Path.home()), "<home>"),
        (tempfile.gettempdir(), "<temp>"),
    ]
    replacements.extend((str(path), "<path>") for path in extra_paths)
    for original, replacement in replacements:
        if original:
            redacted = redacted.replace(original, replacement)
    return "\n".join(redacted.splitlines()[-60:])


def _contains_any(payload: bytes, needles: Sequence[bytes]) -> bool:
    return any(needle and needle in payload for needle in needles)


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    label: str,
    log_path: Path,
    work_dir: Path,
    canaries: Sequence[str] = (),
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=dict(environment),
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
        if any(canary and canary in output for canary in canaries):
            raise GateFailure("%s timed out and exposed a canary credential" % label) from exc
        raise GateFailure(
            "%s exceeded the caller timeout\n%s" % (label, _redact(output, work_dir))
        ) from exc
    except OSError as exc:
        raise GateFailure("%s could not start: %s" % (label, type(exc).__name__)) from exc
    elapsed = time.monotonic() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    if any(canary and canary in completed.stdout for canary in canaries):
        raise GateFailure("%s exposed a canary credential in process output" % label)
    setattr(completed, "g4_elapsed_seconds", elapsed)
    return completed


def _command_output(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    label: str,
    work_dir: Path,
) -> str:
    completed = _run(
        command,
        cwd=cwd,
        environment=environment,
        timeout_seconds=timeout_seconds,
        label=label,
        log_path=work_dir / "logs" / (label.replace(" ", "-") + ".log"),
        work_dir=work_dir,
    )
    if completed.returncode != 0:
        raise GateFailure(
            "%s exited %s\n%s"
            % (label, completed.returncode, _redact(completed.stdout, work_dir))
        )
    return completed.stdout


def _strict_pairs(pairs: Iterable[Tuple[str, Any]]) -> Mapping[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateFailure("JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise GateFailure("JSON contains a non-finite number: %s" % token)


def _load_json(path: Path, label: str) -> Tuple[bytes, Mapping[str, Any]]:
    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8", "strict"),
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, InvalidOperation) as exc:
        raise GateFailure("%s is not strict UTF-8 JSON" % label) from exc
    _require(isinstance(value, Mapping), "%s JSON root is not an object" % label)
    return payload, value


def _canonical_number(value: Decimal) -> str:
    _require(value.is_finite(), "canonical JSON number is not finite")
    if value == 0:
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _canonical_fragment(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, Decimal):
        return _canonical_number(value)
    if isinstance(value, Mapping):
        _require(all(isinstance(key, str) for key in value), "JSON object has a non-string key")
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            + ":"
            + _canonical_fragment(value[key])
            for key in sorted(value)
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_canonical_fragment(item) for item in value) + "]"
    raise GateFailure("unsupported canonical JSON value: %s" % type(value).__name__)


def _canonical_bytes(value: Any) -> bytes:
    return _canonical_fragment(value).encode("utf-8", "strict")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_revision(source: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        list(source.joinpath("blender").rglob("*.py"))
        + list(source.joinpath("shared").rglob("*.py")),
        key=lambda path: path.relative_to(source).as_posix(),
    )
    _require(bool(files), "clean export contains no source files for provenance")
    for path in files:
        relative = path.relative_to(source).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _container_source_revision(source: Path) -> str:
    """Independently reproduce the image's framed source-tree digest.

    The image calls ``shared.source_revision`` with ``include_launcher=True``.
    This gate deliberately does not import that implementation from the clean
    export: it selects the same immutable inputs and reimplements the framing
    before comparing its result with the value baked into the image.
    """

    files: List[Path] = []
    for directory in ("blender", "shared", "builder_cli"):
        files.extend((source / directory).rglob("*.py"))
    files.extend((source / "pyproject.toml", source / "scripts" / "builder"))
    files.sort(key=lambda path: path.relative_to(source).as_posix())
    _require(bool(files), "clean export lacks container provenance sources")
    digest = hashlib.sha256()
    for path in files:
        _require(
            path.is_file() and not path.is_symlink(),
            "clean export lacks a fixed container provenance input",
        )
        relative = path.relative_to(source).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _tree_hash(source: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        path = source / relative
        payload = path.read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _assert_path_free(value: Any, forbidden_roots: Sequence[Path], label: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_path_free(item, forbidden_roots, "%s.%s" % (label, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_path_free(item, forbidden_roots, "%s[%s]" % (label, index))
    elif isinstance(value, str):
        _require(PATH_LIKE.match(value) is None, "%s contains a local path" % label)
        _require("file://" not in value.lower(), "%s contains a file URI" % label)
        for root in forbidden_roots:
            _require(str(root) not in value, "%s embeds a forbidden local root" % label)


def _regular_nonempty(path: Path, label: str) -> None:
    _require(not path.is_symlink(), "%s is a symbolic link" % label)
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise GateFailure("%s could not be statted" % label) from exc
    _require(stat.S_ISREG(mode), "%s is not a regular file" % label)
    _require(path.stat().st_size > 0, "%s is empty" % label)


def _assert_binary_framing(output: Path) -> Mapping[str, int]:
    with (output / "model.blend").open("rb") as stream:
        blend_header = stream.read(7)
    _require(
        blend_header == b"BLENDER" or blend_header[:4] == b"\x28\xb5\x2f\xfd",
        "model.blend header is neither raw Blender nor Zstandard-compressed Blender",
    )
    glb_path = output / "model.glb"
    with glb_path.open("rb") as stream:
        glb_header = stream.read(12)
    _require(len(glb_header) == 12 and glb_header[:4] == b"glTF", "model.glb header is invalid")
    version, declared = struct.unpack_from("<II", glb_header, 4)
    _require(version == 2 and declared == glb_path.stat().st_size, "model.glb framing is invalid")
    stl_path = output / "model.stl"
    with stl_path.open("rb") as stream:
        stl_header = stream.read(84)
    _require(len(stl_header) == 84, "model.stl is truncated")
    triangles = struct.unpack_from("<I", stl_header, 80)[0]
    _require(4 <= triangles <= MAX_TRIANGLES, "model.stl triangle count violates policy")
    _require(stl_path.stat().st_size == 84 + triangles * 50, "model.stl binary framing is invalid")
    png_dimensions: Dict[str, List[int]] = {}
    for relative in (
        "preview.png",
        "diagnostics/front.png",
        "diagnostics/side.png",
        "diagnostics/back.png",
    ):
        with (output / relative).open("rb") as stream:
            header = stream.read(24)
        _require(
            len(header) == 24 and header[:8] == PNG_SIGNATURE and header[12:16] == b"IHDR",
            "%s is not a framed PNG" % relative,
        )
        width, height = struct.unpack_from(">II", header, 16)
        _require(0 < width <= 1024 and 0 < height <= 1024, "%s dimensions violate policy" % relative)
        png_dimensions[relative] = [width, height]
    return {
        "glb_bytes": glb_path.stat().st_size,
        "png_dimensions": png_dimensions,
        "stl_triangles": triangles,
    }


def _assert_exact_tree(output: Path) -> None:
    _require(output.is_dir() and not output.is_symlink(), "artifact output is not a real directory")
    files: set = set()
    directories: set = set()
    for path in output.rglob("*"):
        relative = path.relative_to(output).as_posix()
        _require(not path.is_symlink(), "artifact tree contains a symbolic link")
        if path.is_dir():
            directories.add(relative)
        else:
            _regular_nonempty(path, relative)
            files.add(relative)
    _require(files == REQUIRED_FILES, "published file tree differs from complete-v1")
    _require(directories == REQUIRED_DIRECTORIES, "published directory tree differs from complete-v1")
    manifest_mtime = (output / "manifest.json").stat().st_mtime_ns
    _require(
        manifest_mtime >= max((output / name).stat().st_mtime_ns for name in HASHED_ARTIFACTS),
        "success manifest was not written last",
    )


def _expect_keys(value: Mapping[str, Any], expected: Sequence[str], label: str) -> None:
    _require(set(value) == set(expected), "%s fields differ from the versioned contract" % label)


def _validate_artifacts(
    output: Path,
    *,
    request_path: Path,
    source_revision: str,
    execution_mode: str,
    image_reference: Optional[str],
    image_evidence: Optional[Mapping[str, Any]],
    expected_blender_binary_sha256: str,
    forbidden_roots: Sequence[Path],
) -> Mapping[str, Any]:
    _assert_exact_tree(output)
    framing = _assert_binary_framing(output)
    request_payload, request = _load_json(request_path, "BuildRequest")
    del request_payload
    manifest_payload, manifest = _load_json(output / "manifest.json", "manifest.json")
    qa_payload, qa = _load_json(output / "qa.json", "qa.json")
    _require(manifest_payload == _canonical_bytes(manifest) + b"\n", "manifest.json is not canonical JSON")
    _require(qa_payload == _canonical_bytes(qa) + b"\n", "qa.json is not canonical JSON")
    _assert_path_free(manifest, forbidden_roots, "$.manifest")
    _assert_path_free(qa, forbidden_roots, "$.qa")

    _expect_keys(
        manifest,
        (
            "artifacts",
            "dimensions_mm",
            "execution",
            "generator_version",
            "input_sha256",
            "manifest_version",
            "qa",
            "request_sha256",
            "spec_sha256",
        ),
        "manifest",
    )
    _require(manifest["manifest_version"] == "manifest/v1", "manifest version mismatch")
    _require(manifest["generator_version"] == "1.0.0", "generator version mismatch")
    _require(manifest["input_sha256"] == {}, "v0.1 manifest contains external inputs")
    _require(manifest["request_sha256"] == _canonical_sha256(request), "canonical request hash mismatch")
    _require(manifest["spec_sha256"] == _canonical_sha256(request["spec"]), "canonical spec hash mismatch")
    dimensions = manifest["dimensions_mm"]
    _require(
        isinstance(dimensions, list)
        and len(dimensions) == 3
        and all(isinstance(item, Decimal) and item.is_finite() and item > 0 for item in dimensions),
        "manifest dimensions are invalid",
    )

    execution = manifest["execution"]
    _require(isinstance(execution, Mapping), "manifest execution is not an object")
    _expect_keys(
        execution,
        (
            "blender_binary_sha256",
            "blender_version",
            "mode",
            "project_revision",
            "worker_image_digest",
            "worker_image_id",
            "worker_image_reference",
        ),
        "manifest.execution",
    )
    _require(execution["mode"] == execution_mode, "manifest execution mode mismatch")
    _require(execution["project_revision"] == source_revision, "manifest source revision mismatch")
    _require(execution["blender_version"] == BLENDER_VERSION, "manifest Blender version mismatch")
    _require(
        isinstance(execution["blender_binary_sha256"], str)
        and SHA256.fullmatch(execution["blender_binary_sha256"]) is not None,
        "manifest Blender binary hash is invalid",
    )
    _require(
        execution["blender_binary_sha256"] == expected_blender_binary_sha256,
        "manifest Blender binary provenance mismatch",
    )
    if execution_mode == "native":
        _require(
            execution["worker_image_reference"] is None
            and execution["worker_image_digest"] is None
            and execution["worker_image_id"] is None,
            "native fallback retained container provenance",
        )
    else:
        _require(image_reference is not None and image_evidence is not None, "container validation lacks image evidence")
        _require(execution["worker_image_reference"] == image_reference, "worker image reference mismatch")
        _require(execution["worker_image_id"] == image_evidence["image_id"], "worker image ID mismatch")
        repo_digests = set(image_evidence["repo_digests"])
        recorded_digest = execution["worker_image_digest"]
        # The local Make path records the image ID but intentionally makes no
        # registry-digest claim.  A service may inject a pinned OCI digest; if
        # it does, Docker's independently inspected metadata must support it.
        if recorded_digest is not None:
            _require(recorded_digest in repo_digests, "worker OCI digest does not match docker inspect")

    artifact_entries = manifest["artifacts"]
    _require(isinstance(artifact_entries, Mapping), "manifest artifacts is not an object")
    _require(set(artifact_entries) == HASHED_ARTIFACTS, "manifest artifact names differ from exact output contract")
    total_bytes = 0
    recomputed: Dict[str, Mapping[str, Any]] = {}
    for relative in sorted(HASHED_ARTIFACTS):
        entry = artifact_entries[relative]
        _require(isinstance(entry, Mapping) and set(entry) == {"bytes", "sha256"}, "invalid artifact entry")
        path = output / relative
        size = path.stat().st_size
        digest = _sha256_file(path)
        _require(entry["bytes"] == size, "%s byte count mismatch" % relative)
        _require(entry["sha256"] == digest, "%s SHA-256 mismatch" % relative)
        total_bytes += size
        recomputed[relative] = {"bytes": size, "sha256": digest}
    _require(total_bytes <= MAX_ARTIFACT_BYTES, "published artifacts exceed 2 GiB")

    _expect_keys(qa, ("checks", "measurements", "notes", "qa_version", "status"), "qa.json")
    _require(qa["qa_version"] == "qa/v1" and qa["status"] == "passed", "mandatory QA did not pass")
    checks = qa["checks"]
    _require(isinstance(checks, Mapping), "QA checks is not an object")
    required_true = {
        "finite_geometry",
        "fresh_reload",
        "glb_reimport",
        "height_within_tolerance",
        "manifold",
        "outward_normals",
        "positive_volume",
        "stl_reimport",
    }
    _require(set(checks) == required_true, "QA check fields differ from qa/v1")
    _require(all(checks[name] is True for name in required_true), "one or more mandatory QA checks failed")
    measurements = qa["measurements"]
    _require(isinstance(measurements, Mapping), "QA measurements is not an object")
    _require(
        set(measurements)
        == {
            "connected_shells",
            "dimensions_mm",
            "glb_dimensions_mm",
            "material_count",
            "minimum_feature_mm",
            "minimum_wall_mm",
            "non_manifold_edges",
            "object_count",
            "requested_height_mm",
            "stl_dimensions_mm",
            "triangle_count",
            "zero_area_faces",
        },
        "QA measurement fields differ from qa/v1",
    )
    for field in ("dimensions_mm", "glb_dimensions_mm", "stl_dimensions_mm"):
        measured_dimensions = measurements[field]
        _require(
            isinstance(measured_dimensions, list)
            and len(measured_dimensions) == 3
            and all(
                isinstance(item, Decimal) and item.is_finite() and item > 0
                for item in measured_dimensions
            ),
            "QA %s are invalid" % field,
        )
    _require(measurements["dimensions_mm"] == dimensions, "manifest and QA dimensions disagree")
    notes = qa["notes"]
    _require(
        isinstance(notes, list)
        and bool(notes)
        and all(isinstance(note, str) and bool(note.strip()) for note in notes),
        "QA notes are absent or invalid",
    )
    _require(measurements.get("non_manifold_edges") == 0, "QA reports non-manifold edges")
    _require(measurements.get("zero_area_faces") == 0, "QA reports zero-area faces")
    _require(measurements.get("connected_shells") == 1, "QA reports multiple shells")
    triangle_count = measurements.get("triangle_count")
    minimum_wall = measurements.get("minimum_wall_mm")
    minimum_feature = measurements.get("minimum_feature_mm")
    _require(
        isinstance(triangle_count, Decimal)
        and triangle_count.is_finite()
        and triangle_count == triangle_count.to_integral_value()
        and 0 < triangle_count <= MAX_TRIANGLES,
        "QA triangle count is invalid or above policy",
    )
    for field, maximum in (("object_count", 256), ("material_count", 64)):
        count = measurements[field]
        _require(
            isinstance(count, Decimal)
            and count.is_finite()
            and count == count.to_integral_value()
            and 0 < count <= maximum,
            "QA %s is invalid or above policy" % field,
        )
    requested_height = measurements["requested_height_mm"]
    _require(
        isinstance(requested_height, Decimal)
        and requested_height.is_finite()
        and Decimal("25") <= requested_height <= Decimal("250"),
        "QA requested height is outside policy",
    )
    _require(
        isinstance(minimum_wall, Decimal)
        and minimum_wall.is_finite()
        and minimum_wall >= Decimal("1.2"),
        "QA wall minimum failed",
    )
    _require(
        isinstance(minimum_feature, Decimal)
        and minimum_feature.is_finite()
        and minimum_feature >= Decimal("2.0"),
        "QA feature minimum failed",
    )

    manifest_qa = manifest["qa"]
    _require(isinstance(manifest_qa, Mapping), "manifest QA summary is not an object")
    expected_summary = {
        "connected_shells": measurements["connected_shells"],
        "fresh_reload": checks["fresh_reload"],
        "glb_reimport": checks["glb_reimport"],
        "manifold": checks["manifold"],
        "minimum_feature_mm": measurements["minimum_feature_mm"],
        "minimum_wall_mm": measurements["minimum_wall_mm"],
        "non_manifold_edges": measurements["non_manifold_edges"],
        "positive_volume": checks["positive_volume"],
        "status": qa["status"],
        "stl_reimport": checks["stl_reimport"],
    }
    _require(dict(manifest_qa) == expected_summary, "manifest QA summary disagrees with qa.json")
    return {
        "artifacts": recomputed,
        "execution": dict(execution),
        "framing": framing,
        "manifest": manifest,
        "qa": qa,
        "total_bytes": total_bytes,
    }


def _tracked_export(
    git: Path,
    work_dir: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> Tuple[Path, List[str], str]:
    source = work_dir / "source"
    source.mkdir(mode=0o700)
    tracked_raw = _command_output(
        (str(git), "ls-files", "-z"),
        cwd=ROOT,
        environment=environment,
        timeout_seconds=timeout_seconds,
        label="git ls-files",
        work_dir=work_dir,
    )
    tracked = [item for item in tracked_raw.split("\0") if item]
    _require(bool(tracked), "Git index is empty")
    _command_output(
        (str(git), "checkout-index", "--all", "--prefix=" + str(source) + os.sep),
        cwd=ROOT,
        environment=environment,
        timeout_seconds=timeout_seconds,
        label="git checkout-index",
        work_dir=work_dir,
    )
    actual: List[str] = []
    for path in source.rglob("*"):
        _require(not path.is_symlink(), "clean source export contains a symbolic link")
        if path.is_file():
            actual.append(path.relative_to(source).as_posix())
    _require(set(actual) == set(tracked), "clean export differs from the intentional Git index")
    required = {
        ".dockerignore",
        "Makefile",
        "docker/builder.Dockerfile",
        "tests/container/g4_gate.py",
        "tests/container/test_builder_cli_exit_codes.py",
        "tests/security/g4_runtime_policy.py",
        "tests/security/test_g4_runtime_policy.py",
    }
    _require(required.issubset(actual), "G4 production or gate files are absent from the Git index")
    _require(not (source / ".git").exists(), "clean export unexpectedly contains .git")
    _require(not (source / ".env").exists(), "clean export unexpectedly contains .env")
    _require(not (source / "build").exists(), "clean export unexpectedly contains generated build state")
    forbidden_suffixes = {".key", ".p12", ".pem", ".pfx"}
    for relative in actual:
        path = Path(relative)
        lowered_parts = {part.lower() for part in path.parts}
        _require(
            not (path.name.startswith(".env.") and path.name != ".env.example"),
            "clean export contains a private environment file",
        )
        _require(
            not ({"credentials", "secrets"} & lowered_parts),
            "clean export contains a credential directory",
        )
        _require(path.suffix.lower() not in forbidden_suffixes, "clean export contains a key-like file")
    return source, tracked, _tree_hash(source, tracked)


def _write_proxy(proxy: Path) -> None:
    payload = """#!/usr/bin/env python3
import json
import os
import sys

record = {"argv": sys.argv[1:], "cwd": os.getcwd()}
line = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\\n").encode("utf-8")
descriptor = os.open(os.environ["G4_DOCKER_LOG"], os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
try:
    os.write(descriptor, line)
finally:
    os.close(descriptor)
real = os.environ["G4_REAL_DOCKER"]
os.execv(real, [real] + sys.argv[1:])
"""
    proxy.parent.mkdir(parents=True, mode=0o700)
    proxy.write_text(payload, encoding="utf-8")
    proxy.chmod(0o700)


def _proxy_records(path: Path) -> List[Mapping[str, Any]]:
    if not path.exists():
        return []
    records: List[Mapping[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateFailure("Docker proxy log contains malformed JSON") from exc
        _require(
            isinstance(record, Mapping)
            and isinstance(record.get("argv"), list)
            and all(isinstance(item, str) for item in record["argv"])
            and isinstance(record.get("cwd"), str),
            "Docker proxy record is invalid",
        )
        records.append(record)
    return records


def _option_values(argv: Sequence[str], name: str) -> List[str]:
    values: List[str] = []
    for index, token in enumerate(argv):
        if token == name and index + 1 < len(argv):
            values.append(argv[index + 1])
        if token.startswith(name + "="):
            values.append(token.split("=", 1)[1])
    return values


def _assert_source_build(record: Mapping[str, Any], source: Path, image: str, platform: str) -> None:
    argv = record["argv"]
    _require(argv and argv[0] == "build", "clean source did not invoke docker build")
    _require(Path(record["cwd"]).resolve() == source.resolve(), "docker build ran outside the clean export")
    _require(argv[-1] == ".", "docker build context is not the clean current directory")
    _require(_option_values(argv, "--file") == ["docker/builder.Dockerfile"], "unexpected builder Dockerfile")
    _require(_option_values(argv, "--target") == ["builder"], "docker build did not select the production target")
    _require(_option_values(argv, "--tag") == [image], "docker build tag mismatch")
    _require(_option_values(argv, "--platform") == [platform], "docker build platform mismatch")
    forbidden = {"--build-arg", "--build-context", "--secret", "--ssh"}
    _require(not any(token.split("=", 1)[0] in forbidden for token in argv), "docker build received a secret-capable option")


def _docker_connection_environment(
    docker: Path,
    work_dir: Path,
    base_environment: Mapping[str, str],
    timeout_seconds: int,
) -> Dict[str, str]:
    # Resolve the selected local context once, then use an empty Docker config
    # for the gate.  This proves the source build needs no registry login while
    # retaining access to Docker Desktop's or Engine's local Unix endpoint.
    output = _command_output(
        (str(docker), "context", "inspect", "--format", "{{(index .Endpoints \"docker\").Host}}"),
        cwd=ROOT,
        environment=base_environment,
        timeout_seconds=min(timeout_seconds, 60),
        label="docker context inspect",
        work_dir=work_dir,
    ).strip()
    _require(output.startswith("unix://"), "G4 gate requires a local Unix Docker endpoint")
    config = work_dir / "empty-docker-config"
    config.mkdir(mode=0o700)
    empty_home = work_dir / "empty-home"
    empty_home.mkdir(mode=0o700)
    empty_xdg = work_dir / "empty-xdg-config"
    empty_xdg.mkdir(mode=0o700)
    environment = dict(base_environment)
    environment["DOCKER_CONFIG"] = str(config)
    environment["DOCKER_HOST"] = output
    environment["HOME"] = str(empty_home)
    environment["XDG_CONFIG_HOME"] = str(empty_xdg)
    environment.pop("DOCKER_CONTEXT", None)
    return environment


def _inspect_image(
    docker: Path,
    image: str,
    environment: Mapping[str, str],
    work_dir: Path,
    timeout_seconds: int,
) -> Mapping[str, Any]:
    output = _command_output(
        (str(docker), "image", "inspect", image),
        cwd=work_dir,
        environment=environment,
        timeout_seconds=min(timeout_seconds, 120),
        label="docker image inspect independent",
        work_dir=work_dir,
    )
    try:
        values = json.loads(output)
    except json.JSONDecodeError as exc:
        raise GateFailure("docker image inspect did not return JSON") from exc
    _require(isinstance(values, list) and len(values) == 1 and isinstance(values[0], Mapping), "unexpected image inspect result")
    return values[0]


def _inspect_baked_source_revision(
    docker: Path,
    image: str,
    environment: Mapping[str, str],
    work_dir: Path,
    timeout_seconds: int,
) -> Mapping[str, Any]:
    command = (
        str(docker),
        "run",
        "--rm",
        "--platform",
        DEFAULT_PLATFORM,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "16",
        "--cpus",
        "1",
        "--memory",
        "256m",
        "--user",
        "65532:65532",
        "--entrypoint",
        "/bin/cat",
        image,
        "/opt/builder/provenance/source-tree.sha256",
        "/opt/builder/provenance/blender-version.txt",
        "/opt/builder/provenance/blender-binary.sha256",
        "/opt/builder/provenance/sbom.spdx.json",
    )
    output = _command_output(
        command,
        cwd=work_dir,
        environment=environment,
        timeout_seconds=min(timeout_seconds, 120),
        label="baked source provenance inspect",
        work_dir=work_dir,
    ).splitlines()
    _require(len(output) == 4, "image provenance audit returned an unexpected line count")
    source_revision = output[0].strip()
    blender_version = output[1].strip()
    binary_fields = output[2].split()
    _require(SHA256.fullmatch(source_revision) is not None, "image source provenance file is invalid")
    _require(blender_version == BLENDER_VERSION, "image baked Blender version is invalid")
    _require(
        len(binary_fields) == 2
        and SHA256.fullmatch(binary_fields[0]) is not None
        and binary_fields[1] == "/opt/blender/blender",
        "image baked Blender binary provenance is invalid",
    )
    try:
        sbom = json.loads(
            output[3],
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise GateFailure("image SPDX SBOM is not strict JSON") from exc
    _require(isinstance(sbom, Mapping), "image SPDX SBOM root is not an object")
    _require(sbom.get("spdxVersion") == "SPDX-2.3", "image SBOM SPDX version mismatch")
    _require(sbom.get("dataLicense") == "CC0-1.0", "image SBOM data license mismatch")
    namespace = sbom.get("documentNamespace")
    _require(
        isinstance(namespace, str) and namespace.endswith("/" + source_revision),
        "image SBOM namespace lacks source provenance",
    )
    packages = sbom.get("packages")
    _require(isinstance(packages, list) and len(packages) > 3, "image SBOM package inventory is incomplete")
    by_spdx_id = {
        package.get("SPDXID"): package
        for package in packages
        if isinstance(package, Mapping) and isinstance(package.get("SPDXID"), str)
    }
    project = by_spdx_id.get("SPDXRef-Package-HBCB")
    blender_package = by_spdx_id.get("SPDXRef-Package-Blender")
    base = by_spdx_id.get("SPDXRef-Package-Debian-Base")
    _require(
        isinstance(project, Mapping)
        and project.get("licenseDeclared") == "GPL-3.0-or-later"
        and project.get("checksums")
        == [{"algorithm": "SHA256", "checksumValue": source_revision}],
        "image SBOM project package is invalid",
    )
    _require(
        isinstance(blender_package, Mapping)
        and blender_package.get("versionInfo") == BLENDER_VERSION
        and blender_package.get("licenseDeclared") == "GPL-3.0-or-later"
        and blender_package.get("checksums")
        == [{"algorithm": "SHA256", "checksumValue": BLENDER_DOWNLOAD_SHA256}],
        "image SBOM Blender package is invalid",
    )
    _require(isinstance(base, Mapping), "image SBOM lacks its pinned base package")
    _require(
        output[3] == json.dumps(sbom, sort_keys=True, separators=(",", ":")),
        "image SPDX SBOM is not canonical JSON",
    )
    return {
        "blender_binary_sha256": binary_fields[0],
        "blender_version": blender_version,
        "sbom_package_count": len(packages),
        "sbom_sha256": hashlib.sha256((output[3] + "\n").encode("utf-8")).hexdigest(),
        "source_revision": source_revision,
    }


def _scan_files_for_canaries(root: Path, canaries: Sequence[str]) -> None:
    needles = [item.encode("utf-8") for item in canaries]
    paths: Iterable[Path] = (root,) if root.is_file() else root.rglob("*")
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            overlap = b""
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                payload = overlap + chunk
                _require(not _contains_any(payload, needles), "artifact contains a canary credential")
                overlap = payload[-256:]


def _find_records(records: Sequence[Mapping[str, Any]], command: str) -> List[Mapping[str, Any]]:
    return [record for record in records if record["argv"] and record["argv"][0] == command]


def _replace_mount_source(argv: Sequence[str], target: str, source: Path, *, readonly: Optional[bool] = None) -> List[str]:
    result = list(argv)
    found = False
    index = 0
    while index < len(result):
        token = result[index]
        inline = token.startswith("--mount=")
        if token == "--mount" and index + 1 < len(result):
            value_index = index + 1
            raw = result[value_index]
        elif inline:
            value_index = index
            raw = token.split("=", 1)[1]
        else:
            index += 1
            continue
        parts = raw.split(",")
        parsed: Dict[str, str] = {}
        order: List[str] = []
        for part in parts:
            key, separator, value = part.partition("=")
            canonical = {"src": "source", "dst": "target"}.get(key, key)
            parsed[canonical] = value if separator else "true"
            order.append(canonical)
        if parsed.get("target") == target:
            parsed["source"] = str(source.resolve())
            if readonly is True:
                parsed["readonly"] = "true"
            elif readonly is False:
                parsed.pop("readonly", None)
            canonical_order = [item for item in order if item != "readonly"]
            if "source" not in canonical_order:
                canonical_order.insert(1, "source")
            if readonly is True:
                canonical_order.append("readonly")
            rendered = []
            for key in canonical_order:
                if key == "readonly" and parsed[key] == "true":
                    rendered.append("readonly")
                else:
                    rendered.append("%s=%s" % (key, parsed[key]))
            replacement = ",".join(rendered)
            result[value_index] = "--mount=" + replacement if inline else replacement
            found = True
            break
        index = value_index + 1
    _require(found, "could not replace fixed Docker mount target %s" % target)
    return result


def _replace_env(argv: Sequence[str], name: str, value: str) -> List[str]:
    result = list(argv)
    index = 0
    while index < len(result):
        token = result[index]
        if token == "--env" and index + 1 < len(result):
            if result[index + 1].split("=", 1)[0] == name:
                result[index + 1] = name + "=" + value
                return result
            index += 2
            continue
        if token.startswith("--env=") and token.split("=", 1)[1].split("=", 1)[0] == name:
            result[index] = "--env=" + name + "=" + value
            return result
        index += 1
    raise GateFailure("Docker invocation omitted reserved environment %s" % name)


def _run_expected_exit(
    docker: Path,
    baseline_argv: Sequence[str],
    *,
    request: Path,
    output_parent: Path,
    expected_exit: int,
    label: str,
    environment: Mapping[str, str],
    work_dir: Path,
    timeout_seconds: int,
    canaries: Sequence[str],
    runtime_uid: int,
    runtime_gid: int,
    extra_cli: Sequence[str] = (),
    empty_reference: bool = False,
    preexisting_output: bool = False,
) -> Mapping[str, Any]:
    output_parent.mkdir(parents=True, mode=0o700)
    if os.getuid() == 0:
        try:
            os.chown(output_parent, runtime_uid, runtime_gid)
        except OSError as exc:
            raise GateFailure("could not prepare root-host negative-test output ownership") from exc
    argv = _replace_mount_source(baseline_argv, "/input/request.json", request)
    argv = _replace_mount_source(argv, "/output", output_parent, readonly=False)
    if empty_reference:
        argv = _replace_env(argv, "HBCB_WORKER_IMAGE_REFERENCE", "")
    if extra_cli:
        argv.extend(extra_cli)
    marker: Optional[Path] = None
    if preexisting_output:
        published = output_parent / "demo"
        published.mkdir(mode=0o700)
        marker = published / "caller-owned.txt"
        marker.write_text("preserve\n", encoding="utf-8")
    completed = _run(
        (str(docker), *argv),
        cwd=work_dir / "source",
        environment=environment,
        timeout_seconds=timeout_seconds,
        label=label,
        log_path=work_dir / "logs" / (label + ".log"),
        work_dir=work_dir,
        canaries=canaries,
    )
    if completed.returncode != expected_exit:
        raise GateFailure(
            "%s expected exit %s, observed %s\n%s"
            % (label, expected_exit, completed.returncode, _redact(completed.stdout, work_dir))
        )
    _require("BLENDER_BUILDER: PASS" not in completed.stdout, "%s reported build success" % label)
    published = output_parent / "demo"
    if marker is None:
        _require(not published.exists(), "%s published partial output" % label)
    else:
        _require(marker.read_text(encoding="utf-8") == "preserve\n", "%s modified caller output" % label)
        _require(set(item.name for item in published.iterdir()) == {marker.name}, "%s added caller-output files" % label)
    leftovers = list(output_parent.glob(".demo.launcher-*")) + list(
        output_parent.glob(".demo.staging-*")
    )
    _require(not leftovers, "%s left private launcher or runner staging" % label)
    return {
        "elapsed_seconds": round(float(getattr(completed, "g4_elapsed_seconds", 0.0)), 3),
        "exit_code": completed.returncode,
    }


def _probe(
    blender: Path,
    source: Path,
    output: Path,
    request: Path,
    result: Path,
    environment: Mapping[str, str],
    work_dir: Path,
    timeout_seconds: int,
    label: str,
) -> Mapping[str, Any]:
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
        str(source / "tests" / "blender_integration" / "g3_artifact_probe.py"),
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
    completed = _run(
        command,
        cwd=source,
        environment=environment,
        timeout_seconds=timeout_seconds,
        label=label,
        log_path=work_dir / "logs" / (label + ".log"),
        work_dir=work_dir,
    )
    if completed.returncode != 0 or "G3_ARTIFACT_PROBE: PASS" not in completed.stdout:
        raise GateFailure(
            "%s failed\n%s" % (label, _redact(completed.stdout, work_dir, (blender,)))
        )
    _payload, evidence = _load_json(result, label + " evidence")
    _require(evidence.get("status") == "passed", "%s evidence did not pass" % label)
    _require(evidence.get("blender_version") == BLENDER_VERSION, "%s used wrong Blender" % label)
    _require(isinstance(evidence.get("stable"), Mapping), "%s omitted stable evidence" % label)
    _require(
        evidence.get("stable_sha256") == _canonical_sha256(evidence["stable"]),
        "%s stable evidence hash mismatch" % label,
    )
    return evidence


def _stable_manifest(report: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = report["manifest"]
    return {
        key: manifest[key]
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


def _write_summary(path: Path, summary: Mapping[str, Any]) -> None:
    _require(not path.exists(), "refusing to overwrite G4 summary")
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the explicit G4 clean-source container gate")
    parser.add_argument("--work-dir", required=True, help="new absolute temporary directory outside the repository")
    parser.add_argument("--docker", default="docker", help="Docker CLI name or absolute path")
    parser.add_argument("--make", default="make", help="GNU Make name or absolute path")
    parser.add_argument("--git", default="git", help="Git name or absolute path")
    parser.add_argument("--blender", required=True, help="absolute Blender 4.5.12 executable for native parity")
    parser.add_argument("--platform", default=DEFAULT_PLATFORM, choices=(DEFAULT_PLATFORM,))
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args(argv)
    _require(60 <= args.timeout_seconds <= 3600, "--timeout-seconds must be between 60 and 3600")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    _require(
        hasattr(os, "getuid")
        and hasattr(os, "getgid"),
        "G4 requires Unix numeric UID:GID support",
    )
    runtime_uid = os.getuid() or 65532
    runtime_gid = os.getgid() or 65532
    expected_runtime_user = "%s:%s" % (runtime_uid, runtime_gid)
    work_dir = _work_dir(args.work_dir)
    docker = _executable(args.docker, "Docker")
    make = _executable(args.make, "Make")
    git = _executable(args.git, "Git")
    blender = _executable(args.blender, "Blender")
    _require(Path(args.blender).expanduser().is_absolute(), "--blender must be an explicit absolute path")

    base_environment = _base_environment()
    blender_version = _command_output(
        (str(blender), "--version"),
        cwd=ROOT,
        environment=base_environment,
        timeout_seconds=60,
        label="native Blender version",
        work_dir=work_dir,
    ).splitlines()
    _require(bool(blender_version) and blender_version[0] == "Blender " + BLENDER_VERSION, "native parity requires Blender " + BLENDER_VERSION)
    make_version = _command_output(
        (str(make), "--version"),
        cwd=ROOT,
        environment=base_environment,
        timeout_seconds=60,
        label="make version",
        work_dir=work_dir,
    ).splitlines()
    _require(bool(make_version) and make_version[0].startswith("GNU Make "), "G4 requires GNU Make")

    source, tracked, source_tree_hash = _tracked_export(
        git, work_dir, base_environment, args.timeout_seconds
    )
    native_source_revision = _source_revision(source)
    container_source_revision = _container_source_revision(source)
    docker_environment = _docker_connection_environment(
        docker, work_dir, base_environment, args.timeout_seconds
    )
    docker_version = _command_output(
        (str(docker), "version", "--format", "{{.Client.Version}}|{{.Server.Version}}"),
        cwd=source,
        environment=docker_environment,
        timeout_seconds=60,
        label="docker version",
        work_dir=work_dir,
    ).strip()
    _require("|" in docker_version and all(docker_version.split("|", 1)), "Docker client/server version preflight failed")

    canary_suffix = uuid.uuid4().hex
    canaries = (
        "sk-g4-" + canary_suffix,
        "AKIAG4" + canary_suffix[:16].upper(),
        "g4-secret-" + canary_suffix,
        "g4-wrapper-secret-" + canary_suffix,
    )
    keyless_environment = dict(docker_environment)
    for name in PROVENANCE_ENV:
        keyless_environment.pop(name, None)
    keyless_environment.update(
        {
            "G4_DOCKER_LOG": str(work_dir / "docker-proxy.jsonl"),
            "G4_REAL_DOCKER": str(docker),
        }
    )
    credential_environment = dict(keyless_environment)
    credential_environment.update(
        {
            "AWS_ACCESS_KEY_ID": canaries[1],
            "AWS_SECRET_ACCESS_KEY": canaries[2],
            "HBCB_CANARY_SECRET": canaries[3],
            "OPENAI_API_KEY": canaries[0],
        }
    )
    proxy = work_dir / "tools" / "docker-proxy.py"
    _write_proxy(proxy)
    docker_override = "%s %s" % (shlex.quote(sys.executable), shlex.quote(str(proxy)))
    image = "headless-blender-character-builder:g4-%s-%s" % (
        source_tree_hash[:12],
        uuid.uuid4().hex[:8],
    )
    make_prefix = (
        str(make),
        "DOCKER=" + docker_override,
        "BUILDER_IMAGE=" + image,
        "PLATFORM=" + args.platform,
    )
    proxy_log = work_dir / "docker-proxy.jsonl"

    before = len(_proxy_records(proxy_log))
    first_demo = _run(
        (*make_prefix, "demo"),
        cwd=source,
        environment=keyless_environment,
        timeout_seconds=args.timeout_seconds,
        label="make demo first",
        log_path=work_dir / "logs" / "make-demo-first.log",
        work_dir=work_dir,
        canaries=canaries,
    )
    if first_demo.returncode != 0:
        raise GateFailure(
            "first make demo exited %s\n%s"
            % (first_demo.returncode, _redact(first_demo.stdout, work_dir))
        )
    first_records = _proxy_records(proxy_log)[before:]
    build_records = _find_records(first_records, "build")
    run_records = _find_records(first_records, "run")
    _require(len(build_records) == 1, "first clean demo did not perform exactly one docker source build")
    _require(len(run_records) == 1, "first clean demo did not perform exactly one model container run")
    _assert_source_build(build_records[0], source, image, args.platform)

    first_output = source / "build" / "demo"
    runtime_evidence = assert_hardened_run(
        run_records[0]["argv"],
        clean_source=source,
        workspace=ROOT,
        expected_image=image,
        expected_request=source / "examples" / "requests" / "facet-bot.json",
        expected_output=source / "build",
        expected_platform=args.platform,
        expected_user=expected_runtime_user,
    )
    assert_no_sensitive_mount_text(
        run_records[0]["argv"],
        (ROOT, Path.home(), Path("/var/run/docker.sock")),
    )
    image_raw = _inspect_image(docker, image, docker_environment, work_dir, args.timeout_seconds)
    image_evidence = assert_image_policy(
        image_raw,
        expected_platform=args.platform,
        forbidden_values=canaries,
    )
    baked_provenance = _inspect_baked_source_revision(
        docker, image, docker_environment, work_dir, args.timeout_seconds
    )
    _require(
        baked_provenance["source_revision"] == container_source_revision,
        "baked image provenance differs from independent clean-source calculation",
    )
    first_report = _validate_artifacts(
        first_output,
        request_path=source / "examples" / "requests" / "facet-bot.json",
        source_revision=container_source_revision,
        execution_mode="container",
        image_reference=image,
        image_evidence=image_evidence,
        expected_blender_binary_sha256=baked_provenance["blender_binary_sha256"],
        forbidden_roots=(ROOT, work_dir, Path.home()),
    )
    _scan_files_for_canaries(first_output, canaries)

    verify_before = len(_proxy_records(proxy_log))
    first_verify = _run(
        (*make_prefix, "verify-demo"),
        cwd=source,
        environment=keyless_environment,
        timeout_seconds=args.timeout_seconds,
        label="make verify-demo first",
        log_path=work_dir / "logs" / "make-verify-first.log",
        work_dir=work_dir,
        canaries=canaries,
    )
    if first_verify.returncode != 0:
        raise GateFailure(
            "first make verify-demo exited %s\n%s"
            % (first_verify.returncode, _redact(first_verify.stdout, work_dir))
        )
    verify_records = _proxy_records(proxy_log)[verify_before:]
    verify_runs = _find_records(verify_records, "run")
    _require(len(verify_runs) == 1, "verify-demo did not use one fresh container")
    assert_hardened_run(
        verify_runs[0]["argv"],
        clean_source=source,
        workspace=ROOT,
        expected_image=image,
        expected_request=source / "examples" / "requests" / "facet-bot.json",
        expected_output=source / "build",
        expected_platform=args.platform,
        expected_user=expected_runtime_user,
        expected_command="verify",
        output_readonly=True,
    )
    assert_no_sensitive_mount_text(
        verify_runs[0]["argv"], (ROOT, Path.home(), Path("/var/run/docker.sock"))
    )

    preserved_first = work_dir / "container-first"
    os.rename(first_output, preserved_first)
    second_before = len(_proxy_records(proxy_log))
    second_demo = _run(
        (*make_prefix, "demo"),
        cwd=source,
        environment=credential_environment,
        timeout_seconds=args.timeout_seconds,
        label="make demo repeat",
        log_path=work_dir / "logs" / "make-demo-repeat.log",
        work_dir=work_dir,
        canaries=canaries,
    )
    if second_demo.returncode != 0:
        raise GateFailure(
            "repeat make demo exited %s\n%s"
            % (second_demo.returncode, _redact(second_demo.stdout, work_dir))
        )
    second_records = _proxy_records(proxy_log)[second_before:]
    second_runs = _find_records(second_records, "run")
    _require(len(second_runs) == 1, "repeat demo did not use exactly one model container")
    assert_hardened_run(
        second_runs[0]["argv"],
        clean_source=source,
        workspace=ROOT,
        expected_image=image,
        expected_request=source / "examples" / "requests" / "facet-bot.json",
        expected_output=source / "build",
        expected_platform=args.platform,
        expected_user=expected_runtime_user,
    )
    second_output = source / "build" / "demo"
    repeat_image_raw = _inspect_image(
        docker, image, docker_environment, work_dir, args.timeout_seconds
    )
    repeat_image_evidence = assert_image_policy(
        repeat_image_raw,
        expected_platform=args.platform,
        forbidden_values=canaries,
    )
    _require(
        repeat_image_evidence == image_evidence,
        "repeat source build changed immutable image identity or digest evidence",
    )
    second_report = _validate_artifacts(
        second_output,
        request_path=source / "examples" / "requests" / "facet-bot.json",
        source_revision=container_source_revision,
        execution_mode="container",
        image_reference=image,
        image_evidence=repeat_image_evidence,
        expected_blender_binary_sha256=baked_provenance["blender_binary_sha256"],
        forbidden_roots=(ROOT, work_dir, Path.home()),
    )
    _scan_files_for_canaries(second_output, canaries)
    second_verify_before = len(_proxy_records(proxy_log))
    second_verify = _run(
        (*make_prefix, "verify-demo"),
        cwd=source,
        environment=credential_environment,
        timeout_seconds=args.timeout_seconds,
        label="make verify-demo repeat",
        log_path=work_dir / "logs" / "make-verify-repeat.log",
        work_dir=work_dir,
        canaries=canaries,
    )
    _require(second_verify.returncode == 0, "repeat make verify-demo failed")
    second_verify_records = _proxy_records(proxy_log)[second_verify_before:]
    second_verify_runs = _find_records(second_verify_records, "run")
    _require(len(second_verify_runs) == 1, "repeat verify-demo did not use one fresh container")
    assert_hardened_run(
        second_verify_runs[0]["argv"],
        clean_source=source,
        workspace=ROOT,
        expected_image=image,
        expected_request=source / "examples" / "requests" / "facet-bot.json",
        expected_output=source / "build",
        expected_platform=args.platform,
        expected_user=expected_runtime_user,
        expected_command="verify",
        output_readonly=True,
    )
    _require(first_report["qa"] == second_report["qa"], "repeat QA evidence differs")
    _require(_stable_manifest(first_report) == _stable_manifest(second_report), "repeat stable manifest fields differ")
    preserved_second = work_dir / "container-repeat"
    os.rename(second_output, preserved_second)

    baseline_argv = second_runs[0]["argv"]
    negatives = work_dir / "negative"
    exits: Dict[str, Any] = {}
    exits["2"] = _run_expected_exit(
        docker,
        baseline_argv,
        request=source / "examples" / "requests" / "facet-bot.json",
        output_parent=negatives / "cli",
        expected_exit=2,
        label="exit-2-invalid-cli",
        environment=docker_environment,
        work_dir=work_dir,
        timeout_seconds=args.timeout_seconds,
        canaries=canaries,
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
        extra_cli=("--unsupported",),
    )
    exits["3"] = _run_expected_exit(
        docker,
        baseline_argv,
        request=source / "tests" / "fixtures" / "rejected" / "outer-extra-property.json",
        output_parent=negatives / "request",
        expected_exit=3,
        label="exit-3-invalid-request",
        environment=docker_environment,
        work_dir=work_dir,
        timeout_seconds=args.timeout_seconds,
        canaries=canaries,
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
    )
    exits["4"] = _run_expected_exit(
        docker,
        baseline_argv,
        request=source / "examples" / "requests" / "facet-bot.json",
        output_parent=negatives / "filesystem",
        expected_exit=4,
        label="exit-4-existing-output",
        environment=docker_environment,
        work_dir=work_dir,
        timeout_seconds=args.timeout_seconds,
        canaries=canaries,
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
        preexisting_output=True,
    )
    exits["11"] = _run_expected_exit(
        docker,
        baseline_argv,
        request=source / "examples" / "requests" / "moss-hopper.json",
        output_parent=negatives / "qa",
        expected_exit=11,
        label="exit-11-mandatory-qa",
        environment=docker_environment,
        work_dir=work_dir,
        timeout_seconds=args.timeout_seconds,
        canaries=canaries,
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
    )
    exits["12"] = _run_expected_exit(
        docker,
        baseline_argv,
        request=source / "examples" / "requests" / "facet-bot.json",
        output_parent=negatives / "wrapper",
        expected_exit=12,
        label="exit-12-provenance-contract",
        environment=docker_environment,
        work_dir=work_dir,
        timeout_seconds=args.timeout_seconds,
        canaries=canaries,
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
        empty_reference=True,
    )
    # Code 10 cannot be induced by a valid bounded geometry request without
    # corrupting the trusted image, and black-box code 124 would deliberately
    # consume the full fixed 15-minute budget.  The tracked launcher tests
    # cover those mappings with a missing native binary and a mocked
    # subprocess timeout; the clean-source test-unit target is run below.
    exits["10"] = {"status": "covered_by_clean_source_unit_gate"}
    exits["124"] = {"status": "covered_by_clean_source_unit_gate"}

    native_environment = dict(keyless_environment)
    native_home = work_dir / "native-home"
    native_tmp = work_dir / "native-tmp"
    native_home.mkdir(mode=0o700)
    native_tmp.mkdir(mode=0o700)
    native_environment["HOME"] = str(native_home)
    native_environment["TMPDIR"] = str(native_tmp)
    for name in list(native_environment):
        if name.startswith("HBCB_"):
            native_environment.pop(name, None)
    native_prefix = (
        str(make),
        "DOCKER=" + docker_override,
        "BLENDER=" + str(blender),
        "PYTHON=" + sys.executable,
    )
    native_before = len(_proxy_records(proxy_log))
    native = _run(
        (*native_prefix, "demo-native"),
        cwd=source,
        environment=native_environment,
        timeout_seconds=args.timeout_seconds,
        label="native fallback build",
        log_path=work_dir / "logs" / "native-fallback.log",
        work_dir=work_dir,
    )
    if native.returncode != 0:
        raise GateFailure(
            "native fallback exited %s\n%s"
            % (native.returncode, _redact(native.stdout, work_dir, (blender,)))
        )
    native_output = source / "build" / "demo"
    native_verify = _run(
        (*native_prefix, "verify-demo-native"),
        cwd=source,
        environment=native_environment,
        timeout_seconds=args.timeout_seconds,
        label="native fallback verify",
        log_path=work_dir / "logs" / "native-fallback-verify.log",
        work_dir=work_dir,
    )
    if native_verify.returncode != 0:
        raise GateFailure(
            "native fallback verification exited %s\n%s"
            % (native_verify.returncode, _redact(native_verify.stdout, work_dir, (blender,)))
        )
    _require(
        len(_proxy_records(proxy_log)) == native_before,
        "native fallback unexpectedly invoked Docker",
    )
    native_report = _validate_artifacts(
        native_output,
        request_path=source / "examples" / "requests" / "facet-bot.json",
        source_revision=native_source_revision,
        execution_mode="native",
        image_reference=None,
        image_evidence=None,
        expected_blender_binary_sha256=_sha256_file(blender),
        forbidden_roots=(ROOT, work_dir, Path.home()),
    )
    _scan_files_for_canaries(native_output, canaries)
    preserved_native = work_dir / "native-facet-bot"
    os.rename(native_output, preserved_native)
    native_output = preserved_native

    evidence_dir = work_dir / "evidence"
    evidence_dir.mkdir(mode=0o700)
    first_probe = _probe(
        blender,
        source,
        preserved_first,
        source / "examples" / "requests" / "facet-bot.json",
        evidence_dir / "container-first-probe.json",
        native_environment,
        work_dir,
        args.timeout_seconds,
        "probe-container-first",
    )
    second_probe = _probe(
        blender,
        source,
        preserved_second,
        source / "examples" / "requests" / "facet-bot.json",
        evidence_dir / "container-repeat-probe.json",
        native_environment,
        work_dir,
        args.timeout_seconds,
        "probe-container-repeat",
    )
    native_probe = _probe(
        blender,
        source,
        native_output,
        source / "examples" / "requests" / "facet-bot.json",
        evidence_dir / "native-probe.json",
        native_environment,
        work_dir,
        args.timeout_seconds,
        "probe-native-fallback",
    )
    _require(first_probe["stable"] == second_probe["stable"], "repeat container structural evidence differs")
    _require(second_probe["stable"] == native_probe["stable"], "native fallback lacks structural parity with container")
    _require(
        second_report["manifest"]["request_sha256"] == native_report["manifest"]["request_sha256"]
        and second_report["manifest"]["spec_sha256"] == native_report["manifest"]["spec_sha256"]
        and second_report["manifest"]["generator_version"] == native_report["manifest"]["generator_version"],
        "native fallback contract hashes differ from container",
    )

    unit_before = len(_proxy_records(proxy_log))
    unit = _run(
        (*make_prefix, "test-unit"),
        cwd=source,
        environment=credential_environment,
        timeout_seconds=args.timeout_seconds,
        label="make test-unit clean source",
        log_path=work_dir / "logs" / "make-test-unit.log",
        work_dir=work_dir,
        canaries=canaries,
    )
    if unit.returncode != 0:
        raise GateFailure(
            "clean-source make test-unit exited %s\n%s"
            % (unit.returncode, _redact(unit.stdout, work_dir))
        )
    unit_records = _proxy_records(proxy_log)[unit_before:]
    for record in _find_records(unit_records, "run"):
        assert_no_sensitive_mount_text(
            record["argv"], (ROOT, Path.home(), Path("/var/run/docker.sock"))
        )

    _scan_files_for_canaries(work_dir / "logs", canaries)
    _scan_files_for_canaries(evidence_dir, canaries)
    _scan_files_for_canaries(proxy_log, canaries)
    summary = {
        "artifact_bytes": second_report["total_bytes"],
        "baked_provenance": dict(baked_provenance),
        "blender_version": BLENDER_VERSION,
        "docker_version": docker_version,
        "exit_codes": exits,
        "gate_version": GATE_VERSION,
        "image": image_evidence,
        "image_reference": image,
        "make_version": make_version[0],
        "native_fallback": {
            "execution_mode": native_report["execution"]["mode"],
            "stable_sha256": native_probe["stable_sha256"],
        },
        "platform": args.platform,
        "repeat": {
            "first_stable_sha256": first_probe["stable_sha256"],
            "repeat_stable_sha256": second_probe["stable_sha256"],
        },
        "runtime": runtime_evidence,
        "container_source_revision": container_source_revision,
        "native_source_revision": native_source_revision,
        "source_tree_sha256": source_tree_hash,
        "status": "passed",
        "tracked_file_count": len(tracked),
    }
    summary_path = work_dir / "g4-summary.json"
    _write_summary(summary_path, summary)
    print("G4_GATE: PASS")
    print("G4_GATE_SUMMARY: " + str(summary_path))
    return 0


def _entrypoint() -> None:
    try:
        raise SystemExit(main())
    except (GateFailure, RuntimePolicyFailure) as exc:
        print("G4_GATE: FAIL: %s" % exc, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _entrypoint()
