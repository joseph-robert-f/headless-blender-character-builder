"""Native-OS review contracts; synthetic evidence never executes model source.

Run only this module on candidate platforms. The legacy launcher/controller
suites include Linux execution fixtures and are not portability evidence.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from experimental_modeling import runtime
from experimental_modeling.contracts import Policy, read_json
from experimental_modeling.project import DESCRIPTOR, Project
from experimental_modeling.requirements import RequirementSet, canonical_hash
from experimental_modeling.review_server import LocalReviewServer, ReviewProject
from experimental_modeling.verification import make_report

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == "nt"
WINDOWS_CONSOLE = bool(ctypes.windll.kernel32.GetConsoleCP()) if WINDOWS else False
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jO7cAAAAASUVORK5CYII=")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def snapshot(root):
    """Include directory creation and exact file bytes, not access-time changes."""
    return {path.relative_to(root).as_posix(): digest(path) if path.is_file() else None
            for path in root.rglob("*")}


def fixture(store):
    """Bound test-only evidence; no Blender, source import, or runtime discovery."""
    revision = store / "accepted" / "r0"
    (revision / "inspection" / "views").mkdir(parents=True)
    spec = {"schema_version": 1, "requirements": []}
    policy = {"schema_version": 1, "parts": ["body"], "changed_parts": [],
              "constraints": [], "profile": "scene"}
    observation = {"parts": {"body": {
        "world_vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "triangle_indices": [[0, 1, 2]], "edge_indices": [[0, 1], [1, 2], [2, 0]],
        "geometry_hash": "synthetic-geometry", "transform_hash": "synthetic-transform",
        "material_hash": "synthetic-material"}}}
    write_json(store / "requirements.json", spec)
    write_json(revision / "requirements.json", spec)
    write_json(revision / "policy.json", policy)
    write_json(revision / "inspection" / "observation.json", observation)
    (revision / "inspection" / "views" / "front.png").write_bytes(PNG)
    result = {
        "schema_version": 1, "revision": "r0", "parent": None,
        "parent_result_hash": None, "status": "accepted",
        "jobs": {job: {"exit_code": 0} for job in ("author", "inspect", "roundtrip", "reopen")},
        "provenance_verified": True, "requirements_hash": canonical_hash(spec),
        "policy_hash": digest(revision / "policy.json"), "runtime_hash": "synthetic-fixture",
        "source_files": {}, "failures": [],
    }
    write_json(revision / "verification.json", make_report(
        result, Policy.parse(policy), observation, None, RequirementSet.parse(spec)))
    # Serialized evidence uses POSIX separators even on Windows.
    result["artifacts"] = {path.relative_to(revision).as_posix(): digest(path)
                           for path in revision.rglob("*") if path.is_file()}
    write_json(revision / "result.json", result)
    write_json(store / "last_good.json", {"revision": "r0", "result_hash": digest(revision / "result.json")})
    return revision


def child_env():
    return os.environ | {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def request(origin, path, method="GET", body=None, headers=None):
    port = int(origin.rsplit(":", 1)[1])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    values = {} if headers is None else dict(headers)
    if body is not None:
        values.setdefault("Content-Type", "application/json")
        values.setdefault("Origin", origin)
        body = json.dumps(body).encode("utf-8")
    try:
        connection.request(method, path, body=body, headers=values)
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise AssertionError("Unbounded review response")
        decoded = json.loads(data) if response.getheader("Content-Type", "").startswith("application/json") else data
        return response.status, dict(response.getheaders()), decoded
    finally:
        connection.close()


class PortableCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="portable-review-")
        self.addCleanup(self.temporary.cleanup)
        # macOS /var can itself be a symlink. Resolve only the trusted temp base.
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "Project with spaces 雪"
        result = self.cli("init", "--project", self.root, "--name", "Review 雨 and spaces")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.project = Project.open(self.root)
        self.store = self.project.folder("evidence")
        self.revision = fixture(self.store)
        (self.project.folder("source") / "builder.py").write_text(
            'raise AssertionError("Review must never execute model source")\n', encoding="utf-8")

    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "experimental_modeling.launcher", *map(str, arguments)],
            cwd=ROOT, env=child_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", timeout=20, check=False)

    def spawn(self, arguments):
        process = subprocess.Popen(
            [sys.executable, *map(str, arguments)], cwd=ROOT, env=child_env(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0)
        output = queue.Queue()
        def read_lines():
            # A bounded count and line length prevent unbounded diagnostic storage.
            for _ in range(128):
                line = process.stdout.readline(4096)
                if not line:
                    break
                output.put(line)
        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        def cleanup():
            self.kill(process)
            reader.join(timeout=5)
        self.addCleanup(cleanup)
        return process, output

    @staticmethod
    def kill(process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        if process.stdout is not None:
            process.stdout.close()

    def line(self, process, output, expected):
        deadline = time.monotonic() + 15
        lines = []
        while time.monotonic() < deadline:
            try:
                line = output.get(timeout=.1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            lines.append(line)
            if expected in line:
                return line.strip()
        self.fail("Child did not become ready: " + "".join(lines)[-8192:])

    def start_review(self):
        process, output = self.spawn([
            "-m", "experimental_modeling.launcher", "review", "--project", self.root,
            "--experimental-platform-review", "--port", "0"])
        line = self.line(process, output, "Local project review:")
        match = re.fullmatch(r"Local project review: (http://127\.0\.0\.1:[0-9]+)", line)
        self.assertIsNotNone(match, line)
        return process, match.group(1)

    def stop_review(self, process):
        if WINDOWS and not WINDOWS_CONSOLE:
            # Background Windows runners can lack a console. Forced recovery
            # still runs; the separate graceful-stop test records an explicit skip.
            self.kill(process)
            return
        if WINDOWS:
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=15), 130)
        state = json.loads((self.root / ".launcher-review.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "stopped")


class PortableProjectTests(PortableCase):
    def test_cli_init_move_and_no_probe_doctor(self):
        before = snapshot(self.root)
        result = self.cli("init", "--project", self.root)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(before, snapshot(self.root))
        descriptor = (self.root / DESCRIPTOR).read_bytes()
        moved = self.base / "Moved portable project 雨"
        self.root.rename(moved)
        self.root = moved
        self.project = Project.open(moved)
        self.project.validate_folders()
        self.assertEqual((moved / DESCRIPTOR).read_bytes(), descriptor)
        self.assertNotIn(str(self.base), descriptor.decode("utf-8"))
        before = snapshot(moved)
        result = self.cli("doctor", "--project", moved)
        self.assertEqual(result.returncode, 1, result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["project_name"], "Review 雨 and spaces")
        self.assertFalse(report["probed"])
        self.assertFalse(report["build_ready"])
        self.assertFalse(report["authoring_ready"])
        supported = platform.system() == "Linux" and platform.machine().lower() in {"x86_64", "amd64"}
        self.assertEqual(report["review_ready"], supported)
        self.assertEqual(before, snapshot(moved))

    def test_doctor_cannot_spawn_or_discover_runtime(self):
        before = snapshot(self.root)
        with patch("subprocess.Popen", side_effect=AssertionError("Unexpected runtime spawn")), \
                patch("shutil.which", side_effect=AssertionError("Unexpected runtime discovery")):
            for selection in (runtime.RuntimeSelection(), runtime.RuntimeSelection(
                    mode="trusted-native", blender=Path(sys.executable))):
                report = runtime.doctor(self.project, selection)
                self.assertFalse(report["build_ready"])
                self.assertFalse(report["probed"])
        self.assertEqual(before, snapshot(self.root))

    @unittest.skipIf(platform.system() == "Linux", "Candidate platform gate is exercised on native Windows/macOS")
    def test_default_review_gate_does_not_mutate_store(self):
        before = snapshot(self.root)
        result = self.cli("review", "--project", self.root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("unverified", result.stdout.lower())
        self.assertEqual(before, snapshot(self.root))

    def test_portable_imports_do_not_need_unix_only_modules(self):
        script = """
