# Architecture

## Release boundary

Headless Blender Character Builder has two public execution lanes around one
trusted Blender build contract.

```text
Lane A: keyless one-shot builder

BuildRequest JSON -> bounded CLI -> fresh headless Blender -> local artifact tree
                         |                  |
                         |                  +-> compile, render, export, QA
                         +-> strict schemas      and immutable manifest

Lane B: durable self-hosted service

client -> authenticated API -> PostgreSQL + Redis -> worker supervisor
                 |                    |                    |
                 |                    | build ID only      +-> fresh builder child
                 |                    +-> durable truth         with scrubbed env
                 +-> version-pinned signed URLs                       |
                                                                    versioned S3
```

Lane A is the primary quickstart and remains independent of FastAPI,
PostgreSQL, Redis, object storage, Compose, OpenAI, and MCP. Lane B adds durable
coordination but invokes the same immutable builder image and artifact
contract. A service failure cannot change or disable the one-shot builder.

## Trusted inputs and outputs

The only public modeling input is schema-validated JSON. The normal builder
does not accept Python, shell fragments, Blender flags, add-ons, remote URLs,
host paths, archives, uploaded `.blend` files, or reference images. The
generator registry maps a versioned identifier to reviewed code, a bounded
specification, supported outputs, and QA policy.

One successful build publishes exactly:

```text
model.blend
model.glb
model.stl
preview.png
diagnostics/front.png
diagnostics/side.png
diagnostics/back.png
qa.json
manifest.json
```

`manifest.json` is written last. Before success, a second fresh Blender process
reopens the `.blend`, imports GLB and STL, recomputes hashes and bounds, and
checks the printable shell. Publication uses private staging plus an atomic
rename locally, or exact immutable object versions plus one database
transaction in service mode.

## Components

| Component | Responsibility | Deliberately cannot do |
|---|---|---|
| `builder_cli` | Validate CLI arguments, request bytes, output ownership, and exit contracts | Interpret prompts or contact services |
| `shared` | Canonical JSON, schemas, manifest/QA records, source revision | Import `bpy` or perform I/O outside explicit adapters |
| `blender` | Compile reviewed primitives, render, export, and inspect real geometry | Fetch URLs or execute request-supplied code |
| API | Authenticate, validate, submit, read status, cancel, and authorize downloads | Run Blender or hold worker credentials |
| PostgreSQL | Own build state, attempts, leases, idempotency, artifacts, outbox, and retention work | Deliver job payloads or serve artifact bytes |
| Redis | Deliver bounded build IDs and recover stale claims | Act as durable build truth |
| Worker supervisor | Fence leases and launch one fresh builder process per attempt | Accept arbitrary commands or publish partial output |
| Versioned S3 | Store immutable attempt-scoped artifacts and exact versions | Decide build success |
| Maintenance process | Preview/apply retention, backup, restore, and reconstruct Redis | Administer the database or broadly delete a bucket |

## Security and network boundaries

The Blender child runs non-root with a read-only root filesystem, dropped Linux
capabilities, `no-new-privileges`, bounded CPU/RAM/PIDs/scratch, disabled
auto-execution, and no network. It receives no API token, database password,
Redis credential, object-storage secret, provider key, Docker socket, or host
home mount. These controls are defense in depth around trusted generator code;
Blender is not treated as a sandbox for hostile scripts or files.

The local stack binds API and object downloads to loopback. PostgreSQL and
Redis are not published. The worker has only the internal network. The VPS
package terminates HTTPS with Caddy, keeps storage operations private, requires
distinct public signed-download and internal object endpoints, and uses an
operator-maintained versioned S3-compatible service rather than the bundled
local MinIO compatibility fixture.

See [threat-model.md](threat-model.md) and [deployment.md](deployment.md) for
the detailed controls and operator invariants.

## Persistence and recovery

PostgreSQL is authoritative. Redis can be reconstructed from queued database
rows. Artifact records bind keys, sizes, hashes, and exact storage version IDs.
Backups quiesce API and worker writes, verify a bounded inventory, and restore
only into an empty target. Restored object versions are remapped before Redis
reconstruction. Forward-only upgrades use a persistent target-bound handoff;
after migrations begin, recovery is an exact-target retry or a verified
empty-target restore, never an in-place downgrade.

## Extension seams

New generator versions belong behind the existing registry and must add a
schema, bounded implementation, structural evidence, QA policy, two materially
different examples where appropriate, and fresh-process tests. Storage, queue,
and state implementations remain behind service interfaces. Optional prompt
planning and MCP are post-v0.1 adapters over the public JSON/API contract—not
alternate Blender execution engines.

## Repository map

| Path | Contents |
|---|---|
| `schemas/`, `shared/` | Versioned public contracts and normal-Python implementations |
| `blender/`, `builder_cli/` | Trusted generator, exporters, QA, runner, and one-shot CLI |
| `service/` | API, worker, persistence, queue, storage, and maintenance code |
| `compose.yaml`, `compose/` | Local asynchronous stack and scoped local policies |
| `deploy/vps/` | Production-oriented Compose overlay, Caddy, and operator examples |
| `scripts/` | Trusted launchers, smoke/recovery gates, and release tooling |
| `tests/` | Contract, unit, real-Blender, container, service, deployment, and release gates |
| `docs/assets/` | Only the optimized, separately licensed static documentation preview |

The binding contracts and historical decisions are in [character-spec.md](character-spec.md),
[api.md](api.md), and [decisions.md](decisions.md).
