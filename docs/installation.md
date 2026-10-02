# Installation and first model

We recommend the Docker procedure. It makes a `linux/amd64` Blender image
from this repository, with specified dependency versions. Docker then uses
that image for the build. A one-shot build does not use host Blender, host
Python, Docker Compose, an AI key, or a provider account.

> **Availability:** This repository contains source files and container build
> definitions only. It has no published GitHub Release or container image.
> It has no project-published PyPI package or supported `pip install` procedure.
> Do not install a package with a name that looks the same from PyPI.
> You can clone `main` to examine the source. This does not install a signed,
> versioned release.

The first release (v0.1) is for one trusted user and the local one-shot Docker
procedure. A trusted user controls the computer and writes or examines the
JSON request before use. The JSON contract limits the request. The local
service is experimental. Public, multi-tenant, and VPS operation are outside
v0.1 support.

<a id="choose-a-path"></a>
## Select a procedure

| Path | Status | Requirements |
|---|---|---|
| [Docker with Make](#container-path-recommended) | Supported v0.1 procedure | Git, current Docker Engine/Desktop with BuildKit and `linux/amd64` support, GNU Make |
| [Docker without Make](#docker-without-make) | Equivalent manual procedure | Git, Docker, a POSIX shell, `id`, and `mkdir` |
| [Native Blender](#native-blender-best-effort) | Contributor procedure without a compatibility guarantee | Git, Python 3.11+, Blender 4.5.12 LTS |
| [Local asynchronous service](#local-asynchronous-service) | Experimental, local-only | One trusted operator, local Docker daemon/context, Docker Compose 2.24.4+, Python 3.11+, 8 GiB Docker memory, 20 GB free disk, and the container requirements |
| [VPS reference](deployment.md) | Design reference outside v0.1 support | Linux `amd64`, Python 3.11+, Compose 2.24.4+, and knowledge of operations and security |

The container limits are four CPUs, 4 GB RAM, 512 PIDs, and 2 GB of temporary
storage. For the first build, approximately four CPU cores, 8 GB of host RAM,
and 10 GB of free disk space are necessary. Apple Silicon uses `linux/amd64`
emulation, which is slower.

## Platform setup

### macOS without Homebrew

Homebrew is optional. You can install all necessary software from the vendors:

1. Use `xcode-select --install` in Terminal. Complete the Apple installation
   procedure. The Command Line Tools include Git and GNU Make.
2. Install and start [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/).
   Select the download for your Mac chip. Set a minimum of 4 GB of memory for
   Docker workloads.
3. Open a new Terminal window. Do a check of the tools:

   ```sh
   git --version
   make --version
   docker info
   ```

`make --version` must identify GNU Make. Success from `docker info` shows that
Docker Desktop operates. `docker --version` does a check of the client only.

The one-shot container procedure does not use host Python or Blender. For
native work, install Python 3.11 or newer from
[python.org](https://www.python.org/downloads/macos/). Install Blender 4.5.12
LTS from [blender.org](https://www.blender.org/download/lts/4-5/).
Homebrew is not necessary.

Docker Desktop includes the Compose plugin for the optional local service.
Install Python 3.11+ from python.org. Set a minimum of 8 GiB for Docker Desktop.
For `service-smoke`, set a minimum of 12 GiB. Before a service build, the
service doctor does checks of Python, Compose, and the Docker memory allocation.

### Linux

Install Git and GNU Make with the package manager for your distribution.
On Debian or Ubuntu, use these commands:

```sh
sudo apt-get update
sudo apt-get install -y git make
```

Install Docker Engine and its Buildx plugin. Use the
[official instructions for your distribution](https://docs.docker.com/engine/install/).
Then read the Docker
[Linux post-install guidance](https://docs.docker.com/engine/install/linux-postinstall/).
Select a documented rootless or Docker-group configuration that gives your
user account access to the daemon.

**WARNING:** Docker group membership gives root-level privileges. Examine
this security risk before you enable group membership.

Do these checks:

```sh
git --version
make --version
docker info
docker buildx version
```

Do not make the Docker socket world-writable to correct a daemon permission failure.

For the optional local service, install Python 3.11+ and the Docker Compose
plugin inside Linux. Obey the official Docker repository instructions for
`docker-compose-plugin`. Do not use the previous standalone `docker-compose` binary
for this procedure. Do checks with `python3 --version` and
`docker compose version`. Curl is optional. Only the manual API protocol
example uses it.

Native Linux `amd64` is the reference runtime. Linux `arm64` can emulate the
release image, but this configuration has no compatibility guarantee.
v0.1 does not specify an official native `arm64` Blender archive.

### Windows with WSL2 (experimental)

The Windows procedure is experimental. Windows test failures do not stop the
release. Use a WSL2 Linux distribution. Enable the Docker Desktop WSL
integration for that distribution, or install Docker Engine inside it.
Install Git and GNU Make in the Linux distribution, not only on Windows.

For the optional service, install Python 3.11+ and the Docker Compose plugin
in the same distribution. Do checks of them from the WSL shell.

Keep the repository in the WSL filesystem, for example
`~/headless-blender-character-builder`. Do not use `/mnt/c/...` for this procedure. Bind-mounted
builds usually operate faster there, and filesystem permissions are simpler.
Use the WSL shell for all project commands. If you use Docker Desktop, start
it before you use the doctor.

To open output files from Windows, use the distribution's `\\wsl$` share.
As an alternative, use `explorer.exe .` from the repository directory.
In a bug report, include the Windows, WSL distribution, architecture, and Docker versions.

## Container path (recommended)

Clone the source. Then do the prerequisite check from the repository root:

```sh
git clone https://github.com/joseph-robert-f/headless-blender-character-builder.git
cd headless-blender-character-builder
./scripts/doctor
```

The doctor does checks of Git, GNU Make, Docker, daemon access, and the local
platform. It reports failures. It does not install software or change the configuration.

Use the build and separate verification commands for the included request:

```sh
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
```

`OUTPUT_NAME` must be a lowercase name with hyphens between words. It selects
a direct child of `build/`. It is not a general filesystem path. A build and verification that pass give this output:

```text
BUILDER_BUILD: PASS
BUILDER_VERIFY: PASS
```

The first command makes the local image. This can take some minutes.
Docker uses outbound access only to get the specified image, Blender archive,
and Debian packages. The build and verification containers use these controls:

- `--network none`
- A non-root user
- A read-only root
- Dropped capabilities
- Resource limits.

These previous command names stay as aliases:

```sh
make demo
make verify-demo
```

The aliases use the included request and `build/demo/`. We recommend `build` and
`verify` in documentation and automation for named outputs.

<a id="inspect-and-open-the-artifacts"></a>
## Examine and open the artifacts

A `OUTPUT_NAME=facet-bot` build that passes makes these files:

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

Before you open a large artifact, print the size-limited summary of the
success manifest. The summary contains no paths:

```sh
make inspect OUTPUT_NAME=facet-bot
```

This read-only command validates canonical `manifest.json`. It reports the
version, dimensions, QA summary, artifact count and bytes, and provenance
hashes. It does not include artifact paths or image references. It does not
replace the fresh-process checks in `make verify`.

Examine the preview with the file browser or a platform command:

```sh
# macOS
open build/facet-bot/preview.png

# Linux desktop
xdg-open build/facet-bot/preview.png
```

To use the same Blender version as the verified build environment, open
`model.blend` with Blender 4.5.12 LTS. `model.glb` is the display/interchange
model. Import `model.stl` into your slicer. Select millimeters explicitly.
STL stores numeric coordinates but no unit metadata.

Before you use the model, examine `qa.json`. To keep the provenance data,
keep `manifest.json` with the files.

Automated QA does checks of structural properties. It does not select the
printer, material, nozzle, supports, orientation, or slicer settings.
It cannot give a guarantee of a safe physical print or print success.

<a id="build-another-request"></a>
## Build a different request

Keep experiments in the ignored `build/` directory:

```sh
mkdir -p build/requests
cp examples/requests/facet-bot.json build/requests/my-character.json
# Edit the copy using docs/character-spec.md.
make validate REQUEST="$PWD/build/requests/my-character.json"
make build REQUEST="$PWD/build/requests/my-character.json" OUTPUT_NAME=my-character
make verify REQUEST="$PWD/build/requests/my-character.json" OUTPUT_NAME=my-character
```

`make validate` makes the builder from the source checkout, usually with the
Docker cache. Then it does checks of the JSON contract. It does not start
Blender or write output. Before you change fields, read the
[request examples](../examples/README.md),
[configuration reference](configuration.md), and
[character contract](character-spec.md).

<a id="preserve-clean-up-and-rerun"></a>
## Keep outputs and do a build again

Builds do not overwrite an output directory. Before you use the same name
again, move the previous output:

```sh
mv build/facet-bot build/facet-bot.previous
```

As an alternative, keep the previous output at its path and select a new
`OUTPUT_NAME`. Artifacts are local files. Archive or remove only the specified
build directories that are no longer necessary. Do not use general recursive
cleanup commands on the repository or workspace.

Docker keeps the local builder image in its cache. This makes subsequent
builds faster. To get back the image disk space, first stop the optional
service. Then remove only the specified development image:

```sh
docker image rm headless-blender-character-builder:dev
```

Docker can make the image again from source at the next `make build` command.

## Update a source checkout

First, keep copies of necessary outputs and local changes. Then update the
source without an implicit merge:

```sh
git status --short
git pull --ff-only
./scripts/doctor
```

Use a new output name for the first build after an update. `make build` makes
the builder image from the updated source. For the optional service, use
`make service-up` again. Its wrapper makes the checkout-scoped builder and
service images from the updated source before it starts the stack.

Do not use `git pull` to update a deployed release tree. Future VPS deployments
must use a specified published source release and its related digest lock.
Use the [forward-only upgrade procedure](deployment.md#upgrade-and-rollback).

## Docker without Make

The Makefile is the recommended interface. If GNU Make is not available,
use the equivalent container commands that follow. These commands are for a
non-root POSIX-shell user. Docker Desktop or Docker Engine must have
bind-mount access to the repository path.

Make the `linux/amd64` image with its specified versions. Then examine the image:

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

Make the model:

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

Open the model again in a new container for verification. Use a read-only
output mount:

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

If your user has numeric UID or GID `0`, use the Make targets as an alternative.
They select the container's alternative identity without root privileges.

## Native Blender (best effort)

Native mode is for generator development. Native test failures do not stop
the release. Use Blender 4.5.12 LTS and Python 3.11 or newer. Other Blender
versions can change rendering, import/export, or Python behavior. A usual
native builder operation does not use third-party Python packages.

Set the Blender binary for your platform. Then use the native doctor.
For a standard macOS application installation, first select a compatible
interpreter. For example, use this procedure after Python 3.11 installation
if the system `python3` is older:

```sh
export PYTHON=python3.11
"$PYTHON" --version
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender \
  ./scripts/doctor --native
```

On Linux, use the absolute `blender` executable path from the official
Blender 4.5.12 LTS archive. Then use the build and verification commands from
the repository root:

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

The exported `PYTHON` selector also applies to these aliases:

- `make demo-native BLENDER=/absolute/path/to/blender`
- `make verify-demo-native BLENDER=/absolute/path/to/blender`.

They use `build/demo/`. Keep the same selector for the full native session.

## Local asynchronous service

> **Scope:** This experimental service is for one trusted local operator.
> Keep the service on loopback. Send only requests that you wrote or
> examined. Do not use it for Internet-facing, multi-user, multi-tenant,
> or hostile-input workloads.

The optional local service uses a Docker daemon on this computer. It cannot
use an SSH, TCP, or HTTP Docker context. The API and artifact ports bind to
the daemon host. But the documented client connects to this computer's loopback.

If the doctor reports a remote context, select a local context in Docker Desktop.
As an alternative, use `docker context use <local-context>`.
If `DOCKER_HOST` or `DOCKER_CONTEXT` selects a remote daemon, clear that variable.

First, do a check with `python3 --version`. If the version is older than 3.11,
select an installed interpreter with `export PYTHON=python3.11`.
This selection applies to this terminal session.

Then do these prerequisite checks. Make the credentials one time,
validate the configuration, and start the service:

```sh
./scripts/doctor --service
make init-env
make service-config
make service-up
make service-ps
```

`service-ps` must show `api`, `worker`, PostgreSQL, Redis, and MinIO in operation.
The one-shot `database-init` and `minio-init` rows must show `Exited (0)`.
This output identifies initialization success, not a crash. Send a
request with the lightweight client. When you complete the work, use `make service-down`:

```sh
make service-client REQUEST="$PWD/examples/requests/facet-bot.json"
make service-down
```

Always use Python 3.11 or newer. If `python3` is older, explicitly select an
installed interpreter. For example, use `PYTHON=python3.11 make service-up`.
Use the same `PYTHON=python3.11` override for `service-config`, `service-ps`,
`service-logs`, and `service-smoke`.

On macOS, install Python 3.11+ from
[python.org](https://www.python.org/downloads/macos/) if necessary.
On Linux, use the distribution's supported packages or python.org.
In WSL2, install and use Python inside the Linux distribution, not from Windows.

The default loopback ports are `127.0.0.1:8080` for the API and
`127.0.0.1:9000` for artifact downloads. If a port is in use, select different
ports from 1 through 65535 before `make service-up`. Keep the same values for
each service command:

```sh
export HBCB_API_HOST_PORT=18080 HBCB_STORAGE_HOST_PORT=19000
make service-up
```

`export` keeps this selection for subsequent service and API-client commands
in the terminal. These variables change only the host port. The supported
bind address stays loopback.

The configured limits for steady stack operation total approximately 7 GiB
RAM and 7.5 CPUs. During initialization, the total can increase to
approximately 7.375 GiB and 8.25 CPUs. Start with a minimum of 8 GiB for
Docker and 20 GB of free disk space.

`make service-smoke` is a maintainer integration test. It is not necessary
for startup. Its separate direct-builder workload can add 4 GiB.
For this test, set a minimum of 12 GiB for Docker.

Release and CI validation then use `make orphan-minio-check` as a separate operation.
This destructive test uses a new internal-only Compose project. It uses new
PostgreSQL and MinIO volumes. It does not use the persistent local-service
volumes. It makes sure that it removes its temporary containers, network,
and volumes.

`make init-env` records `HBCB_COMPOSE_PROJECT_NAME`, a safe checkout-specific
Compose identity. If you move the checkout with its ignored `.env`, the
container and named-volume identity stay the same. An older `.env` without
this key keeps the previous `hbcb-local` identity. Thus, its volumes stay
available.

Advanced callers can set the standard `COMPOSE_PROJECT_NAME`. They must use
the same safe value for each command that controls the stack. A different
value selects a different set of containers and volumes.

`make service-down` stops containers but keeps the PostgreSQL, Redis, and
MinIO development volumes. Keep the ignored `.env` while you keep those volumes.
Its generated credentials must continue to agree with the volume credentials.
Read the [API guide](api.md#lightweight-local-client) for the client and protocol.
Read [troubleshooting](troubleshooting.md) for safe recovery and report evidence.

To remove only the local image tags for the selected service project,
first stop the service. Examine the list, then use the removal helper:

```sh
make service-down
make service-images
make service-image-cleanup
```

The helper removes only the six tags that `make service-images` prints.
These are the builder, derived-PostgreSQL, API, worker, MinIO-fixture, and test
tags. It keeps `.env` and each named volume. It also keeps the shared
Docker/BuildKit cache. Docker cannot show that each cache record belongs to
one checkout.

Do not use these global cleanup commands as alternatives:

- `docker system prune`
- `docker builder prune`
- `docker image prune`
- `docker volume prune`.

An previous `.env` without `HBCB_COMPOSE_PROJECT_NAME` selects shared `hbcb-local`
tags. The automatic removal helper rejects that identity. Examine the list.
Before you manually remove specified tags, stop each checkout with that identity.

Use `make service-ps` for status. Use `make service-logs` for the last 100 API
and worker log lines. These wrappers automatically restore the checkout
identity and necessary provenance. Do not use raw `docker compose` commands
as alternatives.

For a different request, copy and validate the example in
[Build a different request](#build-another-request). Start the stack. Give that
JSON path as `REQUEST` to `make service-client`.

The local stack uses loopback only and a MinIO compatibility fixture.
Do not give the Internet access to this stack. It is separate from the
[VPS reference](deployment.md). The VPS material is a design and validation
reference. VPS deployment is outside v0.1 support.
