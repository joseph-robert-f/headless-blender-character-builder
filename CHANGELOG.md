# Changelog

All notable project changes are recorded here. The format follows Keep a
Changelog, and releases use Semantic Versioning.

## Unreleased

### Changed

- Bound release-candidate builder, API, and worker tags and OCI labels to the
  exact distribution version and audited commit, and added checksum-verified
  Blender/project source assets with a machine-readable, image-bound scope
  record to release evidence; public OCI readiness stays explicitly false until
  complete actual-image copyleft/source review.
- Bounded Redis queue and dead-letter storage, added fail-closed orphaned
  object-version discovery with durable exact-version evidence, and advanced
  the maintained PostgreSQL 16 and Redis 8 server pins.
- Added caller-safe request validation details, bounded geometry-QA failure
  summaries, actionable Make preflight markers, and explicit documentation of
  GNU Make versus underlying builder exit statuses.
- Added checkout-scoped local-service identities, selectable loopback API and
  storage ports, wrapper-backed status/log commands, consistent Docker/Python
  selection, and a lighter first-evaluation service journey. The comprehensive
  service smoke remains an optional maintainer integration gate.
- Updated every Debian-derived project image to the maintained
  `bookworm-20260803-slim` base, pinned its reviewed manifest digest, and
  advanced package installation to the immutable `20260804T000000Z` snapshot.
- Raised the bounded OSV per-report limit from 4 MiB to 8 MiB so current image
  reports remain reviewable while preserving the 32 MiB aggregate limit.
- Reorganized public onboarding and documentation navigation, clarified
  path-specific prerequisites and troubleshooting, and aligned planning/test
  language with the completed local release candidate.
- Added a read-only prerequisite doctor, request-only validation, safe named
  build/verify outputs, and immutable compatibility aliases for the original
  `build/demo` workflow.
- Made image inspection compatible with pre-28.1 Docker clients while retaining
  explicit `linux/amd64` validation, kept local parent-image references portable
  across BuildKit, and moved service smoke into pull-request CI.
- Removed repository-configured Dependabot version-update rewrites and added an
  offline dependency-consistency gate, a read-only scheduled
  freshness/vulnerability workflow, coordinated update policy and
  lock-candidate helper, size-capped retained reports, and full release-image
  scanning.

## [0.1.0-rc.1] (local candidate) - 2026-08-03

### Added

- Strict `BuildRequest v1`, `CharacterSpec v1`, QA, and artifact-manifest
  contracts with hostile-input rejection.
- A schema-driven `geometric-character@1.0.0` Blender generator and two
  materially different original examples.
- Headless `.blend`, GLB, millimeter STL, beauty preview, diagnostic views,
  geometry QA, immutable manifest, and fresh-process verification.
- A checksum-pinned Blender 4.5.12 LTS `linux/amd64` builder image and a
  keyless, networkless one-shot quickstart.
- An authenticated asynchronous FastAPI service with PostgreSQL state,
  Redis delivery, versioned S3-compatible artifact storage, and a
  concurrency-one worker that reuses the deterministic builder contract.
- Hardened local Compose and VPS reference packages, scoped identities,
  retention, quiesced backup/restore, Redis reconstruction, digest-locked
  upgrades, forward-only recovery, and public HTTPS operator smoke tooling.
- Public governance, security, licensing, SBOM, CI, release-audit, and
  clean-checkout release-candidate material.

### Limitations

- Only `linux/amd64` is release-blocking.
- The included generator is geometric and declarative; arbitrary prompts,
  reference uploads, user Python, add-ons, and uploaded `.blend` files are not
  accepted.
- Geometry QA is diagnostic. This release does not provide slicer validation,
  a physical-print guarantee, or certification for safety-critical uses.
- OpenAI planning, MCP, managed-cloud templates, GPU orchestration, billing,
  and public multi-tenancy remain outside v0.1.
