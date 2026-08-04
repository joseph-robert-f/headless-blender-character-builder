"""Independent policy checks for the G4 one-shot Docker invocation.

The G4 gate records the *expanded* ``docker run`` argv emitted by Make.  This
module validates that argv and the resulting image metadata without trusting
Makefile text or shell quoting.  It intentionally uses only the Python 3.9
standard library so a reviewer needs no project virtual environment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple


MAX_PIDS = 512
MAX_CPUS = 4.0
MAX_MEMORY_BYTES = 8 * 1024**3
MAX_TMPFS_BYTES = 2 * 1024**3
BLENDER_VERSION = "4.5.12 LTS"
BLENDER_DOWNLOAD_SHA256 = "95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25"

_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_USER = re.compile(r"^(?P<uid>[0-9]+):(?P<gid>[0-9]+)$")
_SAFE_ENV_NAMES = {
    "HBCB_EXECUTION_MODE",
    "HBCB_WORKER_IMAGE_DIGEST",
    "HBCB_WORKER_IMAGE_ID",
    "HBCB_WORKER_IMAGE_REFERENCE",
}
_FORBIDDEN_ENV_MARKERS = (
    "API_KEY",
    "ACCESS_KEY",
    "AUTH",
    "CREDENTIAL",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
    "SIGNED_URL",
    "SSH_",
    "TOKEN",
)
_FORBIDDEN_MOUNT_PARTS = (
    "/.aws",
    "/.config/gcloud",
    "/.docker",
    "/.gnupg",
    "/.kube",
    "/.ssh",
    "/credentials",
    "/docker.sock",
    "/secrets",
)


class RuntimePolicyFailure(AssertionError):
    """One expanded runtime invariant did not hold."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimePolicyFailure(message)


def _single(options: Mapping[str, List[str]], name: str) -> str:
    values = options.get(name, [])
    _require(len(values) == 1, "%s must occur exactly once" % name)
    return values[0]


def _byte_quantity(raw: str) -> int:
    match = re.fullmatch(r"(?i)([0-9]+)([kmgt]?)(i?b?)", raw.strip())
    _require(match is not None, "invalid Docker byte quantity for policy gate")
    assert match is not None
    number = int(match.group(1))
    suffix = match.group(2).lower()
    powers = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}
    return number * (1024 ** powers[suffix])


def _integer(raw: str, label: str) -> int:
    try:
        return int(raw, 10)
    except ValueError as exc:
        raise RuntimePolicyFailure("%s is not an integer" % label) from exc


