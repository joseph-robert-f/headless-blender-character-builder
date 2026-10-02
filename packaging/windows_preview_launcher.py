# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and audit the Windows OS-only launcher. Native Windows build tools only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_NAME = "hbcb-review-preview.exe"
PAYLOAD_NAME = "hbcb-review-preview-runtime.exe"
SOURCE = ROOT / "packaging/windows_preview_launcher.c"
LOAD_CONFIG = ROOT / "packaging/windows_load_config.h"
PROTECTIONS = 0x20 | 0x40 | 0x100  # high-entropy VA, dynamic base, NX
# propsys.dll is the Windows Property System dependency used by CPython _wmi:
# https://learn.microsoft.com/en-us/windows/win32/api/propsys/nf-propsys-psgetpropertysystem
OS_IMPORTS = {
    "advapi32.dll", "bcrypt.dll", "comctl32.dll", "comdlg32.dll", "crypt32.dll",
    "gdi32.dll", "imm32.dll", "iphlpapi.dll", "kernel32.dll", "msvcrt.dll",
    "netapi32.dll", "ntdll.dll", "ole32.dll", "oleaut32.dll", "powrprof.dll",
    "propsys.dll", "psapi.dll", "rpcrt4.dll", "secur32.dll", "setupapi.dll", "shell32.dll",
    "shlwapi.dll", "ucrtbase.dll", "user32.dll", "userenv.dll", "version.dll",
    "winmm.dll", "ws2_32.dll",
}
VC_IMPORTS = {"vcruntime140.dll", "vcruntime140_1.dll"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pe_information(path):
    import pefile

    with pefile.PE(str(path), fast_load=False) as pe:
        def imports(attribute):
            return sorted([
                {"dll": row.dll.decode("ascii").lower(),
                 "symbols": sorted(item.name.decode("ascii") if item.name else f"ordinal:{item.ordinal}"
                                   for item in row.imports)}
                for row in getattr(pe, attribute, [])], key=lambda row: row["dll"])
        config = getattr(pe, "DIRECTORY_ENTRY_LOAD_CONFIG", None)
        return {"sha256": sha256(path), "machine": pe.FILE_HEADER.Machine,
                "subsystem": pe.OPTIONAL_HEADER.Subsystem,
                "optional_header_magic": pe.OPTIONAL_HEADER.Magic,
                "dependent_load_flags": getattr(config.struct, "DependentLoadFlags", None) if config else None,
                "dll_characteristics": pe.OPTIONAL_HEADER.DllCharacteristics,
                "imports": imports("DIRECTORY_ENTRY_IMPORT"),
                "delay_imports": imports("DIRECTORY_ENTRY_DELAY_IMPORT")}


def inspect_launcher(path):
    """A PE import gate; the separate link-input gate excludes static CRT code."""
    result = pe_information(path)
    if result["machine"] != 0x8664 or result["subsystem"] != 3 or result["optional_header_magic"] != 0x20b:
        raise ValueError("The launcher must be a Windows x64 console executable")
    if result["dll_characteristics"] & PROTECTIONS != PROTECTIONS:
        raise ValueError("The launcher must retain ASLR, high-entropy VA, and NX")
    if result["dependent_load_flags"] != 0x800:
        raise ValueError("The launcher must restrict static dependency loading to System32")
    if result["delay_imports"] or [row["dll"] for row in result["imports"]] != ["kernel32.dll"]:
        raise ValueError("The launcher must import only kernel32.dll without delay imports")
    if not result["imports"][0]["symbols"] or any(
            name.startswith("ordinal:") for name in result["imports"][0]["symbols"]):
        raise ValueError("The launcher must use named OS imports")
    return result


def native_pe_inventory(bundle):
    """Check the complete Windows native set, including both public and frozen EXEs."""
    paths = sorted(path for path in bundle.rglob("*") if path.suffix.lower() in {".exe", ".dll", ".pyd"})
    supplied = {path.name.lower() for path in paths}
    if len(supplied) != len(paths):
        raise ValueError("Windows native basenames must be unique")
    rows = []
    unknown = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Windows native files must be regular package files")
        row = pe_information(path)
        if row["machine"] != 0x8664:
            raise ValueError("Unreviewed native Windows architecture")
        for item in row["imports"] + row["delay_imports"]:
            name = item["dll"]
            api_set = re.fullmatch(r"(?:api|ext)-ms-win-[a-z0-9-]+\.dll", name)
            if name not in supplied | OS_IMPORTS | VC_IMPORTS and not api_set:
                unknown.append(f"{path.name}: {name}")
        rows.append({"file": path.relative_to(bundle).as_posix(), **row})
    if unknown:
        raise ValueError("Unreviewed Windows native imports: " + "; ".join(unknown))
    if {path.relative_to(bundle).as_posix() for path in paths if path.suffix.lower() == ".exe"} != {
            PUBLIC_NAME, PAYLOAD_NAME}:
        raise ValueError("The Windows package must contain exactly the launcher and frozen payload EXEs")
    inspect_launcher(bundle / PUBLIC_NAME)
    return rows


def toolchain_environment():
    """Select installed official VS tools; this function never installs software."""
    if sys.platform != "win32":
        raise ValueError("Build the Windows launcher on native Windows")
    program_files = os.environ.get("ProgramFiles(x86)")
    if not program_files:
        raise ValueError("Cannot find installed Visual Studio tools")
    vswhere = Path(program_files) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise ValueError("Install official Visual Studio C++ x64 build tools before this maintainer build")
    result = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                            check=True, capture_output=True, text=True, timeout=30)
    locations = result.stdout.strip().splitlines()
    if len(locations) != 1:
        raise ValueError("Expected one selected Visual Studio installation")
    vcvars = Path(locations[0]) / "VC/Auxiliary/Build/vcvars64.bat"
    # This is an installed vendor script, not input from a project or runtime user.
    # Reject cmd metacharacters rather than interpolating arbitrary paths.
    if not vcvars.is_file() or any(char in str(vcvars) for char in '\r\n"%&|<>^!'):
        raise ValueError("Invalid installed Visual Studio environment script path")
    command_processor = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
    # cmd.exe uses its own quoting, not the CRT argv quoting used by a list.
    # /u gives the environment listing a fixed UTF-16 encoding.
    setup_command = f'"{command_processor}" /d /u /s /c "call "{vcvars}" >nul && set"'
    setup = subprocess.run(setup_command, executable=str(command_processor),
                           check=True, capture_output=True, encoding="utf-16-le", timeout=60)
    env = {key.upper(): value for key, value in os.environ.items()}
    for line in setup.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            key, value = line.split("=", 1)
            env[key.upper()] = value
    # Compiler and linker environment options must not add implicit code inputs.
    for name in list(env):
        if name.upper() in {"CL", "_CL_", "LINK", "_LINK_"}:
            env.pop(name)
    return env, {"vswhere": {"file": str(vswhere), "sha256": sha256(vswhere)},
                 "vcvars": {"file": str(vcvars), "sha256": sha256(vcvars)}}


