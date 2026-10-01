<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Local project and runtime launcher scaffold

This opt-in development increment builds on the [local review program](local-model-review.md)
and [source controller](experimental-source-modeling.md). It is **not an installable
Windows/Mac app**, runtime manager, signed distribution, or expanded v0.1 support.
Windows x64 and Mac Apple Silicon are the first intended distribution targets.
Their candidate review adapters require explicit `--experimental-platform-review`
until native CI establishes the tested support level. Windows review is an
intermediate **read-only** mode: inspection/downloads work, while acceptance and
change-request writes are visibly disabled. Mac uses the existing POSIX review
write path. Generation remains Linux x64 only. None of these modes is a packaged
Windows/Mac application or the final intended Windows feature set.

## Create a portable project

Run from a source checkout with Python 3.11+. On Windows, use your installed
`python` or `py -3.13` in place of `python3` in the examples:

```sh
python3 -m experimental_modeling.launcher init \
  --project "/absolute/path/Projects/My model 雪" --name "My model"
python3 -m experimental_modeling.launcher doctor \
  --project "/absolute/path/Projects/My model 雪"
```

`init` creates `modeling-project.json` (schema 1) and fixed relative folders:

- source: `source/`, with the existing `builder.py` entry point
- assets: `source/assets/`, included in the same bounded source snapshot
- constraints: `constraints/params.json`, `constraints/policy.json`, and optional
  `constraints/requirements.json`
- candidates: `evidence/attempts/`
- accepted: `evidence/accepted/`
- evidence: `evidence/`, including the controller-owned `last_good.json`, locked
  requirements, immutable revision artifacts, and separate review decisions

The candidate and accepted paths intentionally retain the existing controller
layout. There is no duplicate accepted model or second last-good pointer. The
source/asset file types and budgets are unchanged. Creating a project does not
create source, a policy, requirements, or a model.

The descriptor contains only schema, display name, fixed folders and runtime
policy ID. It has no credentials, machine-specific executable paths, native-trust
consent, provider settings or account identifiers. Keep all credentials outside
project folders. This does not scan arbitrary source/assets/evidence for secrets,
and no archive/export feature is implemented. Do not assume an arbitrary project
is safe to share merely because its descriptor is portable.

Copy the entire project to another local folder to preserve relative references.
The descriptor cannot redirect a role to an absolute or parent path. Unknown
fields/versions, duplicate keys, symlinks, junctions and parent-traversal paths
fail closed. Windows detection checks `lstat` reparse-point attributes even on
Python 3.11, not only the newer `Path.is_junction` helper. Network/device paths
are outside this local-filesystem contract. Names and roots can contain spaces and Unicode. `init` does not
adopt nonempty unrelated folders or overwrite a project name. Its descriptor is
published without clobbering another initializer, then missing fixed folders can
be resumed with the same command. This requires a local filesystem supporting
hard-link publication; an unsupported filesystem fails without a fallback that
could overwrite data. Existing files and evidence are never deleted by init.

## Inspect readiness without executing a program

Default `doctor` only reads project/runtime metadata and filesystem state. It
never searches PATH, opens a review server, executes a discovered binary, calls
a model, modifies runtime settings, pulls an image or downloads Blender.

It reports separate readiness for review, build prerequisites, the build recovery
state, and model authoring. `authoring_ready` is always false: model-provider
integration and an automatic queue consumer are not implemented. Source and
policy must still be supplied by a trusted coding agent/operator.

JSON contract checks do not certify source safety, history integrity or geometry.
The existing controller performs those build-time checks. Doctor exit 0 means the
selected build prerequisites were probed and passed with no recovery marker; exit
1 means not ready. Malformed project/selection/CLI inputs use exit 2. A missing
model connection does not prevent reviewing existing evidence or explicitly
building already supplied source.

## Explicit runtime policy and build

The current policy ID is `blender-4.5.12-linux-amd64-v1`. It pins the repository's
existing Blender 4.5.12 release and official Linux archive checksum. It does not
upgrade an installed 4.5 runtime. Other patch/minor versions are not silently
accepted; a future runtime policy needs explicit review and reproducibility tests.

Runtime selection is supplied for each invocation, outside the project descriptor.
Select only a trusted installation and a reviewed image. `--probe` explicitly
runs the chosen version/capability checks; `build` always repeats those checks
before controller dispatch. Native version output is bounded to 8 KiB/10 seconds.
Validated absolute paths are used consistently for probing and execution; project
runtime files, PATH discovery and ambiguous symlink/parent paths are rejected.

The isolated path uses the same experimental Docker backend and immutable local
image ID. Supply the exact local Unix socket rather than inheriting a Docker
context or environment setting. Use its actual non-symlink path (commonly
`/run/docker.sock` on Linux; `/var/run` can be a symlink):

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

Replace the example image placeholder with a complete 64-hex local image ID.
The preflight requires Linux/amd64 image architecture, matching Blender version
and archive metadata, and all existing daemon/image boundary checks. Image labels
alone do not prove trustworthy contents: the operator must review/build the image
from the pinned repository Dockerfile. No image is pulled and no container is
started by doctor. Docker failure **never** falls back to native execution.
A daemon capability check is not a live build or independent security audit.

The separate trusted-development option is explicit on every call:

```sh
python3 -m experimental_modeling.launcher build \
  --project "/absolute/path/Projects/My model 雪" --revision r0 \
  --trusted-reviewed-source --blender /absolute/path/to/trusted/blender
```

This executes arbitrary source with the OS user's authority and is **not a
sandbox**, including when Blender eventually ships inside an application bundle.
Use it only after reviewing all source and assets. A subsequent revision must use
`--parent` equal to current last-good and a new `--revision`; accepted, rejected
and interrupted revision IDs are never overwritten. Requirement locking and
machine/human acceptance remain owned by the original controller/reviewer.

