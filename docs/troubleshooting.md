# Troubleshooting

Start with the read-only preflight from the repository root:

```sh
./scripts/doctor
```

Use `./scripts/doctor --service` for the local API stack or
`./scripts/doctor --native` for the best-effort native Blender path. The doctor
does not install or download packages, pull images, start containers, or change
Docker state. It only queries the configured clients and Docker daemon. The
one-shot doctor can inspect a remote daemon, but `--service` rejects a clearly
remote SSH, TCP, or HTTP Docker context because the local API journey requires
host loopback on this machine. Fix every `FAIL` before retrying the longer
command.

## What success looks like

A request-only check ends with:

```text
BUILDER_VALIDATE: PASS
```

A complete one-shot run and independent reopen end with:

```text
BUILDER_BUILD: PASS
BUILDER_VERIFY: PASS
```

The exit status must also be `0`, and `qa.json` must say `"status":"passed"`.
EGL, OpenGL, emulation, or audio warnings can appear during headless Blender
startup; warnings are not the authority. A nonzero exit, a `BUILDER: FAIL[n]`
line, missing `manifest.json`, or non-passing QA means the result was not
published successfully.

The builder stages privately and refuses to overwrite output. If generation or
QA fails, it removes its stage and must not leave a partial named result.

## Quick diagnosis

