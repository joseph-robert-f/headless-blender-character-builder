<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Local project and runtime launcher scaffold

This optional development feature uses the [local review program](local-model-review.md) and [source controller](experimental-source-modeling.md).
It is **not an installable Windows/Mac application**, runtime manager, signed distribution, or extension of v0.1 support.
Windows x64 and Mac Apple Silicon are the first planned distribution targets.
The candidate review adapters use `--experimental-platform-review` until native CI shows their tested support level.

Windows review is **read-only** at this stage.
Inspection and downloads operate, but the UI disables acceptance and change-request writes.
Mac uses the existing POSIX review-write implementation.
Generation is Linux x64 only.
These modes are not packaged Windows/Mac applications or the full planned Windows features.
Read [HBCB REVIEW PREVIEW](review-preview.md) for the independently packaged read-only program.

## Create a portable project

Use a source checkout with Python 3.11+.
On Windows, replace `python3` in the examples with your installed `python` or `py -3.13`:

```sh
python3 -m experimental_modeling.launcher init \
  --project "/absolute/path/Projects/My model 雪" --name "My model"
python3 -m experimental_modeling.launcher doctor \
  --project "/absolute/path/Projects/My model 雪"
```

`init` makes `modeling-project.json` (schema 1) and these fixed relative directories:

- Source: `source/`, with the existing `builder.py` entry point
- Assets: `source/assets/`, part of the same source snapshot with fixed limits
- Constraints: `constraints/params.json`, `constraints/policy.json`, and optional `constraints/requirements.json`
- Candidates: `evidence/attempts/`
- Accepted results: `evidence/accepted/`
- Evidence: `evidence/`, with controller-owned `last_good.json`, locked requirements, immutable revision artifacts, and independently recorded review decisions.

Candidate and accepted paths use the existing controller layout.
There is no duplicate accepted model or second last-good pointer.
Source and asset file types and size limits do not change.
Project initialization does not make source, a policy, requirements, or a model.

The descriptor contains only the schema, display name, fixed directories, and runtime policy ID.
It has no credentials, machine-specific executable paths, native-trust consent, provider settings, or account identifiers.
Keep all credentials out of project directories.
The launcher does not scan source, assets, or evidence for secrets.
It has no archive or export feature.
A portable descriptor does not make an arbitrary project safe to share.

To keep relative references, copy the full project to a different local directory.
The descriptor cannot redirect a role to an absolute path or parent path.
The launcher rejects unknown fields or versions, duplicate keys, symlinks, junctions, and parent-traversal paths.
Windows detection examines `lstat` reparse-point attributes on Python 3.11.
It does not use only the newer `Path.is_junction` helper.
Network and device paths are not in this local-filesystem contract.

Names and roots can contain spaces and Unicode.
`init` does not adopt unrelated nonempty directories or overwrite a project name.
Descriptor publication cannot overwrite a descriptor from a concurrent initializer.
The same command can then make missing fixed directories.
This operation uses a local filesystem with hard-link publication.
If the filesystem lacks this function, initialization stops without an overwrite fallback.

Initialization does not delete existing files or evidence.

## Inspect readiness without executing a program

The default `doctor` command reads only project metadata, runtime metadata, and filesystem state.
It does not search PATH, open a review server, execute a discovered binary, or call a model.
It does not change runtime settings, pull an image, or download Blender.

The report gives different readiness results for review, build prerequisites, build recovery state, and model authoring.
`authoring_ready` is always false.
Model-provider integration and an automatic queue consumer are not implemented.
The separate [request bridge](model-request-bridge.md) supports explicit handoff, inspection, and isolated execution of external source.
A trusted coding agent or operator must supply source and policy.

JSON contract checks do not certify source safety, history integrity, or geometry.
The existing controller does those checks during a build.
Doctor exit 0 means that the selected build-prerequisite probes passed and there is no recovery marker.
Exit 1 means not ready.
Malformed project, selection, or CLI inputs use exit 2.

A missing model connection does not prevent review of existing evidence.
It does not prevent an explicit build from supplied source.

## Explicit runtime policy and build

