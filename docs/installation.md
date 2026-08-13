# Installation and first model

The recommended path builds a pinned `linux/amd64` Blender image from this
repository and runs it through Docker. You do not need Blender, Python, Docker
Compose, an AI key, or a provider account for one-shot builds.

> **Availability:** this repository currently ships source and container build
> definitions only. There is no published GitHub Release or container image.
> There is also no project-published PyPI package or supported `pip install`
> path; do not substitute a similarly named package from PyPI. Cloning `main`
> is useful for source evaluation, but it is not the same as installing a
> signed versioned release.

## Choose a path

| Path | Status | Requirements |
|---|---|---|
| [Docker with Make](#container-path-recommended) | Recommended local path | Git, current Docker Engine/Desktop with BuildKit and `linux/amd64` support, GNU Make |
| [Docker without Make](#docker-without-make) | Equivalent manual path | Git, Docker, a POSIX shell, `id`, and `mkdir` |
| [Native Blender](#native-blender-best-effort) | Best-effort contributor path | Git, Python 3.11+, exact Blender 4.5.12 LTS |
| [Local asynchronous service](#local-asynchronous-service) | Local integration path | Local Docker daemon/context, Docker Compose 2.24.4+, Python 3.11+, curl, 8 GiB Docker memory, 20 GB free disk, and the container requirements |
| [VPS reference](deployment.md) | Production-oriented design; not yet published for deployment | Linux `amd64`, Python 3.11+, Compose 2.24.4+, domain/TLS, private storage networking, external versioned S3, role secrets, and a future release lock/image set |

The container runtime limit is four CPUs, 4 GB RAM, 512 PIDs, and 2 GB of
scratch. Allow about four CPU cores, 8 GB of host RAM, and 10 GB of free disk
for the quickstart. Apple Silicon uses `linux/amd64` emulation and is slower.

## Platform setup

### macOS without Homebrew

Homebrew is optional. You can install every quickstart prerequisite from the
vendor:

1. Run `xcode-select --install` in Terminal and complete Apple's installer.
   The Command Line Tools provide Git and GNU Make.
2. Install and start [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/).
   Choose the download for your Mac's chip and allow at least 4 GB of memory
   for Docker workloads.
3. Open a new Terminal window and confirm the tools are visible:

   ```sh
   git --version
   make --version
   docker info
   ```

`make --version` must identify GNU Make. A successful `docker info` confirms
that Docker Desktop is running; `docker --version` alone checks only the
client.

The one-shot container path does not need host Python or Blender. For native
work, install Python 3.11 or newer from
[python.org](https://www.python.org/downloads/macos/) and Blender 4.5.12 LTS
from [blender.org](https://www.blender.org/download/lts/4-5/); Homebrew is still
not required.

For the optional local service, Docker Desktop supplies the Compose plugin.
Install Python 3.11+ from python.org, keep the system-provided `curl` current,
and allocate at least 8 GiB to Docker Desktop (12 GiB for `service-smoke`). The
service doctor verifies Python, Compose, curl's required flags, and the current
Docker allocation before any service build.

### Linux

Install Git and GNU Make with your distribution's package manager. On Debian
or Ubuntu:

```sh
sudo apt-get update
sudo apt-get install -y git make
```

Install Docker Engine and its Buildx plugin using the
[official instructions for your distribution](https://docs.docker.com/engine/install/).
Then follow Docker's
[Linux post-install guidance](https://docs.docker.com/engine/install/linux-postinstall/)
to choose a documented rootless or Docker-group setup so your ordinary user
can reach the daemon. Docker group membership grants root-level privileges;
review that tradeoff before enabling it. Verify:

```sh
git --version
make --version
docker info
docker buildx version
```

Do not work around a daemon permission failure by making the Docker socket
world-writable.

For the optional local service, also install `curl`, a Python 3.11+ interpreter,
and Docker's Compose plugin inside Linux. Follow Docker's official repository
instructions for `docker-compose-plugin`; a legacy standalone `docker-compose`
binary is not the documented path. Verify with `python3 --version`,
`curl --version`, and `docker compose version`.

Native Linux `amd64` is the reference runtime. Linux `arm64` can emulate the
release image but is best effort; no official native `arm64` Blender archive is
pinned for v0.1.

### Windows with WSL2 (experimental)

The Windows path is non-release-blocking and experimental. Use a WSL2 Linux
distribution, then either enable Docker Desktop's WSL integration for that
distribution or install Docker Engine inside it. Install Git and GNU Make in
the Linux distribution, not only on Windows. For the optional service, install
Python 3.11+, curl, and the Docker Compose plugin in that same distribution and
verify them from the WSL shell.

Keep the repository in the WSL filesystem, such as
`~/headless-blender-character-builder`, instead of `/mnt/c/...`; bind-mounted
builds are generally faster and have simpler permissions there. Run all
project commands from the WSL shell. If you use Docker Desktop, start it before
running the doctor.

The output files can be opened from Windows through the distribution's
`\\wsl$` share or by running `explorer.exe .` from the repository directory.
Please include the Windows, WSL distribution, architecture, and Docker versions
in any bug report.

## Container path (recommended)

Clone the source and run the prerequisite check from the repository root:

```sh
git clone https://github.com/joseph-robert-f/headless-blender-character-builder.git
cd headless-blender-character-builder
./scripts/doctor
```

The doctor checks Git, GNU Make, Docker, daemon access, and the local platform.
It reports failures without installing or changing anything.

Build and independently verify the bundled request:

```sh
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
```

`OUTPUT_NAME` must be a lowercase, hyphen-separated name. It selects a direct
child of `build/`; it is not a general filesystem path. A complete run prints:

```text
BUILDER_BUILD: PASS
BUILDER_VERIFY: PASS
```

The first command builds the local image and may take several minutes. Docker
needs outbound access only while resolving the pinned image, Blender archive,
and Debian packages. The actual build and verification containers use
`--network none`, a non-root user, a read-only root, dropped capabilities, and
bounded resources.

The old names remain convenience aliases:

```sh
make demo
make verify-demo
```

They use the bundled request and `build/demo/`. Prefer `build` and `verify`
when documenting or automating named outputs.

## Inspect and open the artifacts

A successful `OUTPUT_NAME=facet-bot` run creates:

```text
build/facet-bot/
├── diagnostics/
│   ├── back.png
│   ├── front.png
│   └── side.png
├── manifest.json
├── model.blend
├── model.glb
├── model.stl
├── preview.png
└── qa.json
```

You can inspect the preview with the file browser or a platform command:

```sh
# macOS
open build/facet-bot/preview.png

# Linux desktop
xdg-open build/facet-bot/preview.png
```

Open `model.blend` with Blender 4.5.12 LTS when you need parity with the
verified build environment. `model.glb` is the display/interchange model.
Import `model.stl` into your slicer and select millimeters explicitly; STL
stores numeric coordinates but no unit metadata. Check `qa.json` before using
the model and retain `manifest.json` with the files if provenance matters.

Automated QA establishes structural properties; it does not choose printer,
material, nozzle, supports, orientation, or slicer settings, and it cannot
guarantee a safe or successful physical print.

## Build another request

Keep experiments in the ignored `build/` directory:

```sh
mkdir -p build/requests
cp examples/requests/facet-bot.json build/requests/my-character.json
# Edit the copy using docs/character-spec.md.
make validate REQUEST="$PWD/build/requests/my-character.json"
make build REQUEST="$PWD/build/requests/my-character.json" OUTPUT_NAME=my-character
make verify REQUEST="$PWD/build/requests/my-character.json" OUTPUT_NAME=my-character
```

`make validate` rebuilds the current checkout's builder (normally from Docker's
cache), then checks the bounded JSON contract without starting Blender or
writing output. See the [request examples](../examples/README.md),
[configuration reference](configuration.md), and
[character contract](character-spec.md) before editing fields.

## Preserve, clean up, and rerun

Builds never overwrite an output directory. Preserve a previous run before
reusing its name:

```sh
mv build/facet-bot build/facet-bot.previous
```

Alternatively, leave the old run in place and choose a new `OUTPUT_NAME`.
Artifacts are ordinary local files, so archive or remove only the exact build
directories you no longer need. Do not use broad recursive cleanup commands
against the repository or workspace.

The local builder image is cached so later builds are faster. To reclaim its
disk space after stopping the optional service, remove only the exact dev image:

```sh
docker image rm headless-blender-character-builder:dev
```

Docker can rebuild it from source on the next `make build`.

## Update a source checkout

First preserve wanted outputs and local edits, then update without creating an
implicit merge:

```sh
git status --short
git pull --ff-only
./scripts/doctor
```

Use a new output name for the first build after an update. `make build`
rebuilds the builder image from the current source. For the optional service,
rerun `make service-up`; its wrapper rebuilds the checkout-scoped builder and
service images from the current source before starting the stack.

Do not update a deployed release tree with `git pull`. Future VPS deployments
must install an exact published source release together with its matching
digest lock and follow the [forward-only upgrade procedure](deployment.md#upgrade-and-rollback).

## Docker without Make

The Makefile is the concise, reviewed interface. If GNU Make is unavailable,
the following commands expose the equivalent container contract. They assume
an ordinary non-root POSIX-shell user and a repository path that Docker Desktop
or Docker Engine can bind-mount.

Build and inspect the pinned `linux/amd64` image:

```sh
docker build \
  --file docker/builder.Dockerfile \
  --target builder \
  --tag headless-blender-character-builder:dev \
  --platform linux/amd64 \
  .

test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' \
  headless-blender-character-builder:dev)" = linux/amd64
mkdir -p build
test ! -e build/facet-bot-direct
builder_image_id="$(docker image inspect --format '{{.Id}}' \
  headless-blender-character-builder:dev)"
```

Build the model:

```sh
docker run \
  --rm \
  --init \
  --platform linux/amd64 \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 512 \
  --cpus 4 \
  --memory 4g \
  --user "$(id -u):$(id -g)" \
  --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 \
  --mount "type=bind,source=$PWD/examples/requests/facet-bot.json,target=/input/request.json,readonly" \
  --mount "type=bind,source=$PWD/build,target=/output" \
  --env HBCB_EXECUTION_MODE=container \
  --env HBCB_WORKER_IMAGE_REFERENCE=headless-blender-character-builder:dev \
  --env "HBCB_WORKER_IMAGE_ID=$builder_image_id" \
  headless-blender-character-builder:dev \
  build --request /input/request.json --output /output/facet-bot-direct
```

Then reopen and verify it in a new container with the output mount read-only:

```sh
docker run \
  --rm \
  --init \
  --platform linux/amd64 \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 512 \
  --cpus 4 \
  --memory 4g \
  --user "$(id -u):$(id -g)" \
  --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 \
  --mount "type=bind,source=$PWD/examples/requests/facet-bot.json,target=/input/request.json,readonly" \
  --mount "type=bind,source=$PWD/build,target=/output,readonly" \
  --env HBCB_EXECUTION_MODE=container \
  --env HBCB_WORKER_IMAGE_REFERENCE=headless-blender-character-builder:dev \
  --env "HBCB_WORKER_IMAGE_ID=$builder_image_id" \
  headless-blender-character-builder:dev \
  verify --request /input/request.json --output /output/facet-bot-direct
```

If your current user has numeric UID or GID `0`, use the Make targets instead;
they safely select the container's unprivileged fallback identity.

## Native Blender (best effort)

Native mode is useful while developing the generator, but it is not the
release-blocking path. Use exact Blender 4.5.12 LTS and Python 3.11 or newer;
other Blender versions can change rendering, import/export, or Python behavior.
No third-party Python package is required for a normal native builder run.

Set the Blender binary for your platform and run the native doctor. For a
standard macOS application install, select the supported interpreter first;
for example, after installing Python 3.11 when the system `python3` is older:

```sh
export PYTHON=python3.11
"$PYTHON" --version
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
  ./scripts/doctor --native
```

On Linux, replace that path with the absolute `blender` executable from the
official Blender 4.5.12 LTS archive. Then build and verify from the repository
root:

```sh
mkdir -p build
HBCB_BLENDER_BINARY=/absolute/path/to/blender \
  "$PYTHON" -m builder_cli build \
  --request "$PWD/examples/requests/facet-bot.json" \
  --output "$PWD/build/facet-bot-native"

HBCB_BLENDER_BINARY=/absolute/path/to/blender \
  "$PYTHON" -m builder_cli verify \
  --request "$PWD/examples/requests/facet-bot.json" \
  --output "$PWD/build/facet-bot-native"
```

The exported `PYTHON` selector also reaches the existing
`make demo-native BLENDER=/absolute/path/to/blender` and
`make verify-demo-native BLENDER=/absolute/path/to/blender` aliases; they use
`build/demo/`. Keep the same selector for the complete native session.

## Local asynchronous service

The local service is optional and requires a Docker daemon on this machine.
An SSH, TCP, or HTTP Docker context is not supported because the API and
artifact ports bind to the daemon host while the documented client connects to
this machine's loopback. If the doctor reports a remote context, switch to a
local context in Docker Desktop or with `docker context use <local-context>`;
also clear `DOCKER_HOST` or `DOCKER_CONTEXT` if you set either to select a
remote daemon.

Check `python3 --version` first. If it is older
than 3.11, select an installed interpreter once for this terminal session with
`export PYTHON=python3.11`. Then check the additional prerequisites, create
credentials once, validate the configuration, and start it:

```sh
./scripts/doctor --service
make init-env
make service-config
make service-up
make service-ps
```

`service-ps` should show `api`, `worker`, PostgreSQL, Redis, and MinIO running.
The one-shot `database-init` and `minio-init` rows should show `Exited (0)`;
that is successful initialization, not a crash. Follow [HTTP API v1](api.md),
then run `make service-down` when finished.

Use Python 3.11 or newer consistently. If `python3` is older, select an installed
interpreter explicitly, for example `PYTHON=python3.11 make service-up`; use the
same `PYTHON=python3.11` override for `service-config`, `service-ps`,
`service-logs`, and `service-smoke`. On macOS, install Python 3.11+ from
[python.org](https://www.python.org/downloads/macos/) if needed. On Linux,
install it through the distribution's supported packages or python.org. In
WSL2, install and invoke it inside the Linux distribution, not from Windows.

The default loopback ports are `127.0.0.1:8080` for the API and
`127.0.0.1:9000` for artifact downloads. If either is occupied, choose distinct
ports from 1 through 65535 before `make service-up`, and retain the same values
for every service command:

```sh
export HBCB_API_HOST_PORT=18080 HBCB_STORAGE_HOST_PORT=19000
make service-up
```

The `export` retains the selection for the remaining service and API-client
commands in this terminal. These variables change only the host port; the
supported bind address remains loopback. The steady stack's configured ceilings total about 7 GiB RAM and 7.5
CPUs; initialization can briefly total about 7.375 GiB and 8.25 CPUs. Begin with
at least 8 GiB allocated to Docker and 20 GB free disk. `make service-smoke` is a maintainer
integration gate, not a required startup step: its additional direct-builder
workload can add 4 GiB, so allocate at least 12 GiB to Docker. Release and CI
validation then run `make orphan-minio-check` separately. That destructive test
uses a newly generated, internal-only Compose project with fresh PostgreSQL and
MinIO volumes; it never targets the persistent local-service volumes and
verifies that its disposable containers, network, and volumes are removed.

`make init-env` records `HBCB_COMPOSE_PROJECT_NAME`, a safe checkout-specific
Compose identity. Moving a checkout together with its ignored `.env` preserves
its containers and named-volume identity. An older `.env` without this key keeps
the legacy `hbcb-local` identity so its existing volumes remain reachable.
Advanced callers may set the standard `COMPOSE_PROJECT_NAME`, but must use the
same safe value for every command that manages that stack; changing it selects
a different set of containers and volumes.

`make service-down` stops containers while preserving the PostgreSQL, Redis,
and MinIO development volumes. Preserve the ignored `.env` while those volumes
exist because its generated credentials must continue to match them. The
[API guide](api.md#copy-paste-local-client-journey) provides the request journey, and
[troubleshooting](troubleshooting.md) covers safe recovery and evidence to
include in a report.

Use `make service-ps` for status and `make service-logs` for the last 100 API and
worker log lines. These wrappers restore the checkout identity and required
provenance automatically; do not substitute raw `docker compose` commands.

There is no lightweight custom-request service client yet. For a first custom
request, copy and validate the example as described in [Build another
request](#build-another-request), start the stack, and then use that JSON file in
the [copy-paste API journey](api.md#copy-paste-local-client-journey).

The local stack is loopback-only and uses a MinIO compatibility fixture. It is
not the [VPS reference](deployment.md) and must not be exposed to the Internet.
