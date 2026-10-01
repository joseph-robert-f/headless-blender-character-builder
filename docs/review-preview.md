# HBCB REVIEW PREVIEW

This is an **unsigned developer preview for read-only review of existing local
projects**. It is not the finished modeling application or a supported consumer
installer. It bundles Python, the existing review backend, and its static browser
interface. You do not install Python, Node, Blender, or Docker to use the preview.

It cannot generate or edit models, run project source, record acceptance, save
change requests, connect an account, call an AI provider, or download a runtime.
Generation remains a separate Linux-only experimental workflow. A passing review
test is not evidence of Windows or Mac generation support.

## Preview targets and prerequisites

- `windows-x64`: native Windows x64 CI on Windows Server 2022. An existing
  Microsoft Visual C++ runtime may be required; the exact DLL names excluded
  from redistribution are recorded under `external_microsoft_runtime` in
  `provenance.json`. OS-provided Windows API-set stubs are also omitted; the
  Windows loader resolves these contracts. No runtime is installed or downloaded by this preview.
  CI does not establish behavior on a fresh consumer Windows installation.
- `macos-arm64`: native Apple Silicon CI on macOS 15, with an arm64 executable.
  Intel Macs and older macOS versions are not validated by this build.
- `linux-validation`: packaging development evidence only, not a preview target
  for distribution. Its locally installed Python/dependencies may differ.

The retained smoke report, not this target list, establishes whether a particular
artifact passed. Native CI has Python installed for the **test harness**, but the
extracted executable is started from an unrelated empty working directory with
an empty `PATH` and invalid `PYTHONHOME`/`PYTHONPATH`. This verifies the packaged
interpreter/module closure without claiming a pristine OS installation.

Use a patched OS, an existing web browser, and a trusted version-1 project with
`modeling-project.json` and its original folder layout. Review only projects you
trust. Copy projects into a normal local folder before review; symlinks,
junctions, network/device paths, and concurrent modification are unsupported.
No project is created, migrated, repaired, deleted, or rewritten by the preview.
Opening files can update filesystem access times; content preservation does not
mean forensic immutability.

## Obtain and verify an artifact

Download a matching preview artifact from the repository's **Review preview
packages** GitHub Actions run. Artifacts are retained for 14 days; they are not
public releases. Check that the run and `provenance.json` identify the expected
commit, platform, and successful smoke result. The artifact contains a package
archive, `SHA256SUMS`, provenance, and a native smoke report.

Before extracting, compare the archive SHA-256 with `SHA256SUMS`:

```powershell
# Windows PowerShell, using the exact downloaded archive filename
Get-FileHash -Algorithm SHA256 .\hbcb-review-preview-<tree>-windows-x64.zip
```

```sh
# macOS, from the artifact download folder
shasum -a 256 hbcb-review-preview-*-macos-arm64.tar.gz
```

Hashes detect corruption and mismatched files. They do not authenticate the
publisher or prove safety if both the archive and hashes were replaced.
No publisher signing certificate, notarization, or OS reputation is provided.
macOS binaries have only the ad-hoc loader signature PyInstaller needs for Apple
Silicon. If Gatekeeper, SmartScreen, antivirus, or an organization policy blocks
the artifact, stop and retain the diagnostic. Do not disable protections or
bypass the warning. This preview does not establish consumer installation trust.

Extract into a **new empty folder**, outside your project. Keep the entire
`hbcb-review-preview` folder together, including `_internal`, licenses, source,
and manifests. Never overlay an older extraction or copy only the executable.

```powershell
Expand-Archive -LiteralPath .\hbcb-review-preview-<tree>-windows-x64.zip -DestinationPath .\preview-new
cd .\preview-new\hbcb-review-preview
.\hbcb-review-preview.exe --verify
.\hbcb-review-preview.exe --project "C:\Projects\Example model"
```

```sh
mkdir preview-new
tar -xzf hbcb-review-preview-<tree>-macos-arm64.tar.gz -C preview-new
cd preview-new/hbcb-review-preview
./hbcb-review-preview --verify
./hbcb-review-preview --project "$HOME/Projects/Example model"
```

Use the actual archive filename in place of `<tree>`. The macOS tar archive
preserves the internal links and executable permissions required by PyInstaller.
Extraction and execution do not need administrator privileges, registration,
file associations, a package manager, or OS/security setting changes.

