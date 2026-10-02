# Architecture

## Release boundary

Headless Blender Character Builder has two execution modes. The two modes use the
same trusted Blender build contract.

> **v0.1 support boundary:** v0.1 supports Lane A for one trusted local user.
> The loopback part of Lane B is experimental. Public services, VPS operation,
> and multi-tenant operation are outside v0.1 support.

> The repository contains code and container definitions for the two modes.
> No container image, GitHub Release, or hosted service is published.
> The VPS documents describe a future design. They do not give a supported
> v0.1 procedure for public deployment.

```text
Lane A: keyless one-shot builder

BuildRequest JSON -> bounded CLI -> fresh headless Blender -> local artifact tree
                         |                  |
                         |                  +-> compile, render, export, QA
                         +-> strict schemas      and immutable manifest

Lane B: durable local service / future self-hosted deployment

client -> authenticated API -> PostgreSQL + Redis -> worker supervisor
                 |                    |                    |
                 |                    | build ID only      +-> fresh builder child
                 |                    +-> durable truth         with scrubbed env
                 +-> version-pinned signed URLs                       |
                                                                    versioned S3
```

Use Lane A for the first build. It operates without FastAPI, PostgreSQL,
Redis, object storage, Compose, OpenAI, or MCP. Lane B uses persistent service
state, the same builder CLI, and the same artifact contract.
The local service records the measured builder image identity.
The future VPS design specifies release images with fixed digests.
A service failure cannot change or stop the one-shot builder.

## Trusted inputs and outputs

The v0.1 public model input is JSON that passes schema validation.
The usual builder does not accept Python, shell fragments, Blender flags,
add-ons, remote URLs, host paths, archives, uploaded `.blend` files, or reference images.
The generator registry connects each version identifier to reviewed code,
a specification with limits, supported outputs, and a QA policy.

One successful build publishes only these files:

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

The builder writes `manifest.json` last. Before success, a second new Blender
process opens the `.blend` file and imports GLB and STL.
This process calculates the hashes and bounds again and does a check of the printable shell.
Local publication uses a private staging directory and an atomic rename.
Service publication uses specified immutable object versions and one database transaction.

## Components

| Component | Responsibility | Excluded operations |
|---|---|---|
| `builder_cli` | Validate CLI arguments, request bytes, output ownership, and exit contracts | Interpret prompts or contact services |
| `shared` | Canonical JSON, schemas, manifest/QA records, source revision | Import `bpy` or do I/O outside explicit adapters |
| `blender` | Compile reviewed primitives, render, export, and examine geometry | Fetch URLs or execute request-supplied code |
| API | Authenticate, validate, submit, read status, cancel, and authorize downloads | Run Blender or keep worker credentials |
| PostgreSQL | Own build state, attempts, leases, idempotency, artifacts, outbox, and retention work | Deliver job payloads or serve artifact bytes |
| Redis | Deliver bounded build IDs, recover stale claims, remove settled main entries, and keep a dead-letter tail in its limit | Act as durable build truth |
| Worker supervisor | Fence leases and launch one new builder process for each attempt | Accept arbitrary commands or publish partial output |
| Versioned S3 | Store immutable attempt-scoped artifacts and specified versions | Decide build success |
| Maintenance process | Preview/apply retention, reconcile bounded previous orphan-version inventories, delete durably queued specified versions, make backups, restore, and reconstruct Redis | Administer the database or broadly delete a bucket |

## Security and network boundaries

The execution modes use different network controls:

- **One-shot build and verify:** Each container uses `--network none`.
  It uses a non-root user, a read-only root filesystem, no Linux capabilities,
  and `no-new-privileges`. CPU, RAM, PIDs, and scratch space have limits.
- **Local service:** The API binds only to host loopback.
  PostgreSQL and Redis have no published ports.
  The worker connects only to the `internal: true` service network.
  This network gives access to the database, queue, and local object storage.
- **VPS reference:** Only Caddy connects to the public network.
  The worker connects to different internal database and queue networks.
  The operator supplies an `Internal=true` storage network.
  The worker has no public edge network or general public egress route.

In service mode, the worker starts Blender as a new subprocess.
It does not start a nested container. The subprocess uses the supervisor
container's network namespace. This namespace is internal-only, not `--network none`.

The launcher removes credentials from the subprocess environment.
The child receives no API token, database password, Redis credential,
object-storage secret, provider key, or Docker credential.
The launcher also closes nonstandard inherited descriptors.

Before the Linux supervisor creates credential clients, it sets the non-dumpable
kernel control and disables core dumps. It does a check of these controls and
sets them again before each child starts.
The container has no `CAP_SYS_PTRACE` capability.
Thus, a Blender descendant with the same UID cannot examine the supervisor's
procfs environment or memory. The worker container has no Docker socket,
host home mount, device, or SSH agent.

All modes disable automatic script execution. These controls give more protection during trusted generator execution. Blender is not a sandbox for hostile scripts or files.
The VPS design specifies different public signed-download and internal object endpoints.
The operator must maintain a versioned S3-compatible service.
The local MinIO fixture is not the VPS storage service.

See [threat-model.md](threat-model.md) and [deployment.md](deployment.md)
for the controls and operator conditions.

## Persistence and recovery

PostgreSQL contains the authoritative state. The service can create the Redis
queue again from queued database rows.
Artifact records connect keys, sizes, hashes, and specified storage version IDs.

Before a backup, stop API and worker writes. Do a check of the inventory in
its limits. Restore only into an empty target.
Map restored object version IDs before you create the Redis queue again.

Upgrades move only to a later version and use a persistent handoff tied to the target.
After migrations start, retry the same target or restore a verified backup into an empty target.
Do not downgrade the existing target.

## Extension seams

Add new generator versions to the existing registry.
For each version, add a schema, implementation limits, structural evidence,
a QA policy, and tests in new processes.
Add two different examples where applicable.

Keep storage, queue, and state implementations behind the service interfaces.
Optional prompt planning and MCP are post-v0.1 adapters for the versioned JSON/API contract.
They are not alternative Blender execution engines.

## Repository map

| Path | Contents |
|---|---|
| `schemas/`, `shared/` | Versioned public contracts and standard-Python implementations |
| `blender/`, `builder_cli/` | Trusted generator, exporters, QA, runner, and one-shot CLI |
| `service/` | API, worker, persistence, queue, storage, and maintenance code |
| `compose.yaml`, `compose/` | Local asynchronous stack and scoped local policies |
| `deploy/vps/` | Future VPS design reference: Compose overlay, Caddy, and operator examples |
| `scripts/` | Trusted launchers, smoke/recovery gates, and release tooling |
| `tests/` | Contract, unit, real-Blender, container, service, deployment, and release gates |
| `docs/` | User/operator guides, scope, evidence, and decision records |
| `docs/assets/` | Only the optimized, independently licensed static documentation preview |

Maintenance orchestration is in `hbcb_service.maintenance`. Database
operations are in `maintenance_postgres`. MinIO and backup-file operations are
in `maintenance_storage`. Shared records and checks are in `maintenance_common`.
Existing imports from `hbcb_service.maintenance` continue to work.

The normative contracts and historical decisions are in [character-spec.md](character-spec.md),
[api.md](api.md), and [decisions.md](decisions.md).