import importlib.abc, sys
class NoUnix(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'fcntl', 'resource'}:
            raise ImportError('Unix-only import during portable module loading')
sys.meta_path.insert(0, NoUnix())
from experimental_modeling import controller, launcher, review_server
print('portable imports ready')
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=child_env(),
                                capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("portable imports ready", result.stdout)

    @unittest.skipUnless(WINDOWS, "Actual Windows reparse-point test")
    def test_windows_junction_rejected_on_python_311_and_newer(self):
        from experimental_modeling.platform_io import safe_path
        # Get the trusted OS cmd path, never PATH-search or run project binaries.
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
        self.assertGreater(length, 0)
        self.assertLess(length, len(buffer))
        cmd = Path(buffer.value) / "cmd.exe"
        target = self.base / "Outside junction target 雨"
        target.mkdir()
        (target / "keep.txt").write_text("unchanged", encoding="utf-8")
        junction = self.root / "junction with spaces"
        result = subprocess.run([str(cmd), "/d", "/c", "mklink", "/J", str(junction), str(target)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        self.addCleanup(os.rmdir, junction)
        self.assertTrue(junction.lstat().st_file_attributes & 0x400)
        for path in (junction, junction / "keep.txt", junction / "new-file"):
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                safe_path(path)
        # Project API must share the same 3.11-compatible rejection, not rely
        # only on Path.is_junction (introduced in Python 3.12).
        from experimental_modeling.project import local_path
        with self.assertRaises(ValueError):
            local_path(junction / "keep.txt")
        with self.assertRaisesRegex(ValueError, "symlink|junction|reparse"):
            read_json(junction / "keep.txt")
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "unchanged")

    @unittest.skipIf(WINDOWS, "Symlink creation on Windows can require additional privileges")
    def test_symlink_components_rejected(self):
        from experimental_modeling.platform_io import safe_path
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("deliberately not JSON", encoding="utf-8")
        link = self.root / "redirect"
        link.symlink_to(outside, target_is_directory=True)
        for path in (link, link / "missing", self.root / ".." / "outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(path)
        with self.assertRaisesRegex(ValueError, "symlink|junction|reparse"):
            read_json(link / "keep.txt")


class PortableLockTests(PortableCase):
    def test_kernel_lock_is_exclusive_and_released_after_crash(self):
        lock = self.root / "portable lock 雪"
        holder = """
from pathlib import Path
import sys, time
from experimental_modeling.platform_io import exclusive_lock
with exclusive_lock(Path(sys.argv[1])):
    print('LOCK_HELD', flush=True)
    time.sleep(60)
"""
        contender = """
from pathlib import Path
import sys
from experimental_modeling.platform_io import exclusive_lock
try:
    with exclusive_lock(Path(sys.argv[1])):
        print('ACQUIRED')
except BlockingIOError:
    print('LOCKED')
    raise SystemExit(7)
"""
        process, output = self.spawn(["-c", holder, lock])
        self.line(process, output, "LOCK_HELD")
        def attempt():
            return subprocess.run([sys.executable, "-c", contender, str(lock)], cwd=ROOT,
                                  env=child_env(), capture_output=True, encoding="utf-8", timeout=10)
        result = attempt()
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "LOCKED")
        self.kill(process)
        result = attempt()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "ACQUIRED")
        # A clean context-manager exit must release the lease too.
        self.assertEqual(attempt().returncode, 0)


