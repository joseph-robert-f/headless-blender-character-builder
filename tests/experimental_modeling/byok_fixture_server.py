"""Offline provider fixture for browser QA, optionally followed by real Docker.

The production OpenAI adapter validates the mocked wire response. No external
network, Secret Service lookup, real credential, or source execution is used by
this fixture transport. --fixture-only explicitly disables the Run endpoint;
without that flag the existing isolated bridge and verifier remain unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experimental_modeling.authoring import AuthorConfig
from experimental_modeling.launcher import interruptible, operation_lock
from experimental_modeling.model_provider import OpenAIProvider, ProviderError
from experimental_modeling.project import atomic_json, initialize
from experimental_modeling.request_contract import encoded, sha
from experimental_modeling.runtime import RuntimeSelection
from experimental_modeling.workbench import Workbench, WorkbenchServer

EXAMPLE = ROOT / "experimental_modeling/examples/external_lamp"
# Deliberately fictitious, supplied only to the injected in-memory transport.
FIXTURE_CREDENTIAL = "offline-fixture-credential-not-a-real-key"


class FixtureTransport:
    def __init__(self, output):
        self.output = output
        self.calls = []
        self.credential_reads = 0
        self.lock = threading.Lock()
        self.proposal = {
            "source": [{"name": file.name, "content": file.read_text(encoding="utf-8")}
                       for file in sorted((EXAMPLE / "proposal/source").glob("*.py"))],
            "params_json": (EXAMPLE / "proposal/params.json").read_text(encoding="utf-8"),
        }
        self.record()

    def record(self):
        atomic_json(self.output / "fixture-transport.json", {
            "scope": "Mock HTTP responses through the production adapter; no real API/key",
            "calls": self.calls, "credential_reads": self.credential_reads,
        }, replace=True)

    def credential(self):
        with self.lock:
            self.credential_reads += 1
            self.record()
        return FIXTURE_CREDENTIAL

    def __call__(self, *, body, key, cancel_event, timeout):
        assert key == FIXTURE_CREDENTIAL
        assert key.encode() not in body
        request = json.loads(body)
        context = json.loads(request["input"][0]["content"][0]["text"])
        brief = context["request"]["prompt"]
        case = next((name for name in ("refusal", "invalid", "cancel")
                     if f"[fixture:{name}]" in brief), "success")
        with self.lock:
            number = len(self.calls) + 1
            self.calls.append({"number": number, "case": case})
            self.record()
            # Retain exactly the bytes received by the production adapter's
            # injected HTTP transport, never its credential argument.
            (self.output / f"fixture-request-{number:02d}.json").write_bytes(body)
        if case == "cancel":
            if not cancel_event.wait(min(timeout, 30)):
                raise ProviderError("timeout")
            raise ProviderError("cancelled")
        if cancel_event.wait(0.15):
            raise ProviderError("cancelled")
        content = [{"type": "output_text", "text": json.dumps(self.proposal)}]
        if case == "refusal":
            content = [{"type": "refusal", "refusal": "Offline fixture refusal."}]
        elif case == "invalid":
            invalid = {"source": [{"name": "../escape.py", "content": "# inert"}],
                       "params_json": "{}"}
            content = [{"type": "output_text", "text": json.dumps(invalid)}]
        response = {"status": "completed", "error": None, "incomplete_details": None,
                    "output": [{"type": "message", "role": "assistant", "status": "completed",
                                "content": content}],
                    "usage": {"input_tokens": 1234, "output_tokens": 567,
                              "input_tokens_details": {"cached_tokens": 0}}}
        return 200, encoded(response)


def no_production_access(*_args, **_kwargs):
    raise AssertionError("Browser QA must not use production network or credentials.")


def fixture_runtime_identity(docker, socket_path, image):
    """Inspection-only identity fixture; it can never authorize execution."""
    return {"mode": "docker-isolated", "image": image,
            "docker_sha256": sha(Path(docker).read_bytes()),
            "docker_path_sha256": sha(str(docker).encode()),
            "socket_path_sha256": sha(str(socket_path).encode()),
            "socket_device": 0, "socket_inode": 0}


def fixture_run_disabled(*_args, **_kwargs):
    raise ValueError("Fixture-only QA cannot execute source or claim Blender evidence.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--docker", type=Path)
    parser.add_argument("--docker-socket", type=Path)
    parser.add_argument("--sandbox-image")
    args = parser.parse_args(argv)
    if args.output.exists() and any((args.output / name).exists() for name in
                                    ("project", "handoffs", "proposals", "rules")):
        parser.error("Use a new output directory; existing evidence is never overwritten.")
    if not args.fixture_only and not all((args.docker, args.docker_socket, args.sandbox_image)):
        parser.error("Real integration requires an explicit trusted Docker executable, socket, and image.")
    args.output.mkdir(parents=True, exist_ok=True)
    project = initialize(args.output / "project", "Offline BYOK browser QA")
    roots = [args.output / name for name in ("handoffs", "proposals", "rules")]
    for directory in roots:
        directory.mkdir()
    for name in ("policy-initial.json", "requirements.json"):
        shutil.copyfile(EXAMPLE / name, roots[2] / name)
    transport = FixtureTransport(args.output)
    with ExitStack() as stack:
        if args.fixture_only:
            # The browser-only test does not impersonate a Docker daemon. Its
            # explicit inert runtime identity is used for inspection only.
            socket_path = args.output / "fixture-runtime-marker"
            socket_path.write_text("Inert browser fixture; not a Docker socket.\n", encoding="utf-8")
            for target in ("experimental_modeling.workbench.runtime_identity",
                           "experimental_modeling.requests.runtime_identity"):
                stack.enter_context(patch(target, fixture_runtime_identity))
            selection = RuntimeSelection(docker=Path("/usr/bin/false").resolve(),
                                         socket=socket_path, image="sha256:" + "a" * 64)
            stack.enter_context(patch.object(Workbench, "run", fixture_run_disabled))
        else:
            selection = RuntimeSelection(docker=args.docker, socket=args.docker_socket,
                                         image=args.sandbox_image)
        stack.enter_context(patch("experimental_modeling.model_provider.direct_https_request",
                                  no_production_access))
        stack.enter_context(patch("experimental_modeling.model_provider.read_secret_service_key",
                                  no_production_access))
        provider = OpenAIProvider(transport=transport,
                                  credential_reader=transport.credential)
        config = AuthorConfig("gpt-4.1-mini", "0.40", "1.60", "1.00", 8192, 8)
        with operation_lock(project, "workbench"), interruptible():
            workbench = Workbench(project, selection, *roots, Path(sys.executable).resolve(),
                                  author_config=config, provider=provider)
            server = WorkbenchServer(workbench)
            print(f"Offline BYOK fixture: {server.origin}/workbench", flush=True)
            print("Fixture-only: no source execution" if args.fixture_only else
                  "Real isolated Docker execution remains separately gated", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    workbench.close()
                finally:
                    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
