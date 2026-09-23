#!/usr/bin/env python3
"""Validate the VPS Caddyfile with the reviewed local Caddy build."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "deploy" / "vps" / "Caddyfile"
CADDY_VERSION = "2.11.4"
CADDY_TAG = f"{CADDY_VERSION}-alpine"
CADDY_OCI_VERSION = f"v{CADDY_VERSION}"
CADDY_CUSTOM_VERSION = f"v{CADDY_VERSION}-hbcb.1"
CADDY_PLATFORM = "linux/amd64"
CADDY_DIGEST = "6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b"
CADDY_REFERENCE = f"caddy:{CADDY_TAG}@sha256:{CADDY_DIGEST}"


class GateFailure(RuntimeError):
    pass


def _run(
    command: Sequence[str], *, label: str, timeout: int = 120
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateFailure(f"{label} could not complete ({type(exc).__name__})") from None
    if completed.returncode != 0:
        raise GateFailure(f"{label} failed with exit {completed.returncode}")
    return completed


def _runtime(docker: str, command: Sequence[str]) -> list[str]:
    return [
        docker,
        "run",
        "--rm",
        "--platform",
        CADDY_PLATFORM,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "NET_BIND_SERVICE",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "1",
        "--env",
        "HBCB_API_DOMAIN=builder.example.com",
        "--env",
        "HBCB_ACME_EMAIL=operator@example.com",
        "--mount",
        f"type=bind,source={CADDYFILE},target=/etc/caddy/Caddyfile,readonly",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--tmpfs",
        "/data:rw,nosuid,nodev,noexec,size=16m",
        "--tmpfs",
        "/config:rw,nosuid,nodev,noexec,size=16m",
        CADDY_REFERENCE,
        *command,
    ]


def _inspect_digest(docker: str) -> None:
    completed = _run(
        [docker, "image", "inspect", CADDY_REFERENCE],
        label="pinned Caddy digest inspection",
    )
    try:
        payload = json.loads(completed.stdout.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GateFailure("pinned Caddy digest identity is invalid") from None
    if not isinstance(payload, list) or len(payload) != 1:
        raise GateFailure("pinned Caddy digest identity is invalid")
    document = payload[0]
    if not isinstance(document, dict):
        raise GateFailure("pinned Caddy digest identity is invalid")

    digest_candidates: list[str] = []
    image_id = document.get("Id")
    if image_id is not None:
        if not isinstance(image_id, str):
            raise GateFailure("pinned Caddy digest identity is invalid")
        digest_candidates.append(image_id)

    descriptor = document.get("Descriptor")
    if descriptor is not None:
        if not isinstance(descriptor, dict):
            raise GateFailure("pinned Caddy digest identity is invalid")
        descriptor_digest = descriptor.get("digest")
        if descriptor_digest is not None:
            if not isinstance(descriptor_digest, str):
                raise GateFailure("pinned Caddy digest identity is invalid")
            digest_candidates.append(descriptor_digest)

    repo_digests = document.get("RepoDigests", [])
    if not isinstance(repo_digests, list) or not all(
        isinstance(item, str) for item in repo_digests
    ):
        raise GateFailure("pinned Caddy digest identity is invalid")
    for item in repo_digests:
        if item.count("@") != 1:
            raise GateFailure("pinned Caddy digest identity is invalid")
        repository, repo_digest = item.rsplit("@", 1)
        if not repository or not repo_digest:
            raise GateFailure("pinned Caddy digest identity is invalid")
        digest_candidates.append(repo_digest)

    if f"sha256:{CADDY_DIGEST}" not in digest_candidates:
        raise GateFailure("pinned Caddy digest identity is invalid")


def _runtime_identity(docker: str) -> None:
    completed = _run(
        _runtime(
            docker,
            [
                "/bin/sh",
                "-eu",
                "-c",
                'printf \'%s\\n\' "$CADDY_VERSION"\ncaddy version\nuname -s\nuname -m',
            ],
        ),
        label="pinned Caddy runtime identity",
    )
    try:
        runtime_identity = completed.stdout.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError:
        raise GateFailure("pinned Caddy runtime identity is invalid") from None
    if (
        completed.stderr
        or len(runtime_identity) != 4
        or runtime_identity[0] != CADDY_OCI_VERSION
        or not runtime_identity[1].split()
        or runtime_identity[1].split()[0] != CADDY_OCI_VERSION
        or runtime_identity[2] != "Linux"
        or runtime_identity[3] != "x86_64"
    ):
        raise GateFailure("pinned Caddy runtime identity is invalid")


def _build_custom(docker: str, tag: str) -> str:
    _run(
        [
            docker,
            "build",
            "--file",
            "docker/caddy.Dockerfile",
            "--target",
            "caddy",
            "--tag",
            tag,
            "--platform",
            CADDY_PLATFORM,
            ".",
        ],
        label="custom Caddy build",
        timeout=1800,
    )
    completed = _run([docker, "image", "inspect", tag], label="custom Caddy inspection")
    try:
        payload = json.loads(completed.stdout.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GateFailure("custom Caddy identity is invalid") from None
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise GateFailure("custom Caddy identity is invalid")
    image = payload[0]
    image_id = image.get("Id")
    labels = image.get("Config", {}).get("Labels", {}) if isinstance(image.get("Config"), dict) else None
    if (
        not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.version") != CADDY_CUSTOM_VERSION
    ):
        raise GateFailure("custom Caddy identity is invalid")
    return image_id


def _remove_custom(docker: str, tag: str) -> None:
    try:
        subprocess.run(
            [docker, "image", "rm", tag],
            cwd=ROOT,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _custom_runtime(docker: str, image_id: str, command: Sequence[str]) -> list[str]:
    return [
        docker,
        "run",
        "--rm",
        "--platform",
        str(CADDY_PLATFORM),
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "NET_BIND_SERVICE",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "1",
        "--env",
        "HBCB_API_DOMAIN=builder.example.com",
        "--env",
        "HBCB_ACME_EMAIL=operator@example.com",
        "--mount",
        f"type=bind,source={CADDYFILE},target=/etc/caddy/Caddyfile,readonly",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--tmpfs",
        "/data:rw,nosuid,nodev,noexec,size=16m",
        "--tmpfs",
        "/config:rw,nosuid,nodev,noexec,size=16m",
        image_id,
        *command,
    ]


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--skip-pull", action="store_true")
    args = parser.parse_args(argv)
    docker = args.docker
    if "/" not in docker and shutil.which(docker) is None:
        raise GateFailure("Docker client is unavailable")
    if CADDYFILE.is_symlink() or not CADDYFILE.is_file():
        raise GateFailure("Caddyfile is unavailable")
    if not args.skip_pull:
        _run(
            [docker, "pull", "--platform", CADDY_PLATFORM, CADDY_REFERENCE],
            label="pinned Caddy pull",
        )
    _inspect_digest(docker)
    _runtime_identity(docker)
    tag = "hbcb-caddy-g8:scan-" + secrets.token_hex(12)
    try:
        image_id = _build_custom(docker, tag)
        custom_identity = _run(
            _custom_runtime(docker, image_id, ["caddy", "version"]),
            label="custom Caddy version",
        )
        try:
            version_line = custom_identity.stdout.decode("utf-8", "strict").splitlines()
        except UnicodeDecodeError:
            raise GateFailure("custom Caddy version is invalid") from None
        if (
            custom_identity.stderr
            or len(version_line) != 1
            or not version_line[0].split()
            or version_line[0].split()[0] != CADDY_OCI_VERSION
        ):
            raise GateFailure("custom Caddy version is invalid")
        binary_provenance = _run(
            _custom_runtime(
                docker,
                image_id,
                ["/bin/sh", "-c", "sha256sum -c /usr/share/licenses/caddy/caddy.sha256"],
            ),
            label="custom Caddy binary provenance",
        )
        if (
            binary_provenance.stdout != b"/usr/bin/caddy: OK\n"
            or binary_provenance.stderr
        ):
            raise GateFailure("custom Caddy binary provenance is invalid")
        formatted = _run(
            _custom_runtime(docker, image_id, ["caddy", "fmt", "/etc/caddy/Caddyfile"]),
            label="Caddyfile formatting",
        )
        if formatted.stdout != CADDYFILE.read_bytes() or formatted.stderr:
            raise GateFailure("Caddyfile is not canonically formatted")
        _run(
            _custom_runtime(
                docker,
                image_id,
                ["caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
            ),
            label="Caddyfile validation",
        )
    finally:
        _remove_custom(docker, tag)
    print(
        json.dumps(
            {
                "digest": CADDY_DIGEST,
                "gate": "G8_CADDY_GATE",
                "platform": CADDY_PLATFORM,
                "result": "PASS",
                "custom_image_id": image_id,
                "custom_version": CADDY_CUSTOM_VERSION,
                "version": CADDY_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def cli() -> int:
    try:
        main()
    except GateFailure as exc:
        print(f"G8_CADDY_GATE: FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"G8_CADDY_GATE: FAIL: unexpected {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
