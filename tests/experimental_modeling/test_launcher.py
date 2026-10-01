"""Launcher contracts. Runtime fixtures never discover or run user executables."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shutil
import signal
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from experimental_modeling import launcher, runtime
from experimental_modeling.project import DESCRIPTOR, FOLDERS, Project, atomic_json, initialize
from experimental_modeling.runtime import RuntimeSelection

IMAGE = "sha256:" + "a" * 64
ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def linux():
    with patch("experimental_modeling.runtime.platform.system", return_value="Linux"), patch("experimental_modeling.runtime.platform.machine", return_value="x86_64"):
        yield


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Projects with spaces 雪"

    def test_portable_layout_roundtrip_and_move(self):
        project = initialize(self.root, "雨 and spaces")
        self.assertEqual(Project.open(self.root), project)
        self.assertEqual(project.folder("assets"), self.root / "source/assets")
        self.assertEqual(project.folder("candidates"), self.root / "evidence/attempts")
        self.assertEqual(project.folder("accepted"), self.root / "evidence/accepted")
        data = json.loads((self.root / DESCRIPTOR).read_text())
        self.assertNotIn(str(self.root), json.dumps(data))
        moved = self.root.with_name("Moved 雨")
        shutil.copytree(self.root, moved)
        self.assertEqual(Project.open(moved).name, project.name)
        Project.open(moved).validate_folders()

    def test_repeated_init_preserves_inputs_and_resumes_missing_folders(self):
        project = initialize(self.root)
        original = (self.root / DESCRIPTOR).read_bytes()
        (project.folder("source") / "builder.py").write_text("retained", encoding="utf-8")
        project.folder("accepted").rmdir()
        initialize(self.root)
        self.assertEqual((self.root / DESCRIPTOR).read_bytes(), original)
        self.assertEqual((project.folder("source") / "builder.py").read_text(), "retained")
        project.validate_folders()
        with self.assertRaisesRegex(ValueError, "different name"):
            initialize(self.root, "Different")

    def test_nonempty_destination_is_never_adopted(self):
        self.root.mkdir()
        (self.root / "keep").write_text("safe")
        with self.assertRaisesRegex(ValueError, "never adopts"):
            initialize(self.root)
        self.assertEqual((self.root / "keep").read_text(), "safe")

    def test_descriptor_strict_schema_credentials_versions_and_paths(self):
        initialize(self.root)
        path = self.root / DESCRIPTOR
        original = json.loads(path.read_text())
        for delta in ({"schema_version": True}, {"schema_version": 2}, {"token": "secret"},
                      {"runtime_policy": "blender-latest"}, {"folders": FOLDERS | {"source": "../escape"}},
                      {"name": "bad\nname"}, {"name": " "}, {"name": 1}):
            with self.subTest(delta=delta):
                path.write_text(json.dumps(original | delta))
                with self.assertRaises(ValueError):
                    Project.open(self.root)
        path.write_text('{"schema_version": 1, "schema_version": 1}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            Project.open(self.root)
        path.write_text("x" * 16385)
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            Project.open(self.root)

    def test_symlinks_and_redirected_folders_refused(self):
        project = initialize(self.root)
        project.folder("constraints").rmdir()
        (self.root / "constraints").symlink_to(self.root / "source", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            Project.open(self.root)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            initialize(self.root)

    def test_competing_init_never_replaces_winner(self):
        barrier = threading.Barrier(2)
        original = atomic_json
        def competing(path, value, **kwargs):
            barrier.wait(timeout=5)
            return original(path, value, **kwargs)
        def create(name):
            try:
                return initialize(self.root, name).name
            except ValueError as exc:
                return exc
        with patch("experimental_modeling.project.atomic_json", side_effect=competing), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, name) for name in ("one", "two")]
            results = [future.result(timeout=10) for future in futures]
        winner = Project.open(self.root).name
        self.assertEqual(sum(result == winner for result in results), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)

    def test_metadata_atomic_failure_keeps_previous(self):
        initialize(self.root)
        path = self.root / DESCRIPTOR
        previous = path.read_bytes()
        with patch("experimental_modeling.project.os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                atomic_json(path, {"changed": True})
        self.assertEqual(path.read_bytes(), previous)
        self.assertFalse(list(self.root.glob(".launcher-*.tmp")))


class RuntimeFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = initialize(self.root / "Project 雪")
        self.project.input("params.json").write_text("{}")
        self.project.input("policy.json").write_text(json.dumps({"schema_version": 1, "parts": ["body"], "changed_parts": [], "constraints": [], "profile": "scene"}))
        (self.project.folder("source") / "builder.py").write_text("pass")
        # This file must NEVER execute; probes are injected/mocked.
        self.binary = self.root / "trusted runtime 雪"
        self.binary.write_text("NEVER EXECUTE THIS TEST FIXTURE")
        self.binary.chmod(0o700)
        self.native = RuntimeSelection(mode="trusted-native", blender=self.binary)


class RuntimeTests(RuntimeFixture, unittest.TestCase):
    def test_doctor_default_spawns_nothing_and_leaves_files_unchanged(self):
        before = {str(p): p.read_bytes() for p in self.project.root.rglob("*") if p.is_file()}
        with linux(), patch("subprocess.Popen", side_effect=AssertionError("spawn")), patch("shutil.which", side_effect=AssertionError("discovery")):
            report = runtime.doctor(self.project, self.native)
        after = {str(p): p.read_bytes() for p in self.project.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(report["review_ready"])
        self.assertFalse(report["build_ready"])
        self.assertFalse(report["authoring_ready"])

    def test_windows_and_mac_report_unsupported_without_probe(self):
        for system, machine in (("Windows", "AMD64"), ("Darwin", "arm64"), ("Linux", "aarch64")):
            with self.subTest(system=system), patch("experimental_modeling.runtime.platform.system", return_value=system), patch("experimental_modeling.runtime.platform.machine", return_value=machine), patch("subprocess.Popen", side_effect=AssertionError("spawn")):
                report = runtime.doctor(self.project, self.native, probe=True)
                self.assertFalse(report["review_ready"])
                self.assertFalse(report["build_ready"])
                self.assertEqual(report["checks"][0]["status"], "unsupported")

    def test_runtime_policy_matches_repository_pin(self):
        dockerfile = (ROOT / "docker/builder.Dockerfile").read_text()
        checksum = (ROOT / "docker/blender-download.sha256").read_text()
        self.assertIn('org.blender.version="' + runtime.BLENDER_VERSION + ' LTS"', dockerfile)
        self.assertIn(runtime.BLENDER_ARCHIVE_SHA256, dockerfile)
        self.assertTrue(checksum.startswith(runtime.BLENDER_ARCHIVE_SHA256 + " "))
        self.assertEqual(runtime.RUNTIME_POLICY, "blender-" + runtime.BLENDER_VERSION + "-linux-" + runtime.IMAGE_ARCHITECTURE + "-v1")

    def test_pin_is_exact_and_not_upgraded(self):
        for version, ready in (("4.5.12", True), ("4.3.2", False), ("4.5.13", False), ("5.0.0", False)):
            with self.subTest(version=version), linux(), patch("experimental_modeling.runtime._native_version", return_value=version) as probe:
                report = runtime.doctor(self.project, self.native, probe=True)
                self.assertEqual(report["build_ready"], ready)
                probe.assert_called_once_with(self.binary)

    def test_invalid_input_contract_is_not_build_ready(self):
        self.project.input("policy.json").write_text("{}")
        with linux(), patch("experimental_modeling.runtime._native_version", return_value="4.5.12"):
            report = runtime.doctor(self.project, self.native, probe=True)
        self.assertFalse(report["build_ready"])
        self.assertEqual(next(c for c in report["checks"] if c["id"] == "build_inputs")["status"], "missing")

    def test_missing_relative_and_project_executables_refused(self):
        for path in (None, Path("blender"), self.root / "missing", self.project.folder("source") / "builder.py"):
            with self.subTest(path=path), linux(), patch("subprocess.Popen", side_effect=AssertionError("spawn")):
                report = runtime.doctor(self.project, RuntimeSelection(mode="trusted-native", blender=path), probe=True)
                self.assertFalse(report["build_ready"])
                self.assertEqual(next(c for c in report["checks"] if c["id"] == "runtime")["status"], "blocked")

    def test_symlink_parent_traversal_cannot_change_probed_runtime(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "link").symlink_to(self.project.folder("source"), target_is_directory=True)
        probe = outside / "runtime"
        probe.write_text("never execute")
        probe.chmod(0o700)
        dispatch = self.project.root / "runtime"
        dispatch.write_text("never execute")
        dispatch.chmod(0o700)
        selected = outside / "link" / ".." / "runtime"
        with linux(), patch("subprocess.Popen", side_effect=AssertionError("spawn")):
            report = runtime.doctor(self.project, RuntimeSelection(mode="trusted-native", blender=selected), probe=True)
        self.assertFalse(report["build_ready"])
        with self.assertRaisesRegex(ValueError, "traversal"):
            runtime.canonical_selection(RuntimeSelection(mode="trusted-native", blender=selected), self.project)
        with self.assertRaisesRegex(ValueError, "traversal"):
            runtime.canonical_selection(RuntimeSelection(docker=selected, image=IMAGE), self.project)

    def test_selection_cannot_mix_modes_or_use_tags(self):
        for kwargs in ({"mode": "auto"}, {"image": "latest"}, {"mode": "trusted-native", "image": IMAGE}, {"blender": self.binary}):
            with self.assertRaises(ValueError):
                RuntimeSelection(**kwargs)

    def test_docker_preflight_pins_architecture_version_and_archive(self):
        selection = RuntimeSelection(docker=self.binary, socket=self.root / "docker.sock", image=IMAGE)
        good = {"image_architecture": "amd64", "blender_version": "4.5.12 LTS", "blender_archive_sha256": runtime.BLENDER_ARCHIVE_SHA256}
        for delta, ready in (({}, True), ({"image_architecture": "arm64"}, False), ({"blender_version": "4.5.13 LTS"}, False), ({"blender_archive_sha256": "bad"}, False)):
            backend = Mock()
            backend.verify_runtime.return_value = good | delta
            with linux(), patch("experimental_modeling.runtime._sandbox", return_value=backend), patch("experimental_modeling.runtime._native_version", side_effect=AssertionError("native fallback")):
                self.assertEqual(runtime.doctor(self.project, selection, probe=True)["build_ready"], ready)
        backend.verify_runtime.side_effect = RuntimeError("Docker unavailable")
        with linux(), patch("experimental_modeling.runtime._sandbox", return_value=backend), patch("experimental_modeling.runtime._native_version", side_effect=AssertionError("native fallback")):
            self.assertFalse(runtime.doctor(self.project, selection, probe=True)["build_ready"])

    def test_explicit_docker_does_not_search_path(self):
        from experimental_modeling.sandbox import DockerSandbox
        with patch("shutil.which", side_effect=AssertionError("discovery")):
            backend = DockerSandbox(IMAGE, docker_executable=self.binary)
        self.assertEqual(backend.docker, str(self.binary))
        with patch("shutil.which", side_effect=AssertionError("discovery")), self.assertRaises(ValueError):
            DockerSandbox(IMAGE, docker_executable=Path("docker"))

    def test_native_probe_is_bounded_and_uses_selected_binary(self):
        actual_popen = subprocess.Popen
        for program, expected in (("print('Blender 4.5.12')", "4.5.12"),
                                  ("print('wrong tool')", ValueError),
                                  ("print('x' * 20000)", RuntimeError),
                                  ("raise SystemExit(1)", RuntimeError)):
            calls = []
            def spawn(command, **kwargs):
                calls.append(command)
                return actual_popen([sys.executable, "-c", program], **kwargs)
            with self.subTest(program=program), patch("experimental_modeling.runtime.subprocess.Popen", side_effect=spawn):
                if isinstance(expected, str):
                    self.assertEqual(runtime._native_version(self.binary), expected)
                else:
                    with self.assertRaises(expected):
                        runtime._native_version(self.binary)
            self.assertEqual(calls, [[str(self.binary), "--version"]])

    def test_stale_build_is_visible_to_doctor(self):
        atomic_json(self.project.root / ".launcher-build.json", {"schema_version": 1, "status": "running", "revision": "r0"})
        with linux(), patch("experimental_modeling.runtime._native_version", return_value="4.5.12"):
            report = runtime.doctor(self.project, self.native, probe=True)
        self.assertTrue(report["recovery_required"])
        self.assertTrue(report["build_prerequisites_ready"])
        self.assertFalse(report["build_ready"])


class IntegrationTests(RuntimeFixture, unittest.TestCase):
    def ready(self):
        return patch("experimental_modeling.runtime._native_version", return_value="4.5.12")

    def test_build_forwards_project_and_explicit_runtime_to_same_controller(self):
        result = {"status": "accepted", "revision": "r0", "failures": []}
        with linux(), self.ready(), patch("experimental_modeling.controller.build", return_value=result) as build:
            self.assertEqual(launcher.build_project(self.project, self.native, revision="r0"), result)
        values = build.call_args.kwargs
        self.assertEqual(values["source"], self.project.folder("source"))
        self.assertEqual(values["store"], self.project.folder("evidence"))
        self.assertTrue(values["trusted_reviewed_source"])
        self.assertEqual(values["blender"], str(self.binary))
        self.assertIsNone(values["requirements_path"])
        self.assertEqual(json.loads((self.project.root / ".launcher-build.json").read_text())["status"], "finished")

    def test_interrupted_build_needs_explicit_recovery_and_keeps_evidence(self):
        with linux(), self.ready(), patch("experimental_modeling.controller.build", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                launcher.build_project(self.project, self.native, revision="r0")
        with linux(), self.ready(), patch("experimental_modeling.controller.build", side_effect=AssertionError("executed")):
            with self.assertRaisesRegex(RuntimeError, "Interrupted build"):
                launcher.build_project(self.project, self.native, revision="r1")
        result = {"status": "rejected", "revision": "r1", "failures": []}
        with linux(), self.ready(), patch("experimental_modeling.controller.build", return_value=result):
            launcher.build_project(self.project, self.native, revision="r1", acknowledge_interrupted=True)
        self.assertEqual(json.loads((self.project.root / ".launcher-build.json").read_text())["result_status"], "rejected")

    def test_controller_retained_cleanup_error_requires_recovery(self):
        from experimental_modeling.sandbox import SandboxError
        self.project.input("policy.json").write_text(json.dumps({"schema_version": 1, "parts": ["body"], "changed_parts": [], "constraints": [], "profile": "scene"}))
        backend = Mock()
        backend.blender = "/opt/blender/blender"
        backend.security_boundary = "EXPERIMENTAL_DOCKER"
        backend.run.side_effect = SandboxError("sandbox cleanup failed: daemon unavailable")
        selection = RuntimeSelection(docker=self.binary, socket=self.root / "docker.sock", image=IMAGE)
        with patch("experimental_modeling.launcher.doctor", return_value={"build_prerequisites_ready": True}), patch("experimental_modeling.sandbox.DockerSandbox", return_value=backend):
            result = launcher.build_project(self.project, selection, revision="r0")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("cleanup failed", result["error"])
        self.assertEqual(json.loads((self.project.root / ".launcher-build.json").read_text())["status"], "recovery_required")
        self.assertTrue((self.project.folder("candidates") / "r0/result.json").is_file())
        with linux(), self.ready():
            self.assertTrue(runtime.doctor(self.project, self.native, probe=True)["recovery_required"])
        with linux(), self.ready(), patch("experimental_modeling.controller.build", side_effect=AssertionError("executed")):
            with self.assertRaisesRegex(RuntimeError, "Interrupted build"):
                launcher.build_project(self.project, self.native, revision="r1")

    def test_existing_revision_is_never_overwritten(self):
        directory = self.project.folder("candidates") / "r0"
        directory.mkdir()
        (directory / "keep").write_text("crash evidence")
        with linux(), self.ready(), patch("experimental_modeling.controller.build", side_effect=AssertionError("executed")):
            with self.assertRaisesRegex(ValueError, "already exists"):
                launcher.build_project(self.project, self.native, revision="r0", acknowledge_interrupted=True)
        self.assertEqual((directory / "keep").read_text(), "crash evidence")

    def test_lease_is_separate_from_store_lock_and_kernel_released(self):
        from experimental_modeling.controller import store_lock
        with launcher.operation_lock(self.project, "review"):
            with store_lock(self.project.folder("evidence")):
                pass
            with self.assertRaisesRegex(RuntimeError, "already running"):
                with launcher.operation_lock(self.project, "review"):
                    pass
        with launcher.operation_lock(self.project, "review"):
            pass

    def test_bad_review_metadata_fails_before_opening_listener(self):
        (self.project.root / ".launcher-review.json").symlink_to(self.project.input("params.json"))
        with linux(), patch("experimental_modeling.review_server.LocalReviewServer", side_effect=AssertionError("listener opened")):
            with self.assertRaisesRegex(ValueError, "symlinks"):
                launcher.review_project(self.project)

    def test_review_uses_project_name_and_closes_after_interruption(self):
        server = Mock()
        server.origin = "http://127.0.0.1:1234"
        server.serve_forever.side_effect = KeyboardInterrupt
        with linux(), patch("experimental_modeling.review_server.LocalReviewServer", return_value=server) as factory, patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(KeyboardInterrupt):
                launcher.review_project(self.project)
        self.assertEqual(factory.call_args.args[0].project()["project_name"], self.project.name)
        self.assertFalse(server.daemon_threads)
        server.server_close.assert_called_once()
        self.assertEqual(json.loads((self.project.root / ".launcher-review.json").read_text())["status"], "stopped")
        with launcher.operation_lock(self.project, "review"):
            pass

    def test_cli_json_is_safe_for_legacy_stdout_encodings(self):
        class ASCIIStream(io.StringIO):
            def write(self, value):
                value.encode("ascii")
                return super().write(value)
        with patch("sys.stdout", new_callable=ASCIIStream) as stream:
            code = launcher.main(["init", "--project", str(self.root / "CLI 雨"), "--name", "雪"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue())["name"], "雪")

    def test_cli_init_and_doctor_import_without_unix_modules(self):
        # Known interpreter only. No Blender/Docker discovery or fixture execution.
        program = '''import builtins, sys, subprocess
real = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ('fcntl', 'resource'):
        raise AssertionError('Unix backend imported')
    return real(name, *args, **kwargs)
builtins.__import__ = guarded
from experimental_modeling.launcher import main
assert main(['init', '--project', sys.argv[1]]) == 0
assert main(['doctor', '--project', sys.argv[1]]) == 1
'''
        result = subprocess.run([sys.executable, "-c", program, str(self.root / "portable new 雪")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_review_real_repeated_start_sigterm_and_crash_recovery(self):
        processes = []
        command = [sys.executable, "-m", "experimental_modeling.launcher", "review", "--project", str(self.project.root)]
        def start():
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            processes.append(process)
            ready, _, _ = select.select([process.stdout], [], [], 10)
            self.assertTrue(ready, "Review server did not report startup")
            self.assertIn("Local project review: http://127.0.0.1:", process.stdout.readline())
            return process
        try:
            first = start()
            repeated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("already running", repeated.stdout)
            first.terminate()
            first.communicate(timeout=15)
            self.assertEqual(first.returncode, 130)
            self.assertEqual(json.loads((self.project.root / ".launcher-review.json").read_text())["status"], "stopped")
            crashed = start()
            crashed.kill()
            crashed.communicate(timeout=15)
            self.assertEqual(json.loads((self.project.root / ".launcher-review.json").read_text())["status"], "running")
            recovered = start()  # OS lease is authority, never stale process/URL metadata.
            recovered.terminate()
            recovered.communicate(timeout=15)
            self.assertEqual(recovered.returncode, 130)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=15)

    def test_signal_handler_restored_after_shutdown(self):
        previous = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(KeyboardInterrupt):
            with launcher.interruptible():
                os.kill(os.getpid(), signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)


if __name__ == "__main__":
    unittest.main()
