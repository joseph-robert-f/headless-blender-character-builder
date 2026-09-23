#!/usr/bin/env python3
"""Build and prove the exact gosu-free PostgreSQL service runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

_COMMON_DIR = str(Path(__file__).resolve().parent)
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
import fixture_gate_common
from fixture_gate_common import (
    CHILD_TERMINATION_GRACE_SECONDS,
    CLEANUP_DOCKER_TIMEOUT_SECONDS,
    CONTAINER_ID,
    GateError,
    _process_group_exists,
    _safe_tool_selector,
    _TerminationGuard,
    _TerminationSignal,
)


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker" / "postgres.Dockerfile"
EXPECTED_BASE_IMAGE = (
    "postgres:16.15-alpine3.24@sha256:"
    "721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
)
EXPECTED_RECIPE_ID = "postgres-16.15-alpine3.24-gosu-free-v1"
EXPECTED_VERSION = "16.15-alpine3.24-hbcb.1"
EXPECTED_UPSTREAM_REVISION = "9d15534160ade17f2b6c455a39ee967c49b1937d"
EXPECTED_UPSTREAM_SOURCE = (
    "https://github.com/docker-library/postgres/tree/"
    + EXPECTED_UPSTREAM_REVISION
    + "/16/alpine3.24"
)
BUILD_TAG_PREFIX = "hbcb-postgres-security-build-"
EXPECTED_ENTRYPOINT_SHA256 = (
    "9c440299ae04a0a79d55b8bf03307036d890a40979d2fb698073c9050d4b20a5"
)
OWNER_LABEL_KEY = "io.hbcb.postgres-fixture-owner"
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
RESOURCE_NAME = re.compile(r"^hbcb-postgres-security-[0-9a-f]{16}$")
BUILD_TAG = re.compile(r"^hbcb-postgres-security-build-[0-9a-f]{16}:local$")
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBER_COUNT = 100_000
MAX_ARCHIVE_CONFIG_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_MANIFEST_BYTES = 1024 * 1024
MAX_OWNED_RUNTIME_DOCKER_TIMEOUT_SECONDS = 60
CLEANUP_DOCKER_OPERATION_COUNT = 12
BUILD_OWNER_LABEL_KEY = "io.hbcb.postgres-build-owner"


def _run(
    command: Sequence[str], *, timeout: int = 30, check: bool = True, interruptible: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return fixture_gate_common._run(
        command, timeout=timeout, check=check, interruptible=interruptible,
        check_failure_message="the reviewed PostgreSQL fixture check failed",
    )


def _owned_container_ids(
    docker: str, name: str, owner_label: str, *, timeout: int = 30, interruptible: bool = True,
) -> list[str]:
    return fixture_gate_common._owned_container_ids(
        _run, docker, name, owner_label,
        label="the PostgreSQL container", timeout=timeout, interruptible=interruptible,
    )


def _remove_owned_container(docker: str, name: str, owner_label: str) -> None:
    fixture_gate_common._remove_owned_container(
        _run, docker, name, owner_label,
        label="the PostgreSQL container", timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )


def _json_document(payload: bytes, label: str) -> Mapping[str, object]:
    try:
        document = json.loads(payload.decode("utf-8", "strict"))
    except (UnicodeError, ValueError, RecursionError) as failure:
        raise GateError(label + " is invalid") from failure
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise GateError(label + " is invalid")
    return document[0]


def _inspect_image(docker: str, image: str) -> Mapping[str, object]:
    return _json_document(
        _run(
            (
                docker,
                "image",
                "inspect",
                "--platform",
                "linux/amd64",
                image,
            )
        ).stdout,
        "the PostgreSQL image identity",
    )


def _inspect_tag(docker: str, image: str) -> Mapping[str, object]:
    return _json_document(
        _run((docker, "image", "inspect", image)).stdout,
        "the PostgreSQL local image identity",
    )


def _validate_image(document: Mapping[str, object], image: str) -> str:
    if IMAGE_ID.fullmatch(image) is None:
        raise GateError("the PostgreSQL runtime must be selected by exact image ID")
    image_id = document.get("Id")
    config = document.get("Config")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise GateError("the PostgreSQL image ID is invalid")
    if image_id != image:
        raise GateError("the PostgreSQL image selection changed during inspection")
    if document.get("Os") != "linux" or document.get("Architecture") != "amd64":
        raise GateError("the PostgreSQL image platform is not linux/amd64")
    if not isinstance(config, dict):
        raise GateError("the PostgreSQL image configuration is invalid")
    if config.get("Entrypoint") != ["docker-entrypoint.sh"]:
        raise GateError("the PostgreSQL image entrypoint is invalid")
    if config.get("Cmd") != ["postgres"]:
        raise GateError("the PostgreSQL image command is invalid")
    if config.get("User") != "70:70":
        raise GateError("the PostgreSQL image default user is not UID/GID 70")
    environment = config.get("Env")
    required_environment = {
        "PG_MAJOR=16",
        "PG_VERSION=16.15",
        "PG_SHA256=c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed",
        "PGDATA=/var/lib/postgresql/data",
        "DOCKER_PG_LLVM_DEPS=llvm21-dev \t\tclang21",
    }
    if (
        not isinstance(environment, list)
        or not all(isinstance(item, str) for item in environment)
        or not required_environment.issubset(environment)
    ):
        raise GateError("the PostgreSQL image environment is invalid")
    if any(item.startswith("GOSU_VERSION=") for item in environment):
        raise GateError("the PostgreSQL image still advertises gosu")
    if config.get("Volumes") != {"/var/lib/postgresql/data": {}}:
        raise GateError("the PostgreSQL data-volume contract is invalid")
    if config.get("WorkingDir") != "/" or config.get("StopSignal") != "SIGINT":
        raise GateError("the PostgreSQL process contract is invalid")
    if config.get("ExposedPorts") != {"5432/tcp": {}}:
        raise GateError("the PostgreSQL port contract is invalid")
    labels = config.get("Labels")
    expected_labels = {
        "org.opencontainers.image.version": EXPECTED_VERSION,
        "org.opencontainers.image.revision": EXPECTED_UPSTREAM_REVISION,
        "org.opencontainers.image.source": EXPECTED_UPSTREAM_SOURCE,
        "org.opencontainers.image.licenses": "PostgreSQL",
        "org.opencontainers.image.base.name": "postgres:16.15-alpine3.24",
        "org.opencontainers.image.base.digest": "sha256:"
        + EXPECTED_BASE_IMAGE.rsplit("sha256:", 1)[1],
        "io.hbcb.postgres.recipe-id": EXPECTED_RECIPE_ID,
    }
    if not isinstance(labels, dict) or any(
        labels.get(key) != value for key, value in expected_labels.items()
    ):
        raise GateError("the PostgreSQL image provenance labels are invalid")
    return image_id


def _tag_descriptor_id(document: Mapping[str, object]) -> str:
    image_id = document.get("Id")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise GateError("the PostgreSQL build image ownership is invalid")
    descriptor = document.get("Descriptor")
    if descriptor is None:
        return image_id
    if not isinstance(descriptor, dict):
        raise GateError("the PostgreSQL build image ownership is invalid")
    digest = descriptor.get("digest")
    if not isinstance(digest, str) or IMAGE_ID.fullmatch(digest) is None:
        raise GateError("the PostgreSQL build image ownership is invalid")
    return digest


def _validate_selected_image(docker: str, image: str, config_id: str) -> str:
    if IMAGE_ID.fullmatch(image) is None or IMAGE_ID.fullmatch(config_id) is None:
        raise GateError(
            "the PostgreSQL runtime and linux/amd64 config must use exact image IDs"
        )
    selected = _inspect_tag(docker, image)
    if _tag_descriptor_id(selected) != image:
        raise GateError("the PostgreSQL image selection changed during inspection")
    configured = _inspect_image(docker, image)
    configured_id = configured.get("Id")
    if not isinstance(configured_id, str):
        raise GateError("the PostgreSQL linux/amd64 image identity is invalid")
    _validate_image(configured, configured_id)
    if _exported_config_id(docker, image) != config_id:
        raise GateError("the PostgreSQL linux/amd64 config identity changed")
    return image


def _safe_archive_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise GateError("the PostgreSQL image archive member is invalid")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) != value:
        raise GateError("the PostgreSQL image archive member is invalid")
    return value


def _archive_config_id(archive: Path) -> str:
    try:
        metadata = archive.lstat()
    except OSError as failure:
        raise GateError("the PostgreSQL image archive is unavailable") from failure
    if (
        archive.is_symlink()
        or not archive.is_file()
        or metadata.st_size <= 0
        or metadata.st_size > MAX_ARCHIVE_BYTES
    ):
        raise GateError("the PostgreSQL image archive is invalid")
    try:
        with tarfile.open(archive, mode="r:") as handle:
            members = handle.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBER_COUNT:
                raise GateError("the PostgreSQL image archive is too large")
            by_name = {member.name: member for member in members}
            if len(by_name) != len(members):
                raise GateError("the PostgreSQL image archive is ambiguous")
            manifest_member = by_name.get("manifest.json")
            if (
                manifest_member is None
                or not manifest_member.isfile()
                or manifest_member.size <= 0
                or manifest_member.size > MAX_ARCHIVE_MANIFEST_BYTES
            ):
                raise GateError("the PostgreSQL image archive manifest is invalid")
            manifest_stream = handle.extractfile(manifest_member)
            if manifest_stream is None:
                raise GateError("the PostgreSQL image archive manifest is unavailable")
            manifest_payload = manifest_stream.read(MAX_ARCHIVE_MANIFEST_BYTES + 1)
            manifest_stream.close()
            manifest = json.loads(manifest_payload.decode("utf-8", "strict"))
            if (
                not isinstance(manifest, list)
                or len(manifest) != 1
                or not isinstance(manifest[0], dict)
            ):
                raise GateError("the PostgreSQL image archive manifest is invalid")
            config_name = _safe_archive_name(manifest[0].get("Config"))
            config_member = by_name.get(config_name)
            if (
                config_member is None
                or not config_member.isfile()
                or config_member.size <= 0
                or config_member.size > MAX_ARCHIVE_CONFIG_BYTES
            ):
                raise GateError("the PostgreSQL image archive config is invalid")
            config_stream = handle.extractfile(config_member)
            if config_stream is None:
                raise GateError("the PostgreSQL image archive config is unavailable")
            config_payload = config_stream.read(MAX_ARCHIVE_CONFIG_BYTES + 1)
            config_stream.close()
    except GateError:
        raise
    except (OSError, tarfile.TarError, UnicodeError, ValueError) as failure:
        raise GateError("the PostgreSQL image archive is invalid") from failure
    if len(config_payload) != config_member.size:
        raise GateError("the PostgreSQL image archive config is invalid")
    try:
        config = json.loads(config_payload.decode("utf-8", "strict"))
    except (UnicodeError, ValueError, RecursionError) as failure:
        raise GateError("the PostgreSQL image archive config is invalid") from failure
    if (
        not isinstance(config, dict)
        or config.get("os") != "linux"
        or config.get("architecture") != "amd64"
        or not isinstance(config.get("config"), dict)
    ):
        raise GateError("the PostgreSQL image archive config is invalid")
    return "sha256:" + hashlib.sha256(config_payload).hexdigest()


def _exported_config_id(docker: str, image: str) -> str:
    with tempfile.TemporaryDirectory(prefix="hbcb-postgres-image-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        archive = directory / "postgres-image.tar"
        _run(
            (docker, "image", "save", "--output", str(archive), image),
            timeout=600,
        )
        return _archive_config_id(archive)


def _resource_identity() -> tuple[str, str]:
    token = uuid.uuid4().hex
    return "hbcb-postgres-security-" + token[:16], OWNER_LABEL_KEY + "=" + uuid.uuid4().hex


def _build_tag() -> str:
    return BUILD_TAG_PREFIX + uuid.uuid4().hex[:16] + ":local"


def _build_owner_label() -> str:
    return BUILD_OWNER_LABEL_KEY + "=" + uuid.uuid4().hex


def _tag_image_ids(
    docker: str,
    tag: str,
    *,
    interruptible: bool = True,
    timeout: int = 30,
) -> list[str]:
    result = _run(
        (
            docker,
            "image",
            "ls",
            "--no-trunc",
            "--quiet",
            "--filter",
            "reference=" + tag,
        ),
        check=False,
        interruptible=interruptible,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise GateError("the PostgreSQL build tag could not be queried")
    try:
        identifiers = result.stdout.decode("ascii", "strict").splitlines()
    except UnicodeError as failure:
        raise GateError("the PostgreSQL build tag identity is invalid") from failure
    if any(IMAGE_ID.fullmatch(item) is None for item in identifiers) or len(
        set(identifiers)
    ) != len(identifiers):
        raise GateError("the PostgreSQL build tag identity is invalid")
    return identifiers


def _validate_dockerfile() -> None:
    try:
        source = DOCKERFILE.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as failure:
        raise GateError("the PostgreSQL Dockerfile is unavailable") from failure
    required = (
        "FROM --platform=linux/amd64 " + EXPECTED_BASE_IMAGE + " AS postgres-sanitized",
        "FROM scratch AS postgres",
        "rm -f /usr/local/bin/gosu",
        "COPY --from=postgres-sanitized / /",
        "USER 70:70",
        'ENTRYPOINT ["docker-entrypoint.sh"]',
        'CMD ["postgres"]',
        'io.hbcb.postgres.recipe-id="' + EXPECTED_RECIPE_ID + '"',
    )
    if any(item not in source for item in required):
        raise GateError("the PostgreSQL Dockerfile is outside the reviewed contract")


def _build_image(docker: str) -> tuple[str, str, str, str]:
    _validate_dockerfile()
    tag = _build_tag()
    owner_label = _build_owner_label()
    if BUILD_TAG.fullmatch(tag) is None:
        raise GateError("the PostgreSQL build tag is invalid")
    if _tag_image_ids(docker, tag):
        raise GateError("the PostgreSQL build tag already exists")
    try:
        _run(
            (
                docker,
                "build",
                "--file",
                str(DOCKERFILE),
                "--target",
                "postgres",
                "--label",
                owner_label,
                "--tag",
                tag,
                "--platform",
                "linux/amd64",
                str(ROOT),
            ),
            timeout=900,
        )
        document = _inspect_image(docker, tag)
        configured_id = document.get("Id")
        if not isinstance(configured_id, str):
            raise GateError("the built PostgreSQL image ID is invalid")
        labels = document.get("Config")
        if (
            not isinstance(labels, dict)
            or not isinstance(labels.get("Labels"), dict)
            or labels["Labels"].get(BUILD_OWNER_LABEL_KEY) != owner_label.split("=", 1)[1]
        ):
            raise GateError("the PostgreSQL build image ownership is invalid")
        _validate_image(document, configured_id)
        runtime_id = _tag_descriptor_id(_inspect_tag(docker, tag))
        config_id = _exported_config_id(docker, runtime_id)
        return tag, owner_label, runtime_id, config_id
    except BaseException:
        _remove_owned_image_tag(docker, tag, owner_label, None)
        raise


def _remove_owned_image_tag(
    docker: str,
    tag: str,
    owner_label: str,
    expected_id: str | None,
) -> None:
    if BUILD_TAG.fullmatch(tag) is None:
        raise GateError("the PostgreSQL build tag is invalid")
    expected_owner = owner_label.split("=", 1)
    if (
        len(expected_owner) != 2
        or expected_owner[0] != BUILD_OWNER_LABEL_KEY
        or re.fullmatch(r"[0-9a-f]{32}", expected_owner[1]) is None
    ):
        raise GateError("the PostgreSQL build image ownership is invalid")
    identifiers = _tag_image_ids(
        docker,
        tag,
        interruptible=False,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )
    if not identifiers:
        return
    if len(identifiers) != 1:
        raise GateError("the PostgreSQL build image ownership is ambiguous")
    inspected = _run(
        (docker, "image", "inspect", tag),
        check=False,
        interruptible=False,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )
    if inspected.returncode != 0:
        raise GateError("the PostgreSQL build image ownership could not be inspected")
    document = _json_document(inspected.stdout, "the PostgreSQL build image identity")
    observed_id = _tag_descriptor_id(document)
    config = document.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict) or labels.get(BUILD_OWNER_LABEL_KEY) != expected_owner[1]:
        raise GateError("the PostgreSQL build image is not owned by this run")
    if identifiers != [observed_id]:
        raise GateError("the PostgreSQL build image ownership is ambiguous")
    if expected_id is not None and observed_id != expected_id:
        raise GateError("the PostgreSQL build image ownership changed")
    removal = _run(
        (docker, "image", "rm", tag),
        check=False,
        interruptible=False,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )
    remaining = _tag_image_ids(
        docker,
        tag,
        interruptible=False,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )
    if removal.returncode != 0 or remaining:
        raise GateError("the PostgreSQL build image tag could not be removed")


def _owned_volume_names(
    docker: str,
    name: str,
    owner_label: str,
    *,
    timeout: int = 30,
    interruptible: bool = True,
) -> list[str]:
    result = _run(
        (
            docker,
            "volume",
            "ls",
            "--quiet",
            "--filter",
            "name=^" + name + "$",
            "--filter",
            "label=" + owner_label,
        ),
        timeout=timeout,
        check=False,
        interruptible=interruptible,
    )
    if result.returncode != 0:
        raise GateError("the PostgreSQL volume ownership could not be inspected")
    try:
        names = result.stdout.decode("ascii", "strict").splitlines()
    except UnicodeError as failure:
        raise GateError("the PostgreSQL volume ownership is invalid") from failure
    if any(item != name for item in names) or len(names) != len(set(names)) or len(names) > 1:
        raise GateError("the PostgreSQL volume ownership is ambiguous")
    return names


def _remove_owned_volume(docker: str, name: str, owner_label: str) -> None:
    owned = _owned_volume_names(
        docker,
        name,
        owner_label,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
        interruptible=False,
    )
    if owned:
        removal = _run(
            (docker, "volume", "rm", owned[0]),
            timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
            check=False,
            interruptible=False,
        )
        remaining = _owned_volume_names(
            docker,
            name,
            owner_label,
            timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
            interruptible=False,
        )
        if removal.returncode != 0 or remaining:
            raise GateError("the PostgreSQL fixture volume could not be removed")


def _runtime_gate(docker: str, image: str) -> str:
    if IMAGE_ID.fullmatch(image) is None:
        raise GateError("the PostgreSQL runtime must be selected by exact image ID")
    name, owner_label = _resource_identity()
    volume_name = name
    password = "hbcb-gate-" + uuid.uuid4().hex

    with _TerminationGuard() as termination_guard:
        try:
            created = _run(
                (docker, "volume", "create", "--label", owner_label, volume_name)
            )
            try:
                observed_volume = created.stdout.decode("ascii", "strict").strip()
            except UnicodeError as failure:
                raise GateError("the PostgreSQL fixture volume identity is invalid") from failure
            if observed_volume != volume_name or _owned_volume_names(
                docker, volume_name, owner_label
            ) != [volume_name]:
                raise GateError("the PostgreSQL fixture volume ownership is invalid")

            result = _run(
                (
                    docker,
                    "run",
                    "--detach",
                    "--name",
                    name,
                    "--label",
                    owner_label,
                    "--platform",
                    "linux/amd64",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--pids-limit",
                    "256",
                    "--memory",
                    "1g",
                    "--cpus",
                    "1",
                    "--user",
                    "70:70",
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777",
                    "--tmpfs",
                    "/var/run/postgresql:rw,nosuid,nodev,noexec,size=16m,mode=3777",
                    "--mount",
                    "type=volume,source=" + volume_name + ",target=/var/lib/postgresql/data",
                    "--env",
                    "POSTGRES_DB=hbcb_gate",
                    "--env",
                    "POSTGRES_USER=hbcb_gate",
                    "--env",
                    "POSTGRES_PASSWORD=" + password,
                    image,
                    "postgres",
                ),
                timeout=MAX_OWNED_RUNTIME_DOCKER_TIMEOUT_SECONDS,
            )
            termination_guard.raise_if_pending()
            try:
                container_id = result.stdout.decode("ascii", "strict").strip()
            except UnicodeError as failure:
                raise GateError("the PostgreSQL fixture container ID is invalid") from failure
            if CONTAINER_ID.fullmatch(container_id) is None:
                raise GateError("the PostgreSQL fixture container ID is invalid")
            if _owned_container_ids(docker, name, owner_label) != [container_id]:
                raise GateError("the PostgreSQL fixture container ownership is invalid")

            deadline = time.monotonic() + 60
            while True:
                ready = _run(
                    (
                        docker,
                        "exec",
                        container_id,
                        "/bin/sh",
                        "-eu",
                        "-c",
                        'test "$(cat /proc/1/comm)" = postgres && '
                        "exec pg_isready --quiet --username hbcb_gate --dbname hbcb_gate",
                    ),
                    timeout=10,
                    check=False,
                )
                termination_guard.raise_if_pending()
                if ready.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    raise GateError("the isolated PostgreSQL fixture did not become ready")
                time.sleep(1)

            proof_script = (
                'test "$(id -u)" = 70; '
                'test "$(id -g)" = 70; '
                'test "$(awk \'/^Uid:/{print $2}\' /proc/1/status)" = 70; '
                'test "$(cat /proc/1/comm)" = postgres; '
                'test "$(tr \'\\000\' \'\\n\' </proc/1/cmdline)" = postgres; '
                'test "$(cat "$PGDATA/PG_VERSION")" = 16; '
                'test ! -e /usr/local/bin/gosu; test ! -L /usr/local/bin/gosu; '
                'test "$(sha256sum /usr/local/bin/docker-entrypoint.sh | awk \'{print $1}\')" = '
                + EXPECTED_ENTRYPOINT_SHA256
                + "; exec psql --no-password --username \"$POSTGRES_USER\" "
                "--dbname \"$POSTGRES_DB\" --tuples-only --no-align "
                "--command \"SELECT current_user || '|' || current_database()\""
            )
            proof = _run(
                (docker, "exec", container_id, "/bin/sh", "-eu", "-c", proof_script),
                timeout=30,
            )
            termination_guard.raise_if_pending()
            try:
                database_identity = proof.stdout.decode("utf-8", "strict").strip()
            except UnicodeError as failure:
                raise GateError("the PostgreSQL runtime proof is invalid") from failure
            if database_identity != "hbcb_gate|hbcb_gate":
                raise GateError("the PostgreSQL fresh-volume initialization is invalid")
            return container_id
        finally:
            cleanup_failures = []
            for label, cleanup, arguments in (
                ("container", _remove_owned_container, (docker, name, owner_label)),
                ("volume", _remove_owned_volume, (docker, volume_name, owner_label)),
            ):
                try:
                    cleanup(*arguments)
                except GateError as failure:
                    cleanup_failures.append(label + ": " + str(failure))
            if cleanup_failures:
                raise GateError(
                    "the PostgreSQL fixture cleanup failed ("
                    + "; ".join(cleanup_failures)
                    + ")"
                )


def execute(docker: str, image: str | None, config_id: str | None = None) -> int:
    if not _safe_tool_selector(docker):
        raise GateError("the Docker executable is unsafe")
    if (image is None) != (config_id is None):
        raise GateError(
            "prebuilt PostgreSQL validation requires both runtime and config IDs"
        )
    if image is not None and (
        IMAGE_ID.fullmatch(image) is None
        or not isinstance(config_id, str)
        or IMAGE_ID.fullmatch(config_id) is None
    ):
        raise GateError(
            "the PostgreSQL runtime and linux/amd64 config must use exact image IDs"
        )

    build_tag: str | None = None
    build_owner_label: str | None = None
    image_id: str | None = image
    with _TerminationGuard() as termination_guard:
        try:
            if image_id is None:
                build_tag, build_owner_label, image_id, config_id = _build_image(docker)
            else:
                assert config_id is not None
                image_id = _validate_selected_image(docker, image_id, config_id)
            termination_guard.raise_if_pending()
            _runtime_gate(docker, image_id)
            termination_guard.raise_if_pending()
            print(
                json.dumps(
                    {
                        "base_image_reference": EXPECTED_BASE_IMAGE,
                        "entrypoint_sha256": EXPECTED_ENTRYPOINT_SHA256,
                        "event": "postgres_fixture_security",
                        "gosu_present": False,
                        "image_id": image_id,
                        "linux_amd64_config_id": config_id,
                        "platform": "linux/amd64",
                        "recipe_id": EXPECTED_RECIPE_ID,
                        "runtime_gid": 70,
                        "runtime_uid": 70,
                        "status": "pass",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        finally:
            if build_tag is not None and build_owner_label is not None:
                _remove_owned_image_tag(
                    docker, build_tag, build_owner_label, image_id
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument(
        "--image",
        help="prebuilt derived image selected by exact runnable local sha256: ID",
    )
    parser.add_argument(
        "--config-id",
        help="exact linux/amd64 config sha256: ID paired with --image",
    )
    options = parser.parse_args()
    os.umask(0o077)
    try:
        return execute(options.docker, options.image, options.config_id)
    except GateError as failure:
        sys.stderr.write("POSTGRES_FIXTURE_SECURITY: " + str(failure) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
