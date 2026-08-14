"""Trusted launcher commands and the local-filesystem artifact adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from shared.build_manifest import BuildManifest, REQUIRED_ARTIFACTS
from shared.character_spec import BuildRequest
from shared.json_contract import (
    ContractValidationError,
    MAX_BUILD_REQUEST_BYTES,
    canonical_json_bytes,
)
from shared.source_revision import source_revision

from .exit_codes import APPLICATION_FAILURES, ExitCode


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "blender" / "runner.py"
PUBLISHED_VERIFIER = ROOT / "blender" / "published_verifier.py"
CONTAINER_BLENDER = Path("/opt/blender/blender")
PROVENANCE_ROOT = Path("/opt/builder/provenance")
BUILD_TIMEOUT_SECONDS = 15 * 60
PROCESS_TERM_GRACE_SECONDS = 5.0
PROCESS_KILL_GRACE_SECONDS = 5.0
PROCESS_GROUP_POLL_SECONDS = 0.02
PROCESS_SIGNAL_POLL_SECONDS = 0.1
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_VERIFIER_RESULT_BYTES = 64 * 1024
PUBLISHED_VERIFICATION_VERSION = "published-artifact-verifier/v1"
EXACT_FILES = set(REQUIRED_ARTIFACTS) | {"manifest.json"}
EXACT_DIRECTORIES = {"diagnostics"}
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,254}$")
CONTRACT_PATH = re.compile(
    r"^\$(?:(?:\.[A-Za-z_][A-Za-z0-9_]{0,63})|(?:\[[0-9]{1,6}\])){0,16}$"
)
MAX_CONTRACT_PATH_CHARACTERS = 256
PROVENANCE_ENV = (
    "HBCB_EXECUTION_MODE",
    "HBCB_WORKER_IMAGE_REFERENCE",
    "HBCB_WORKER_IMAGE_DIGEST",
    "HBCB_WORKER_IMAGE_ID",
)
REQUEST_REJECTION_REASONS = {
    "duplicate_item": "items that must be unique contain a duplicate",
    "duplicate_key": "duplicate object keys are forbidden",
    "excessive_nesting": "JSON nesting exceeds the supported limit",
    "expected_number": "value must be a number",
    "expected_object": "value must be an object",
    "extra_property": "request contains unsupported field(s)",
    "incompatible_components": "component choices are mutually exclusive",
    "invalid_color": "palette colors must use uppercase #RRGGBB",
    "invalid_components": "components must be a bounded array of supported presets",
    "invalid_enum": "value is not one of the supported choices",
    "invalid_json": "payload is not valid JSON",
    "invalid_json_value": "payload contains an unsupported JSON value",
    "invalid_name": "name does not satisfy the documented character-name format",
    "invalid_number": "payload contains an invalid JSON number",
    "invalid_object_key": "JSON object keys must be strings",
    "invalid_palette": "palette must contain between one and eight colors",
    "invalid_payload_type": "JSON payload must be UTF-8 bytes or text",
    "invalid_slug": "slug must be a 1-48 character lowercase safe slug",
    "invalid_unicode": "JSON contains invalid Unicode",
    "invalid_utf8": "JSON payload must be valid UTF-8",
    "missing_property": "request is missing one or more required fields",
    "nonfinite_number": "non-finite JSON numbers are forbidden",
    "number_out_of_range": "number is outside the supported range",
    "numeric_limit": "JSON number exceeds the bounded numeric policy",
    "payload_too_large": f"JSON payload exceeds the {MAX_BUILD_REQUEST_BYTES}-byte limit",
    "unsupported_contract_value": "value does not match the supported build contract",
    "unsupported_version": "value does not match the supported character-spec version",
}
_TERMINATION_SIGNALS = tuple(
    item
    for item in (
        signal.SIGINT,
        getattr(signal, "SIGHUP", None),
        signal.SIGTERM,
    )
    if isinstance(item, int)
)


class BuilderCliFailure(RuntimeError):
    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = int(exit_code)
        self.message = message


class _TerminationSignal(SystemExit):
    """Preserve the conventional shell status for a recorded TERM or HUP."""

    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(128 + signum)


class _TerminationGuard:
    """Defer CLI-default termination signals until an owned child is published."""

    def __init__(self) -> None:
        self.received: int | None = None
        self.previous: dict[int, Any] = {}
        self.installed: set[int] = set()

    def _record(self, signum: int, _frame: object) -> None:
        if self.received is None:
            self.received = int(signum)

    def __enter__(self) -> _TerminationGuard:
        try:
            for signum in _TERMINATION_SIGNALS:
                previous = signal.getsignal(signum)
                self.previous[signum] = previous
                # An embedding process owns explicit custom/ignored behavior.
                # Python's usual SIGINT handler is the interactive CLI default.
                if previous == signal.SIG_DFL or (
                    signum == signal.SIGINT
                    and previous == signal.default_int_handler
                ):
                    signal.signal(signum, self._record)
                    self.installed.add(signum)
        except (OSError, RuntimeError, ValueError) as exc:
            for installed in self.installed:
                signal.signal(installed, self.previous[installed])
            raise BuilderCliFailure(
                int(ExitCode.INTERNAL),
                "could not establish signal-safe Blender execution",
            ) from exc
        return self

    def __exit__(self, exception_type: object, _value: object, _traceback: object) -> None:
        for signum in self.installed:
            signal.signal(signum, self.previous[signum])
        # A first signal may arrive while teardown is handling an unrelated
        # failure. Preserve the operator-requested signal status in that case.
        self.raise_if_pending()

    def raise_if_pending(self) -> None:
        if self.received is None:
            return
        if self.received == signal.SIGINT:
            raise KeyboardInterrupt
        raise _TerminationSignal(self.received)


def _request_rejection(exc: ContractValidationError) -> str:
    """Render a stable diagnostic without reflecting caller-controlled values."""

    code = exc.code if exc.code in REQUEST_REJECTION_REASONS else "invalid_request"
    path = (
        exc.path
        if isinstance(exc.path, str)
        and len(exc.path) <= MAX_CONTRACT_PATH_CHARACTERS
        and CONTRACT_PATH.fullmatch(exc.path) is not None
        else "$"
    )
    reason = REQUEST_REJECTION_REASONS.get(
        code, "request does not satisfy the supported build contract"
    )
    return f"BuildRequest was rejected: {code} at {path}: {reason}"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not hash artifact") from exc
    return digest.hexdigest()


def _request(raw_path: str) -> tuple[Path, BuildRequest]:
    try:
        path = Path(raw_path).expanduser().resolve(strict=False)
        with path.open("rb") as stream:
            payload = stream.read(MAX_BUILD_REQUEST_BYTES + 1)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not read request") from exc
    try:
        return path, BuildRequest.from_json(payload)
    except ContractValidationError as exc:
        raise BuilderCliFailure(
            int(ExitCode.INVALID_REQUEST), _request_rejection(exc)
        ) from exc
    except (TypeError, ValueError) as exc:
        raise BuilderCliFailure(int(ExitCode.INVALID_REQUEST), "BuildRequest was rejected") from exc


def validate_request(request_path: str) -> None:
    """Validate one bounded BuildRequest without starting Blender or writing output."""

    _request(request_path)


def inspect_manifest(manifest_path: str) -> None:
    """Print one bounded, path-free summary of a canonical success manifest."""

    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(manifest_path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("manifest is not a regular file")
        if metadata.st_size <= 0:
            raise BuilderCliFailure(
                int(ExitCode.VERIFICATION), "success manifest is invalid"
            )
        if metadata.st_size > MAX_MANIFEST_BYTES:
            raise BuilderCliFailure(
                int(ExitCode.VERIFICATION), "success manifest exceeds its size limit"
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(MAX_MANIFEST_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (
                (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
                != (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                )
                or len(payload) != metadata.st_size
            ):
                raise OSError("manifest changed while being read")
    except OSError as exc:
        raise BuilderCliFailure(
            int(ExitCode.FILESYSTEM), "could not read success manifest"
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    try:
        manifest = BuildManifest.from_json(payload)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise BuilderCliFailure(
            int(ExitCode.VERIFICATION), "success manifest is invalid"
        ) from exc
    if payload != manifest.canonical_bytes + b"\n":
        raise BuilderCliFailure(
            int(ExitCode.VERIFICATION), "success manifest is not canonical"
        )
    summary = {
        "artifact_count": len(manifest.artifacts),
        "artifact_total_bytes": sum(
            int(entry["bytes"]) for entry in manifest.artifacts.values()
        ),
        "blender_version": manifest.execution["blender_version"],
        "dimensions_mm": list(manifest.dimensions_mm),
        "execution_mode": manifest.execution["mode"],
        "generator_version": manifest.generator_version,
        "manifest_version": manifest.manifest_version,
        "project_revision": manifest.execution["project_revision"],
        "qa": {
            "connected_shells": manifest.qa["connected_shells"],
            "manifold": manifest.qa["manifold"],
            "minimum_feature_mm": manifest.qa["minimum_feature_mm"],
            "minimum_wall_mm": manifest.qa["minimum_wall_mm"],
            "status": manifest.qa["status"],
        },
        "request_sha256": manifest.request_sha256,
        "spec_sha256": manifest.spec_sha256,
    }
    print(canonical_json_bytes(summary).decode("utf-8", "strict"))


def _new_output(raw_path: str) -> Path:
    try:
        supplied = Path(raw_path).expanduser()
        if supplied.is_symlink():
            raise BuilderCliFailure(
                int(ExitCode.FILESYSTEM), "output must not already exist"
            )
        output = supplied.resolve(strict=False)
    except BuilderCliFailure:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "output path could not be resolved") from exc
    if output.is_symlink() or output.exists():
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "output must not already exist")
    if not output.parent.is_dir():
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "output parent does not exist")
    return output


def _published_output(raw_path: str) -> Path:
    try:
        supplied = Path(raw_path).expanduser()
        if supplied.is_symlink():
            raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "published output cannot be a symlink")
        output = supplied.resolve(strict=True)
    except BuilderCliFailure:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "published output could not be resolved") from exc
    if not output.is_dir():
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "published output is not a directory")
    return output


def _private_stage(output: Path) -> Path:
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.launcher-", dir=str(output.parent)))
        stage.chmod(0o700)
        return stage
    except OSError as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not create launcher staging") from exc


def _execution_context() -> dict[str, str]:
    mode = os.environ.get("HBCB_EXECUTION_MODE")
    values = {key: os.environ[key] for key in PROVENANCE_ENV if key in os.environ}
    if mode is None:
        if values:
            raise BuilderCliFailure(int(ExitCode.INTERNAL), "partial execution provenance")
        return {}
    if mode != "container":
        raise BuilderCliFailure(int(ExitCode.INTERNAL), "unsupported execution mode")
    reference = values.get("HBCB_WORKER_IMAGE_REFERENCE")
    if reference is None or IMAGE_REFERENCE.fullmatch(reference) is None:
        raise BuilderCliFailure(int(ExitCode.INTERNAL), "invalid container image reference")
    for field in ("HBCB_WORKER_IMAGE_DIGEST", "HBCB_WORKER_IMAGE_ID"):
        candidate = values.get(field)
        if candidate is not None and IMAGE_DIGEST.fullmatch(candidate) is None:
            raise BuilderCliFailure(int(ExitCode.INTERNAL), "invalid container image digest")
    return values


def _provenance_text(name: str, maximum_bytes: int = 512) -> str:
    path = PROVENANCE_ROOT / name
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError("unsafe provenance file")
        with path.open("rb") as stream:
            payload = stream.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise OSError("oversized provenance file")
        return payload.decode("utf-8", "strict").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise BuilderCliFailure(int(ExitCode.INTERNAL), "container provenance is unavailable") from exc


def _ensure_runtime_directories(environment: Mapping[str, str]) -> None:
    for field in ("HOME", "TMPDIR"):
        raw = environment.get(field)
        if not raw:
            continue
        try:
            Path(raw).mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise BuilderCliFailure(int(ExitCode.FILESYSTEM), f"could not prepare {field}") from exc


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
    environment.update(_execution_context())
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if environment.get("HBCB_EXECUTION_MODE") == "container":
        environment["LIBGL_ALWAYS_SOFTWARE"] = "1"
    _ensure_runtime_directories(environment)
    return environment


def _blender_binary() -> Path:
    if os.environ.get("HBCB_EXECUTION_MODE") == "container":
        candidate = CONTAINER_BLENDER
    else:
        configured = os.environ.get("HBCB_BLENDER_BINARY")
        discovered = shutil.which("blender") if configured is None else None
        candidate = Path(configured or discovered or "")
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BuilderCliFailure(int(ExitCode.BLENDER), "Blender executable is unavailable") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise BuilderCliFailure(int(ExitCode.BLENDER), "Blender executable is unavailable")
    return resolved


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except (OSError, PermissionError):
        # An unexpected failure cannot prove that all descendants are gone.
        return True
    return True


def _signal_process_group(process: subprocess.Popen[Any], selected_signal: int) -> None:
    try:
        os.killpg(process.pid, selected_signal)
    except ProcessLookupError:
        pass
    except OSError:
        # Retain a direct-child fallback, while group polling below remains
        # fail-closed when a POSIX descendant is still alive.
        try:
            if selected_signal == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
        except OSError:
            pass


def _wait_for_process_group_exit(
    process: subprocess.Popen[Any],
    deadline: float,
) -> bool:
    while True:
        try:
            process.poll()
        except OSError:
            pass
        if not _process_group_exists(process.pid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(PROCESS_GROUP_POLL_SECONDS, remaining))


def _terminate(process: subprocess.Popen[Any]) -> None:
    """Boundedly stop the complete new-session child tree and reap its leader."""

    if os.name == "nt":
        try:
            process.terminate()
            process.wait(timeout=PROCESS_TERM_GRACE_SECONDS)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
            process.wait(timeout=PROCESS_KILL_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return

    _signal_process_group(process, signal.SIGTERM)
    group_gone = _wait_for_process_group_exit(
        process,
        time.monotonic() + PROCESS_TERM_GRACE_SECONDS,
    )
    if not group_gone:
        _signal_process_group(process, signal.SIGKILL)
        _wait_for_process_group_exit(
            process,
            time.monotonic() + PROCESS_KILL_GRACE_SECONDS,
        )
    try:
        if process.poll() is None:
            process.wait(timeout=PROCESS_KILL_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run(command: Sequence[str], environment: Mapping[str, str]) -> int:
    process: subprocess.Popen[Any] | None = None
    with _TerminationGuard() as termination:
        try:
            termination.raise_if_pending()
            spawn_failure: OSError | None = None
            try:
                process = subprocess.Popen(
                    list(command),
                    cwd=str(ROOT),
                    env=dict(environment),
                    stdin=subprocess.DEVNULL,
                    start_new_session=os.name != "nt",
                )
            except OSError as exc:
                spawn_failure = exc

            # The installed handlers never raise from inside Popen. A signal
            # delivered during spawn is recorded, Popen publishes its process
            # object, and only this ownership-safe checkpoint may unwind.
            termination.raise_if_pending()
            if spawn_failure is not None:
                raise BuilderCliFailure(
                    int(ExitCode.INTERNAL), "could not start Blender"
                ) from spawn_failure
            if process is None:
                raise BuilderCliFailure(
                    int(ExitCode.INTERNAL), "could not start Blender"
                )

            deadline = time.monotonic() + BUILD_TIMEOUT_SECONDS
            while True:
                termination.raise_if_pending()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BuilderCliFailure(
                        int(ExitCode.TIMEOUT), "controlled wall-clock timeout"
                    )
                try:
                    return_code = process.wait(
                        timeout=min(PROCESS_SIGNAL_POLL_SECONDS, remaining)
                    )
                except subprocess.TimeoutExpired:
                    continue
                termination.raise_if_pending()
                break
            if os.name != "nt" and _process_group_exists(process.pid):
                _terminate(process)
            termination.raise_if_pending()
        except BaseException:
            # Keep the record-only handlers installed until the complete
            # child group has been stopped and reaped. Repeated termination
            # signals therefore cannot interrupt teardown and orphan Blender.
            if process is not None:
                _terminate(process)
            raise
    return 128 + abs(return_code) if return_code < 0 else return_code


def _validate_tree(output: Path, request: BuildRequest, blender: Path) -> BuildManifest:
    files: set[str] = set()
    directories: set[str] = set()
    try:
        for index, path in enumerate(output.rglob("*"), start=1):
            if index > len(EXACT_FILES) + len(EXACT_DIRECTORIES):
                raise BuilderCliFailure(int(ExitCode.VERIFICATION), "artifact tree contains too many entries")
            relative = path.relative_to(output).as_posix()
            if path.is_symlink():
                raise BuilderCliFailure(int(ExitCode.VERIFICATION), "artifact tree contains a symlink")
            if path.is_dir():
                directories.add(relative)
            elif path.is_file():
                if path.stat().st_size <= 0:
                    raise BuilderCliFailure(int(ExitCode.VERIFICATION), "artifact tree contains an empty file")
                files.add(relative)
            else:
                raise BuilderCliFailure(int(ExitCode.VERIFICATION), "artifact tree contains a special file")
    except OSError as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not inspect artifact tree") from exc
    if files != EXACT_FILES or directories != EXACT_DIRECTORIES:
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "artifact tree differs from complete-v1")
    try:
        with (output / "manifest.json").open("rb") as stream:
            manifest_payload = stream.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not read manifest") from exc
    if len(manifest_payload) > MAX_MANIFEST_BYTES:
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "success manifest exceeds its size limit")
    try:
        manifest = BuildManifest.from_json(manifest_payload)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "success manifest is invalid") from exc
    if manifest_payload != manifest.canonical_bytes + b"\n":
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "success manifest is not canonical")
    if manifest.request_sha256 != request.request_sha256 or manifest.spec_sha256 != request.spec_sha256:
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "manifest request provenance mismatch")
    for name in REQUIRED_ARTIFACTS:
        path = output / name
        entry = manifest.artifacts[name]
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not stat artifact") from exc
        if size != int(entry["bytes"]) or _hash_file(path) != entry["sha256"]:
            raise BuilderCliFailure(int(ExitCode.VERIFICATION), "artifact hash or byte count mismatch")
    context = _execution_context()
    expected_mode = "container" if context else "native"
    if manifest.execution["mode"] != expected_mode:
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "manifest execution mode mismatch")
    if context:
        revision = _provenance_text("source-tree.sha256")
        version = _provenance_text("blender-version.txt")
        binary_record = _provenance_text("blender-binary.sha256")
        binary_fields = binary_record.split()
        binary_sha256 = binary_fields[0] if len(binary_fields) == 2 else ""
        if (
            IMAGE_DIGEST.fullmatch("sha256:" + revision) is None
            or IMAGE_DIGEST.fullmatch("sha256:" + binary_sha256) is None
            or len(binary_fields) != 2
            or binary_fields[1] != str(CONTAINER_BLENDER)
            or manifest.execution["project_revision"] != revision
            or manifest.execution["blender_version"] != version
            or manifest.execution["blender_binary_sha256"] != binary_sha256
        ):
            raise BuilderCliFailure(int(ExitCode.VERIFICATION), "manifest baked provenance mismatch")
        mappings = (
            ("worker_image_reference", "HBCB_WORKER_IMAGE_REFERENCE"),
            ("worker_image_digest", "HBCB_WORKER_IMAGE_DIGEST"),
            ("worker_image_id", "HBCB_WORKER_IMAGE_ID"),
        )
        for manifest_field, environment_field in mappings:
            if manifest.execution[manifest_field] != context.get(environment_field):
                raise BuilderCliFailure(int(ExitCode.VERIFICATION), "manifest image provenance mismatch")
    else:
        try:
            revision = source_revision(ROOT, include_launcher=False)
        except OSError as exc:
            raise BuilderCliFailure(int(ExitCode.INTERNAL), "native source provenance is unavailable") from exc
        if manifest.execution["project_revision"] != revision:
            raise BuilderCliFailure(int(ExitCode.VERIFICATION), "manifest source provenance mismatch")
    if manifest.execution["blender_binary_sha256"] != _hash_file(blender):
        raise BuilderCliFailure(int(ExitCode.VERIFICATION), "manifest Blender binary provenance mismatch")
    return manifest


def _runner_command(blender: Path, request: Path, output: Path) -> list[str]:
    return [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        "--python-exit-code",
        str(int(ExitCode.INTERNAL)),
        "--python",
        str(RUNNER),
        "--",
        "--request",
        str(request),
        "--output",
        str(output),
    ]


def build_artifacts(request_path: str, output_path: str) -> None:
    request_file, request = _request(request_path)
    output = _new_output(output_path)
    blender = _blender_binary()
    environment = _child_environment()
    stage = _private_stage(output)
    published = False
    try:
        result = stage / "result"
        return_code = _run(_runner_command(blender, request_file, result), environment)
        if return_code != 0:
            mapped = return_code if return_code in APPLICATION_FAILURES or 128 <= return_code <= 255 else int(ExitCode.INTERNAL)
            raise BuilderCliFailure(mapped, "Blender build failed")
        if not result.is_dir():
            raise BuilderCliFailure(int(ExitCode.INTERNAL), "Blender omitted staged artifacts")
        _validate_tree(result, request, blender)
        if output.is_symlink() or output.exists():
            raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "output appeared during build")
        try:
            os.rename(result, output)
            published = True
            stage.rmdir()
        except OSError as exc:
            if not published:
                raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "atomic launcher publication failed") from exc
    finally:
        if not published and stage.exists():
            try:
                shutil.rmtree(stage)
            except OSError as exc:
                raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not remove launcher staging") from exc


def _verification_command(
    blender: Path,
    request: Path,
    output: Path,
    result: Path,
) -> list[str]:
    return [
        str(blender),
        "--background",
        "--factory-startup",
        "--offline-mode",
        "--disable-autoexec",
        str(output / "model.blend"),
        "--python-exit-code",
        str(int(ExitCode.VERIFICATION)),
        "--python",
        str(PUBLISHED_VERIFIER),
        "--",
        "--blend",
        str(output / "model.blend"),
        "--glb",
        str(output / "model.glb"),
        "--stl",
        str(output / "model.stl"),
        "--request",
        str(request),
        "--manifest",
        str(output / "manifest.json"),
        "--result",
        str(result),
    ]


def verify_artifacts(request_path: str, output_path: str) -> None:
    request_file, request = _request(request_path)
    output = _published_output(output_path)
    blender = _blender_binary()
    _validate_tree(output, request, blender)
    environment = _child_environment()
    try:
        verification_root = Path(tempfile.mkdtemp(prefix="hbcb-published-verify-"))
        verification_root.chmod(0o700)
    except OSError as exc:
        raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not create verifier scratch") from exc
    try:
        result = verification_root / "result.json"
        return_code = _run(
            _verification_command(blender, request_file, output, result),
            environment,
        )
        if return_code == int(ExitCode.TIMEOUT):
            raise BuilderCliFailure(int(ExitCode.TIMEOUT), "published verification timed out")
        if return_code != 0 or not result.is_file():
            raise BuilderCliFailure(int(ExitCode.VERIFICATION), "published verification failed")
        try:
            with result.open("rb") as stream:
                evidence_payload = stream.read(MAX_VERIFIER_RESULT_BYTES + 1)
            if len(evidence_payload) > MAX_VERIFIER_RESULT_BYTES:
                raise ValueError("oversized verifier evidence")
            evidence = json.loads(evidence_payload.decode("utf-8", "strict"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BuilderCliFailure(int(ExitCode.VERIFICATION), "published verifier evidence is invalid") from exc
        expected_fields = {
            "checks",
            "dimensions_mm",
            "request_sha256",
            "spec_sha256",
            "status",
            "verification_version",
        }
        checks = evidence.get("checks") if isinstance(evidence, Mapping) else None
        if (
            not isinstance(evidence, Mapping)
            or set(evidence) != expected_fields
            or evidence.get("status") != "passed"
            or evidence.get("verification_version") != PUBLISHED_VERIFICATION_VERSION
            or evidence.get("request_sha256") != request.request_sha256
            or evidence.get("spec_sha256") != request.spec_sha256
            or not isinstance(checks, Mapping)
            or set(checks)
            != {
                "artifact_hashes",
                "blend_fresh_reload",
                "glb_clean_reimport",
                "no_embedded_or_external_content",
                "stl_clean_reimport",
            }
            or not all(value is True for value in checks.values())
        ):
            raise BuilderCliFailure(int(ExitCode.VERIFICATION), "published verifier did not pass")
    finally:
        try:
            shutil.rmtree(verification_root)
        except OSError as exc:
            raise BuilderCliFailure(int(ExitCode.FILESYSTEM), "could not remove verifier scratch") from exc


__all__ = [
    "BuilderCliFailure",
    "build_artifacts",
    "validate_request",
    "verify_artifacts",
]
