"""Opt-in Linux source-only external-author workbench. Never a model provider."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socketserver
import stat
import subprocess
import threading
from http.server import ThreadingHTTPServer

from . import requests
from .launcher import interruptible, operation_lock
from .platform_io import safe_path
from .project import Project, atomic_json
from .request_contract import (MAX_SOURCE, _unique, encoded, prompt_text, read_bytes,
    read_json, relative_name, runtime_identity, sha)
from .review_server import ReviewHandler, ReviewProject
from .runtime import RuntimeSelection, canonical_selection, executable

STATIC = Path(__file__).with_name("workbench_static")
ID = re.compile(r"[0-9a-f]{32}\Z")
MAX_RECORD = 80 * 1024 * 1024
MAX_RECORDS = 32


def opaque(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Select an existing workbench item.")
    return value


def identity(path):
    info = safe_path(path).stat()
    return [info.st_dev, info.st_ino]


def text_or_binary(data):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class Workbench:
    def __init__(self, project, selection, handoffs, proposals, rules, python):
        requests.supported()
        project.validate_folders()
        self.project = project
        self.review = ReviewProject(project.folder("evidence"), name=project.name)
        self.token = self.review.token
        self.selection = canonical_selection(selection, project)
        self.runtime = runtime_identity(self.selection.docker, self.selection.socket, self.selection.image)
        self.checkout = safe_path(Path(__file__).parent.parent)
        self.python = executable(python, project)
        self.roots = {"handoffs": safe_path(handoffs), "proposals": safe_path(proposals), "rules": safe_path(rules)}
        roots = [project.root, self.checkout, *self.roots.values()]
        for root in self.roots.values():
            if not root.is_dir():
                raise ValueError("Create each dedicated intake directory before startup.")
            for other in roots:
                if root != other:
                    requests.disjoint(root, other)
            if roots.count(root) != 1:
                raise ValueError("Use distinct intake directories.")
            for trusted in (self.python, self.selection.docker, self.selection.socket):
                if trusted.is_relative_to(root):
                    raise ValueError("Trusted runtime inputs cannot come from an intake directory.")
        self.root_ids = {str(root): identity(root) for root in roots}
        self.descriptor = sha(read_bytes(project.root / "modeling-project.json", 16384))
        self.code = self.code_identity()
        self.python_hash = sha(read_bytes(self.python, 256 * 1024 * 1024))
        self.directory = safe_path(project.root / ".authoring-workbench")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.choices = {}
        self.lock = threading.RLock()
        self.child = None
        self.child_id = None
        self.stopped_process = None
        self.monitor = None
        self.stopping = False

    def stop_owned(self, process):
        with self.lock:
            if self.stopped_process is process:
                return
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
            self.stopped_process = process

    def code_identity(self):
        return {path.name: sha(read_bytes(path, 4 * 1024 * 1024))
                for path in sorted((self.checkout / "experimental_modeling").glob("*.py"))}

    def pinned(self):
        for root, expected in self.root_ids.items():
            if identity(Path(root)) != expected:
                raise ValueError("A startup root changed. Stop and examine the selected paths.")
        if (sha(read_bytes(self.project.root / "modeling-project.json", 16384)) != self.descriptor or
                self.code_identity() != self.code or
                sha(read_bytes(self.python, 256 * 1024 * 1024)) != self.python_hash or
                runtime_identity(self.selection.docker, self.selection.socket, self.selection.image) != self.runtime):
            raise ValueError("A trusted startup input changed. Restart only after reviewing the change.")

    def records(self, kind):
        result = []
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if entry.name.startswith(kind + "-") and entry.name.endswith(".json"):
                    if len(result) >= MAX_RECORDS:
                        raise ValueError("Workbench record limit reached. Keep this journal for review.")
                    value = read_json(Path(entry.path), MAX_RECORD)
                    if kind == "inspection":
                        value = {key: value[key] for key in ("id", "revision", "inspection_digest", "summary")}
                    result.append(value)
        return sorted(result, key=lambda item: item["id"])

    def record(self, kind, item_id):
        return read_json(self.directory / (kind + "-" + opaque(item_id) + ".json"), MAX_RECORD)

    def save(self, kind, value, *, replace=False):
        if len(encoded(value)) > MAX_RECORD:
            raise ValueError("The complete inspection exceeds the workbench record limit.")
        atomic_json(self.directory / (kind + "-" + opaque(value["id"]) + ".json"), value, replace=replace)

    def catalogue(self):
        result = {}
        for kind, root in self.roots.items():
            items = []
            with os.scandir(root) as entries:
                for count, entry in enumerate(entries):
                    if count >= 128:
                        raise ValueError("An intake root exceeds 128 entries.")
                    relative_name(entry.name)
                    path = safe_path(Path(entry.path))
                    info = path.lstat()
                    if kind == "rules":
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.suffix != ".json":
                            raise ValueError("The reviewed-rules root permits only regular JSON files without links.")
                    elif not stat.S_ISDIR(info.st_mode):
                        raise ValueError("Handoff and proposal roots permit only directories without links.")
                    key = (kind, str(path))
                    token = next((key_id for key_id, selected in self.choices.items() if selected == key), None)
                    if token is None:
                        token = secrets.token_hex(16)
                        self.choices[token] = key
                    items.append({"id": token, "label": entry.name})
            result[kind] = sorted(items, key=lambda item: item["label"])
        return result

    def selected(self, item_id, kind):
        selected_kind, value = self.choices[opaque(item_id)]
        path = safe_path(Path(value))
        if selected_kind != kind or path.parent != self.roots[kind]:
            raise ValueError("Selection is outside its pinned intake root.")
        return path

    def operation(self, item_id):
        record = self.record("operation", item_id)
        result = {key: record[key] for key in ("id", "revision", "state", "detail")}
        live = self.child_id == item_id and self.child is not None and self.child.poll() is None
        result["can_interrupt"] = live
        if record["state"] in {"claimed", "running", "interruption_requested"} and not live:
            result["state"] = "uncertain"
            result["detail"] = "Execution ownership was lost. No restart or retry occurs. Examine the terminal recovery state and retained journal."
        try:
            revision = self.review.revision(record["revision"])
            from .review_server import verified_revision
            from .request_contract import validate_result_binding
            directory, raw, _ = verified_revision(self.project.folder("evidence"), record["revision"])
            binding = validate_result_binding(directory, raw)
            if binding is None or binding["inspection_digest"] != record["inspection_digest"]:
                raise ValueError("The candidate has a different request binding.")
            result["result"] = revision
            result["comparison_url"] = "/"
        except (ValueError, OSError, KeyError, TypeError):
            pass
        return result

    def state(self):
        with self.lock:
            self.pinned()
            return {"csrf_token": self.token, "project_name": self.project.name,
                    "roots": {key: str(value) for key, value in self.roots.items()},
                    "choices": self.catalogue(),
                    "operations": [self.operation(row["id"]) for row in self.records("operation")],
                    "inspections": [{key: row[key] for key in ("id", "revision", "inspection_digest", "summary")}
                                    for row in self.records("inspection")]}

    def prepare(self, payload):
        with self.lock:
            self.pinned()
            allowed = {"csrf_token", "brief"} if "brief" in payload else {"csrf_token", "request_id"}
            if set(payload) != allowed:
                raise ValueError("Supply only one initial brief or saved request ID.")
            catalogue = self.catalogue()
            if len(catalogue["handoffs"]) >= 128 or sum(1 for _ in self.directory.glob("brief-*.txt")) >= 128:
                raise ValueError("Handoff preparation limit reached. Keep partial files for examination.")
            output = self.roots["handoffs"] / ("handoff-" + secrets.token_hex(16))
            if "brief" in payload:
                brief = prompt_text(payload["brief"])
                # Brief stays inside trusted metadata, never inside author code.
                path = self.directory / ("brief-" + secrets.token_hex(16) + ".txt")
                requests._write(path, brief.encode("utf-8"))
                value = requests.prepare(self.project, output, brief_file=path)
            else:
                value = requests.prepare(self.project, output, request_id=payload["request_id"])
            self.catalogue()
            return {**value, "path": str(output), "label": output.name}

    def inspect(self, payload):
        with self.lock:
            self.pinned()
            if set(payload) != {"csrf_token", "handoff_id", "proposal_id", "policy_id", "requirements_id"}:
                raise ValueError("Select handoff, proposal and separately reviewed rules.")
            if len(self.records("inspection")) >= MAX_RECORDS - 1:
                raise ValueError("The workbench inspection limit is reached. Keep the journal for review.")
            handoff = self.selected(payload["handoff_id"], "handoffs")
            proposal = self.selected(payload["proposal_id"], "proposals")
            policy = self.selected(payload["policy_id"], "rules")
            requirements = self.selected(payload["requirements_id"], "rules") if payload["requirements_id"] else None
            values = requests.inspect_proposal(self.project, handoff, proposal, policy, self.selection, requirements_path=requirements)
            summary, request, approval, params, rules, required, _ = values
            source, before_source = [], {}
            for name, expected in approval["source_files"].items():
                data = read_bytes(proposal / "source" / name, MAX_SOURCE)
                if sha(data) != expected:
                    raise ValueError("Source changed during complete inspection.")
                source.append({"name": name, "sha256": expected, "bytes": len(data), "text": text_or_binary(data)})
            for name, expected in request["context_files"].items():
                if name.startswith("context/source/"):
                    data = read_bytes(handoff / name, MAX_SOURCE)
                    if sha(data) != expected:
                        raise ValueError("Reference changed during complete inspection.")
                    before_source[name[len("context/source/"):]] = text_or_binary(data)
            before = {}
            for role in ("params", "policy", "requirements"):
                name = "context/" + role + ".json"
                before[role] = read_json(handoff / name, 4 * 1024 * 1024) if name in request["context_files"] else {}
            # Verify the complete displayed snapshot still has the original digest.
            again = requests.inspect_proposal(self.project, handoff, proposal, policy, self.selection, requirements_path=requirements)[0]
            if again["inspection_digest"] != summary["inspection_digest"]:
                raise ValueError("Inputs changed during complete inspection.")
            item_id = secrets.token_hex(16)
            after_source = {row["name"]: row["text"] for row in source}
            value = {"id": item_id, "revision": "wb-" + item_id, "inspection_digest": summary["inspection_digest"],
                     "summary": summary, "inputs": {"request": request, "source": source, "parameters": params, "policy": rules, "requirements": required},
                     "diffs": {"source": [{"name": name, "before": before_source.get(name), "after": after_source.get(name), "before_sha256": request["context_files"].get("context/source/" + name), "after_sha256": approval["source_files"].get(name)} for name in summary["changed_files"]],
                               "parameters": {"before": before["params"], "after": params},
                               "policy": {"before": before["policy"], "after": rules},
                               "requirements": {"before": before["requirements"], "after": required}},
                     "paths": {"handoff": str(handoff), "proposal": str(proposal), "policy": str(policy), "requirements": str(requirements) if requirements else None}}
            self.save("inspection", value)
            return value

    def run(self, item_id):
        with self.lock:
            item_id = opaque(item_id)
            path = self.directory / ("operation-" + item_id + ".json")
            if path.exists():
                return self.operation(item_id)
            self.pinned()
            if self.stopping:
                raise ValueError("The server is stopping.")
            for old in self.records("operation"):
                if self.operation(old["id"])["state"] in {"running", "claimed", "interruption_requested", "uncertain"}:
                    raise ValueError("An operation is active or uncertain. Examine it before another build.")
            inspection = self.record("inspection", item_id)
            paths = inspection["paths"]
            for role, kind in (("handoff", "handoffs"), ("proposal", "proposals"), ("policy", "rules"), ("requirements", "rules")):
                if paths[role] is not None and safe_path(Path(paths[role])).parent != self.roots[kind]:
                    raise ValueError("Recorded input is outside the pinned root.")
            # Claim durably BEFORE reinspection/spawn. Every failure consumes this ID.
            record = {"id": item_id, "revision": inspection["revision"], "inspection_digest": inspection["inspection_digest"],
                      "state": "claimed", "detail": "Permission consumed for this exact revision and inspection."}
            self.save("operation", record)
            try:
                actual = requests.inspect_proposal(self.project, Path(paths["handoff"]), Path(paths["proposal"]), Path(paths["policy"]), self.selection,
                                                  requirements_path=Path(paths["requirements"]) if paths["requirements"] else None)[0]
                if actual["inspection_digest"] != inspection["inspection_digest"]:
                    raise ValueError("Inputs changed. This permission was consumed without execution. Inspect again.")
                args = [str(self.python), "-I", "-c", "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('experimental_modeling.requests',run_name='__main__')",
                        str(self.checkout), "run", "--project", str(self.project.root), "--handoff", paths["handoff"], "--proposal", paths["proposal"],
                        "--policy", paths["policy"], "--docker", str(self.selection.docker), "--docker-socket", str(self.selection.socket),
                        "--sandbox-image", self.selection.image, "--expected-digest", inspection["inspection_digest"], "--revision", inspection["revision"]]
                if paths["requirements"]:
                    args += ["--requirements", paths["requirements"]]
                self.pinned()
                self.child = subprocess.Popen(args, shell=False, cwd=self.checkout, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={"PATH": "/usr/bin:/bin", "HOME": str(self.directory), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}, start_new_session=True)
                self.child_id = item_id
                self.monitor = threading.Thread(target=self.watch, args=(self.child, dict(record)), daemon=False)
                self.monitor.start()
                record.update(state="running", detail="The isolated request bridge is running. Closing the browser does not stop it.")
                self.save("operation", record, replace=True)
            except (ValueError, OSError, RuntimeError) as exc:
                if self.child_id == item_id:
                    self.stop_owned(self.child)
                    if self.monitor is None or self.monitor.ident is None:
                        self.watch(self.child, dict(record))
                else:
                    record.update(state="failed_before_execution", detail=str(exc)[:2000])
                    self.save("operation", record, replace=True)
                raise
            return self.operation(item_id)

    def watch(self, process, record):
        output = bytearray()
        failure = None
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                if len(output) < 65536:
                    output.extend(chunk[:65536 - len(output)])
        except (OSError, ValueError) as exc:
            failure = str(exc)
            self.stop_owned(process)
        finally:
            # Reap even when pipe reading fails. Only this live Popen object
            # authorizes signalling; no PID is ever persisted or recovered.
            code = process.wait()
            process.stdout.close()
        with self.lock:
            record.update(state="failed" if failure else "finished" if code in (0, 1) else "interrupted" if code in (130, -signal.SIGTERM, -signal.SIGINT) else "failed",
                          detail=failure or output.decode("utf-8", errors="replace"), exit_code=code)
            try:
                self.save("operation", record, replace=True)
            except (OSError, ValueError):
                # Preserve the durable consumed claim as uncertain. A journal
                # write error cannot justify retry or invent a terminal record.
                pass

    def interrupt(self, item_id):
        with self.lock:
            item_id = opaque(item_id)
            if self.child_id != item_id or self.child is None or self.child.poll() is not None:
                return self.operation(item_id)
            record = self.record("operation", item_id)
            record.update(state="interruption_requested", detail="Stop requested. Waiting for the bridge to preserve recovery evidence and clean up.")
            self.save("operation", record, replace=True)
            self.stop_owned(self.child)
            return self.operation(item_id)

    def close(self):
        with self.lock:
            self.stopping = True
            process = self.child
            if process is not None and process.poll() is None:
                # Cleanup cannot depend on writable/readable metadata.
                self.stop_owned(process)
        if self.monitor is not None and self.monitor.ident is not None:
            self.monitor.join()
        elif process is not None:
            process.wait()
            if process.stdout is not None:
                process.stdout.close()


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = False
    def __init__(self, workbench, port=0):
        self.workbench = workbench
        self.project = workbench.review
        super().__init__(("127.0.0.1", port), WorkbenchHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class WorkbenchHandler(ReviewHandler):
    def boundary(self, post=False):
        for name in ("Host", "Origin", "Sec-Fetch-Site", "Content-Type", "Content-Length", "Transfer-Encoding"):
            if len(self.headers.get_all(name, [])) > 1:
                raise PermissionError("Duplicate security headers are not permitted.")
        super().boundary(post)

    def do_GET(self):
        try:
            self.boundary()
            path = self.route()
            workbench = self.server.workbench
            if path == "/api/workbench":
                return self.json(200, workbench.state())
            for kind in ("operations", "inspections"):
                prefix = "/api/workbench/" + kind + "/"
                if path.startswith(prefix):
                    item_id = opaque(path[len(prefix):])
                    return self.json(200, workbench.operation(item_id) if kind == "operations" else workbench.record("inspection", item_id))
            files = {"/workbench": "index.html", "/workbench/static/app.js": "app.js", "/workbench/static/style.css": "style.css"}
            if path in files:
                file = STATIC / files[path]
                data = read_bytes(file, 512 * 1024)
                mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
                self.send_headers(200, mime + "; charset=utf-8", len(data))
                return self.wfile.write(data)
            return super().do_GET()
        except PermissionError as exc:
            self.json(403, {"error": str(exc)})
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            self.json(409, {"error": str(exc)[:2000]})

    def do_POST(self):
        try:
            self.boundary(post=True)
            path = self.route()
            if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("A bounded JSON body is required.")
            length = self.headers.get("Content-Length", "")
            if not length.isdigit() or not 0 < int(length) <= 65536:
                raise ValueError("Incorrect bounded content length.")
            payload = json.loads(self.rfile.read(int(length)), object_pairs_hook=_unique,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Incorrect JSON number.")))
            workbench = self.server.workbench
            if not isinstance(payload, dict) or not isinstance(payload.get("csrf_token"), str) or not secrets.compare_digest(payload["csrf_token"], workbench.token):
                raise PermissionError("Incorrect CSRF token.")
            if path == "/api/requests":
                return self.json(200, workbench.review.request(payload))
            if path.startswith("/api/revisions/") and path.endswith("/accept"):
                from .contracts import identifier
                revision = identifier(path[len("/api/revisions/"):-len("/accept")])
                return self.json(200, workbench.review.accept(revision, payload))
            if path == "/api/workbench/prepare":
                return self.json(200, workbench.prepare(payload))
            if path == "/api/workbench/inspect":
                return self.json(200, workbench.inspect(payload))
            if path == "/api/workbench/run" and set(payload) == {"csrf_token", "inspection_id"}:
                return self.json(200, workbench.run(payload["inspection_id"]))
            if path == "/api/workbench/interrupt" and set(payload) == {"csrf_token", "operation_id"}:
                return self.json(200, workbench.interrupt(payload["operation_id"]))
            raise ValueError("Unknown workbench command or fields.")
        except PermissionError as exc:
            self.json(403, {"error": str(exc)})
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            self.json(409, {"error": str(exc)[:2000]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "handoff-root", "proposal-root", "rules-root", "docker", "docker-socket", "python"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    project = Project.open(args.project)
    with operation_lock(project, "workbench"), interruptible():
        workbench = Workbench(project, RuntimeSelection(docker=args.docker, socket=args.docker_socket, image=args.sandbox_image),
                              args.handoff_root, args.proposal_root, args.rules_root, args.python)
        server = WorkbenchServer(workbench, args.port)
        print(f"External author workbench: {server.origin}/workbench", flush=True)
        print("Linux source-only. External author required. Each Run consumes one inspected permission. Ctrl-C stops the owned bridge.", flush=True)
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