class PortableReviewTests(PortableCase):
    def test_loopback_server_startup_never_resolves_dns(self):
        review = ReviewProject(self.store, read_only=True)
        with patch("socket.getfqdn", side_effect=AssertionError("Unexpected forward/FQDN lookup")), \
                patch("socket.gethostbyaddr", side_effect=AssertionError("Unexpected reverse DNS lookup")):
            with LocalReviewServer(review) as server:
                self.assertEqual(server.server_address[0], "127.0.0.1")
                self.assertEqual(server.server_name, "127.0.0.1")
                self.assertGreater(server.server_port, 0)
                self.assertEqual(server.server_port, server.server_address[1])
                self.assertEqual(server.origin, f"http://127.0.0.1:{server.server_port}")

    def test_read_only_constructor_and_mutations_never_write_store(self):
        before = snapshot(self.store)
        review = ReviewProject(self.store, read_only=True)
        data = review.project()
        self.assertTrue(data["read_only"])
        self.assertTrue(data["read_only_reason"])
        self.assertTrue(review.revision("r0")["report"]["machine_verified"])
        with LocalReviewServer(review) as server:
            self.assertEqual(server.server_address[0], "127.0.0.1")
        for operation in (lambda: review.accept("r0", {}), lambda: review.request({})):
            with self.assertRaises(PermissionError):
                operation()
        if WINDOWS:
            self.assertTrue(ReviewProject(self.store, read_only=False).project()["read_only"])
        self.assertEqual(before, snapshot(self.store))

    def test_live_http_boundaries_and_platform_mutation_contract(self):
        before = snapshot(self.store)
        process, origin = self.start_review()
        code, headers, data = request(origin, "/api/project")
        self.assertEqual(code, 200, data)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(data["project_name"], self.project.name)
        self.assertEqual(data["read_only"], WINDOWS)
        self.assertEqual(data["latest_revision"], "r0")
        self.assertTrue(data["revisions"][0]["machine_verified"])
        self.assertEqual(request(origin, "/")[0], 200)
        self.assertEqual(request(origin, "/static/app.js")[0], 200)
        self.assertEqual(request(origin, "/static/style.css")[0], 200)
        code, _, revision = request(origin, "/api/revisions/r0")
        self.assertEqual(code, 200, revision)
        self.assertTrue(revision["report"]["machine_verified"])
        self.assertEqual(request(origin, "/artifacts/r0/view-front")[2], PNG)
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(request(origin, "/api/project", headers=headers)[0], 403)
        self.assertEqual(request(origin, "/artifacts/r0/%2e%2e%2fresult.json")[0], 409)
        payload = {"csrf_token": data["csrf_token"], "expected_result_hash": revision["revision"]["result_hash"],
                   "notes": "Portable review 雪"}
        self.assertEqual(request(origin, "/api/revisions/r0/accept", "POST", payload,
                                 headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(request(origin, "/api/revisions/r0/accept", "POST", payload | {"csrf_token": "bad"})[0], 403)
        edit = {"csrf_token": data["csrf_token"], "revision_id": "r0",
                "expected_result_hash": payload["expected_result_hash"], "prompt": "Add a synthetic fin 雨"}
        expected = 403 if WINDOWS else 200
        code, _, accepted = request(origin, "/api/revisions/r0/accept", "POST", payload)
        self.assertEqual(code, expected, accepted)
        code, _, queued = request(origin, "/api/requests", "POST", edit)
        self.assertEqual(code, expected, queued)
        if WINDOWS:
            self.assertTrue(data["read_only_reason"])
            self.assertEqual(before, snapshot(self.store))
            self.assertEqual(request(origin, "/api/requests")[2], [])
        else:
            self.assertTrue(accepted["human_accepted"])
            self.assertEqual(queued["status"], "queued")
            reopened = ReviewProject(self.store)
            self.assertTrue(reopened.revision("r0")["state"]["human_accepted"])
            self.assertEqual(reopened.requests()[0]["prompt"], edit["prompt"])
            self.assertEqual(reopened.requests()[0]["execution"], "not_started")
        self.stop_review(process)
        process, second_origin = self.start_review()
        reopened = request(second_origin, "/api/revisions/r0")[2]
        self.assertEqual(reopened["state"]["human_accepted"], not WINDOWS)
        self.stop_review(process)
        if WINDOWS:
            self.assertEqual(before, snapshot(self.store))
        else:
            # Review writes only metadata and its kernel-lock file, never evidence.
            after = snapshot(self.store)
            for path, value in before.items():
                self.assertEqual(after[path], value, path)

    @unittest.skipIf(WINDOWS and not WINDOWS_CONSOLE, "Windows runner has no console for CTRL_BREAK_EVENT; forced recovery is tested separately")
    def test_graceful_shutdown_records_stopped_and_releases_session(self):
        process, origin = self.start_review()
        self.assertEqual(request(origin, "/api/project")[0], 200)
        self.stop_review(process)
        process, origin = self.start_review()
        self.assertEqual(request(origin, "/api/project")[0], 200)
        self.stop_review(process)

    def test_repeated_launch_and_force_kill_restart(self):
        process, origin = self.start_review()
        state_path = self.root / ".launcher-review.json"
        running = state_path.read_bytes()
        before = snapshot(self.store)
        duplicate = self.cli("review", "--project", self.root, "--experimental-platform-review")
        self.assertEqual(duplicate.returncode, 2, duplicate.stdout)
        self.assertIn("already running", duplicate.stdout.lower())
        self.assertEqual(state_path.read_bytes(), running)
        self.assertEqual(request(origin, "/api/project")[0], 200)
        self.assertEqual(snapshot(self.store), before)
        self.stop_review(process)
        process, origin = self.start_review()
        self.assertEqual(request(origin, "/api/project")[0], 200)
        self.kill(process)
        self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["status"], "running")
        # Kernel ownership, not the stale PID/status record, decides admission.
        process, origin = self.start_review()
        self.assertEqual(request(origin, "/api/project")[0], 200)
        self.stop_review(process)
        self.assertEqual(snapshot(self.store), before)


if __name__ == "__main__":
    unittest.main()
