# Compatibility

This matrix describes the v0.1.0-rc.1 source candidate. “Release-blocking”
means the path is exercised by the repository's local release gates; it does
not imply that a release, image, hosted service, SLA, or production support
offering has been published.

## Toolchain

| Surface | Version or capability | v0.1 status |
|---|---|---|
| Blender in the builder image | Exact Blender 4.5.12 LTS Linux x64 archive | Pinned and release-blocking |
| Builder/service image platform | `linux/amd64` | Release reference |
| Docker Engine or Docker Desktop | A current maintained release with BuildKit and `linux/amd64` support | Required for container builds; no minimum patch release is asserted |
| GNU Make | Any maintained version that can run the project Makefile | Required for the recommended interface; [direct Docker commands](installation.md#docker-without-make) are available |
| Docker Compose | 2.24.4 or newer | Required by the current service doctor and the VPS/G8/full-release path; the VPS overlay uses Compose `!reset` and `!override` tags |
| Python | 3.11 or newer | Required for native use, service smoke/recovery, and release tooling; not required for one-shot Docker builds |
| GPU | None | Release paths use CPU-compatible headless rendering; Cycles/GPU orchestration is not included |

Run `./scripts/doctor` for the one-shot Docker path,
`./scripts/doctor --service` for the local service toolchain, or
`BLENDER=/absolute/path/to/blender ./scripts/doctor --native` for native use.
The checks are read-only and do not install software.

## Platforms

| Host path | Status | Notes |
|---|---|---|
| Linux `amd64` + Docker | Release reference | Builder, service, deployment, recovery, and release gates target this platform. |
| Docker Desktop on Apple Silicon | Evaluation path | Runs the `linux/amd64` image through emulation and is slower than native `amd64`. |
| Docker Desktop on Intel macOS | Evaluation path | Runs the Linux image in Docker Desktop; it is not a native macOS service deployment. |
| Native Linux `amd64` + Blender 4.5.12 | Best-effort contributor path | Useful for generator development; container output remains the release reference. |
| Native macOS + Blender 4.5.12 | Best-effort contributor path | Requires Python 3.11+ and the exact Blender binary; not a hosted-service target. |
| Linux `arm64` | Best effort | Docker may emulate `linux/amd64`; no official checksum-pinned native Blender archive is accepted for v0.1. |
| Windows with WSL2 | Experimental | Use a Linux distribution and Docker Desktop WSL integration or Docker Engine inside WSL. This path is non-release-blocking. |
| Native Windows without WSL2 | Not documented | Path, shell, permissions, and runtime-policy contracts have not been validated. |

See [Installation](installation.md) for platform-specific setup, including
macOS without Homebrew and the experimental WSL2 workflow.

## Resource envelope

The one-shot quickstart assumes about four CPU cores, 8 GB of host RAM, and
10 GB of free disk. Each builder container is limited to four CPUs, 4 GB RAM,
512 PIDs, and 2 GB of temporary scratch. The first image build needs outbound
access for checksum-pinned upstream downloads; actual model generation and
verification run with networking disabled.

The asynchronous stack and full release gate need additional time, memory, and
disk for PostgreSQL, Redis, local object storage, service/test images, recovery
targets, and retained evidence. The VPS planning baseline is 8 vCPU and 32 GiB
RAM for one concurrency-one worker plus host overhead; it is an operational
starting point, not a sizing guarantee.

## Native-mode boundary

Native mode must use exact Blender 4.5.12 LTS and Python 3.11+. A newer Blender
may open the `.blend`, but it is outside the verified v0.1 build contract and
can change renders, import/export behavior, or Python APIs. Native results are
useful for development comparisons; the pinned Linux container remains the
reference for release evidence.

## Versioned contracts

Application version, request schema version, generator version, QA schema, and
manifest schema are separate contracts. A compatible application update must
preserve the meaning of existing v1 request documents. Breaking request or
artifact changes require a new schema version and an explicit migration note.