The current policy ID is `blender-4.5.12-linux-amd64-v1`.
It pins the repository's Blender 4.5.12 release and official Linux archive checksum.
It does not upgrade an installed 4.5 runtime.
The launcher does not silently accept other patch or minor versions.
A future runtime policy must have explicit review and reproducibility tests.

Supply runtime selection for each invocation, not in the project descriptor.
Select only a trusted installation and a reviewed image.
`--probe` runs the selected version and capability checks.
`build` repeats those checks before it starts the controller.
Native version output has limits of 8 KiB and 10 seconds.

Probes and execution use the same validated absolute paths.
The launcher rejects project runtime files, PATH discovery, and ambiguous symlink or parent paths.

The isolated workflow uses the existing experimental Docker backend and immutable local image ID.
Supply the local Unix socket explicitly.
Do not depend on a Docker context or environment setting.
Use the socket path without symlinks (usually `/run/docker.sock` on Linux).
`/var/run` can be a symlink.

```sh
python3 -m experimental_modeling.launcher doctor \
  --project "/absolute/path/Projects/My model 雪" --probe \
  --docker /absolute/path/to/docker --docker-socket /absolute/path/to/local/docker.sock \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID
python3 -m experimental_modeling.launcher build \
  --project "/absolute/path/Projects/My model 雪" --revision r0 \
  --docker /absolute/path/to/docker --docker-socket /absolute/path/to/local/docker.sock \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID
```

Replace `YOUR_REVIEWED_LOCAL_IMAGE_ID` with 64 hexadecimal digits.
Keep the `sha256:` prefix.
Preflight examines Linux/amd64 image architecture, Blender version, archive metadata, and existing daemon and image boundary controls.
Image labels alone do not show trust in the contents.
Examine the image build from the pinned repository Dockerfile.

Doctor does not pull images or start containers.
A Docker failure **never** causes native execution.

A daemon capability check is not a live build or a security audit done independently.

The trusted-development option is explicit on each invocation:

```sh
python3 -m experimental_modeling.launcher build \
  --project "/absolute/path/Projects/My model 雪" --revision r0 \
  --trusted-reviewed-source --blender /absolute/path/to/trusted/blender
```

**CAUTION:** Examine all source and assets before native execution.
This mode executes arbitrary source with the authority of your OS account.
It is **not a sandbox**.
This also applies if a future application package contains Blender.
Host files and acceptance evidence can change.

For a subsequent revision, set `--parent` to the current last-good revision.
Use a new `--revision`.
The controller does not overwrite accepted, rejected, or interrupted revision IDs.
The original controller and review program control requirement locking and machine and human acceptance.

## Review, interruption and recovery

```sh
python3 -m experimental_modeling.launcher review \
  --project "/absolute/path/Projects/My model 雪"
```

Review uses the existing loopback-only server and APIs with the descriptor's display name.
Open the displayed local URL on the same computer.
Blender, Docker, and a model connection are not necessary.
The launcher does not open an external browser or host the program remotely.

A different kernel lease permits one launcher review session for each project.
It does not hold the controller's build and review-write lock.
POSIX uses `flock`.
Windows uses a nonblocking byte-zero `msvcrt.locking` lease.
Lock-file names and POSIX semantics do not change.
The launcher does not delete files to force ownership of a lease.

A repeated startup tells the operator to stop the existing session.
On POSIX, Ctrl-C or SIGTERM closes the listener, finishes active requests with fixed limits, and releases the lease.
Windows console Ctrl-C or Ctrl-Break closes the same session.
Windows `TerminateProcess` forces an exit.
Subsequent lease recovery handles that exit.
It is not a controlled cleanup.

A process crash automatically releases its lease.
A new review session can start without lock deletion or termination of a stored PID.
Saved URLs and PIDs do not give process authority.
Launcher metadata `.launcher-review.json` and `.launcher-build.json` contains no authentication data.

Before a Linux build, the launcher atomically writes and syncs its running journal.
An interrupted build or saved execution or cleanup error causes a recovery requirement.
This includes Docker cleanup failure when the controller returns `needs_review`.
Examine the saved attempt, current `last_good.json`, and owned `modeling-*` Docker resources.
Use the [backend recovery guide](EXPERIMENTAL_MODELING_SANDBOX.md).

