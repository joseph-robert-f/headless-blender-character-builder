# Headless Blender Character Builder

An open-source, self-hostable pipeline for turning a bounded JSON character request into real Blender geometry, portable 3D exports, diagnostic renders, and machine-readable QA.

> **Status: G0–G4 passed; keyless container builder implemented, service pending.** The strict v0.1 contracts, generic Blender generator, `.blend`/GLB/STL exports, four renders, geometry QA, success manifest, fresh-process verification, pinned builder image, and hardened Docker/Make quickstart are implemented. The API, Compose service, VPS package, and release automation remain pending. This is not production-ready yet.

The planned public contract is deliberately narrow: original geometric, low-poly, or chibi characters compiled from reviewed Blender primitives—not unrestricted text-to-3D, customer-authored Python, exact likenesses, protected-character replication, or guaranteed physical prints.

## Start here

- [PLAN.md](PLAN.md) is the authoritative product scope and implementation sequence.
- [TEST_PLAN.md](TEST_PLAN.md) explains how an owner or reviewer will prove each feature and records what input is still needed.
- [docs/character-spec.md](docs/character-spec.md) documents the implemented bounded JSON contracts and test command.
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

The secondary path will add an asynchronous self-hosted service through Docker Compose. OpenAI planning and MCP support remain optional post-v0.1 adapters and will never be required by the deterministic Blender builder.

## Repository state

The repository contains four Draft 2020-12 schemas, pure-standard-library production validation/canonicalization, two original example requests, hostile rejection fixtures, and schema/policy tests. Its `geometric-character@1.0.0` registry entry compiles requests into separate material-bearing display meshes and one closed, connected manufacturing-oriented `PRINT` shell using real procedural Blender geometry. The trusted launcher publishes exactly the required nine-file tree through a private staging directory and atomic rename, writes the success manifest last, and launches a second isolated Blender process to reload `.blend` and re-import GLB/STL.

The G4 gate exported a clean tree from the Git index, built the pinned `linux/amd64` production image without credentials, ran and verified `facet-bot` twice, and matched its structural evidence to the native fallback. The model container ran non-root with no network, a read-only root, all capabilities dropped, no-new-privileges, and bounded PID/CPU/RAM/scratch. The image carries immutable source/Blender hashes, upstream notices, and an SPDX 2.3 SBOM. The more complex `moss-hopper` request deliberately returns `needs_review`, exit `11`, and no published output because short wall candidates remain ambiguous.

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