| Symptom | Likely cause | Safe next action |
|---|---|---|
| `Docker is unavailable` | Docker CLI is not installed or not on `PATH` | Install Docker Desktop/Engine, open it, then rerun `./scripts/doctor` |
| `Docker daemon is not reachable` or socket permission error | Docker is stopped, the current user lacks daemon access, or the selected context is unavailable | Make `docker info` succeed as the current user; on Linux follow [Docker's non-root guidance](https://docs.docker.com/engine/install/linux-postinstall/) and its root-equivalent group warning rather than using broad `sudo` workarounds |
| `local service requires a local Docker daemon/context` | The selected Docker endpoint uses SSH, TCP, or HTTP, so its published loopback ports would exist on another host | Switch to a local context in Docker Desktop or with `docker context use <local-context>`; clear `DOCKER_HOST` or `DOCKER_CONTEXT` if either selects the remote daemon, then rerun `./scripts/doctor --service` |
| Failure while downloading Blender/Debian inputs | The **image build** needs outbound HTTPS/DNS access to pinned sources | Check proxy/DNS/firewall settings and retry `make image`; do not weaken checksum or digest verification |
| BuildKit/frontend error | Docker is too old or BuildKit/Buildx is unavailable | Upgrade Docker; `docker build` must support `--platform` and the pinned Dockerfile frontend |
| `linux/amd64` platform or emulation error | The release image is amd64 and emulation is unavailable | Enable Docker Desktop's amd64 emulation or use an amd64 Linux host |
| `linux/amd64` error on Linux `arm64` | The host has no working amd64 emulation; no checksum-pinned native arm64 Blender archive is accepted for v0.1 | Configure the host's maintained Docker/binfmt emulation and confirm a simple `linux/amd64` container runs, or use an amd64 Linux host. This remains a best-effort path, not release support. |
| Very slow first build on Apple Silicon | Blender and its base image run through amd64 emulation | Allow extra time; later builds reuse verified local layers |
| Builder code / Make `Error 137`, or daemon reports OOM | Docker killed Blender under memory pressure | Close heavy workloads, give Docker at least 4 GiB for the one-shot path, and retry with a fresh output name |
| `no space left on device` | Image layers, build cache, or outputs filled Docker/host storage | Inspect `docker system df` and host free space; remove only independently identified disposable data—never blindly prune service volumes |
| Bind mount/file-sharing error on macOS | The checkout is outside Docker Desktop's shared paths | Move/share the repository path in Docker Desktop, then rerun the doctor |
| `docker: command not found` inside WSL2, or the WSL shell cannot reach Docker | Docker Desktop integration is disabled for that distribution, Docker Desktop is stopped, or Engine was installed only on Windows | Enable Docker Desktop WSL integration for the selected distribution or install Engine inside that distribution; make `docker info` succeed from the same WSL shell before rerunning the doctor. WSL2 remains experimental. |
| WSL2 bind mounts are very slow or produce Windows ownership/permission surprises | The checkout is under `/mnt/c/...` rather than the WSL filesystem | Move the checkout below the WSL home directory (for example `~/headless-blender-character-builder`) and run every project command from that WSL shell. |
| Native Windows shell or path errors | Native Windows without WSL2 has not been validated against the POSIX shell, path, and permission contracts | Use the documented experimental WSL2 path or an amd64 Linux host; do not translate commands ad hoc and assume release parity. |
| Output files are inaccessible | A prior root-run or unusual Docker mapping owns them | Do not rerun the builder as root; inspect ownership and move the old result aside before a new named build |
| `HBCB_MAKE: FAIL[request_missing]` | `REQUEST` does not name an existing regular file | Set `REQUEST=/absolute/path/to/request.json`; Make checks this before building or inspecting an image |
| `HBCB_MAKE: FAIL[output_exists]` | The selected build output already exists and publication is intentionally no-clobber | Choose a new safe `OUTPUT_NAME`, or move the complete old output aside |
| `HBCB_MAKE: FAIL[output_missing]` | `make verify` cannot find a regular, non-symlink output directory | Run `make build` first with the same `REQUEST` and `OUTPUT_NAME`, or correct the name; verification deliberately refuses an output-directory symlink |
| `HBCB_MAKE: FAIL[manifest_missing]` | `make inspect` cannot find the selected regular, non-symlink `manifest.json` | Confirm `OUTPUT_NAME`, then complete `make build` and `make verify`; do not substitute a manifest from another output |
| `output must not already exist` / `BUILDER: FAIL[4]` | A direct builder invocation reached the same no-clobber guard | Choose a new output path, or move the complete old output aside |
| `manifest request provenance mismatch` / `BUILDER: FAIL[11]` | Verification used a different JSON request than the build | Verify with the exact request that produced the manifest; compare its recorded request hash |
| `manifest baked provenance mismatch`, `manifest image provenance mismatch`, or `manifest source provenance mismatch` / `BUILDER: FAIL[11]` | The verifier is running from different project source or a different container image than the one that built the output | Keep the old output unchanged for inspection. Build and verify a new output name from the current checkout; advanced operators may instead retain and use the exact prior image recorded by the old manifest |
| `manifest Blender binary provenance mismatch` / `BUILDER: FAIL[11]` | Native verification selected a different Blender executable, or the exact container binary no longer matches the build record | Verify with the exact Blender binary used for the build, or build and verify a new output with the current exact Blender 4.5.12 binary |
| `BuildRequest was rejected` / `BUILDER: FAIL[3]` | JSON, field, enum, size, or runtime contract violation | Run `make validate REQUEST=/absolute/path/request.json`; compare with the [character guide](character-spec.md) |
| `needs_review` / `BUILDER: FAIL[11]` with no output | Mandatory geometry evidence was unknown or below policy | Read the preceding `BLENDER_BUILDER: FAIL[11]` line after `safe diagnostics:` for the bounded reason, then adjust the recipe and use a new output name; do not manufacture a success manifest |
| Native Blender exits during Metal initialization | Host Blender/backend incompatibility occurred before project code | Prefer the Docker path; native macOS is best effort even with exact Blender 4.5.12 |

## Named builds and reruns

The README quickstart uses `build/facet-bot`; the older `make demo` alias uses
`build/demo`. Custom work should use a distinct output name so results coexist:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot.json"
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-2
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-2
```

`OUTPUT_NAME` is one lowercase, hyphen-separated directory name of at most 48
characters. Paths, slashes, `.`/`..`, spaces, shell syntax, and uppercase names
are rejected. Published output is immutable by design; the builder has no
overwrite switch.

To read a bounded provenance and QA summary without printing artifact paths,
image references, or signed URLs, inspect the selected success manifest:

```sh
make inspect OUTPUT_NAME=facet-bot
```

This is read-only and does not reopen the Blender, GLB, or STL artifacts;
`make verify` remains the independent artifact check.

## Builder codes versus Make's exit status

The codes below belong to the `builder` process. A direct `builder` or
`docker run` invocation returns that code to its caller. When a Make target's
recipe fails, GNU Make itself usually exits `2` instead of forwarding the
recipe's code. Read the preceding `BUILDER: FAIL[n]` marker or GNU Make's
`Error n` diagnostic to identify the underlying builder status. For example, a
geometry review failure commonly looks like this:

```text
BLENDER_BUILDER: FAIL[11]: mandatory geometry QA status is needs_review; safe diagnostics: minimum wall measurement unavailable
BUILDER: FAIL[11]: Blender build failed
make: *** [build] Error 11
```

The shell status after that `make build` command is normally `2`, while `11`
remains the builder status. The named `HBCB_MAKE: FAIL[...]` markers are Make
precondition failures; they stop before Docker work and use recipe status `2`.

| Builder code | Meaning |
|---:|---|
| `0` | Requested operation passed |
| `2` | Invalid CLI usage or unsupported option |
| `3` | Request could not be accepted |
| `4` | Input/output filesystem or no-clobber failure |
| `10` | Blender executable/startup failure |
| `11` | Geometry/artifact verification failed or needs review |
| `12` | Internal trusted-launcher failure |
| `124` | Controlled timeout |
| `128`–`255` | Child process ended by a signal or equivalent platform status |

Unexpected failures deliberately suppress tracebacks, host paths, environment
values, and exception details at the public CLI boundary.

## Local asynchronous service

Check the larger prerequisite set first:

```sh
./scripts/doctor --service
make init-env
make service-config
```

The local stack needs Python 3.11+, Docker Compose 2.24.4+, at least 8 GiB
allocated to Docker, 20 GB free disk, and two free loopback ports. The defaults are `8080`
(API) and `9000` (artifact fixture). If `python3` is older, use the same explicit
selection for every command, beginning with:

```sh
PYTHON=python3.11 ./scripts/doctor --service
PYTHON=python3.11 make service-config
PYTHON=python3.11 make service-up
```

Use the project wrappers for read-only status and bounded logs:

```sh
make service-ps
make service-logs
```

`service-ps` includes stopped containers for this checkout. `service-logs`
prints only the last 100 lines from `api` and `worker`. Do not substitute raw
Compose commands: the wrapper restores this checkout's project identity,
selected ports, and required image-provenance interpolation. Sanitize even these
bounded logs before sharing them. Never paste `.env`, bearer tokens, database or
Redis URLs, storage credentials, private references, signed artifact URLs, or
unredacted request/model content into a public issue.

Common service cases:

- **`.env` is missing on a fresh checkout:** run `make init-env` once. It
  creates an ignored, mode-`0600` file, records a checkout-specific Compose
  project identity, and refuses to overwrite anything.
- **`.env` exists:** keep it. `make service-down` preserves PostgreSQL, Redis,
  and MinIO volumes whose credentials are tied to that file.
- **An older `.env` has no `HBCB_COMPOSE_PROJECT_NAME`:** it deliberately uses
  the legacy `hbcb-local` identity so existing containers and volumes remain
  reachable. Do not add or change the identity merely to silence a warning.
- **The checkout moved:** keep its `.env`; the stored project identity continues
  to select the same Docker resources. If you intentionally use the standard
  `COMPOSE_PROJECT_NAME` override, supply one safe value consistently to every
  command. Changing it selects another stack; it does not migrate data.
- **`.env` is missing but old named volumes remain:** restore the original
  `.env` from a secure local backup. Generating new credentials does not rotate
  credentials inside existing data volumes.
- **The old data is intentionally disposable:** stop the stack, confirm there
  is no needed local data or backup, then remove only this Compose project's
  named volumes through the active Docker context's scoped project view (for
  example, Docker Desktop on macOS/Windows). Use the exact project name printed
  by `make service-ps`; do not select similarly named resources or run a global
  prune. This is irreversible. Only after those volumes are gone should you
  move aside the old `.env` and run `make init-env` again. The project
  intentionally provides no one-command reset that could erase volumes
  accidentally.
- **Port conflict:** find and stop the local program using `127.0.0.1:8080` or
  `127.0.0.1:9000`, or choose distinct loopback host ports and use them for
  every command, for example
  `export HBCB_API_HOST_PORT=18080 HBCB_STORAGE_HOST_PORT=19000`, followed by
  `make service-up` in that terminal.
  Ports must be distinct canonical decimal values from 1 through 65535. Do not
  change the bind address to a public interface.
- **Trusted builder source changed:** rerun `make service-up`. Its wrapper owns
  the current-source builder-image step before starting the service.
- **A dependency stays unhealthy:** inspect bounded `ps`/tail logs, preserve
  `.env` and volumes, then use `make service-down` followed by
  `make service-up`. Avoid volume pruning as a generic repair.
- **The API reports `needs_review`:** the service intentionally exposes the
  stable `builder_needs_review` terminal code rather than private child output.
  Run the same JSON through the one-shot `make build` path to see its bounded
  `safe diagnostics:` reason before changing the character.
- **Docker reports OOM or the host becomes unresponsive:** the steady service
  ceilings total about 7 GiB RAM and 7.5 CPUs; initialization can briefly total
  about 7.375 GiB and 8.25 CPUs. Stop other workloads or allocate more Docker
  resources. The maintainer smoke adds a separate 4 GiB builder workload and is
  best run with at least 12 GiB allocated to Docker.

A successful lightweight client run ends with:

```text
verified model and evidence saved in .../build/service-client/<build-id>/artifacts
```

That directory contains the nine verified builder artifacts plus `build.json`.
For the slower maintainer integration check, success ends with:

```text
SERVICE_SMOKE: PASS project=<checkout-project> evidence=.../build/service-smoke/run.XXXXXX
```

This is the optional maintainer/integration confidence gate: it performs direct
and service builds, restart, cancellation, artifact, Redis, and IAM checks and
retains evidence under `build/service-smoke/`. It is not required to start or
try the API. Use `make service-client REQUEST=/absolute/path/to/request.json`
for the documented first evaluation of this experimental path; the [HTTP API
guide](api.md) also retains a longer manual protocol example for integrators.

For exact image cleanup, stop the stack, list the selected service project's
six tags, review them, and then remove only that list:

```sh
make service-down
make service-images
make service-image-cleanup
```

The last command fails if Docker cannot prove whether a tag exists. It also
refuses the legacy shared `hbcb-local` identity; in that case inspect the list
and remove exact tags manually only after confirming every older checkout that
could share them is stopped. Named PostgreSQL, Redis, and MinIO volumes and
`.env` are retained. Shared Docker/BuildKit cache is retained because Docker
does not expose a trustworthy checkout owner for every cache record. Inspect
space with `docker system df`, but never run a global image, builder, volume, or
system prune as a repair or cleanup shortcut. Ignored
`build/service-smoke/run.*` evidence is ordinary local output and is not
removed by the image helper.

## Release and deployment checks

`make release-static` is the fast, offline publication-policy check. The full
`HBCB_RELEASE_RUN_ID=<unique-safe-id> make release-check` builds images, runs real Blender and service gates,
exercises recovery, and packages sanitized evidence. It requires Docker,
Python 3.11+, Compose 2.24.4+, substantial time/disk, and a clean intended Git
index.

Evidence is no-clobber. A run ID is mandatory; choose a new unique lowercase
value for every run:

```sh
HBCB_RELEASE_RUN_ID=public-check-2 make release-check
```

Only one full release check may use a Docker daemon at a time. If it reports an
existing `hbcb-release-check-claim` volume, inspect that volume and confirm
whether an earlier release process is active. Do not delete or take over the
claim without maintainer approval; the wrapper deliberately leaves a foreign or
ambiguous claim untouched.

Do not operate the VPS reference until publisher-supplied image digests, source
metadata, and a usable release lock exist. The checked-in example lock contains
intentional placeholders and the operator tooling rejects it. Deployment
failures and recovery rules are covered in the [deployment guide](deployment.md).

## Ask for help with safe evidence

For a reproducible public bug report, include:

```sh
./scripts/doctor                 # or --service / --native
git rev-parse HEAD
uname -a
```

Also include the exact command, the shell status, the final `PASS`,
`BUILDER: FAIL[n]`, `HBCB_MAKE: FAIL[...]`, or `Error n` line, and only relevant
sanitized manifest/QA fields. Do not attach a complete build if you do not have
redistribution rights. Suspected vulnerabilities belong in the private process
described by [SECURITY.md](../SECURITY.md), not a public issue.
