# Headless Blender Character Builder

An open-source, self-hostable pipeline for turning a bounded JSON character request into real Blender geometry, portable 3D exports, diagnostic renders, and machine-readable QA.

> **Status: G0–G7 passed; the keyless builder and local asynchronous Compose service are implemented.** The deterministic Blender/container path, authenticated API, durable PostgreSQL state, concurrency-one worker, Redis recovery, versioned artifact storage, scoped local identities, and end-to-end service smoke are tested. The VPS package and release automation remain pending. This is not production-ready yet.

The planned public contract is deliberately narrow: original geometric, low-poly, or chibi characters compiled from reviewed Blender primitives—not unrestricted text-to-3D, customer-authored Python, exact likenesses, protected-character replication, or guaranteed physical prints.

## Start here

- [PLAN.md](PLAN.md) is the authoritative product scope and implementation sequence.
- [TEST_PLAN.md](TEST_PLAN.md) explains how an owner or reviewer will prove each feature and records what input is still needed.
- [docs/character-spec.md](docs/character-spec.md) documents the implemented bounded JSON contracts and test command.
- [docs/api.md](docs/api.md) documents the implemented and runnable HTTP contract.
- [SECURITY.md](SECURITY.md) describes the current security status and reporting path.
- [CONTRIBUTING.md](CONTRIBUTING.md) explains how to propose changes safely.

## Keyless container quickstart

Bring Git, Docker Engine/Desktop, GNU Make, about 10 GB of free disk, and a machine with roughly 4 CPU cores and 8 GB RAM. No Compose stack, `.env`, third-party account, API key, or host Blender installation is required.

```sh
make demo
make verify-demo
```

The first image build downloads checksum-pinned Blender and Debian packages. The actual model build then runs with networking disabled and publishes exactly nine files under `build/demo/`; `make verify-demo` reopens the saved `.blend` and imports GLB/STL in a fresh Blender process. The output directory must not already exist, so move an earlier `build/demo/` aside before rebuilding. Docker Desktop on Apple Silicon runs the release `linux/amd64` image through emulation and will be slower than native Linux.

Developers who already have Blender 4.5.12 LTS can exercise the same contract without Docker:

```sh
make demo-native BLENDER=/absolute/path/to/blender
make verify-demo-native BLENDER=/absolute/path/to/blender
```

## Local asynchronous service

Bring Docker Compose v2 in addition to the keyless quickstart prerequisites. The service starts PostgreSQL, Redis, a local S3-compatible fixture, the API, and one Blender worker. It needs no OpenAI key, provider account, registry login for a source build, or other third-party credential.

```sh
make init-env
make service-up
make service-smoke
make service-down
```

`make init-env` creates an ignored mode-`0600` `.env` once and refuses to overwrite it. Storage access-key IDs are fixed role names while their secrets remain independently random. `make service-up` builds the service images, applies forward-only migrations, converges scoped database/storage identities (including reserved pre-release identity names), and binds the API and object downloads to host loopback only. `make service-smoke` exercises authentication, asynchronous submission, polling, idempotency, cancellation, API restart, real Blender artifacts, fresh verification, Redis stale-claim recovery, and negative IAM permissions. Its final line names the ignored evidence directory. `make service-down` stops containers while preserving the three durable volumes.

The first service start source-builds the checksum-pinned final MinIO Community security release and can take several minutes. Later starts reuse it only when its OCI version/revision labels, exact Dockerfile Git-blob recipe label, and a networkless read-only live binary check all match. Set `HBCB_REBUILD_MINIO=1` for an intentional rebuild. This MinIO image is a zero-account local compatibility fixture, not a production storage recommendation; G8 uses a supported managed or operator-maintained S3 service.

The API listens at `http://127.0.0.1:8080`; artifact URLs use `http://localhost:9000`. See [docs/api.md](docs/api.md) for equivalent HTTP calls and response contracts. OpenAI planning and MCP support remain optional post-v0.1 adapters and will never be required by the deterministic builder.

## Repository state

The repository contains four Draft 2020-12 schemas, pure-standard-library production validation/canonicalization, two original example requests, hostile rejection fixtures, and schema/policy tests. Its `geometric-character@1.0.0` registry entry compiles requests into separate material-bearing display meshes and one closed, connected manufacturing-oriented `PRINT` shell using real procedural Blender geometry. The trusted launcher publishes exactly the required nine-file tree through a private staging directory and atomic rename, writes the success manifest last, and launches a second isolated Blender process to reload `.blend` and re-import GLB/STL.

The G4 gate exported a clean tree from the Git index, built the pinned `linux/amd64` production image without credentials, ran and verified `facet-bot` twice, and matched its structural evidence to the native fallback. The model container ran non-root with no network, a read-only root, all capabilities dropped, no-new-privileges, and bounded PID/CPU/RAM/scratch. The image carries immutable source/Blender hashes, upstream notices, and an SPDX 2.3 SBOM. The more complex `moss-hopper` request deliberately returns `needs_review`, exit `11`, and no published output because short wall candidates remain ambiguous.

G5–G7 add the service without changing that builder revision. PostgreSQL owns state, leases, cancellation, retry, artifacts, and a transactional queue outbox; Redis messages contain only build IDs and stale pending claims are recoverable. The worker launches one fresh wrapper per attempt, kills the full nested Blender process tree on cancellation/timeout/lease loss, verifies exact outputs, uploads immutable object versions, and atomically publishes success. The auth-first API exposes async submission, status, cancellation, readiness, and short-lived version-pinned downloads.

The complete local stack passed a 157-test repository run—156 on macOS plus the separately exercised Linux process-tree case—real PostgreSQL migrations and role convergence, real Redis stale-claim/dead-letter behavior, seven database/storage denial probes, and an end-to-end HTTP-to-Blender-to-download smoke. The smoke returned `202` in 72 ms, produced and independently verified the exact nine artifacts, proved direct/service structural parity, recovered across API restart, and confirmed the worker has no public egress or provider key. G8 production deployment and G9 release gates remain outstanding.

Native contributors with Blender 4.5.12 LTS can also run the explicit artifact gate:

```sh
python3 tests/blender_integration/g3_gate.py \
  --blender /absolute/path/to/blender \
  --work-dir /absolute/path/to/dedicated-temporary-directory
```

The local research workspace also contains a hardcoded Blender proof-of-concept, but it remains excluded from publication because it is branded, writes generated files beside source, and some generated assets contain local filesystem metadata.

## Safety and limitations

- The normal worker will accept declarative, schema-validated requests only. Arbitrary Python, Blender flags, add-ons, remote URLs, and host paths are out of scope.
- Geometry checks and later slicer checks are diagnostic evidence, not a warranty that a model will print safely or successfully.
- Users remain responsible for rights to names, designs, references, logos, and generated outputs. The project grants no rights to third-party characters or brands.
- No currently published release is supported for production use.

## License

Project source is licensed under GPL-3.0-or-later. Original sample assets will use the separate policy in [ASSET_LICENSE.md](ASSET_LICENSE.md). No sample model or render is included in the initial planning commit.
