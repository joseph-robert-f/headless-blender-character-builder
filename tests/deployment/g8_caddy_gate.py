#!/usr/bin/env python3
"""Validate the VPS Caddyfile with the exact reviewed linux/amd64 image."""

from __future__ import annotations

import argparse
import json
import os
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
CADDY_DIGEST = "5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648"
CADDY_REFERENCE = f"caddy:{CADDY_TAG}@sha256:{CADDY_DIGEST}"


class GateFailure(RuntimeError):
    pass


def _run(command: Sequence[str], *, label: str) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=ROOT,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
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
        "linux/amd64",
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
            [docker, "pull", "--platform", "linux/amd64", CADDY_REFERENCE],
            label="pinned Caddy pull",
        )
    inspected = _run(
        [
            docker,
            "image",
            "inspect",
            "--format",
            "{{.Os}}/{{.Architecture}} {{.Id}} {{index .Config.Labels \"org.opencontainers.image.version\"}}",
            CADDY_REFERENCE,
        ],
        label="pinned Caddy inspection",
    ).stdout.decode("utf-8", "strict").strip().split()
    if (
        len(inspected) != 3
        or inspected[0] != "linux/amd64"
        or not inspected[1].startswith("sha256:")
        or len(inspected[1]) != 71
        or inspected[2] != CADDY_OCI_VERSION
    ):
        raise GateFailure("pinned Caddy identity is invalid")

    formatted = _run(
        _runtime(docker, ["caddy", "fmt", "/etc/caddy/Caddyfile"]),
        label="Caddyfile formatting",
    )
    if formatted.stdout != CADDYFILE.read_bytes() or formatted.stderr:
        raise GateFailure("Caddyfile is not canonically formatted")
    _run(
        _runtime(
            docker,
            ["caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
        ),
        label="Caddyfile validation",
    )
    print(
        json.dumps(
            {
                "digest": CADDY_DIGEST,
                "gate": "G8_CADDY_GATE",
                "result": "PASS",
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
