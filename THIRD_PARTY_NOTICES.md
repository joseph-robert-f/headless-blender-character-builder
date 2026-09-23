<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Third-party notices

Headless Blender Character Builder is licensed under `GPL-3.0-or-later` and
depends on independently licensed software. Copyright remains with the
respective authors. This file is a human-readable inventory, not a substitute
for the complete license and copyright files shipped by each upstream project.

The version locks, image digests, download checksums, installed package
metadata, and generated SBOM are the authoritative release-specific inventory.
Maintainers must update this file when a direct dependency or bundled binary
changes.

## Bundled builder components

| Component | Pinned v0.1 input | License / notice location |
|---|---|---|
| Blender | 4.5.12 LTS Linux x64 binary archive | Blender is distributed under `GPL-3.0-or-later` with compatible third-party components. The image preserves `/opt/blender/copyright.txt`, `/opt/blender/license/`, and copies principal notices to `/usr/share/licenses/blender/`. See `docker/BLENDER_SOURCE_NOTICE.md` for the exact binary, checksum, and corresponding-source locations. |
| Debian GNU/Linux | `bookworm-20260918-slim`, digest pinned and resolved through the documented snapshot | Debian packages have package-specific licenses. Installed copyright notices remain under `/usr/share/doc/*/copyright`; the builder SBOM inventories installed packages without replacing those notices. |
| Headless Blender Character Builder | 0.1.0 source copied into the images | `GPL-3.0-or-later`; full text in `LICENSE` and in the image under `/usr/share/licenses/headless-blender-character-builder/LICENSE`. |

The builder image writes an SPDX 2.3 inventory to
`/opt/builder/provenance/sbom.spdx.json`. Its SPDX document data license is
`CC0-1.0`; that designation applies to the inventory data, not to the software
packages it describes.

Anyone redistributing an image that contains Blender is responsible for the
GPL's corresponding-source and notice requirements for that distribution
method. The release gate packages the exact checksum-verified Blender source
archive and image-to-source inventory; an upstream link alone is not the
project's delivery method.

## Python packages

Runtime and test wheels are checksum locked in
`docker/service-requirements.lock`, `docker/service-test-requirements.lock`,
and `docker/test-requirements.lock`. Direct dependencies currently include:

| Package | Pinned version | Upstream license identifier or family |
|---|---:|---|
| async-timeout | 5.0.1 | `Apache-2.0` |
| FastAPI | 0.141.1 | `MIT` |
| MinIO Python SDK | 7.2.20 | `Apache-2.0` |
| Psycopg / psycopg-binary | 3.3.4 | Psycopg is `LGPL-3.0-only`; the binary wheel also carries independently licensed native components identified by its upstream notices. |
| redis-py | 8.1.0 | `MIT` |
| Uvicorn | 0.52.1 | `BSD-3-Clause` |
| jsonschema (test only) | 4.26.0 | `MIT` |
| httpx2 / httpcore2 (test only) | 2.12.0 | `BSD-3-Clause` |
| truststore (test only) | 0.10.4 | `MIT` |

Transitive packages and their exact versions are listed in the lock files.
Their installed `.dist-info` metadata and license files remain authoritative.
Do not infer the Redis server's license from the independently licensed
`redis-py` client.

## Local Compose and VPS components

These services are separate programs and retain their own licenses:

| Component | v0.1 use | Notice |
|---|---|---|
| PostgreSQL | Project-derived gosu-free runtime from the exact `postgres:16.15-alpine3.24` digest-pinned official image; local state service and future digest-locked VPS input | PostgreSQL License plus the official base image's Alpine notices. `docker/postgres.Dockerfile` preserves the upstream filesystem, entrypoint, and notices while flattening the final image after removing the unused `gosu` helper. The VPS path remains future/out of v0.1 scope and requires an independently published digest-pinned derived image. |
| Redis server | `redis:8.2.10-alpine3.22` local and VPS-reference queue/coordination service | Use is governed by the selectable terms and notices shipped with that exact Redis 8 source/image release. Preserve those upstream files when redistributing the image. The VPS overlay inherits this pin from the base Compose model. |
| MinIO server | Final Community source revision `7aac2a2c5b7c882e68c1ce017d8256be2feea27f`, with Go security modules updated 2026-09-23, on digest-pinned `alpine:3.22.6`; local compatibility fixture only | `AGPL-3.0-or-later`; the image copies upstream `LICENSE` and `CREDITS` to `/licenses/minio/` and retains Alpine's installed package notices. The modified module graph is reproducibly hash checked in `docker/minio.Dockerfile`; this archived Community line is not the recommended production object store. |
| MinIO client (`mc`) | Final Community source revision `77f82e18b5401a65958f1619df6ebb994634bd88`, with the same reviewed Go security-module set; health, initialization, and recovery helper only | `AGPL-3.0-or-later`; the image retains the upstream client license and credits under `/licenses/minio/`. |
| Go toolchain | 1.26.8, MinIO and `mc` build stage only | Go's BSD-style license; the toolchain is not copied into the MinIO runtime stage. |
| Caddy | `caddy:2.11.4-alpine` runtime base for the local `v2.11.4-hbcb.1` source-built edge image | `Apache-2.0`; the custom image is not published. A future VPS release requires its own reviewed digest. |

The source-built MinIO server is a development compatibility fixture only. The
future, out-of-scope VPS overlay instead requires an operator-managed external
versioned S3 service and private gateway. That future path requires
digest-pinned derived PostgreSQL and service images, the pinned Redis service,
and a digest-pinned Caddy image; it is not part of the supported local-builder
v0.1 contract.

This repository does not currently publish or redistribute the builder,
service, database, queue, storage, or edge images as a release set. An operator
who assembles or redistributes that set is responsible for reviewing the exact
upstream terms, retaining required notices and corresponding source, tracking
security support, and updating pins as one coordinated release change.

## Optional and post-v0.1 services

OpenAI prompt planning and MCP integration are post-v0.1 adapters and are not
dependencies of the deterministic builder or v0.1 service. Operators who add
them must bring their own credentials, follow the provider's terms and usage
policies, inventory the selected SDK/model integration, and keep provider
secrets out of the Blender worker and generated artifacts.

Project names and upstream names identify compatibility or provenance only.
They do not imply sponsorship or endorsement.