## Review and stop

Open the printed `http://127.0.0.1:<port>` address in your browser. The backend
always binds numeric loopback and enforces the existing Host/Origin/CSRF checks.
The UI displays **REVIEW PREVIEW**, and all acceptance/request writes are also
rejected by the backend. Historical decisions and requests may still be read.
The existing viewer shows rendered evidence and can download an existing GLB;
it is not an interactive 3D editor. A download is controlled by your browser and
creates a separate file where the browser saves it.

Keep the terminal open. Type `q` and press Enter, or use Ctrl-C, to stop the
session. Closing a browser tab alone does not stop the terminal process. A hard
terminal/process termination is recoverable because this mode writes no lease,
status record, or project metadata. Run the same command again to reopen.
Two read-only sessions may coexist; neither authorizes concurrent generation.
If a fixed `--port` is occupied, choose another port or omit the option. The
preview never kills another process or changes firewall settings.

Every launch verifies the extracted package inventory before opening a project.
If verification fails, preserve the diagnostic and extract a fresh complete
archive. The manifest does not protect against hostile replacement of the
verifier itself, same-user process access, or a compromised OS. The loopback
service is intended for one trusted local user, not remote or hostile input.

## Source, dependencies, and reproducibility

`source/hbcb-corresponding-source.tar.gz` contains the exact indexed project
source used for the package, including the existing controller/reviewer,
packaging scripts, static assets, tests, pins, notices, and license. Its Git tree
is recorded in `provenance.json`. CI requires that tree to match its checkout
commit. Local staged validation builds explicitly record when they differ.

Project code is GPL-3.0-or-later. Complete license texts and upstream notice
sources are in `licenses/`; runtime selection/relocation and macOS thinning are
recorded as changes. The preview bundles neither Blender nor generated models
or user project data; its corresponding-source archive does include the
repository's example source code.
CPython, PyInstaller, and incorporated components retain their own licenses.
The notice inventory is operational distribution evidence, not a legal opinion
or a blanket assurance covering arbitrary redistributed dependencies.

Build inputs: official standard-GIL CPython **3.13.16**, PyInstaller **6.22.3**,
and hash-locked build wheels in
`packaging/review-preview-requirements.lock`. Runtime application dependencies
are Python's standard library and project-authored HTML/CSS/JavaScript. Unused
TLS, compression, ctypes, database, GUI, and Blender-execution modules are
excluded. Windows Microsoft runtime DLLs are not redistributed; Apple system
frameworks stay OS-provided. Unknown native dependencies fail packaging.

Each native CI runner installs build dependencies, creates the one-folder
package, archives it, extracts it afresh, and tests the **extracted executable**.
The report covers startup, packaged static assets, bound evidence, backend write
denials, invalid projects, corruption detection, controlled and forced shutdown,
repeated runs, port reuse, and unchanged project/bundle contents. Synthetic
fixtures never establish real model generation quality or a pristine desktop's
installer/security behavior. Actual artifact results remain in the run report.

For maintainers, build on the matching native platform in a clean environment:

```sh
python -m pip install --require-hashes --only-binary=:all: -r packaging/review-preview-requirements.lock
python scripts/build-review-preview --target macos-arm64 --output build/review-preview
python scripts/test-review-preview --package build/review-preview/hbcb-review-preview-<tree>-macos-arm64.tar.gz --output build/review-preview/smoke-results.json --expected-target macos-arm64
```

Use `windows-x64` and the `.zip` package on Windows. Output directories must be
new or empty. Build scripts make no release, tag, installer registration, signing
request, or deployment. Updating pins requires new notice/native-inventory
review and native smoke evidence; do not copy a new version into one file.

### Design references

- [PyInstaller one-folder behavior](https://pyinstaller.org/en/stable/operating-mode.html)
- [Native builds and target architecture](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html)
- [CPython 3.13.16](https://www.python.org/downloads/release/python-31316/)
- [Actions Python distribution provenance](https://github.com/actions/python-versions/blob/main/README.md)
- [Microsoft runtime redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)
- [Microsoft API-set loader behavior](https://learn.microsoft.com/en-us/windows/win32/apiindex/api-set-loader-operation)
- [Tauri sidecars](https://v2.tauri.app/develop/sidecar/) would still need native
  Python packaging; this bounded preview avoids a second launcher toolchain.
