# Compatibility

## Release reference

| Surface | v0.1 status |
|---|---|
| Linux `amd64` builder and service images | Release-blocking and supported by the local release gates |
| Docker Engine with Compose v2 | Required for the documented container and service paths |
| Native Linux `amd64` | Reference runtime and intended hosted platform |
| Docker Desktop on Apple Silicon | Tested through `linux/amd64` emulation; slower, but supported for evaluation |
| Native macOS with Blender 4.5.12 LTS | Contributor fallback for builder/artifact tests, not a service deployment target |
| Linux `arm64` | Best effort; no official checksum-pinned Blender archive is accepted for this release |
| Windows / WSL2 | Experimental and non-release-blocking |
| GPU / Cycles orchestration | Not included; release paths use CPU-compatible headless rendering |

The builder pins Blender 4.5.12 LTS and an immutable Debian Bookworm base. The
public image is intentionally single-platform until an official Blender Linux
`arm64` distribution can be checksum-pinned and subjected to the same artifact
and runtime-policy gates.

## Resource envelope

The quickstart assumes about four CPU cores, 8 GB RAM, and 10 GB free disk.
Runtime builder limits are four CPUs, 4 GB RAM, 512 PIDs, and 2 GB temporary
scratch. Docker image builds require network access for pinned upstream
downloads; actual model generation and verification run with networking
disabled.

## Stable versions

Application version, request schema version, generator version, QA schema, and
manifest schema are separate contracts. A compatible application update must
preserve the meaning of existing v1 request documents. Breaking request or
artifact changes require a new schema version and an explicit migration note.
