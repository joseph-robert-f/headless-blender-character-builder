#!/usr/bin/env python3
"""Prove the exact PostgreSQL image initializes without its dormant gosu helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Mapping, Sequence


EXPECTED_IMAGE = (
    "postgres:16.14-alpine3.24@sha256:"
    "57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
)
EXPECTED_ENTRYPOINT_SHA256 = (
    "9c440299ae04a0a79d55b8bf03307036d890a40979d2fb698073c9050d4b20a5"
)
OWNER_LABEL_KEY = "io.hbcb.postgres-fixture-owner"
SAFE_TOOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
RESOURCE_NAME = re.compile(r"^hbcb-postgres-security-[0-9a-f]{16}$")
MAX_OUTPUT_BYTES = 1024 * 1024
CLEANUP_DOCKER_TIMEOUT_SECONDS = 5
MAX_OWNED_RUNTIME_DOCKER_TIMEOUT_SECONDS = 60
CLEANUP_DOCKER_OPERATION_COUNT = 6


class GateError(RuntimeError):
    pass


class _TerminationSignal(SystemExit):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(128 + signum)


class _TerminationGuard:
    """Defer default termination until the owned container and volume are gone."""

    def __init__(self) -> None:
        self.received: int | None = None
        self.previous: dict[int, object] = {}
        self.installed: set[int] = set()

    def _record(self, signum: int, _frame: object) -> None:
        if self.received is None:
            self.received = int(signum)

    def __enter__(self) -> "_TerminationGuard":
        for signum in (signal.SIGINT, getattr(signal, "SIGHUP", None), signal.SIGTERM):
            if not isinstance(signum, int) or signum in self.previous:
                continue
            previous = signal.getsignal(signum)
            self.previous[signum] = previous
            if previous == signal.SIG_DFL or (
                signum == signal.SIGINT and previous == signal.default_int_handler
            ):
                signal.signal(signum, self._record)
                self.installed.add(signum)
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        for signum in self.installed:
            signal.signal(signum, self.previous[signum])
        self.raise_if_pending()

    def raise_if_pending(self) -> None:
        if self.received is None:
            return
        if self.received == signal.SIGINT:
            raise KeyboardInterrupt
        raise _TerminationSignal(self.received)


def _safe_tool_selector(value: str) -> bool:
    if SAFE_TOOL.fullmatch(value) is not None:
        return True
    if not value or len(value) > 1024 or any(ord(character) < 32 for character in value):
        return False
    supplied = Path(value)
    if not supplied.is_absolute() or supplied == Path("/") or ".." in supplied.parts:
        return False
    try:
        resolved = supplied.resolve(strict=True)
    except OSError:
        return False
    return resolved.is_file() and os.access(resolved, os.X_OK)


def _run(
    command: Sequence[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=dict(os.environ, LC_ALL="C"),
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as failure:
        raise GateError("a bounded Docker operation failed") from failure
    if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
        raise GateError("a Docker operation exceeded the output limit")
    if check and completed.returncode != 0:
        raise GateError("the reviewed PostgreSQL fixture check failed")
    return completed


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


def _validate_image(document: Mapping[str, object], image: str) -> str:
    if image != EXPECTED_IMAGE:
        raise GateError("the PostgreSQL image reference is not the reviewed exact pin")
    image_id = document.get("Id")
    config = document.get("Config")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise GateError("the PostgreSQL image ID is invalid")
    if document.get("Os") != "linux" or document.get("Architecture") != "amd64":
        raise GateError("the PostgreSQL image platform is not linux/amd64")
    if not isinstance(config, dict):
        raise GateError("the PostgreSQL image configuration is invalid")
    if config.get("Entrypoint") != ["docker-entrypoint.sh"]:
        raise GateError("the PostgreSQL image entrypoint is invalid")
    if config.get("Cmd") != ["postgres"]:
        raise GateError("the PostgreSQL image command is invalid")
    environment = config.get("Env")
    required_environment = {
        "GOSU_VERSION=1.19",
        "PG_MAJOR=16",
        "PG_VERSION=16.14",
        "PGDATA=/var/lib/postgresql/data",
    }
    if (
        not isinstance(environment, list)
        or not all(isinstance(item, str) for item in environment)
        or not required_environment.issubset(environment)
    ):
        raise GateError("the PostgreSQL image environment is invalid")
    if config.get("Volumes") != {"/var/lib/postgresql/data": {}}:
        raise GateError("the PostgreSQL data-volume contract is invalid")
    return image_id


def _resource_identity() -> tuple[str, str]:
    token = uuid.uuid4().hex
    return "hbcb-postgres-security-" + token[:16], OWNER_LABEL_KEY + "=" + uuid.uuid4().hex


def _owned_container_ids(
    docker: str,
    name: str,
    owner_label: str,
    *,
    timeout: int = 30,
) -> list[str]:
    result = _run(
        (
            docker,
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--quiet",
            "--filter",
            "name=^/" + name + "$",
            "--filter",
            "label=" + owner_label,
        ),
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise GateError("the PostgreSQL container ownership could not be inspected")
    try:
        identifiers = result.stdout.decode("ascii", "strict").splitlines()
    except UnicodeError as failure:
        raise GateError("the PostgreSQL container ownership is invalid") from failure
    if (
        any(CONTAINER_ID.fullmatch(identifier) is None for identifier in identifiers)
        or len(identifiers) != len(set(identifiers))
        or len(identifiers) > 1
    ):
        raise GateError("the PostgreSQL container ownership is ambiguous")
    return identifiers


def _owned_volume_names(
    docker: str,
    name: str,
    owner_label: str,
    *,
    timeout: int = 30,
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


def _remove_owned_container(docker: str, name: str, owner_label: str) -> None:
    owned = _owned_container_ids(
        docker,
        name,
        owner_label,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )
    if owned:
        removal = _run(
            (docker, "rm", "--force", owned[0]),
            timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
            check=False,
        )
        remaining = _owned_container_ids(
            docker,
            name,
            owner_label,
            timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
        )
        if removal.returncode != 0 or remaining:
            raise GateError("the PostgreSQL fixture container could not be removed")


def _remove_owned_volume(docker: str, name: str, owner_label: str) -> None:
    owned = _owned_volume_names(
        docker,
        name,
        owner_label,
        timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
    )
    if owned:
        removal = _run(
            (docker, "volume", "rm", owned[0]),
            timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
            check=False,
        )
        remaining = _owned_volume_names(
            docker,
            name,
            owner_label,
            timeout=CLEANUP_DOCKER_TIMEOUT_SECONDS,
        )
        if removal.returncode != 0 or remaining:
            raise GateError("the PostgreSQL fixture volume could not be removed")


def _runtime_gate(docker: str, image: str) -> tuple[str, str]:
    name, owner_label = _resource_identity()
    volume_name = name
    password = "hbcb-gate-" + uuid.uuid4().hex
    sentinel_payload = b"#!/bin/sh\nexit 97\n"
    sentinel_sha256 = hashlib.sha256(sentinel_payload).hexdigest()

    with tempfile.TemporaryDirectory(prefix="hbcb-postgres-gosu-") as temporary:
        sentinel = Path(temporary) / "gosu"
        sentinel.write_bytes(sentinel_payload)
        sentinel.chmod(0o555)
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
                        "--mount",
                        "type=bind,source="
                        + str(sentinel.resolve())
                        + ",target=/usr/local/bin/gosu,readonly",
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
                            "pg_isready",
                            "--quiet",
                            "--username",
                            "hbcb_gate",
                            "--dbname",
                            "hbcb_gate",
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
                    'test "$(sha256sum /usr/local/bin/docker-entrypoint.sh | awk \'{print $1}\')" = '
                    + EXPECTED_ENTRYPOINT_SHA256
                    + '; test "$(sha256sum /usr/local/bin/gosu | awk \'{print $1}\')" = '
                    + sentinel_sha256
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
                return container_id, sentinel_sha256
            finally:
                cleanup_failures = []
                for label, cleanup, arguments in (
                    (
                        "container",
                        _remove_owned_container,
                        (docker, name, owner_label),
                    ),
                    (
                        "volume",
                        _remove_owned_volume,
                        (docker, volume_name, owner_label),
                    ),
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


def execute(docker: str, image: str) -> int:
    if not _safe_tool_selector(docker) or image != EXPECTED_IMAGE:
        raise GateError("the Docker executable or PostgreSQL image reference is unsafe")
    _run((docker, "pull", "--quiet", "--platform", "linux/amd64", image), timeout=600)
    image_id = _validate_image(_inspect_image(docker, image), image)
    _container_id, sentinel_sha256 = _runtime_gate(docker, image)
    print(
        json.dumps(
            {
                "entrypoint_sha256": EXPECTED_ENTRYPOINT_SHA256,
                "event": "postgres_fixture_security",
                "gosu_sentinel_sha256": sentinel_sha256,
                "image_id": image_id,
                "image_reference": image,
                "platform": "linux/amd64",
                "runtime_uid": 70,
                "status": "pass",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--image", default=EXPECTED_IMAGE)
    options = parser.parse_args()
    os.umask(0o077)
    try:
        return execute(options.docker, options.image)
    except GateError as failure:
        sys.stderr.write("POSTGRES_FIXTURE_SECURITY: " + str(failure) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