def tool_record(path):
    import pefile

    record = {"file": str(path), "sha256": sha256(path)}
    with pefile.PE(str(path), fast_load=False) as pe:
        fixed = getattr(pe, "VS_FIXEDFILEINFO", [])
        if not fixed:
            raise ValueError("The installed build tool must have version information")
        version = fixed[0]
        record["version"] = ".".join(map(str, [version.FileVersionMS >> 16, version.FileVersionMS & 0xffff,
                                                version.FileVersionLS >> 16, version.FileVersionLS & 0xffff]))
    return record


def compile_native(source, output, work, *, entry="launcher_entry", libraries=("kernel32.lib",), dll=False):
    """Use one source object plus explicit Windows SDK import libraries, without a CRT.

    Test fixtures can request shell32 or a DLL. The shipped launcher uses only
    the default kernel32 import library and is checked separately below.
    """
    if libraries not in {("kernel32.lib",), ("kernel32.lib", "shell32.lib")}:
        raise ValueError("Only explicit Windows OS import libraries are permitted")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", entry):
        raise ValueError("Invalid native entry point")
    source, output, work = Path(source).resolve(strict=True), Path(output).resolve(), Path(work).resolve()
    if output.exists():
        raise ValueError("Native output must not already exist")
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    env, selection = toolchain_environment()
    env_keys = {key.upper(): value for key, value in env.items()}
    compiler_name = shutil.which("cl.exe", path=env_keys.get("PATH", ""))
    if not compiler_name:
        raise ValueError("The installed x64 C++ compiler was not found")
    compiler = Path(compiler_name).resolve(strict=True)
    linker = compiler.with_name("link.exe")
    if [part.lower() for part in compiler.parts[-3:-1]] != ["hostx64", "x64"]:
        raise ValueError("Use the native x64 host and target compiler")
    sdk = Path(env_keys["WINDOWSSDKDIR"]) / "Lib" / env_keys["WINDOWSSDKVERSION"].rstrip("\\/") / "um/x64"
    imports = [(sdk / name).resolve(strict=True) for name in libraries]
    obj = work / (output.stem + ".obj")
    map_file = work / (output.stem + ".map")
    if obj.exists() or map_file.exists():
        raise ValueError("Native intermediate output must be new")
    compile_command = [str(compiler), "/nologo", "/TC", "/c", "/O1", "/W4", "/WX", "/GS", "/Zl",
                       "/utf-8", "/Brepro", f"/FI{LOAD_CONFIG}", f"/Fo{obj}", str(source)]
    link_command = [str(linker), "/nologo", "/WX", "/NODEFAULTLIB", f"/ENTRY:{entry}", "/MACHINE:X64",
                    "/SUBSYSTEM:CONSOLE", "/DYNAMICBASE", "/HIGHENTROPYVA", "/NXCOMPAT", "/INCREMENTAL:NO",
                    "/MANIFEST:NO", "/DEPENDENTLOADFLAG:0x800", "/Brepro", f"/MAP:{map_file}",
                    f"/OUT:{output}", str(obj), *(str(path) for path in imports)]
    if dll:
        link_command.append("/DLL")
    results = []
    for command in (compile_command, link_command):
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        results.append({"command": command, "returncode": result.returncode,
                        "stdout": result.stdout[-8192:], "stderr": result.stderr[-8192:]})
        if result.returncode:
            (work / (output.stem + "-failure.json")).write_text(json.dumps(results, indent=2), encoding="utf-8")
            raise RuntimeError(f"Native launcher build failed: {result.stdout[-8192:]} {result.stderr[-8192:]}")
    map_text = map_file.read_text(encoding="utf-8", errors="replace")
    # /NODEFAULTLIB prevents implicit libraries. No /MT, CRT import/static lib,
    # resource object, precompiled object, or compiler startup object is supplied.
    evidence = {"schema_version": 1, "source": str(source), "source_sha256": sha256(source),
                "compiler": tool_record(compiler), "linker": tool_record(linker), "selection": selection,
                "forced_include": {"file": str(LOAD_CONFIG), "sha256": sha256(LOAD_CONFIG)},
                "windows_sdk_version": env_keys["WINDOWSSDKVERSION"].rstrip("\\/"),
                "import_libraries": [{"file": str(path), "sha256": sha256(path)} for path in imports],
                "object": {"file": obj.name, "sha256": sha256(obj)}, "commands": results,
                "map": {"file": map_file.name, "sha256": sha256(map_file), "text": map_text},
                "output_sha256": sha256(output),
                "link_input_policy": "One freshly compiled project C object and explicit OS import libraries; no default or CRT libraries"}
    return evidence


def build_launcher(bundle, work):
    bundle = Path(bundle).resolve(strict=True)
    public, payload = bundle / PUBLIC_NAME, bundle / PAYLOAD_NAME
    if public.is_symlink() or not public.is_file() or payload.exists() or public.stat().st_nlink != 1:
        raise ValueError("The launcher requires one new regular PyInstaller executable")
    public.rename(payload)
    evidence = compile_native(SOURCE, public, Path(work) / "windows-launcher")
    evidence["pe"] = inspect_launcher(public)
    evidence["payload"] = {"file": PAYLOAD_NAME, **pe_information(payload)}
    return evidence
