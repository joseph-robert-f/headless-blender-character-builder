#!/usr/bin/env python3
"""Black-box G7 HTTP, persistence, artifact, and isolation smoke gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.build_manifest import BuildManifest


REQUIRED_ARTIFACTS = (
    "model.blend",
    "model.glb",
    "model.stl",
    "preview.png",
    "diagnostics/front.png",
    "diagnostics/side.png",
    "diagnostics/back.png",
    "qa.json",
    "manifest.json",
)
TERMINAL = {"succeeded", "failed", "canceled", "needs_review"}
PROVIDER_MARKERS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


class GateFailure(AssertionError):
    pass


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Make every redirect observable to the caller instead of following it."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    RejectRedirects(),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise GateFailure(f"environment line {number} is malformed")
        name, value = line.split("=", 1)
        if not name or name in values:
            raise GateFailure(f"environment line {number} is ambiguous")
        values[name] = value
    return values


def json_value(payload: bytes) -> Mapping[str, Any]:
    value = json.loads(payload.decode("utf-8", "strict"))
    require(isinstance(value, dict), "HTTP response must be a JSON object")
    return value


def http(
    base_url: str,
    method: str,
    path: str,
    *,
    token: Optional[str] = None,
    body: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 10.0,
) -> tuple[int, Mapping[str, str], bytes]:
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict(exc.headers.items()), exc.read()


def problem_code(payload: bytes) -> str:
    value = json_value(payload)
    error = value.get("error")
    require(isinstance(error, dict), "error response has no envelope")
    code = error.get("code")
    require(isinstance(code, str), "error response has no code")
    return code


def build_status(base_url: str, token: str, build_id: str) -> Mapping[str, Any]:
    status, _headers, payload = http(base_url, "GET", f"/v1/builds/{build_id}", token=token)
    require(status == 200, "build status request failed")
    document = json_value(payload)
    require(document.get("build_id") == build_id, "status build ID changed")
    return document


def submit(
    base_url: str, token: str, request: bytes, key: str
) -> tuple[int, Mapping[str, Any], float]:
    started = time.monotonic()
    status, _headers, payload = http(
        base_url,
        "POST",
        "/v1/builds",
        token=token,
        body=request,
        headers={"Content-Type": "application/json", "Idempotency-Key": key},
    )
    elapsed = time.monotonic() - started
    return status, json_value(payload), elapsed


def cancel(base_url: str, token: str, build: Mapping[str, Any]) -> Mapping[str, Any]:
    build_id = str(build["build_id"])
    status, _headers, payload = http(
        base_url,
        "POST",
        f"/v1/builds/{build_id}/cancel",
        token=token,
        body=b"",
        headers={"Content-Length": "0"},
    )
    require(status in (200, 202), "cancellation request failed")
    return json_value(payload)


def run_command(command: list[str], *, timeout: float = 120.0, expected: int = 0) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env=dict(os.environ),
    )
    if completed.returncode != expected:
        raise GateFailure(
            f"controlled command failed with exit {completed.returncode}: {' '.join(command[:4])}"
        )
    return completed.stdout


def docker_command(*arguments: str) -> list[str]:
    return [os.environ.get("DOCKER", "docker"), *arguments]


def compose_command(project_name: str, *arguments: str) -> list[str]:
    direct_binary = os.environ.get("HBCB_COMPOSE_BIN")
    if direct_binary:
        return [direct_binary, "--project-name", project_name, *arguments]
    return docker_command("compose", "--project-name", project_name, *arguments)


def compose_container_ids(
    env_file: Path, project_name: str, service: str
) -> list[str]:
    output = run_command(
        compose_command(
            project_name, "--env-file", str(env_file), "ps", "-q", service
        )
    )
    return [line for line in output.splitlines() if line]


def inspect_runtime(
    env_file: Path, project_name: str, api_host_port: int
) -> dict[str, str]:
    identities: dict[str, str] = {}
    for service in ("api", "worker"):
        ids = compose_container_ids(env_file, project_name, service)
        require(len(ids) == 1, f"Compose must run exactly one {service} container")
        container_id = ids[0]
        identities[service] = container_id
        inspected = json.loads(run_command(docker_command("inspect", container_id)))[0]
        environment = inspected["Config"].get("Env") or []
        names = {value.split("=", 1)[0] for value in environment}
        require(not (names & set(PROVIDER_MARKERS)), f"{service} received a provider key")
        require(bool(inspected["HostConfig"].get("ReadonlyRootfs")), f"{service} root is writable")
        require("ALL" in (inspected["HostConfig"].get("CapDrop") or []), f"{service} retains capabilities")
        require(
            any("no-new-privileges" in value for value in inspected["HostConfig"].get("SecurityOpt") or []),
            f"{service} lacks no-new-privileges",
        )
        require(int(inspected["HostConfig"].get("PidsLimit") or 0) > 0, f"{service} lacks a PID cap")
        mounts = inspected.get("Mounts") or []
        require(
            all("docker.sock" not in str(item.get("Source", "")) for item in mounts),
            f"{service} received a Docker socket",
        )
        networks = inspected["NetworkSettings"].get("Networks") or {}
        expected_networks = 2 if service == "api" else 1
        require(len(networks) == expected_networks, f"{service} network count is unexpected")
        network_rows = [
            json.loads(
                run_command(docker_command("network", "inspect", value["NetworkID"]))
            )[0]
            for value in networks.values()
        ]
        internal_count = sum(row.get("Internal") is True for row in network_rows)
        require(internal_count == 1, f"{service} lacks its bounded internal network")
        if service == "worker":
            require(all(row.get("Internal") is True for row in network_rows), "worker has public egress")
        else:
            bindings = inspected["HostConfig"].get("PortBindings") or {}
            api_bindings = bindings.get("8080/tcp") or []
            require(
                len(api_bindings) == 1
                and api_bindings[0].get("HostIp") == "127.0.0.1"
                and api_bindings[0].get("HostPort") == str(api_host_port),
                "API does not use the exact selected loopback host port",
            )

    run_command(
        compose_command(
            project_name,
            "--env-file",
            str(env_file),
            "exec",
            "-T",
            "api",
            "/bin/sh",
            "-c",
            "test ! -e /opt/blender && test ! -e /usr/local/bin/builder",
        )
    )
    # A direct numeric route avoids DNS ambiguity.  Internal Docker networks
    # return a controlled connection error because they have no default route.
    run_command(
        compose_command(
            project_name,
            "--env-file",
            str(env_file),
            "exec",
            "-T",
            "worker",
            "/opt/blender/4.5/python/bin/python3.11",
            "-c",
            "import socket;\ntry:\n socket.create_connection(('1.1.1.1',443),2); raise SystemExit(0)\nexcept OSError:\n raise SystemExit(7)",
        ),
        timeout=20,
        expected=7,
    )
    return identities


def wait_ready(base_url: str, token: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _headers, payload = http(
                base_url, "GET", "/readyz", token=token, timeout=3
            )
        # A deliberate container restart can race a just-established socket:
        # urllib wraps connection refusal as URLError, while a peer that
        # accepted before SIGTERM may surface RemoteDisconnected/HTTPException
        # or an OSError.  These are transient only inside this bounded
        # readiness loop; all HTTP status responses still flow through normal
        # validation below.
        except (urllib.error.URLError, HTTPException, OSError):
            time.sleep(1)
            continue
        if status == 200 and json_value(payload).get("status") == "ready":
            return
        time.sleep(1)
    raise GateFailure("API did not become ready")


def choose_active_and_cancel_other(
    base_url: str, token: str, first_id: str, second_id: str
) -> tuple[str, str]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        first = build_status(base_url, token, first_id)
        second = build_status(base_url, token, second_id)
        states = (str(first["status"]), str(second["status"]))
        require(states.count("running") <= 1, "two builds ran concurrently")
        if "succeeded" in states:
            index = states.index("succeeded")
            active, other = (first, second) if index == 0 else (second, first)
            if str(other["status"]) not in TERMINAL:
                cancel(base_url, token, other)
            return str(active["build_id"]), str(other["build_id"])
        if states.count("running") == 1:
            index = states.index("running")
            active, other = (first, second) if index == 0 else (second, first)
            cancel(base_url, token, other)
            return str(active["build_id"]), str(other["build_id"])
        require(not any(state in ("failed", "needs_review") for state in states), "facet build failed early")
        time.sleep(0.5)
    raise GateFailure("worker did not claim either queued build")


def wait_terminal(base_url: str, token: str, build_id: str, timeout: float = 1200) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        document = build_status(base_url, token, build_id)
        current = str(document["status"])
        if current != previous:
            print(json.dumps({"build_id": build_id, "status": current}, sort_keys=True))
            previous = current
        if current in TERMINAL:
            return document
        time.sleep(2)
    raise GateFailure("build did not reach a terminal state")


def download_artifacts(
    base_url: str, token: str, build_id: str, output: Path, storage_host_port: int
) -> tuple[BuildManifest, int]:
    status, _headers, payload = http(
        base_url, "GET", f"/v1/builds/{build_id}/artifacts", token=token
    )
    require(status == 200, "artifact listing failed")
    document = json_value(payload)
    entries = document.get("artifacts")
    require(
        isinstance(entries, list)
        and len(entries) == 9
        and all(isinstance(item, dict) for item in entries),
        "artifact listing is incomplete",
    )
    require(tuple(item.get("path") for item in entries) == REQUIRED_ARTIFACTS, "artifact order changed")
    budget = 2 * 1024 * 1024 * 1024
    declared_total = 0

    def checked_download_url(raw: Any) -> str:
        require(
            isinstance(raw, str)
            and len(raw) <= 8192
            and all(33 <= ord(character) <= 126 for character in raw),
            "signed URL is malformed",
        )
        try:
            parsed = urllib.parse.urlsplit(raw)
            port = parsed.port
            query = urllib.parse.parse_qs(parsed.query)
        except ValueError:
            raise GateFailure("signed URL is malformed") from None
        require(parsed.scheme == "http", "signed URL transport is not local HTTP")
        require(parsed.hostname in ("localhost", "127.0.0.1"), "signed URL is not host-local")
        require(port == storage_host_port, "signed URL does not use the exact selected storage host port")
        require(parsed.username is None and parsed.password is None, "signed URL contains credentials")
        require(not parsed.fragment, "signed URL contains a fragment")
        require("versionId" in query and len(query["versionId"]) == 1, "signed URL is not version-pinned")
        return raw

    for entry in entries:
        expected_bytes = entry.get("bytes")
        expected_hash = entry.get("sha256")
        require(
            type(expected_bytes) is int and 0 <= expected_bytes <= budget,
            "artifact byte evidence is invalid",
        )
        require(
            isinstance(expected_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None,
            "artifact hash evidence is invalid",
        )
        checked_download_url(entry.get("download_url"))
        declared_total += expected_bytes
        require(declared_total <= budget, "artifact set exceeds the v0.1 budget")

    total = 0
    output.mkdir(mode=0o700)
    for entry in entries:
        path = str(entry["path"])
        expected_bytes = entry["bytes"]
        expected_hash = entry["sha256"]
        download_url = entry["download_url"]
        destination = output / path
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        consumed = 0
        try:
            response = NO_REDIRECT_OPENER.open(download_url, timeout=30)
        except urllib.error.HTTPError as error:
            error.close()
            if 300 <= error.code < 400:
                raise GateFailure("artifact redirect was rejected") from None
            raise GateFailure("artifact download returned an HTTP error") from None
        except (urllib.error.URLError, HTTPException, OSError, TimeoutError):
            raise GateFailure("artifact download failed") from None
        try:
            with response:
                require(
                    checked_download_url(response.geturl()) == download_url,
                    "artifact final URL changed",
                )
                require(getattr(response, "status", None) == 200, "artifact HTTP status changed")
                with destination.open("xb") as stream:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        consumed += len(chunk)
                        require(consumed <= expected_bytes, "artifact exceeded its declared size")
                        digest.update(chunk)
                        stream.write(chunk)
        except (urllib.error.URLError, HTTPException, OSError, TimeoutError):
            raise GateFailure("artifact download failed") from None
        require(consumed == expected_bytes, "artifact size does not match API evidence")
        require(digest.hexdigest() == expected_hash, "artifact hash does not match API evidence")
        total += consumed
        require(total <= 2 * 1024 * 1024 * 1024, "artifact set exceeds the v0.1 budget")
    manifest = BuildManifest.from_json((output / "manifest.json").read_bytes())
    return manifest, total


def parity(service: BuildManifest, direct: BuildManifest) -> None:
    require(service.request_sha256 == direct.request_sha256, "request provenance differs from one-shot")
    require(service.spec_sha256 == direct.spec_sha256, "spec provenance differs from one-shot")
    require(service.generator_version == direct.generator_version, "generator version differs from one-shot")
    require(dict(service.execution) == dict(direct.execution), "builder execution provenance differs from one-shot")
    require(service.dimensions_mm == direct.dimensions_mm, "model dimensions differ from one-shot")
    require(dict(service.qa) == dict(direct.qa), "mandatory QA differs from one-shot")
    require(tuple(service.artifacts) == tuple(direct.artifacts), "artifact contract differs from one-shot")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-port", type=int, default=8080)
    parser.add_argument("--storage-port", type=int, default=9000)
    parser.add_argument("--compose-project", default="hbcb-local")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--direct-output", type=Path, required=True)
    parser.add_argument("--service-output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    arguments = parser.parse_args()

    require(1 <= arguments.api_port <= 65535, "API host port is outside policy")
    require(
        1 <= arguments.storage_port <= 65535,
        "storage host port is outside policy",
    )
    require(
        arguments.base_url == f"http://127.0.0.1:{arguments.api_port}",
        "base URL does not match the exact selected API host port",
    )

    environment = load_env(arguments.env_file)
    token = environment["HBCB_API_TOKEN"]
    facet = (ROOT / "examples/requests/facet-bot.json").read_bytes()
    moss = (ROOT / "examples/requests/moss-hopper.json").read_bytes()

    status, _headers, payload = http(arguments.base_url, "GET", "/healthz")
    require(status == 200 and json_value(payload).get("status") == "ok", "public health failed")
    status, _headers, payload = http(arguments.base_url, "GET", "/readyz")
    require(status == 401 and problem_code(payload) == "unauthorized", "private readiness is public")
    status, _headers, payload = http(
        arguments.base_url, "GET", "/readyz", token="invalid-" + uuid4().hex
    )
    require(status == 401 and problem_code(payload) == "unauthorized", "invalid bearer was accepted")
    wait_ready(arguments.base_url, token)
    identities = inspect_runtime(
        arguments.env_file, arguments.compose_project, arguments.api_port
    )

    key = "g7-primary-" + uuid4().hex
    second_key = "g7-secondary-" + uuid4().hex
    first_status, first, elapsed = submit(arguments.base_url, token, facet, key)
    require(first_status == 202, "first submission was not accepted asynchronously")
    require(elapsed < 10, "submission waited for Blender")
    second_status, second, _second_elapsed = submit(arguments.base_url, token, facet, second_key)
    require(second_status == 202, "second submission was not accepted")
    require(first["build_id"] != second["build_id"], "independent keys reused a build")

    replay_status, replay, _replay_elapsed = submit(arguments.base_url, token, facet, key)
    require(replay_status == 200 and replay["build_id"] == first["build_id"], "idempotent replay failed")
    conflict_status, conflict, _conflict_elapsed = submit(arguments.base_url, token, moss, key)
    require(conflict_status == 409, "conflicting idempotency key was accepted")
    error = conflict.get("error")
    require(isinstance(error, dict) and error.get("code") == "idempotency_conflict", "conflict code changed")

    active_id, canceled_id = choose_active_and_cancel_other(
        arguments.base_url, token, str(first["build_id"]), str(second["build_id"])
    )

    run_command(
        compose_command(
            arguments.compose_project,
            "--env-file",
            str(arguments.env_file),
            "restart",
            "api",
        ),
        timeout=120,
    )
    wait_ready(arguments.base_url, token)
    require(build_status(arguments.base_url, token, active_id)["build_id"] == active_id, "active build was lost on API restart")
    require(build_status(arguments.base_url, token, canceled_id)["build_id"] == canceled_id, "canceled build was lost on API restart")

    terminal = wait_terminal(arguments.base_url, token, active_id)
    require(terminal["status"] == "succeeded", "facet build did not succeed")
    canceled = wait_terminal(arguments.base_url, token, canceled_id, timeout=180)
    require(canceled["status"] == "canceled", "queued sibling was not canceled")

    manifest, total = download_artifacts(
        arguments.base_url,
        token,
        active_id,
        arguments.service_output,
        arguments.storage_port,
    )
    direct_manifest = BuildManifest.from_json(
        (arguments.direct_output / "manifest.json").read_bytes()
    )
    parity(manifest, direct_manifest)

    summary = {
        "active_build_id": active_id,
        "api_container_id": identities["api"],
        "artifact_bytes": total,
        "artifacts": len(REQUIRED_ARTIFACTS),
        "asynchronous_response_seconds": round(elapsed, 6),
        "canceled_build_id": canceled_id,
        "gate": "G7_SERVICE_SMOKE",
        "idempotency_conflict": True,
        "idempotency_replay": True,
        "manifest_sha256": hashlib.sha256(
            (arguments.service_output / "manifest.json").read_bytes()
        ).hexdigest(),
        "provider_key_present": False,
        "result": "PASS",
        "worker_container_id": identities["worker"],
        "worker_count": 1,
        "worker_public_egress": False,
    }
    arguments.summary.write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