## Review, interruption and recovery

```sh
python3 -m experimental_modeling.launcher review \
  --project "/absolute/path/Projects/My model 雪"
```

Review uses the existing loopback-only server/APIs and the descriptor's display
name. Open the printed local URL on the same computer. It does not require Blender,
Docker or a model connection. No external browser launch or remote hosting occurs.

A separate kernel lease permits one launcher review session per project without
holding the controller's build/review-write lock. POSIX retains `flock`; Windows
uses a nonblocking byte-zero `msvcrt.locking` lease. Existing lock-file names and
POSIX semantics are preserved; files are not deleted to force takeover. A repeated startup reports that
the existing session must be stopped. On POSIX, Ctrl-C/SIGTERM closes the listener, drains bounded active requests and
releases the lease. Windows console Ctrl-C/Ctrl-Break unwinds the same session;
Windows `TerminateProcess` is a forced exit, handled by subsequent lease recovery,
not described as graceful cleanup. A crashed process loses its lease
automatically; a new review may start without deleting locks or killing a stored
PID. Persisted URLs/PIDs are not used as process authority. Launcher metadata
`.launcher-review.json` and `.launcher-build.json` contains no authentication data.

Before a build, its running journal is atomically written and synced on Linux.
An interrupted build or controller-retained execution/cleanup error leaves
recovery required, including when Docker cleanup fails but the controller returns
a `needs_review` result. Inspect the retained attempt, current `last_good.json`,
and any owned `modeling-*` Docker resources using the existing
[backend recovery guidance](EXPERIMENTAL_MODELING_SANDBOX.md). After confirming
cleanup, explicitly pass `--acknowledge-interrupted-build` with a fresh revision
ID. This flag does not delete artifacts, roll back accepted state, kill processes
or remove Docker resources. Ordinary geometric rejection remains a finished run.
A hard kill or unreachable daemon can still leave resources requiring operator
cleanup; this scaffold makes no physical power-loss or automatic-recovery claim.

## Verification and remaining portability work

Run the focused tests, then the complete experimental suite:

```sh
python3 -m unittest discover -s tests/experimental_modeling -p test_launcher.py -v
python3 -m unittest discover -s tests/experimental_modeling -v
```

Runtime fixtures are inert and probes are injected. Lifecycle tests execute only
the known Python interpreter and local review server, covering repeated launch,
SIGTERM cleanup, SIGKILL/restart, separate store locks and Unicode/spaced paths.
Passing mocked platform gates is not Windows/macOS execution evidence. A separate
`Experimental project native platforms` workflow runs the dedicated portable suite on
actual Windows x64, Mac arm64 and Linux runners, with observed architecture checks,
Python 3.11/3.13, real kernel-lock/process lifecycle tests, and retained logs. Windows
runs a real junction test and read-only HTTP denial tests; POSIX runs persistent
review-write tests. The browser gate also checks read-only mutation controls and
desktop/mobile screenshots. A configured workflow is not a passing result; inspect
its exact-commit outcome before updating support claims. Actual Docker/native-
Blender tests retain their separate opt-in gates.

Before a Windows x64/Mac Apple Silicon distribution can be called supported:

1. **Windows durable review writes:** kernel leases and junction-aware path checks
   are implemented, but Windows review decisions remain read-only. The next adapter
   needs no-clobber/atomic publication using appropriate Windows file APIs, explicit
   file-identity checks and durable journal/recovery semantics. Test concurrent
   writers, sharing violations, interrupted replacement, reopen/recovery and
   unchanged accepted-model pointers on real NTFS. Windows can support durable
   writes; this increment deliberately does not pretend its current POSIX directory
   fsync routine is that adapter
2. **Owned source-process lifecycle:** `controller.run_job` still uses POSIX
   rlimits, `preexec_fn`, `start_new_session` and `os.killpg`; source execution is
   explicitly refused on Windows before input reads. Windows needs an owned-process
   tree/Job Object implementation. Mac needs validated build/resource behavior.
   Candidate review runs only the trusted in-process server; its console-signal and
   forced-exit tests do not validate a generated-code runtime. Test cancellation,
   descendants, timeouts and cleanup failures before enabling source execution
3. **Docker transport/mount architecture:** `sandbox.DockerSandbox` currently uses
   a Unix socket, Linux path/mount syntax, selector-readable process pipes and a
   fixed Linux filesystem environment. Validate Docker Desktop socket/path sharing
   and native Windows transport before enabling those adapters. The current
   `docker/builder.Dockerfile` is deliberately `linux/amd64`; Mac Apple Silicon
   must either explicitly test that emulated path or introduce a separately
   checksum-pinned Linux arm64 image and rerun all containment/evidence gates.
   Do not silently substitute a native bundled Blender for failed Docker isolation
4. **Runtime/package manifest:** resolve official Windows x64 and macOS arm64
   4.5.12 archives/checksums, redistribution/license/source obligations, managed
   install locations, interrupted download/extraction and rollback. No runtime
   archives, downloads, install code, credentials or signing identities are part
   of this increment
5. **Installable app:** package the experimental Python modules and review assets
   explicitly (the stable `pyproject.toml` does not include this experiment), add
   the desktop shell, platform CI, native clean-machine install/uninstall tests,
   signed release/notarization process and provider connection UI. Only actual
   resulting platform tests can change the current readiness gates

Implementation references: Python's [Windows byte-range locking](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking),
[Windows file attributes](https://docs.python.org/3/library/os.html#os.stat_result.st_file_attributes),
and [subprocess signal behavior](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.send_signal).

The existing version is a local source-checkout integration scaffold based on the
merged source-modeling and review changes; it does not reclassify them as a
released end-user product.
