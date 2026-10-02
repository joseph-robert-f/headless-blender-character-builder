"""Offline sealing contracts. Only native macOS CI can establish codesign success."""
from contextlib import ExitStack
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def build_module():
    loader = importlib.machinery.SourceFileLoader("macos_sealing_build_test", str(ROOT / "scripts/build-review-preview"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def framework_fixture(bundle):
    framework = bundle / "_internal/Python.framework"
    version = framework / "Versions/3.13"
    (version / "Resources").mkdir(parents=True)
    (version / "Python").write_bytes(b"synthetic unsealed Mach-O")
    (version / "Resources/Info.plist").write_bytes(b"synthetic framework metadata")
    (framework / "Python").symlink_to("Versions/Current/Python")
    (framework / "Resources").symlink_to("Versions/Current/Resources", target_is_directory=True)
    (framework / "Versions/Current").symlink_to("3.13", target_is_directory=True)
    (bundle / "hbcb-review-preview").write_bytes(b"synthetic signed launcher")
    return framework, version


class MacOSFrameworkSealingTests(unittest.TestCase):
    def setUp(self):
        self.build = build_module()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.bundle = self.base / "dist" / self.build.NAME
        self.framework, self.version = framework_fixture(self.bundle)
        self.sign = Mock(side_effect=self.make_seal)
        vendor = ModuleType("PyInstaller.utils.osx")
        vendor.sign_binary = self.sign
        self.vendor_modules = {"PyInstaller": ModuleType("PyInstaller"),
                               "PyInstaller.utils": ModuleType("PyInstaller.utils"),
                               "PyInstaller.utils.osx": vendor}

    def make_seal(self, filename, **kwargs):
        version = Path(filename) / "Versions/3.13"
        (version / "_CodeSignature").mkdir()
        (version / "_CodeSignature/CodeResources").write_bytes(b"synthetic resource seal")
        # A new embedded signature changes the Mach-O bytes before inventory.
        (version / "Python").write_bytes(b"synthetic sealed Mach-O")

    def macos(self, run=None):
        stack = ExitStack()
        stack.enter_context(patch.object(self.build.sys, "platform", "darwin"))
        stack.enter_context(patch.object(self.build.importlib.metadata, "version", return_value="6.22.3"))
        stack.enter_context(patch.dict(sys.modules, self.vendor_modules))
        self.run = run or Mock(return_value=subprocess.CompletedProcess([], 0, "", "valid on disk"))
        stack.enter_context(patch.object(self.build.subprocess, "run", self.run))
        self.processes = []
        def execute(command, **kwargs):
            self.assertEqual(kwargs, {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                                      "text": True, "start_new_session": True})
            process = Mock(pid=12340 + len(self.processes), returncode=None)
            self.processes.append(process)
            def communicate(timeout=None):
                if timeout is None:
                    return "", ""  # Reap after cleanup on error.
                if command[:3] == [sys.executable, "-I", "-c"]:
                    self.assertEqual(command, [sys.executable, "-I", "-c", self.build.MACOS_SEAL_CODE, command[-1]])
                    self.assertEqual(timeout, 60)
                    # Run only the trusted helper invocation against the fake vendor module.
                    with patch.object(sys, "argv", ["-c", command[-1]]):
                        exec(command[3], {})
                    result = subprocess.CompletedProcess(command, 0, "", "synthetic ad-hoc signing")
                else:
                    self.assertEqual(timeout, 30)
                    result = self.run(command, timeout=timeout)
                process.returncode = result.returncode
                return result.stdout, result.stderr
            process.communicate.side_effect = communicate
            return process
        self.commands = stack.enter_context(patch.object(self.build.subprocess, "Popen", side_effect=execute))
        self.kill_group = stack.enter_context(patch.object(self.build.os, "killpg"))
        return stack

    def test_seals_only_framework_then_strictly_checks_framework_binary_and_launcher(self):
        before = self.build.sha256(self.version / "Python")
        with self.macos():
            evidence = self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.sign.assert_called_once_with(str(self.framework), identity=None, entitlements_file=None, deep=False)
        paths = [self.framework, self.version / "Python", self.bundle / self.build.NAME]
        self.assertEqual(self.run.call_count, len(paths))
        self.assertEqual(self.commands.call_count, len(paths) + 1)
        self.assertEqual(self.commands.call_args_list[0].args[0],
                         [sys.executable, "-I", "-c", self.build.MACOS_SEAL_CODE, str(self.framework)])
        for call, path in zip(self.run.call_args_list, paths):
            self.assertEqual(call.args, (["/usr/bin/codesign", "--verify", "--strict", "--verbose=4", str(path)],))
            self.assertEqual(call.kwargs, {"timeout": 30})
        self.kill_group.assert_not_called()
        self.assertNotEqual(before, self.build.sha256(self.version / "Python"))
        self.assertEqual(evidence["identity"], "ad-hoc")
        self.assertFalse(evidence["deep"])
        self.assertIsNone(evidence["entitlements"])
        self.assertIn("No publisher signature or notarization", evidence["scope"])
        self.assertEqual(evidence["resource_seal"]["sha256"], self.build.sha256(self.version / "_CodeSignature/CodeResources"))
        self.assertEqual([row["file"] for row in evidence["strict_verification"]],
                         [path.relative_to(self.bundle).as_posix() for path in paths])
        self.assertNotIn(str(self.base), json.dumps(evidence))

    def test_symlinked_temporary_parent_uses_canonical_command_paths(self):
        # macOS can report /var/folders while the real location is /private/var/folders.
        alias = self.base / "temporary-parent-alias"
        alias.symlink_to(self.base, target_is_directory=True)
        bundle = alias / "dist" / self.build.NAME
        self.assertNotEqual(bundle, bundle.resolve())
        with self.macos():
            evidence = self.build.seal_macos_framework(bundle, "macos-arm64")
        self.sign.assert_called_once_with(str(self.framework), identity=None, entitlements_file=None, deep=False)
        self.assertEqual(self.commands.call_args_list[0].args[0],
                         [sys.executable, "-I", "-c", self.build.MACOS_SEAL_CODE, str(self.framework)])
        paths = [self.framework, self.version / "Python", self.bundle / self.build.NAME]
        self.assertEqual([call.args[0][-1] for call in self.run.call_args_list], [str(path) for path in paths])
        self.assertEqual([row["file"] for row in evidence["strict_verification"]],
                         [path.relative_to(self.bundle).as_posix() for path in paths])
        self.kill_group.assert_not_called()

    def test_other_targets_are_noops_without_macos_tools_or_inputs(self):
        with patch.object(self.build.importlib.metadata, "version") as metadata, patch.object(
                self.build.subprocess, "Popen") as run:
            for target in ("windows-x64", "linux-validation"):
                self.assertIsNone(self.build.seal_macos_framework(self.base / "absent", target))
        metadata.assert_not_called()
        run.assert_not_called()
        self.sign.assert_not_called()

    def test_macos_target_rejects_wrong_host_or_vendor_version(self):
        with patch.object(self.build.sys, "platform", "linux"), self.assertRaisesRegex(ValueError, "on macOS"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        with self.macos(), patch.object(self.build.importlib.metadata, "version", return_value="7.0.0"):
            with self.assertRaisesRegex(ValueError, "reviewed PyInstaller"):
                self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.sign.assert_not_called()
        self.run.assert_not_called()

    def test_existing_package_metadata_stops_sealing(self):
        for name in (self.build.MANIFEST, "provenance.json", "source"):
            with self.subTest(name=name):
                marker = self.bundle / name
                marker.write_bytes(b"already packaged")
                with self.macos(), self.assertRaisesRegex(ValueError, "only new build output"):
                    self.build.seal_macos_framework(self.bundle, "macos-arm64")
                marker.unlink()
        self.sign.assert_not_called()

    def test_missing_binary_stops_before_signing(self):
        (self.version / "Python").unlink()
        with self.macos(), self.assertRaises((ValueError, FileNotFoundError)):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.sign.assert_not_called()
        self.run.assert_not_called()

    def test_redirected_framework_and_binary_cannot_change_external_files(self):
        original = self.build.sha256(self.version / "Python")
        moved = self.base / "source-Python.framework"
        self.framework.rename(moved)
        self.framework.symlink_to(moved, target_is_directory=True)
        with self.macos(), self.assertRaisesRegex(ValueError, "stay in the new build"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.assertEqual(self.build.sha256(moved / "Versions/3.13/Python"), original)
        self.sign.assert_not_called()
        self.framework.unlink()
        moved.rename(self.framework)
        binary = self.version / "Python"
        external = self.base / "source-Python"
        binary.rename(external)
        binary.symlink_to(external)
        with self.macos(), self.assertRaisesRegex(ValueError, "stay in the new build"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.assertEqual(self.build.sha256(external), original)
        self.sign.assert_not_called()

    def test_bundle_and_internal_directory_symlinks_are_rejected(self):
        for path in (self.bundle, self.bundle / "_internal"):
            with self.subTest(path=path):
                destination = self.base / "moved"
                path.rename(destination)
                path.symlink_to(destination, target_is_directory=True)
                with self.macos(), self.assertRaises(ValueError):
                    self.build.seal_macos_framework(self.bundle, "macos-arm64")
                self.sign.assert_not_called()
                path.unlink()
                destination.rename(path)

    def test_hardlinked_signing_inputs_cannot_change_external_files(self):
        for path in (self.version / "Python", self.version / "Resources/Info.plist", self.bundle / self.build.NAME):
            with self.subTest(path=path):
                external = self.base / "external-source"
                os.link(path, external)
                before = self.build.sha256(external)
                with self.macos(), self.assertRaisesRegex(ValueError, "must not have hardlinks"):
                    self.build.seal_macos_framework(self.bundle, "macos-arm64")
                self.sign.assert_not_called()
                self.run.assert_not_called()
                self.assertEqual(self.build.sha256(external), before)
                external.unlink()

    def test_changed_framework_links_and_extra_resources_are_rejected(self):
        link = self.framework / "Python"
        link.unlink()
        link.symlink_to("Versions/3.13/Python")
        with self.macos(), self.assertRaisesRegex(ValueError, "reviewed internal links"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        link.unlink()
        link.symlink_to("Versions/Current/Python")
        (self.version / "Resources/extra").write_bytes(b"unreviewed resource")
        with self.macos(), self.assertRaisesRegex(ValueError, "layout differs"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.sign.assert_not_called()

    def test_unreviewed_framework_is_not_recursively_signed(self):
        (self.bundle / "_internal/Other.framework").mkdir()
        with self.macos(), self.assertRaisesRegex(ValueError, "only the reviewed Python"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.sign.assert_not_called()

    def test_signing_failure_and_missing_resource_seal_stop_verification(self):
        self.sign.side_effect = SystemError("codesign failed")
        with self.macos(), self.assertRaisesRegex(SystemError, "codesign failed"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.run.assert_not_called()
        self.sign.side_effect = None
        with self.macos(), self.assertRaisesRegex(ValueError, "did not produce a resource seal"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.run.assert_not_called()

    def test_signing_subprocess_failure_or_timeout_stops_verification(self):
        for error in (subprocess.CalledProcessError(1, "helper", stderr="signing failure"),
                      subprocess.TimeoutExpired("helper", 60, output=b"partial output")):
            with self.subTest(error=type(error).__name__), self.macos():
                process = Mock(pid=8123, returncode=1)
                process.communicate.side_effect = [error, ("", "")]
                self.commands.side_effect = None
                self.commands.return_value = process
                with self.assertRaises(type(error)) as raised:
                    self.build.seal_macos_framework(self.bundle, "macos-arm64")
                self.assertEqual(self.commands.call_count, 1)
                self.run.assert_not_called()
                self.sign.assert_not_called()
                self.assertTrue(raised.exception.__notes__)
                self.kill_group.assert_called_once_with(process.pid, signal.SIGKILL)
                self.assertEqual(process.communicate.call_args_list[0].kwargs, {"timeout": 60})
                self.assertEqual(process.communicate.call_args_list[1].kwargs, {})
    def test_redirected_or_empty_resource_seal_is_rejected(self):
        def invalid_seal(filename, **kwargs):
            signature = self.version / "_CodeSignature"
            signature.mkdir()
            (signature / "CodeResources").symlink_to(self.version / "Resources/Info.plist")
        self.sign.side_effect = invalid_seal
        with self.macos(), self.assertRaisesRegex(ValueError, "did not produce a resource seal"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.run.assert_not_called()
        (self.version / "_CodeSignature/CodeResources").unlink()
        (self.version / "_CodeSignature").rmdir()
        def empty_seal(filename, **kwargs):
            self.make_seal(filename, **kwargs)
            (self.version / "_CodeSignature/CodeResources").write_bytes(b"")
        self.sign.side_effect = empty_seal
        with self.macos(), self.assertRaisesRegex(ValueError, "did not produce a resource seal"):
            self.build.seal_macos_framework(self.bundle, "macos-arm64")
        self.run.assert_not_called()

    def test_each_strict_check_fails_closed_without_retry(self):
        for failure_index in range(3):
            with self.subTest(failure_index=failure_index):
                run = Mock(side_effect=[subprocess.CompletedProcess([], 0, "", "")] * failure_index +
                           [subprocess.CalledProcessError(1, "codesign", stderr="strict failure")])
                with self.macos(run), self.assertRaises(subprocess.CalledProcessError):
                    self.build.seal_macos_framework(self.bundle, "macos-arm64")
                self.assertEqual(run.call_count, failure_index + 1)
                (self.version / "_CodeSignature/CodeResources").unlink()
                (self.version / "_CodeSignature").rmdir()

    def test_strict_timeout_or_unavailable_tool_stops_build(self):
        for error in (subprocess.TimeoutExpired("codesign", 30), FileNotFoundError("codesign")):
            with self.subTest(error=type(error).__name__):
                with self.macos(Mock(side_effect=error)), self.assertRaises(type(error)):
                    self.build.seal_macos_framework(self.bundle, "macos-arm64")
                self.assertEqual(self.run.call_count, 1)
                (self.version / "_CodeSignature/CodeResources").unlink()
                (self.version / "_CodeSignature").rmdir()

    def test_verification_evidence_is_bounded(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, "x" * 8192, "y" * 8192))
        with self.macos(run):
            evidence = self.build.seal_macos_framework(self.bundle, "macos-arm64")
        for check in evidence["strict_verification"]:
            self.assertEqual(len(check["stdout"]), 4096)
            self.assertEqual(len(check["stderr"]), 4096)
            self.assertTrue(check["stdout_truncated"])
            self.assertTrue(check["stderr_truncated"])

    def test_failed_command_output_is_bounded_in_diagnostics(self):
        process = Mock(pid=8234, returncode=1)
        process.communicate.return_value = ("x" * 8192, "y" * 8192)
        with patch.object(self.build.subprocess, "Popen", return_value=process), patch.object(
                self.build.os, "killpg") as kill_group:
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                self.build.checked_macos_command(["/usr/bin/codesign", "--verify"], timeout=30)
        kill_group.assert_called_once_with(process.pid, signal.SIGKILL)
        self.assertEqual(raised.exception.__notes__, [
            "stdout (last 4096 characters): " + "x" * 4096,
            "stderr (last 4096 characters): " + "y" * 4096])

    def test_cleanup_reaps_an_already_exited_group(self):
        process = Mock(pid=8235, returncode=1)
        process.communicate.return_value = ("", "strict failure")
        with patch.object(self.build.subprocess, "Popen", return_value=process), patch.object(
                self.build.os, "killpg", side_effect=ProcessLookupError):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build.checked_macos_command(["/usr/bin/codesign", "--verify"], timeout=30)
        self.assertEqual(process.communicate.call_count, 2)

    def test_interruption_stops_and_reaps_only_the_owned_group(self):
        process = Mock(pid=8236, returncode=None)
        process.communicate.side_effect = [KeyboardInterrupt, ("", "")]
        with patch.object(self.build.subprocess, "Popen", return_value=process), patch.object(
                self.build.os, "killpg") as kill_group:
            with self.assertRaises(KeyboardInterrupt):
                self.build.checked_macos_command(["/usr/bin/codesign", "--verify"], timeout=30)
        kill_group.assert_called_once_with(process.pid, signal.SIGKILL)
        self.assertEqual(process.communicate.call_count, 2)

    def build_context(self, output, fail_verification=False):
        events = []
        def run(command, **kwargs):
            if command[1:3] == ["-m", "PyInstaller"]:
                events.append("collect")
                bundle = output / "dist" / self.build.NAME
                framework_fixture(bundle)
                decimal = "_decimal.cpython-313-darwin.so"
                (bundle / "_internal" / decimal).write_bytes(b"synthetic decimal module")
                work = output / "work" / self.build.NAME
                work.mkdir(parents=True)
                (work / "Analysis-00.toc").write_text(repr([[
                    ("Python", "official/Python", "BINARY"), (decimal, "official/" + decimal, "EXTENSION")]]))
            elif command[0] == "/usr/bin/codesign":
                events.append("strict")
                if fail_verification:
                    raise subprocess.CalledProcessError(1, command, stderr="strict failure")
            elif command[:2] == ["git", "archive"]:
                events.append("source archive")
                kwargs["stdout"].write(b"synthetic corresponding source archive")
            else:
                self.fail(f"Unexpected command: {command}")
            return subprocess.CompletedProcess(command, 0, "", "valid on disk")
        real_inventory = self.build.native_inventory
        def native_inventory(*args):
            events.append("native hashes")
            self.assertEqual(events, ["collect", "seal", "strict", "strict", "strict", "native hashes"])
            return real_inventory(*args)
        def sign(*args, **kwargs):
            events.append("seal")
            self.make_seal(*args, **kwargs)
        self.sign.side_effect = sign
        stack = self.macos(Mock(side_effect=run))
        stack.enter_context(patch.object(sys, "argv", ["build-review-preview", "--target", "macos-arm64", "--output", str(output)]))
        stack.enter_context(patch.object(self.build.platform, "system", return_value="Darwin"))
        stack.enter_context(patch.object(self.build.platform, "machine", return_value="arm64"))
        stack.enter_context(patch.object(self.build.platform, "python_version", return_value="3.13.16"))
        stack.enter_context(patch.object(self.build.sysconfig, "get_config_var", return_value=0))
        stack.enter_context(patch.object(self.build, "git", side_effect=lambda *args: "" if args[0] == "diff" else "a" * 40))
        stack.enter_context(patch.object(self.build, "dependencies", return_value={"pyinstaller": "6.22.3"}))
        stack.enter_context(patch.object(self.build, "decimal_component", return_value={"component": "synthetic decimal"}))
        stack.enter_context(patch.object(self.build, "collect_notices"))
        stack.enter_context(patch.object(self.build, "native_inventory", side_effect=native_inventory))
        return stack, events

    def test_main_seals_before_hashes_source_manifest_and_archive(self):
        output = self.base / "new-build"
        context, events = self.build_context(output)
        with context:
            self.build.main()
        self.assertEqual(events, ["collect", "seal", "strict", "strict", "strict", "native hashes", "source archive"])
        bundle = output / "dist" / self.build.NAME
        report = json.loads((output / "macos-framework-sealing.json").read_text())
        provenance = json.loads((bundle / "provenance.json").read_text())
        self.assertEqual(provenance["macos_framework_sealing"], report)
        native = {row["file"]: row for row in provenance["native_components"]}
        binary = "_internal/Python.framework/Versions/3.13/Python"
        self.assertEqual(native[binary]["sha256"], self.build.sha256(bundle / binary))
        manifest = json.loads((bundle / self.build.MANIFEST).read_text())
        seal = report["resource_seal"]
        self.assertEqual(manifest["files"][seal["file"]]["sha256"], seal["sha256"])
        self.assertTrue(self.build.verify(bundle)["verified"])
        archives = list(output.glob("*.tar.gz"))
        self.assertEqual(len(archives), 1)
        with tarfile.open(archives[0]) as archive:
            self.assertEqual(archive.extractfile(self.build.NAME + "/" + binary).read(), b"synthetic sealed Mach-O")
            self.assertEqual(archive.extractfile(self.build.NAME + "/" + seal["file"]).read(), b"synthetic resource seal")

    def test_main_strict_failure_stops_before_hashes_metadata_or_archive(self):
        output = self.base / "failed-build"
        context, events = self.build_context(output, fail_verification=True)
        with context, self.assertRaises(subprocess.CalledProcessError):
            self.build.main()
        self.assertEqual(events, ["collect", "seal", "strict"])
        bundle = output / "dist" / self.build.NAME
        for name in ("source", "provenance.json", self.build.MANIFEST):
            self.assertFalse((bundle / name).exists())
        self.assertEqual(list(output.glob("*.tar.gz")), [])
        self.assertFalse((output / "build-result.json").exists())


if __name__ == "__main__":
    unittest.main()
