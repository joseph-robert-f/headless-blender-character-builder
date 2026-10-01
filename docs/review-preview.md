# HBCB REVIEW PREVIEW

This **unsigned developer preview** lets you examine existing local projects in read-only mode.
It is not the completed modeling application or a supported consumer installer.
The package includes Python, the existing review backend, and its static browser interface.
Python, Node, Blender, and Docker installation is not necessary to use the preview.

The preview cannot do these operations:

- Make or change models
- Execute project source
- Record acceptance or save change requests
- Connect an account or call an AI provider
- Download a runtime.

Model generation uses a different Linux-only experimental workflow.
A review test that passes does not show model-generation support on Windows or Mac.

## Preview targets and prerequisites

- `windows-x64`: Native Windows x64 CI uses Windows Server 2022. An existing Microsoft Visual C++ runtime can be necessary.
  The `external_microsoft_runtime` field in `provenance.json` identifies DLLs that the package does not redistribute.
  The package also excludes Windows API-set stubs that the OS supplies. The Windows loader resolves these contracts.
  This preview does not install or download a runtime.

  CI does not show the behavior on a new consumer Windows installation.
- `macos-arm64`: Native Apple Silicon CI uses macOS 15 and an arm64 executable.
  This build does not validate Intel Macs or earlier macOS versions.
- `linux-validation`: This target gives packaging development evidence only.
  It is not a preview distribution target. Its locally installed Python and dependencies can be different.

The saved smoke report shows the test result for each artifact.
The target list alone does not show test success.
Native CI has Python for the **test harness**.
The test starts the extracted executable from an unrelated empty directory.
It uses an empty `PATH` and invalid `PYTHONHOME` and `PYTHONPATH` values.

This test examines the packaged interpreter and modules.
It does not show the behavior on an OS without development tools.

Use an OS with current security updates and an existing web browser.
Use a trusted version-1 project with `modeling-project.json` and its original directory layout.
Examine only projects that you trust.
Before review, copy the project to a local directory without links.
The preview does not support symlinks, junctions, network paths, device paths, or concurrent changes.

The preview does not make, migrate, repair, delete, or change a project.
File access can change filesystem access times.
Unchanged file content does not show forensic immutability.

## Obtain and verify an artifact

Download the applicable artifact from the repository's **Review preview packages** workflow in GitHub Actions.
GitHub keeps these artifacts for 14 days.
They are not public releases.
Make sure that the workflow and `provenance.json` identify the expected commit, platform, and smoke-test pass.
The artifact includes a package archive, `SHA256SUMS`, provenance, and a native smoke report.

Before extraction, compare the archive SHA-256 with `SHA256SUMS`:

```powershell
# Windows PowerShell, using the exact downloaded archive filename
Get-FileHash -Algorithm SHA256 .\hbcb-review-preview-<tree>-windows-x64.zip
```

```sh
# macOS, from the artifact download folder
shasum -a 256 hbcb-review-preview-*-macos-arm64.tar.gz
```

Hashes identify corruption and mismatched files.
They do not authenticate the publisher.
If an attacker replaces the archive and hashes, the hashes cannot show safety.
The package has no publisher certificate, notarization, or verified OS reputation.
macOS binaries have only the ad-hoc loader signature that PyInstaller uses for Apple Silicon.

**CAUTION:** If Gatekeeper, SmartScreen, antivirus, or an organization policy blocks the artifact, stop.
Keep the diagnostic information.
Do not disable security controls or bypass the warning.
A bypass can let untrusted software execute.
This preview does not show consumer installation trust.

Extract the archive into a **new empty directory** in a location that is not in your project.
Keep the full `hbcb-review-preview` directory together.
This includes `_internal`, licenses, source, and manifests.
Do not extract into a directory with an older installation.
Do not copy only the executable.

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

Use the downloaded archive name in each command.
The macOS tar archive keeps the internal links and executable permissions that PyInstaller uses.
Extraction and execution do not use administrator privileges, registration, file associations, or a package manager.
OS and security-setting changes are not necessary.

## Review and stop

Open the displayed `http://127.0.0.1:<port>` address in your browser.
The backend binds to numeric loopback only.
It enforces the existing Host, Origin, and CSRF checks.
The UI shows **REVIEW PREVIEW**.
The backend also rejects all acceptance and request writes.
You can read historical decisions and requests.

