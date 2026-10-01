# Compatibility

This matrix describes the v0.1.0-rc.1 source candidate.
A release-blocking test is part of the repository's local release gates.
This term does not mean that a release, image, hosted service, SLA,
or production support is available.

The [standalone review preview](review-preview.md) has a different native-platform test scope.
Its read-only review results do not show Blender generation support on those platforms.

## First-release support boundary

| Use | v0.1 status |
|---|---|
| One trusted user builds their own model locally with the one-shot Docker builder | Supported |
| One trusted operator evaluates the Compose service on loopback | Experimental and local-only |
| Internet-facing, public, hostile-input, or multi-tenant service | Out of scope |
| VPS deployment | Design and validation reference only. out of scope |

A trusted user has control of the machine and creates or reviews each JSON request.
This definition excludes requests from unknown users.

## Toolchain

| Surface | Version or capability | v0.1 status |
|---|---|---|
| Blender in the builder image | Specified Blender 4.5.12 LTS Linux x64 archive | Pinned and release-blocking |
| Builder/service image platform | `linux/amd64` | Release reference |
| Docker Engine or Docker Desktop | A current maintained release with BuildKit and `linux/amd64` support | Necessary for container builds. no minimum patch release is specified. The local asynchronous service must use a local daemon/context, not an SSH, TCP, or HTTP endpoint. |
| GNU Make | A maintained version that can run the project Makefile | Necessary for the recommended interface. [direct Docker commands](installation.md#docker-without-make) are available |
| Docker Compose | 2.24.4 or newer | Necessary for the current service doctor and the VPS/G8/full-release path. the VPS overlay uses Compose `!reset` and `!override` tags |
| Python | 3.11 or newer | Necessary for native use, service smoke/recovery, VPS operations, and release tooling. not necessary for one-shot Docker builds |
| curl | Supports `--fail-with-body` and `--noproxy` | Optional. used only by the manual API protocol example. The stdlib lightweight client does not use it, and the service doctor reports curl limitations as notes. |
| GPU | None | Release paths use CPU-compatible headless rendering. Cycles/GPU orchestration is not included |

Use the applicable command:

- For the one-shot Docker mode, run `./scripts/doctor`.
- For the local service toolchain, run `./scripts/doctor --service`.
- For native use, run `BLENDER=/absolute/path/to/blender ./scripts/doctor --native`.

These checks are read-only. They do not install software.

## Platforms

| Host path | Status | Notes |
|---|---|---|
| Linux `amd64` + Docker | Release reference | The one-shot builder targets this platform. Service, deployment, and recovery gates validate experimental or future paths. they do not expand v0.1 support. |
| Docker Desktop on Apple Silicon | Evaluation path | Runs the `linux/amd64` image through emulation and is slower than native `amd64`. |
| Docker Desktop on Intel macOS | Evaluation path | Runs the Linux image in Docker Desktop. it is not a native macOS service deployment. |
| Native Linux `amd64` + Blender 4.5.12 | Best-effort contributor path | Useful for generator development. container output is the release reference. |
| Native macOS + Blender 4.5.12 | Best-effort contributor path | Use Python 3.11+ and the specified Blender binary. not a hosted-service target. |
| Linux `arm64` | Best effort | Docker can emulate `linux/amd64`. no official checksum-pinned native Blender archive is accepted for v0.1. |
| Windows with WSL2 | Experimental | Use a Linux distribution and Docker Desktop WSL integration or Docker Engine in WSL. This path is non-release-blocking. |
| Native Windows without WSL2 | Not documented | Path, shell, permissions, and runtime-policy contracts have not been validated. |

See [Installation](installation.md) for platform-specific setup, with
macOS without Homebrew and the experimental WSL2 workflow.

## Resource envelope

For the one-shot quickstart, use approximately four CPU cores, 8 GB of host RAM,
and 10 GB of free disk space.
Each builder container has limits of four CPUs, 4 GB RAM, 512 PIDs,
and 2 GB of temporary scratch space.
The first image build downloads upstream files with fixed checksums.
Model generation and verification have no network access.

The asynchronous stack uses more time, memory, and disk space for PostgreSQL,
Redis, local object storage, service images, and one worker.
Its configured limits total approximately 7 GiB RAM and 7.5 CPUs during usual operation.
During initialization, the total can briefly be 7.375 GiB and 8.25 CPUs.
For basic local-service evaluation, use a minimum of 8 GiB Docker memory and 20 GB free disk space.

The optional `make service-smoke` gate starts another direct builder with a 4 GiB limit.
For this gate, use a minimum of 12 GiB Docker memory and sufficient disk space for the evidence.

The independent `make orphan-minio-check` release/CI test deletes specified orphan versions
in an internal-only Compose project.
It uses new temporary PostgreSQL and MinIO volumes.
When the gate exits, it removes these project resources and confirms their removal.

The full release gate also builds test and recovery targets and keeps more evidence.
The future VPS design uses a baseline of 8 vCPU and 32 GiB RAM.
This baseline includes one concurrency-one worker and host overhead.
It is a design input, not a capacity guarantee or supported deployment configuration.

## Native-mode boundary

Native mode must use Blender 4.5.12 LTS without a version change and Python 3.11+.
A newer Blender version can open the `.blend` file, but it is outside
the verified v0.1 build contract.
It can change renders, import/export behavior, or Python APIs.
Use native results for development comparisons.
The pinned Linux container is the reference for release evidence.

## Versioned contracts

Application version, request schema version, generator version, QA schema,
and manifest schema are different contracts.
A compatible application update must keep the meaning of existing v1 request documents.
If a request or artifact change is not compatible, use a new schema version and an explicit migration note.