def _floating(raw: str, label: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimePolicyFailure("%s is not numeric" % label) from exc


def _parse_mount(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in raw.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            key = {"src": "source", "dst": "target"}.get(key, key)
            _require(bool(value), "Docker mount option has an empty value")
        else:
            key, value = item, "true"
        _require(key not in result, "Docker mount repeats option %s" % key)
        result[key] = value
    return result


def _parse_tmpfs(raw: str) -> Tuple[str, Dict[str, str]]:
    target, separator, option_text = raw.partition(":")
    _require(separator == ":" and bool(target) and bool(option_text), "invalid --tmpfs value")
    options: Dict[str, str] = {}
    for item in option_text.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
        else:
            key, value = item, "true"
        _require(key not in options, "tmpfs repeats option %s" % key)
        options[key] = value
    return target, options


def _json_strings(value: Any) -> List[str]:
    strings: List[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                strings.append(key)
            strings.extend(_json_strings(item))
    elif isinstance(value, list):
        for item in value:
            strings.extend(_json_strings(item))
    return strings


def _parse_run(argv: Sequence[str]) -> Tuple[Dict[str, bool], Dict[str, List[str]], str, List[str]]:
    _require(bool(argv) and argv[0] == "run", "record is not a docker run invocation")
    flags: Dict[str, bool] = {}
    options: Dict[str, List[str]] = {}
    flag_names = {"--init", "--read-only", "--rm"}
    value_names = {
        "--cap-drop",
        "--cpus",
        "--env",
        "--memory",
        "--mount",
        "--network",
        "--pids-limit",
        "--platform",
        "--security-opt",
        "--tmpfs",
        "--user",
    }
    explicitly_forbidden = {
        "--cap-add",
        "--device",
        "--device-cgroup-rule",
        "--env-file",
        "--entrypoint",
        "--ipc",
        "--pid",
        "--privileged",
        "--security-opt=seccomp=unconfined",
        "--userns",
        "--volume",
        "-e",
        "-v",
    }
    index = 1
    while index < len(argv):
        token = argv[index]
        if not token.startswith("-"):
            image = token
            command = list(argv[index + 1 :])
            _require(bool(command), "docker run omitted the fixed builder command")
            return flags, options, image, command
        name, separator, inline = token.partition("=")
        _require(token not in explicitly_forbidden and name not in explicitly_forbidden, "forbidden docker run option: %s" % name)
        if name in flag_names:
            _require(not separator, "%s does not accept a value" % name)
            _require(name not in flags, "%s is duplicated" % name)
            flags[name] = True
            index += 1
            continue
        _require(name in value_names, "unexpected docker run option: %s" % name)
        if separator:
            value = inline
            index += 1
        else:
            _require(index + 1 < len(argv), "%s is missing its value" % name)
            value = argv[index + 1]
            index += 2
        _require(bool(value), "%s has an empty value" % name)
        options.setdefault(name, []).append(value)
    raise RuntimePolicyFailure("docker run omitted its image")


def _assert_no_broad_or_sensitive_source(source: Path, clean_source: Path, workspace: Path) -> None:
    resolved = source.resolve()
    text = resolved.as_posix()
    _require(resolved != Path(resolved.anchor), "mount source is a filesystem root")
    _require(resolved != Path.home().resolve(), "mount source is the caller home directory")
    _require(resolved != clean_source.resolve(), "mount source is the clean repository root")
    _require(resolved != workspace.resolve(), "mount source is the development repository root")
    lowered = text.lower()
    for marker in _FORBIDDEN_MOUNT_PARTS:
        _require(marker not in lowered, "mount source resembles a socket or credential path")


def assert_hardened_run(
    argv: Sequence[str],
    *,
    clean_source: Path,
    workspace: Path,
    expected_image: str,
    expected_request: Path,
    expected_output: Path,
    expected_platform: str,
    expected_user: str,
    expected_command: str = "build",
    output_readonly: bool = False,
) -> Mapping[str, Any]:
    """Validate one expanded Make-emitted build or verification invocation."""

    flags, options, image, command = _parse_run(argv)
    _require(image == expected_image, "docker run used an unexpected image reference")
    _require(expected_command in {"build", "verify"}, "gate expected-command policy is invalid")
    _require(
        command
        == [expected_command, "--request", "/input/request.json", "--output", "/output/demo"],
        "docker run did not use the fixed narrow builder command",
    )
    _require(flags.get("--rm") is True, "model container is not disposable")
    _require(flags.get("--read-only") is True, "model container root is not read-only")

    _require(_single(options, "--network") == "none", "model container network is not none")
    cap_drops = [item.upper() for item in options.get("--cap-drop", [])]
    _require(cap_drops == ["ALL"], "model container must drop all capabilities exactly once")
    security_options = options.get("--security-opt", [])
    _require(
        security_options in (["no-new-privileges"], ["no-new-privileges:true"]),
        "model container must enable only no-new-privileges",
    )
    _require(
        _integer(_single(options, "--pids-limit"), "PID limit") == MAX_PIDS,
        "PID limit differs from the v0.1 contract",
    )
    cpus = _floating(_single(options, "--cpus"), "CPU limit")
    _require(0 < cpus <= MAX_CPUS, "CPU limit is absent, invalid, or above four CPUs")
    memory = _byte_quantity(_single(options, "--memory"))
    _require(0 < memory <= MAX_MEMORY_BYTES, "memory limit is absent, invalid, or above 8 GiB")
    _require(_single(options, "--platform") == expected_platform, "runtime platform is not release-pinned")

    user = _single(options, "--user")
    match = _USER.fullmatch(user)
    _require(match is not None, "runtime user must be an explicit numeric UID:GID")
    assert match is not None
    _require(int(match.group("uid")) > 0, "runtime UID is root")
    _require(int(match.group("gid")) > 0, "runtime GID is root")
    _require(user == expected_user, "runtime user does not match the invoking host UID:GID")

    tmpfs_values = options.get("--tmpfs", [])
    _require(len(tmpfs_values) == 1, "model container must have exactly one bounded tmpfs")
    tmpfs_target, tmpfs_options = _parse_tmpfs(tmpfs_values[0])
    _require(tmpfs_target == "/work", "bounded tmpfs target must be /work")
    _require(tmpfs_options.get("rw") == "true", "/work tmpfs is not writable")
    _require(tmpfs_options.get("nosuid") == "true", "/work tmpfs lacks nosuid")
    _require(tmpfs_options.get("nodev") == "true", "/work tmpfs lacks nodev")
    _require(tmpfs_options.get("noexec") == "true", "/work tmpfs lacks noexec")
    _require(tmpfs_options.get("mode") == "1777", "/work tmpfs mode is not 1777")
    _require(
        0 < _byte_quantity(tmpfs_options.get("size", "")) <= MAX_TMPFS_BYTES,
        "/work tmpfs is absent, unbounded, or above 2 GiB",
    )
    _require(
        set(tmpfs_options) == {"mode", "nodev", "noexec", "nosuid", "rw", "size"},
        "/work tmpfs contains an unexpected option",
    )

    raw_mounts = options.get("--mount", [])
    _require(len(raw_mounts) == 2, "model container must have exactly two bind mounts")
    mounts = [_parse_mount(raw) for raw in raw_mounts]
    by_target = {mount.get("target"): mount for mount in mounts}
    _require(set(by_target) == {"/input/request.json", "/output"}, "bind-mount targets are not fixed")

    request_mount = by_target["/input/request.json"]
    output_mount = by_target["/output"]
    for mount in mounts:
        _require(mount.get("type") == "bind", "only bind mounts are permitted")
        _require("source" in mount, "bind mount is missing its source")
        _require(
            set(mount).issubset({"type", "source", "target", "readonly"}),
            "bind mount has an unexpected option",
        )
        _assert_no_broad_or_sensitive_source(Path(mount["source"]), clean_source, workspace)
    _require(request_mount.get("readonly") == "true", "request mount is not read-only")
    if output_readonly:
        _require(output_mount.get("readonly") == "true", "verification artifact mount is not read-only")
    else:
        _require("readonly" not in output_mount, "build artifact mount is unexpectedly read-only")
    _require(
        Path(request_mount["source"]).resolve() == expected_request.resolve(),
        "request mount source is not the bundled fixed request",
    )
    _require(
        Path(output_mount["source"]).resolve() == expected_output.resolve(),
        "artifact mount source is not the fixed demo directory",
    )
    _require(expected_request.is_file() and not expected_request.is_symlink(), "request source is not a regular fixed file")
    _require(expected_output.is_dir() and not expected_output.is_symlink(), "artifact source is not a real directory")

    env_values: Dict[str, str] = {}
    for assignment in options.get("--env", []):
        _require("=" in assignment, "docker run may not inherit an environment variable by name")
        name, value = assignment.split("=", 1)
        _require(name in _SAFE_ENV_NAMES, "docker run passes a non-provenance environment variable")
        _require(name not in env_values, "docker run repeats a provenance environment variable")
        env_values[name] = value
    _require(
        {"HBCB_EXECUTION_MODE", "HBCB_WORKER_IMAGE_REFERENCE", "HBCB_WORKER_IMAGE_ID"}.issubset(env_values),
        "Make omitted required local-container provenance variables",
    )
    _require(env_values["HBCB_EXECUTION_MODE"] == "container", "Make supplied the wrong execution mode")
    _require(
        env_values["HBCB_WORKER_IMAGE_REFERENCE"] == expected_image,
        "Make image-reference provenance differs from the executed image",
    )
    _require(
        _IMAGE_DIGEST.fullmatch(env_values["HBCB_WORKER_IMAGE_ID"]) is not None,
        "Make supplied an invalid local image ID",
    )
    if "HBCB_WORKER_IMAGE_DIGEST" in env_values:
        _require(
            _IMAGE_DIGEST.fullmatch(env_values["HBCB_WORKER_IMAGE_DIGEST"]) is not None,
            "Make supplied an invalid OCI image digest",
        )

    return {
        "cap_drop": "ALL",
        "cpus": cpus,
        "memory_bytes": memory,
        "mount_targets": sorted(by_target),
        "network": "none",
        "no_new_privileges": True,
        "pids_limit": MAX_PIDS,
        "platform": expected_platform,
        "read_only_root": True,
        "runtime_user": user,
        "tmpfs_bytes": _byte_quantity(tmpfs_options["size"]),
        "verified_command": expected_command,
    }


def assert_image_policy(
    image: Mapping[str, Any],
    *,
    expected_platform: str,
    forbidden_values: Sequence[str],
) -> Mapping[str, Any]:
    """Check immutable image metadata relevant to the G4 runtime boundary."""

    expected_os, expected_arch = expected_platform.split("/", 1)
    _require(image.get("Os") == expected_os, "image OS does not match the release platform")
    _require(image.get("Architecture") == expected_arch, "image architecture does not match the release platform")
    for text in _json_strings(image):
        for forbidden in forbidden_values:
            _require(not forbidden or forbidden not in text, "image metadata embeds a canary credential value")
    image_id = image.get("Id")
    _require(isinstance(image_id, str) and _IMAGE_DIGEST.fullmatch(image_id) is not None, "image ID is not a sha256 digest")
    config = image.get("Config")
    _require(isinstance(config, Mapping), "docker image inspect omitted Config")
    assert isinstance(config, Mapping)
    user = config.get("User")
    _require(isinstance(user, str) and bool(user), "image has no non-root default user")
    lowered_user = user.strip().lower()
    _require(lowered_user not in {"0", "0:0", "root", "root:root"}, "image default user is root")
    _require(
        config.get("Entrypoint") == ["/usr/local/bin/builder"],
        "image entrypoint is not the narrow trusted builder",
    )
    labels = config.get("Labels")
    _require(isinstance(labels, Mapping), "image Config.Labels is invalid")
    assert isinstance(labels, Mapping)
    _require(labels.get("org.blender.version") == BLENDER_VERSION, "image Blender-version label mismatch")
    _require(
        labels.get("org.blender.download.sha256") == BLENDER_DOWNLOAD_SHA256,
        "image Blender-download checksum label mismatch",
    )
    _require(
        labels.get("org.opencontainers.image.licenses") == "GPL-3.0-or-later",
        "image source-license label mismatch",
    )

    env = config.get("Env") or []
    _require(isinstance(env, list) and all(isinstance(item, str) for item in env), "image Config.Env is invalid")
    for assignment in env:
        name, _separator, value = assignment.partition("=")
        upper = name.upper()
        if name not in _SAFE_ENV_NAMES:
            _require(
                not any(marker in upper for marker in _FORBIDDEN_ENV_MARKERS),
                "image declares a credential-like environment variable",
            )
    repo_digests = image.get("RepoDigests") or []
    _require(
        isinstance(repo_digests, list) and all(isinstance(item, str) for item in repo_digests),
        "image RepoDigests metadata is invalid",
    )
    digests: List[str] = []
    for reference in repo_digests:
        _name, separator, digest = reference.rpartition("@")
        _require(separator == "@" and _IMAGE_DIGEST.fullmatch(digest) is not None, "invalid RepoDigest")
        digests.append(digest)

    return {
        "default_user": user,
        "image_id": image_id,
        "repo_digests": sorted(set(digests)),
        "trusted_entrypoint": "/usr/local/bin/builder",
    }


def assert_no_sensitive_mount_text(argv: Sequence[str], forbidden_roots: Sequence[Path]) -> None:
    """Defense-in-depth textual scan for socket, credential, repo, and home mounts."""

    joined = "\n".join(argv).lower()
    for marker in _FORBIDDEN_MOUNT_PARTS:
        _require(marker not in joined, "docker argv contains a forbidden mount marker")
    for root in forbidden_roots:
        text = root.resolve().as_posix().rstrip("/").lower()
        if text:
            _require(
                not any(token == text or token.startswith(text + ":") for token in argv),
                "docker argv mounts a forbidden broad host root",
            )