The viewer shows rendered evidence and lets you download an existing GLB file.
It is not an interactive 3D editor.
Your browser controls downloads and saves a different file to its selected location.

Keep the terminal open.
To stop the session, type `q`.
Then press Enter.
As an alternative, press Ctrl-C.
The terminal process continues after you close a browser tab.

You can start the preview again after a forced terminal or process exit.
This mode writes no lease, status record, or project metadata.
To open it again, enter the same command.
Two read-only sessions can operate at the same time.
Do not start model generation during these sessions.

If a fixed `--port` is in use, select a different port or omit the option.
The preview does not terminate a different process or change firewall settings.

Each startup verifies the extracted package inventory before it opens a project.
If verification does not pass, keep the diagnostic information.
Then extract a new archive with all files.
The manifest cannot prevent hostile replacement of the verifier itself.

It cannot prevent access by a different process with the same user identity or an attack through a compromised OS.
The loopback service is for one trusted local user.
Do not use it for remote or hostile input.

## Source, dependencies, and reproducibility

`source/hbcb-corresponding-source.tar.gz` contains the exact indexed project source for the package.
It includes the controller, review program, packaging scripts, static assets, tests, pins, notices, and license.
`provenance.json` records its Git tree.
CI stops if that tree differs from the checkout commit tree.
Local builds from staged files record any difference.

Project code is GPL-3.0-or-later.
`licenses/` contains the full license texts and upstream notice sources.
The package records runtime selection, relocation, and macOS thinning as changes.
It does not include Blender, generated models, or user project data.
Its corresponding-source archive includes the example source code from the repository.

CPython, PyInstaller, and incorporated components keep their own licenses.
The notice inventory gives operational distribution evidence.
It is not a legal opinion or an assurance for all redistributed dependencies.

Build inputs are official standard-GIL CPython **3.13.16**, PyInstaller **6.22.3**, and hash-locked wheels in `packaging/review-preview-requirements.lock`.
Runtime application dependencies are the Python standard library and project HTML, CSS, and JavaScript.
The package excludes unused TLS, compression, ctypes, database, GUI, and Blender-execution modules.
It does not redistribute Windows Microsoft runtime DLLs.
The OS supplies Apple system frameworks.
Packaging stops if it finds an unknown native dependency.

Each native CI runner installs build dependencies and makes the one-folder package.
It makes an archive, extracts a new copy, and tests the **extracted executable**.
The report includes these checks:

- Startup and packaged static assets
- Evidence bindings and backend write rejection
- Invalid projects and corruption detection
- Controlled and forced shutdown
- Repeated execution and port reuse
- Unchanged project and package contents.

Synthetic fixtures do not show model-generation quality.
They do not show installation or security behavior on a new desktop.
Read the report for the artifact results.

For a maintainer build, use a clean environment on the applicable native platform:

```sh
python -m pip install --require-hashes --only-binary=:all: -r packaging/review-preview-requirements.lock
python scripts/build-review-preview --target macos-arm64 --output build/review-preview
python scripts/test-review-preview --package build/review-preview/hbcb-review-preview-<tree>-macos-arm64.tar.gz --output build/review-preview/smoke-results.json --expected-target macos-arm64
```

On Windows, use `windows-x64` and the `.zip` package.
Output directories must be new or empty.
Build scripts do not make a release, tag, installer registration, signature request, or deployment.
Before a pin update, examine the new notices and native inventory.
Get new native smoke evidence.
Do not update a version in only one file.

### Design references

- [PyInstaller one-folder behavior](https://pyinstaller.org/en/stable/operating-mode.html)
- [Native builds and target architecture](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html)
- [CPython 3.13.16](https://www.python.org/downloads/release/python-31316/)
- [Actions Python distribution provenance](https://github.com/actions/python-versions/blob/main/README.md)
- [Microsoft runtime redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)
- [Microsoft API-set loader behavior](https://learn.microsoft.com/en-us/windows/win32/apiindex/api-set-loader-operation)
- [Tauri sidecars](https://v2.tauri.app/develop/sidecar/).

Native Python packaging is also necessary for Tauri sidecars.
This preview avoids a second launcher toolchain.
