"""Offline launcher gates; real Windows behavior requires the native harness."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def load_file(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def launcher_helper():
    return load_file("windows_launcher_offline_test", ROOT / "packaging/windows_preview_launcher.py")


def harness_module():
    return load_file("windows_launcher_harness_test", ROOT / "scripts/test-windows-preview-launcher")


class NativeSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "packaging/windows_preview_launcher.c").read_text(encoding="utf-8")

    def test_preflight_uses_real_system_directory_actual_load_and_loaded_path_check(self):
        for required in ("GetSystemDirectoryW(", "LoadLibraryExW(system_path, NULL, LOAD_LIBRARY_SEARCH_SYSTEM32)",
                         "GetModuleFileNameW(runtime,", "CompareStringOrdinal(", "FreeLibrary(runtime)",
                         'L"VCRUNTIME140.dll"', 'L"VCRUNTIME140_1.dll"'):
            self.assertIn(required, self.source)
        for forbidden in ("GetEnvironmentVariable", "SearchPathW(", "LoadLibraryW(", "SetDllDirectory",
                          "GetFileVersionInfo", "RegOpenKey"):
            self.assertNotIn(forbidden, self.source)
        entry = self.source.split("void WINAPI launcher_entry(void)", 1)[1]
        self.assertLess(entry.index("check_runtime();"), entry.index("CreateProcessW("))

    def test_diagnostics_are_actionable_terminal_output_without_automatic_install(self):
        self.assertIn("STD_ERROR_HANDLE", self.source)
        self.assertIn("WriteFile(", self.source)
        self.assertIn("EXIT_PREREQUISITE 78u", self.source)
        self.assertIn("Microsoft Visual C++ x64 runtime", self.source)
        self.assertIn("https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist", self.source)
        for forbidden in ("ShellExecute", "URLDownload", "WinHttp", "WinInet", "MessageBox", "system("):
            self.assertNotIn(forbidden, self.source)

    def test_exact_tail_absolute_child_and_atomic_job_inheritance(self):
        for required in ("GetCommandLineW()", "GetModuleFileNameW(NULL", 'L"hbcb-review-preview-runtime.exe"',
                         "append(command_line, &command_length, tail)", "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
                         "PROC_THREAD_ATTRIBUTE_JOB_LIST", "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
                         "EXTENDED_STARTUPINFO_PRESENT", "CREATE_SUSPENDED", "ResumeThread(child.hThread)",
                         "GetExitCodeProcess(child.hProcess, &status)", "ExitProcess(status)"):
            self.assertIn(required, self.source)
        self.assertNotIn("CommandLineToArgvW", self.source)
        self.assertNotIn("CREATE_BREAKAWAY_FROM_JOB", self.source)
        self.assertNotIn("SetConsoleCtrlHandler(NULL", self.source)

    def test_range_failure_uses_noreturn_hardware_intrinsic_without_crt(self):
        header = (ROOT / "packaging/windows_load_config.h").read_text(encoding="utf-8")
        self.assertIn("__declspec(noreturn) void __cdecl __report_rangecheckfailure(void)", header)
        self.assertIn("__fastfail(FAST_FAIL_RANGE_CHECK_FAILURE);", header)
        self.assertNotIn("ExitProcess(", header)
        self.assertNotIn("return;", header)
        harness = (ROOT / "scripts/test-windows-preview-launcher").read_text(encoding="utf-8")
        self.assertIn("process.returncode == 0xC0000409", harness)

    def test_public_source_has_only_windows_header_and_no_crt_entrypoint(self):
        includes = [line.strip() for line in self.source.splitlines() if line.lstrip().startswith("#include")]
        self.assertEqual(includes, ["#include <windows.h>"])
        self.assertIn("void WINAPI launcher_entry(void)", self.source)
        for forbidden in ("int main(", "int wmain(", "printf(", "malloc(", "fopen(", "getenv("):
            self.assertNotIn(forbidden, self.source)
        self.assertIn("FILE_ATTRIBUTE_REPARSE_POINT", self.source)
        self.assertIn("GetDriveTypeW(", self.source)


class HarnessContractTests(unittest.TestCase):
    def setUp(self):
        self.harness = harness_module()

    @staticmethod
    def argv_bytes(values):
        encoded = [value.encode("utf-16-le") for value in values]
        return struct.pack("<I", len(values)) + b"".join(struct.pack("<I", len(value) // 2) + value for value in encoded)

    def test_fixture_protocol_keeps_empty_unicode_quotes_and_backslashes(self):
        values = ["C:\\Preview 雪\\runtime.exe", "", 'x"y', "\\\\", "café 🚀", "line\nbreak"]
        self.assertEqual(self.harness.read_argv(self.argv_bytes(values)), values)

    def test_fixture_protocol_rejects_truncation_extra_bytes_and_oversize(self):
        good = self.argv_bytes(["hello"])
        for data in (b"", b"abc", good[:-1], good + b"x", struct.pack("<I", 32769),
                     struct.pack("<II", 1, 32768), b"a" * (128 * 1024 + 1)):
            with self.subTest(data=data[:20]), self.assertRaises(AssertionError):
                self.harness.read_argv(data)

    def test_non_windows_run_saves_explicit_failure_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "results.json"
            with patch.object(self.harness.sys, "platform", "linux"), patch.object(
                    self.harness.subprocess, "run") as run, redirect_stderr(io.StringIO()):
                code = self.harness.main(["--launcher", "unused.exe", "--output", str(output)])
            self.assertEqual(code, 1)
            run.assert_not_called()
            result = json.loads(output.read_text())
            self.assertFalse(result["successful"])
            self.assertEqual(result["checks"], [])
            self.assertIn("requires native Windows x64", result["error"])

    def test_missing_runtime_mode_needs_no_compiler_and_poison_does_not_modify_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            launcher = base / "public.exe"
            launcher.write_bytes(b"synthetic launcher")
            output = base / "results.json"
            diagnostic = (b"Cannot load VCRUNTIME140.dll and VCRUNTIME140_1.dll from Windows System32\n"
                          b"Microsoft Visual C++ x64 runtime required: https://learn.microsoft.com/\n")

            def execute(command, **kwargs):
                self.assertEqual(command[1:], ["--verify"])
                self.assertNotEqual(Path(command[0]), launcher)
                self.assertFalse((Path(command[0]).parent / self.harness.PAYLOAD_NAME).exists())
                self.assertTrue((Path(kwargs["env"]["SystemRoot"]) / "System32/VCRUNTIME140.dll").is_file())
                self.assertTrue((Path(kwargs["env"]["PATH"]) / "VCRUNTIME140_1.dll").is_file())
                self.assertTrue((kwargs["cwd"] / "VCRUNTIME140.dll").is_file())
                return subprocess.CompletedProcess(command, 78, b"", diagnostic)

            with patch.object(self.harness.sys, "platform", "win32"), patch.object(
                    self.harness.platform, "machine", return_value="AMD64"), patch.object(
                    self.harness, "load_helper") as helper, patch.object(
                    self.harness.subprocess, "run", side_effect=execute), redirect_stdout(io.StringIO()):
                code = self.harness.main(["--launcher", str(launcher), "--output", str(output), "--expect-missing-runtime"])
            self.assertEqual(code, 0)
            helper.assert_not_called()
            self.assertEqual(launcher.read_bytes(), b"synthetic launcher")
            result = json.loads(output.read_text())
            self.assertTrue(result["successful"])
            self.assertEqual(result["mode"], "missing-runtime")
            self.assertEqual(len(result["checks"]), 1)

    def test_missing_runtime_mode_rejects_ordinary_loader_failure_as_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            launcher = base / "public.exe"
            launcher.write_bytes(b"synthetic launcher")
            for code, stderr in ((0xC0000135, b""), (78, b"generic error"), (0, b"Microsoft Visual C++ x64 https://example.com")):
                output = base / "results.json"
                with self.subTest(code=code), patch.object(self.harness.sys, "platform", "win32"), patch.object(
                        self.harness.platform, "machine", return_value="AMD64"), patch.object(
                        self.harness.subprocess, "run", return_value=subprocess.CompletedProcess([], code, b"", stderr)), \
                        redirect_stderr(io.StringIO()):
                    status = self.harness.main(["--launcher", str(launcher), "--output", str(output), "--expect-missing-runtime"])
                self.assertEqual(status, 1)
                self.assertFalse(json.loads(output.read_text())["successful"])


class MockPE(SimpleNamespace):
    def parse_data_directories(self, *args, **kwargs):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def pe_fixture(*, machine=0x8664, subsystem=3, protections=0x160, imports=None, delay=None, magic=0x20B, load_flags=0x800):
    def imported(name, symbols):
        return SimpleNamespace(dll=name.encode("ascii"),
                               imports=[SimpleNamespace(name=symbol.encode("ascii") if symbol else None,
                                                        ordinal=1 if symbol is None else None) for symbol in symbols])
    return MockPE(FILE_HEADER=SimpleNamespace(Machine=machine, Characteristics=0x22),
                  OPTIONAL_HEADER=SimpleNamespace(Magic=magic, Subsystem=subsystem, DllCharacteristics=protections,
                                                   AddressOfEntryPoint=0x1000,
                                                   DATA_DIRECTORY=[SimpleNamespace(VirtualAddress=0, Size=0) for _ in range(16)]),
                  DIRECTORY_ENTRY_LOAD_CONFIG=SimpleNamespace(struct=SimpleNamespace(DependentLoadFlags=load_flags)),
                  DIRECTORY_ENTRY_IMPORT=[imported(name, symbols) for name, symbols in (imports if imports is not None else
                                                                                     [("KERNEL32.dll", ["ExitProcess", "LoadLibraryExW"])])],
                  DIRECTORY_ENTRY_DELAY_IMPORT=[] if delay is None else [imported(name, symbols) for name, symbols in delay])


class LauncherPEGateTests(unittest.TestCase):
    def setUp(self):
        self.helper = launcher_helper()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.executable = Path(temporary.name) / "launcher.exe"
        self.executable.write_bytes(b"synthetic PE input: pefile parsing mocked")

    def inspect(self, pe):
        vendor = ModuleType("pefile")
        vendor.PE = Mock(return_value=pe)
        vendor.DIRECTORY_ENTRY = {"IMAGE_DIRECTORY_ENTRY_IMPORT": 1, "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT": 13}
        with patch.dict(sys.modules, {"pefile": vendor}):
            return self.helper.inspect_launcher(self.executable)

    def test_accepts_only_x64_console_pe_with_required_protections_and_os_imports(self):
        row = self.inspect(pe_fixture())
        self.assertEqual(row["machine"], 0x8664)
        self.assertEqual(row["subsystem"], 3)
        self.assertEqual(row["dll_characteristics"] & 0x160, 0x160)
        self.assertEqual(row["imports"], [{"dll": "kernel32.dll", "symbols": ["ExitProcess", "LoadLibraryExW"]}])
        self.assertEqual(row["delay_imports"], [])
        self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")

    def test_rejects_wrong_machine_subsystem_or_optional_header(self):
        for values in ({"machine": 0x14C}, {"machine": 0xAA64}, {"subsystem": 2}, {"magic": 0x10B}):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "launcher"):
                self.inspect(pe_fixture(**values))

    def test_rejects_each_missing_memory_protection(self):
        for flag in (0x20, 0x40, 0x100):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "launcher"):
                self.inspect(pe_fixture(protections=0x160 & ~flag))

    def test_requires_system32_static_load_configuration(self):
        for flags in (None, 0, 0x1000):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, "launcher"):
                self.inspect(pe_fixture(load_flags=flags))
        self.assertEqual(self.inspect(pe_fixture())["dependent_load_flags"], 0x800)

    def test_rejects_crt_python_api_set_and_other_unreviewed_imports(self):
        for name in ("VCRUNTIME140.dll", "ucrtbase.dll", "msvcrt.dll", "python313.dll",
                     "api-ms-win-crt-runtime-l1-1-0.dll", "shell32.dll"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "launcher"):
                self.inspect(pe_fixture(imports=[("kernel32.dll", ["ExitProcess"]), (name, ["unexpected"])]))

    def test_rejects_empty_and_ordinal_imports_and_any_delayed_dependencies(self):
        for pe in (pe_fixture(imports=[]), pe_fixture(imports=[("kernel32.dll", [None])]),
                   pe_fixture(delay=[("kernel32.dll", ["ExitProcess"])]),
                   pe_fixture(delay=[("VCRUNTIME140.dll", ["memcpy"])])):
            with self.subTest(pe=pe), self.assertRaisesRegex(ValueError, "launcher"):
                self.inspect(pe)


class WindowsNativeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.helper = launcher_helper()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bundle = Path(temporary.name)
        for name in (self.helper.PUBLIC_NAME, self.helper.PAYLOAD_NAME, "_wmi.pyd"):
            (self.bundle / name).write_bytes(b"synthetic native input")

    def inventory(self, imports):
        def inspect(path):
            names = imports if path.name == "_wmi.pyd" else ["kernel32.dll"]
            return {"machine": 0x8664, "imports": [{"dll": name, "symbols": []} for name in names],
                    "delay_imports": []}
        with patch.object(self.helper, "pe_information", side_effect=inspect), patch.object(
                self.helper, "inspect_launcher"):
            return self.helper.native_pe_inventory(self.bundle)

    def test_cpython_wmi_can_use_os_property_system_without_bundling_it(self):
        rows = self.inventory(["propsys.dll", "ole32.dll", "kernel32.dll"])
        self.assertEqual(len(rows), 3)
        self.assertFalse((self.bundle / "propsys.dll").exists())

    def test_all_unreviewed_imports_are_reported_without_weakening_gate(self):
        with self.assertRaises(ValueError) as caught:
            self.inventory(["unknown-one.dll", "propsys.dll", "unknown-two.dll"])
        self.assertIn("unknown-one.dll", str(caught.exception))
        self.assertIn("unknown-two.dll", str(caught.exception))
        self.assertNotIn("propsys.dll", str(caught.exception))


class LauncherBuildInputTests(unittest.TestCase):
    def setUp(self):
        self.helper = launcher_helper()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "source.c"
        self.source.write_text("void launcher_entry(void) {}", encoding="utf-8")
        self.work = self.base / "work"
        self.work.mkdir()
        self.output = self.base / "output.exe"
        self.compiler = self.base / "MSVC/bin/Hostx64/x64/cl.exe"
        self.compiler.parent.mkdir(parents=True)
        self.compiler.write_bytes(b"compiler fixture")
        self.linker = self.compiler.with_name("link.exe")
        self.linker.write_bytes(b"linker fixture")
        self.sdk = self.base / "Windows SDK"
        self.lib = self.sdk / "Lib/10.test/um/x64/kernel32.lib"
        self.lib.parent.mkdir(parents=True)
        self.lib.write_bytes(b"OS import library fixture")
        self.env = {"PATH": str(self.compiler.parent), "WindowsSdkDir": str(self.sdk),
                    "WindowsSDKVersion": "10.test\\"}

    def simulate_compile(self, command, **kwargs):
        self.assertEqual(kwargs["env"], self.env)
        for item in command:
            for prefix, content in (("/Fo", b"fresh source object"), ("/OUT:", b"native PE output"),
                                    ("/MAP:", b"link map fixture\n")):
                if item.startswith(prefix):
                    Path(item[len(prefix):]).write_bytes(content)
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_product_build_uses_one_fresh_object_explicit_os_lib_and_no_crt_defaults(self):
        with patch.object(self.helper, "toolchain_environment", return_value=(self.env, {})), patch.object(
                self.helper.shutil, "which", return_value=str(self.compiler)), patch.object(
                self.helper, "tool_record", return_value={"version": "fixture", "sha256": "a" * 64}), patch.object(
                self.helper.subprocess, "run", side_effect=self.simulate_compile) as run:
            evidence = self.helper.compile_native(self.source, self.output, self.work)
        self.assertEqual(run.call_count, 2)
        compile_command, link_command = [call.args[0] for call in run.call_args_list]
        self.assertEqual(compile_command[0], str(self.compiler))
        for option in ("/TC", "/c", "/GS", "/Zl", "/WX"):
            self.assertIn(option, compile_command)
        self.assertEqual(link_command[0], str(self.linker))
        for option in ("/NODEFAULTLIB", "/ENTRY:launcher_entry", "/MACHINE:X64", "/SUBSYSTEM:CONSOLE",
                       "/DYNAMICBASE", "/NXCOMPAT", "/HIGHENTROPYVA"):
            self.assertIn(option, link_command)
        self.assertEqual([value for value in link_command if value.lower().endswith(".lib")], [str(self.lib)])
        self.assertEqual(len([value for value in link_command if value.lower().endswith(".obj")]), 1)
        self.assertNotIn("/DLL", link_command)
        self.assertIn("/DEPENDENTLOADFLAG:0x800", link_command)
        self.assertIn(f"/FI{self.helper.LOAD_CONFIG}", compile_command)
        self.assertEqual(evidence["forced_include"]["sha256"], self.helper.sha256(self.helper.LOAD_CONFIG))
        self.assertFalse({"/MT", "/MD", "/GS-"} & set(compile_command))
        self.assertEqual(evidence["output_sha256"], self.helper.sha256(self.output))
        self.assertEqual(evidence["source_sha256"], self.helper.sha256(self.source))
        self.assertEqual(evidence["import_libraries"], [{"file": str(self.lib), "sha256": self.helper.sha256(self.lib)}])

    def test_compile_accepts_mixed_case_toolchain_environment_keys(self):
        self.env = {"PaTh": str(self.compiler.parent), "wInDoWsSdKdIr": str(self.sdk),
                    "windowsSDKVersion": "10.test\\"}
        with patch.object(self.helper, "toolchain_environment", return_value=(self.env, {})), patch.object(
                self.helper.shutil, "which", return_value=str(self.compiler)) as which, patch.object(
                self.helper, "tool_record", return_value={"version": "fixture", "sha256": "a" * 64}), patch.object(
                self.helper.subprocess, "run", side_effect=self.simulate_compile):
            evidence = self.helper.compile_native(self.source, self.output, self.work)
        which.assert_called_once_with("cl.exe", path=str(self.compiler.parent))
        self.assertEqual(evidence["windows_sdk_version"], "10.test")

    def test_toolchain_environment_normalizes_keys_strips_flags_and_decodes_cmd_utf16(self):
        program_files = self.base / "Program Files (x86)"
        vswhere = program_files / "Microsoft Visual Studio/Installer/vswhere.exe"
        vswhere.parent.mkdir(parents=True)
        vswhere.write_bytes(b"vendor discovery fixture")
        installation = self.base / "Visual Studio fixture"
        vcvars = installation / "VC/Auxiliary/Build/vcvars64.bat"
        vcvars.parent.mkdir(parents=True)
        vcvars.write_bytes(b"vendor environment fixture")
        system_root = self.base / "Windows 雪"
        initial = {"ProgramFiles(x86)": str(program_files), "SystemRoot": str(system_root), "Path": "old-path",
                   "CL": "/MT", "_cl_": "/GS-", "LINK": "libcmt.lib", "_LiNk_": "unreviewed.lib"}
        listing = (f"Path={self.compiler.parent}\r\nwindowsSDKDir={self.sdk}\r\nwindowsSDKVersion=10.test\\\r\n"
                   "cl=/MD\r\n_Cl_=/MT\r\nlink=libcmt.lib\r\n_link_=crt.lib\r\n"
                   "Unicode=雪=café\r\n=C:=C:\\hidden drive directory\r\n")
        responses = [subprocess.CompletedProcess([], 0, str(installation) + "\n", ""),
                     subprocess.CompletedProcess([], 0, listing, "")]
        with patch.object(self.helper.sys, "platform", "win32"), patch.dict(self.helper.os.environ, initial, clear=True), \
                patch.object(self.helper.subprocess, "run", side_effect=responses) as run:
            env, selection = self.helper.toolchain_environment()
        self.assertEqual(env["PATH"], str(self.compiler.parent))
        self.assertEqual(env["WINDOWSSDKDIR"], str(self.sdk))
        self.assertEqual(env["WINDOWSSDKVERSION"], "10.test\\")
        self.assertEqual(env["UNICODE"], "雪=café")
        self.assertTrue(all(key == key.upper() for key in env))
        self.assertFalse({"CL", "_CL_", "LINK", "_LINK_"} & set(env))
        self.assertFalse(any(key.startswith("=") for key in env))
        command, = run.call_args_list[1].args
        self.assertIsInstance(command, str)
        self.assertIn(" /d /u /s /c ", command)
        self.assertIn(f'call "{vcvars}" >nul && set', command)
        self.assertEqual(run.call_args_list[1].kwargs["executable"], str(system_root / "System32/cmd.exe"))
        self.assertEqual(run.call_args_list[1].kwargs["encoding"], "utf-16-le")
        self.assertNotIn("shell", run.call_args_list[1].kwargs)
        self.assertEqual(selection["vcvars"]["sha256"], self.helper.sha256(vcvars))

    def test_rejects_other_link_inputs_and_entrypoint_options_before_tool_execution(self):
        with patch.object(self.helper, "toolchain_environment") as environment:
            for libraries in (("libcmt.lib",), ("kernel32.lib", "vcruntime.lib"), ("custom.lib",)):
                with self.subTest(libraries=libraries), self.assertRaises(ValueError):
                    self.helper.compile_native(self.source, self.output, self.work, libraries=libraries)
            with self.assertRaises(ValueError):
                self.helper.compile_native(self.source, self.output, self.work, entry="entry /DEFAULTLIB:libcmt")
            self.output.write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "already exist"):
                self.helper.compile_native(self.source, self.output, self.work)
            environment.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_public_swap_preserves_payload_and_checks_both_executables(self):
        bundle = self.base / "bundle"
        bundle.mkdir()
        public = bundle / self.helper.PUBLIC_NAME
        payload = bundle / self.helper.PAYLOAD_NAME
        public.write_bytes(b"original PyInstaller payload")

        def compile_source(source, output, work):
            self.assertEqual(source, self.helper.SOURCE)
            self.assertEqual(payload.read_bytes(), b"original PyInstaller payload")
            self.assertFalse(public.exists())
            self.assertEqual(output, public)
            output.write_bytes(b"new OS-only launcher")
            return {"source_sha256": "b" * 64}

        with patch.object(self.helper, "compile_native", side_effect=compile_source), patch.object(
                self.helper, "inspect_launcher", return_value={"sha256": "c" * 64}) as inspect, patch.object(
                self.helper, "pe_information", return_value={"sha256": "d" * 64}) as payload_pe:
            result = self.helper.build_launcher(bundle, self.work)
        inspect.assert_called_once_with(public)
        payload_pe.assert_called_once_with(payload)
        self.assertEqual(payload.read_bytes(), b"original PyInstaller payload")
        self.assertEqual(public.read_bytes(), b"new OS-only launcher")
        self.assertEqual(result["payload"], {"file": self.helper.PAYLOAD_NAME, "sha256": "d" * 64})

    def test_public_swap_rejects_existing_payload_without_mutating_either_file(self):
        bundle = self.base / "bundle"
        bundle.mkdir()
        public, payload = bundle / self.helper.PUBLIC_NAME, bundle / self.helper.PAYLOAD_NAME
        public.write_bytes(b"public")
        payload.write_bytes(b"payload")
        with patch.object(self.helper, "compile_native") as compile_source, self.assertRaises(ValueError):
            self.helper.build_launcher(bundle, self.work)
        compile_source.assert_not_called()
        self.assertEqual(public.read_bytes(), b"public")
        self.assertEqual(payload.read_bytes(), b"payload")


class ServerCoreWrapperTests(unittest.TestCase):
    def setUp(self):
        self.wrapper = load_file("windows_prerequisite_offline_test", ROOT / "scripts/test-windows-preview-prerequisite")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.archive = self.base / "preview.zip"
        self.provenance = {"target": "windows-x64", "commit_matches_source": True,
                           "commit": "a" * 40, "source_tree": "b" * 40}
        self.launcher = b"synthetic OS-only public launcher"

    def make_archive(self, extra=(), provenance=None):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("hbcb-review-preview/", b"")
            archive.writestr("hbcb-review-preview/provenance.json", json.dumps(
                self.provenance if provenance is None else provenance))
            archive.writestr("hbcb-review-preview/hbcb-review-preview.exe", self.launcher)
            for name, data in extra:
                if isinstance(name, str):
                    member = zipfile.ZipInfo("raw-fixture")
                    # Preserve deliberately malformed bytes on Windows too.
                    member.filename = name
                    member.orig_filename = name
                else:
                    member = name
                archive.writestr(member, data)
        return self.archive

    def test_accepts_exact_commit_windows_archive_and_binds_launcher_bytes(self):
        provenance, digest = self.wrapper.validate_archive(self.make_archive())
        self.assertEqual(provenance, self.provenance)
        self.assertEqual(digest, hashlib.sha256(self.launcher).hexdigest())

    def test_rejects_zip_traversal_backslashes_ads_case_aliases_and_noncanonical_paths(self):
        for name in ("outside.txt", "hbcb-review-preview/../outside.txt", "hbcb-review-preview/sub/../../outside.txt",
                     "hbcb-review-preview/sub\\outside.txt", "hbcb-review-preview/file:stream",
                     "hbcb-review-preview/PROVENANCE.JSON", "hbcb-review-preview/./provenance.json",
                     "hbcb-review-preview//provenance.json", "hbcb-review-preview/provenance.json.",
                     "hbcb-review-preview/provenance.json "):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.wrapper.validate_archive(self.make_archive([(name, b"unsafe")]))

    def test_rejects_raw_name_before_windows_zipinfo_normalization(self):
        archive = self.make_archive([("hbcb-review-preview/sub\\outside.txt", b"unsafe")])
        with patch.object(zipfile.os, "sep", "\\"), self.assertRaises(ValueError):
            self.wrapper.validate_archive(archive)

    def test_rejects_unix_symlink_zip_member(self):
        member = zipfile.ZipInfo("hbcb-review-preview/link")
        member.create_system = 3
        member.external_attr = (0o120000 | 0o777) << 16
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.wrapper.validate_archive(self.make_archive([(member, b"../outside")]))

    def test_rejects_other_targets_and_nonboolean_commit_match(self):
        for target, matches in (("macos-arm64", True), ("linux-validation", True), ("windows-x64", False),
                                ("windows-x64", None), ("windows-x64", "false"), ("windows-x64", 1)):
            with self.subTest(target=target, matches=matches), self.assertRaises(ValueError):
                self.wrapper.validate_archive(self.make_archive(provenance={**self.provenance,
                                                                            "target": target,
                                                                            "commit_matches_source": matches}))

    def invoke_mock_docker(self, *, wrong_owner=False, start_fails=False):
        archive = self.make_archive()
        output = self.base / "results"
        commands, container = [], {}
        image_id = "sha256:" + "c" * 64

        def execute(command, **kwargs):
            self.assertEqual(command[0], "docker-fixture")
            args = command[1:]
            commands.append(args)
            stdout, stderr, code = "", "", 0
            if args[0] == "info":
                stdout = json.dumps({"OSType": "windows"})
            elif args[:2] == ["image", "inspect"]:
                self.assertEqual(args[2], self.wrapper.IMAGE)
                stdout = json.dumps([{"Id": image_id, "Os": "windows", "Architecture": "amd64",
                                      "OsVersion": "10.0.20348.1",
                                      "RepoDigests": ["mcr.microsoft.com/windows/servercore@sha256:" + "d" * 64]}])
            elif args[0] == "create":
                container["name"] = args[args.index("--name") + 1]
                container["token"] = args[args.index("--label") + 1].split("=", 1)[1]
                for flag in ("--isolation=process", "--network=none", "--pull=never"):
                    self.assertIn(flag, args)
                self.assertIn(image_id, args)
                self.assertNotIn(self.wrapper.IMAGE, args)
                mounts = [args[index + 1] for index, value in enumerate(args) if value == "--mount"]
                self.assertEqual(len(mounts), 2)
                self.assertTrue(mounts[0].endswith(r"target=C:\input,readonly"))
                self.assertTrue(mounts[1].endswith(r"target=C:\results"))
                self.assertEqual((output / "input/preview.zip").read_bytes(), archive.read_bytes())
                stdout = "container-fixture-id\n"
            elif args[0] == "start":
                if start_fails:
                    code, stderr = 1, "synthetic start failure"
                else:
                    diagnostic = {"successful": True, "archive_sha256": self.wrapper.digest(archive),
                                  "launcher_sha256": hashlib.sha256(self.launcher).hexdigest()}
                    (output / "results/diagnostic.json").write_text(json.dumps(diagnostic), encoding="utf-8")
            elif args[0] == "inspect":
                stdout = json.dumps([{"State": {"Running": False, "ExitCode": 0},
                                      "Config": {"Labels": {"hbcb.launcher-test": "not-owned" if wrong_owner else container["token"]}}}])
            elif args[0] == "rm":
                self.assertEqual(args, ["rm", "--force", container["name"]])
                stdout = container["name"]
                container["removed"] = True
            elif args[0] == "ps":
                self.assertIn("label=hbcb.launcher-test=" + container["token"], args)
                if not container.get("removed"):
                    stdout = json.dumps({"Names": "unexpected-name" if wrong_owner else container["name"]}) + "\n"
            else:
                self.fail(f"Unexpected Docker operation: {args!r}")
            return subprocess.CompletedProcess(command, code, stdout, stderr)

        with patch.object(self.wrapper.sys, "platform", "win32"), patch.object(
                self.wrapper.sys, "getwindowsversion", create=True, return_value=SimpleNamespace(build=20348)), patch.object(
                self.wrapper.sys, "argv", ["probe", "--package", str(archive), "--output", str(output)]), patch.object(
                self.wrapper.shutil, "which", return_value="docker-fixture"), patch.object(
                self.wrapper.subprocess, "check_output", side_effect=["a" * 40 + "\n", "b" * 40 + "\n"]), patch.object(
                self.wrapper.subprocess, "run", side_effect=execute), redirect_stderr(io.StringIO()):
            code = self.wrapper.main()
        return code, json.loads((output / "servercore-results.json").read_text()), commands

    def test_execution_is_offline_readonly_input_immutable_image_and_owned_cleanup(self):
        code, report, commands = self.invoke_mock_docker()
        self.assertEqual(code, 0)
        self.assertTrue(report["successful"])
        self.assertTrue(report["archive_unchanged"])
        self.assertIn("cleanup", report)
        self.assertEqual([command[0] for command in commands],
                         ["info", "image", "create", "start", "inspect", "ps", "rm", "ps"])

    def test_failed_start_still_removes_only_owned_container(self):
        code, report, commands = self.invoke_mock_docker(start_fails=True)
        self.assertEqual(code, 1)
        self.assertFalse(report["successful"])
        self.assertIn("synthetic start failure", report["error"])
        self.assertIn("cleanup", report)
        self.assertTrue(report["archive_unchanged"])
        self.assertEqual([command[0] for command in commands][-3:], ["ps", "rm", "ps"])

    def test_label_filtered_cleanup_rejects_unexpected_name_and_fails_report(self):
        code, report, commands = self.invoke_mock_docker(wrong_owner=True)
        self.assertEqual(code, 1)
        self.assertFalse(report["successful"])
        self.assertIn("unexpected container name", report["cleanup_error"])
        self.assertNotIn("rm", [command[0] for command in commands])

    def test_powershell_probe_has_real_missing_runtime_gate_and_no_installation_or_download(self):
        source = (ROOT / "packaging/windows_missing_runtime_probe.ps1").read_text(encoding="utf-8")
        for required in ("[Environment]::SystemDirectory", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll",
                         "$result.probe.exit_code -eq 78", "$result.probe.stdout.Length -eq 0",
                         "$p.StartInfo.UseShellExecute = $false", "$p.WaitForExit(20000)",
                         "Get-FileHash -LiteralPath $Package", "$ExpectedCommit", "$ExpectedTree"):
            self.assertIn(required, source)
        for forbidden in ("Invoke-WebRequest", "Start-BitsTransfer", "Set-Service", "Enable-WindowsOptionalFeature",
                          "vc_redist.x64.exe", "Remove-Item", "Rename-Item"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
