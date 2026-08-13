#!/usr/bin/env python3
"""Prove the local MinIO fixture's reviewed identity and disabled auth features."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Mapping, Sequence


SAFE_TOOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
SAFE_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,510}[A-Za-z0-9]$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
SERVER_REVISION = "7aac2a2c5b7c882e68c1ce017d8256be2feea27f"
CLIENT_REVISION = "77f82e18b5401a65958f1619df6ebb994634bd88"
FIXTURE_VERSION = "final-community-20260212-hbcb.1"
SECURITY_MODULE_DATE = "2026-08-12"
MAX_OUTPUT_BYTES = 1024 * 1024


class GateError(RuntimeError):
    pass


class _TerminationSignal(SystemExit):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(128 + signum)


class _TerminationGuard:
    """Defer CLI-default termination until the named fixture is removed."""

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
        raise GateError("a reviewed MinIO fixture check failed")
    return completed


def _inspect(docker: str, image: str) -> Mapping[str, object]:
    result = _run((docker, "image", "inspect", image))
    try:
        document = json.loads(result.stdout.decode("utf-8", "strict"))
    except (UnicodeError, ValueError, RecursionError) as failure:
        raise GateError("the MinIO image identity is invalid") from failure
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise GateError("the MinIO image identity is invalid")
    return document[0]


def _validate_image(document: Mapping[str, object]) -> str:
    image_id = document.get("Id")
    config = document.get("Config")
    if not isinstance(image_id, str) or IMAGE_ID.fullmatch(image_id) is None:
        raise GateError("the MinIO image ID is invalid")
    if document.get("Os") != "linux" or document.get("Architecture") != "amd64":
        raise GateError("the MinIO image platform is not linux/amd64")
    if not isinstance(config, dict):
        raise GateError("the MinIO image configuration is invalid")
    labels = config.get("Labels")
    expected_labels = {
        "io.hbcb.mc-revision": CLIENT_REVISION,
        "io.hbcb.scope": "local-development-only",
        "io.hbcb.security-modules": SECURITY_MODULE_DATE,
        "org.opencontainers.image.licenses": "AGPL-3.0-or-later",
        "org.opencontainers.image.revision": SERVER_REVISION,
        "org.opencontainers.image.version": FIXTURE_VERSION,
    }
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected_labels.items()):
        raise GateError("the MinIO image labels do not match the reviewed fixture")
    if config.get("User") != "65532:65532":
        raise GateError("the MinIO image user is invalid")
    if config.get("Entrypoint") != ["/usr/local/bin/minio"]:
        raise GateError("the MinIO image entrypoint is invalid")
    if config.get("Cmd") != ["server", "/data", "--address", ":9000"]:
        raise GateError("the MinIO image command is not the reviewed single-node command")
    environment = config.get("Env")
    if not isinstance(environment, list) or not all(isinstance(item, str) for item in environment):
        raise GateError("the MinIO image environment is invalid")
    if "MINIO_BROWSER=off" not in environment or "MINIO_UPDATE=off" not in environment:
        raise GateError("the MinIO image update/browser policy is invalid")
    if any(item.startswith(("MINIO_IDENTITY_OPENID_", "MINIO_IDENTITY_LDAP_")) for item in environment):
        raise GateError("an external identity provider is configured in the MinIO image")
    return image_id


def _runtime_version(docker: str, image: str, entrypoint: str) -> str:
    result = _run(
        (
            docker,
            "run",
            "--rm",
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
            "32",
            "--entrypoint",
            entrypoint,
            image,
            "--version",
        )
    )
    try:
        return result.stdout.decode("utf-8", "strict")
    except UnicodeError as failure:
        raise GateError("a MinIO fixture binary returned invalid text") from failure


def _feature_config(docker: str, image: str) -> tuple[str, str]:
    name = "hbcb-minio-security-" + uuid.uuid4().hex[:16]
    owner = uuid.uuid4().hex
    owner_label = f"io.hbcb.minio-fixture-owner={owner}"

    def owned_container_ids() -> list[str]:
        discovered = _run(
            (
                docker,
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--quiet",
                "--filter",
                f"name=^/{name}$",
                "--filter",
                f"label={owner_label}",
            ),
            timeout=30,
            check=False,
        )
        if discovered.returncode != 0:
            raise GateError("the isolated MinIO fixture ownership could not be inspected")
        try:
            identifiers = discovered.stdout.decode("ascii", "strict").splitlines()
        except UnicodeError as failure:
            raise GateError(
                "the isolated MinIO fixture ownership is invalid"
            ) from failure
        if (
            any(CONTAINER_ID.fullmatch(identifier) is None for identifier in identifiers)
            or len(identifiers) != len(set(identifiers))
            or len(identifiers) > 1
        ):
            raise GateError("the isolated MinIO fixture ownership is ambiguous")
        return identifiers

    with _TerminationGuard() as termination_guard:
        try:
            result = _run(
                (
                    docker,
                    "run",
                    "--detach",
                    "--rm",
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
                    "--tmpfs",
                    "/data:rw,nosuid,nodev,noexec,size=128m,mode=0700,uid=65532,gid=65532",
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777",
                    "--tmpfs",
                    "/work:rw,nosuid,nodev,noexec,size=16m,mode=0700,uid=65532,gid=65532",
                    "--env",
                    "MINIO_ROOT_USER=hbcb_fixture_review",
                    "--env",
                    "MINIO_ROOT_PASSWORD=test-only-minio-fixture-password",
                    "--entrypoint",
                    "/usr/local/bin/minio",
                    image,
                    "server",
                    "/data",
                    "--address",
                    "127.0.0.1:9000",
                ),
                timeout=60,
            )
            termination_guard.raise_if_pending()
            try:
                container_id = result.stdout.decode("ascii", "strict").strip()
            except UnicodeError as failure:
                raise GateError("the MinIO fixture container ID is invalid") from failure
            if CONTAINER_ID.fullmatch(container_id) is None:
                raise GateError("the MinIO fixture container ID is invalid")
            if owned_container_ids() != [container_id]:
                raise GateError("the MinIO fixture container ownership is invalid")
            ready_script = (
                'mc alias set audit http://127.0.0.1:9000 "$MINIO_ROOT_USER" '
                '"$MINIO_ROOT_PASSWORD" >/dev/null && mc ready audit >/dev/null'
            )
            deadline = time.monotonic() + 60
            while True:
                ready = _run(
                    (docker, "exec", container_id, "/bin/sh", "-ec", ready_script),
                    timeout=10,
                    check=False,
                )
                termination_guard.raise_if_pending()
                if ready.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    raise GateError("the isolated MinIO fixture did not become ready")
                time.sleep(1)
            outputs = []
            for subsystem in ("identity_openid", "identity_ldap"):
                completed = _run(
                    (
                        docker,
                        "exec",
                        container_id,
                        "/bin/sh",
                        "-ec",
                        "MC_CONFIG_DIR=/tmp/mc; export MC_CONFIG_DIR; "
                        "exec mc admin config get audit " + subsystem,
                    )
                )
                termination_guard.raise_if_pending()
                try:
                    outputs.append(completed.stdout.decode("utf-8", "strict").strip())
                except UnicodeError as failure:
                    raise GateError("the MinIO feature configuration is invalid") from failure
            return outputs[0], outputs[1]
        finally:
            owned = owned_container_ids()
            if owned:
                owned_container_id = owned[0]
                cleanup = _run(
                    (docker, "rm", "--force", owned_container_id),
                    timeout=30,
                    check=False,
                )
                remaining = owned_container_ids()
                if cleanup.returncode != 0 and remaining:
                    raise GateError("the isolated MinIO fixture could not be removed")
                if remaining:
                    raise GateError("the isolated MinIO fixture could not be removed")


def execute(docker: str, image: str) -> int:
    if not _safe_tool_selector(docker) or SAFE_IMAGE.fullmatch(image) is None or image.startswith("-"):
        raise GateError("the Docker executable or image reference is unsafe")
    image_id = _validate_image(_inspect(docker, image))
    server_version = _runtime_version(docker, image, "/usr/local/bin/minio")
    client_version = _runtime_version(docker, image, "/usr/local/bin/mc")
    if "version DEVELOPMENT.GOGET" not in server_version or f"commit-id={SERVER_REVISION}" not in server_version:
        raise GateError("the MinIO server binary identity is invalid")
    if "version DEVELOPMENT.GOGET" not in client_version or f"commit-id={CLIENT_REVISION}" not in client_version:
        raise GateError("the MinIO client binary identity is invalid")
    openid, ldap = _feature_config(docker, image)
    if re.search(r"(?:^|\s)config_url=(?:\s|$)", openid) is None:
        raise GateError("MinIO OIDC is not demonstrably disabled")
    if re.search(r"(?:^|\s)server_addr=(?:\s|$)", ldap) is None:
        raise GateError("MinIO LDAP is not demonstrably disabled")
    if re.search(r"(?:^|\s)enable=on(?:\s|$)", openid + " " + ldap):
        raise GateError("a MinIO external identity provider is enabled")
    print(
        json.dumps(
            {
                "event": "minio_fixture_security",
                "image_id": image_id,
                "mc_revision": CLIENT_REVISION,
                "platform": "linux/amd64",
                "server_revision": SERVER_REVISION,
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
    parser.add_argument("--image", required=True)
    options = parser.parse_args()
    try:
        return execute(options.docker, options.image)
    except GateError as failure:
        sys.stderr.write("MINIO_FIXTURE_SECURITY: " + str(failure) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