After cleanup verification, supply `--acknowledge-interrupted-build` with a new revision ID.
This flag does not delete artifacts, restore accepted state, terminate processes, or remove Docker resources.
An ordinary geometry rejection is a completed operation.
A forced exit or unreachable daemon can leave resources for manual cleanup.
This feature does not claim physical power-loss recovery or automatic recovery.

## Verification and remaining portability work

First, run the focused tests.
Then run the full experimental test suite:

```sh
python3 -m unittest discover -s tests/experimental_modeling -p test_launcher.py -v
python3 -m unittest discover -s tests/experimental_modeling -v
```

Runtime fixtures do not execute, and tests inject their probes.
Lifecycle tests execute only the known Python interpreter and local review server.
They include repeated startup, SIGTERM cleanup, SIGKILL and restart, different store locks, and paths with Unicode and spaces.
Mocked platform tests do not show Windows or macOS execution evidence.

The `Experimental project native platforms` workflow runs the portable suite on Windows x64, Mac arm64, and Linux runners.
It examines the observed architecture and uses Python 3.11 and 3.13.
It tests kernel locks and process lifecycle and keeps logs.
Windows tests include a junction and read-only HTTP rejection.
POSIX tests include persistent review writes.

The browser test also examines read-only write controls and desktop and mobile screenshots.
A configured workflow is not a passing result.
Before a support-status change, examine the result for the applicable commit.
Docker and native-Blender tests keep their own optional test gates.

Before a supported Windows x64 or Mac Apple Silicon distribution, complete these areas:

1. **Windows durable review writes.** Kernel leases and junction-aware path checks exist.
   Windows review decisions are read-only.
   The next adapter must use no-clobber and atomic publication through applicable Windows file APIs.
   It must have explicit file-identity checks and durable journal and recovery semantics.

   Test concurrent writers, sharing violations, interrupted replacement, reopening, recovery, and unchanged accepted-model pointers on NTFS.
   Windows can give durable writes.
   The current POSIX directory `fsync` routine is not that Windows adapter.

2. **Owned source-process lifecycle.** `controller.run_job` uses POSIX rlimits, `preexec_fn`, `start_new_session`, and `os.killpg`.
   The controller rejects source execution on Windows before input access.
   An owned process tree and Job Object implementation are necessary on Windows.
   Mac build and resource behavior must pass validation.

   Candidate review runs only the trusted in-process server.
   Its console-signal and forced-exit tests do not validate a generated-code runtime.
   Before source execution, test cancellation, child processes, timeouts, and cleanup failures.

3. **Docker transport and mounts.** `sandbox.DockerSandbox` uses a Unix socket, Linux path and mount syntax, selector-readable process pipes, and fixed Linux filesystem settings.
   Before new adapters, validate Docker Desktop socket and path sharing and native Windows transport.
   The current `docker/builder.Dockerfile` uses `linux/amd64`.

   On Mac Apple Silicon, explicitly test that emulated workflow.
   As an alternative, introduce a Linux arm64 image with its own checksum pin.
   Then repeat all isolation and evidence tests.
   Do not substitute native packaged Blender after Docker isolation failure.

4. **Runtime and package manifest.** Identify the official Windows x64 and macOS arm64 Blender 4.5.12 archives and checksums.
   Resolve redistribution, license, and source obligations.
   Define managed installation locations, interrupted-download recovery, extraction recovery, and rollback.
   This feature contains no runtime archives, downloads, installation code, credentials, or signature identities.

5. **Installable application.** Package the experimental Python modules and review assets explicitly.
   The stable `pyproject.toml` does not include this experiment.
   Add the desktop shell, platform CI, and native installation and removal tests on systems without development tools.
   Add the signed-release and notarization process and provider-connection UI.
   Only the resulting platform test evidence can change readiness status.

Implementation references:

- [Windows byte-range locking](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking)
- [Windows file attributes](https://docs.python.org/3/library/os.html#os.stat_result.st_file_attributes)
- [Subprocess signal behavior](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.send_signal).

This version is a local source-checkout integration feature.
It uses the merged source-modeling and review changes.
It does not make those changes a released end-user product.
