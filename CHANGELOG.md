# Changelog

All notable project changes are recorded here. The format follows Keep a
Changelog, and releases use Semantic Versioning.

## Unreleased

### Fixed

- Made the in-memory state store reject non-boolean retry flags, matching
  PostgreSQL validation before any state change.
- Included the canonical manifest and its final newline in the builder's
  2 GiB publication limit, matching service uploads and client downloads.
- Waited for successful completion of both orphan-test setup containers,
  instead of expecting one-time setup containers to remain running in Compose.

### Changed

- Moved maintenance database and file-storage operations into separate modules.
  Existing imports from `hbcb_service.maintenance` remain available.
- Shared one-shot Make command setup through `scripts/builder-container`, with
  separate resource limits and mount permissions for each operation.
- Right-sized the operative release process for a solo maintainer (D-070):
  the source-only transaction now consists of green GitHub-hosted CI, one
  fresh `make release-check`, a reviewed dependency scan, `SHA256SUMS`
  verification, a signed tag (GPG or SSH signing), and a draft-then-published
  GitHub Release, while the unchanged, still-blocked conditional
  image-publication transaction moved verbatim to `docs/oci-publication.md`.
- Documented a dedicated, fail-closed source-only v0.1 release transaction
  (D-069) that publishes the signed `v0.1.0-rc.1` Git tag and a
  source-bearing GitHub Release without authenticating to GHCR, pushing an
  image, or changing package visibility, leaving the conditional
  image-publication transaction and its `public_oci_ready` gate unchanged.
- Bound release-candidate builder, API, and worker tags and OCI labels to the
  exact distribution version and audited commit, and added checksum-verified
  Blender/project source assets with a machine-readable, image-bound scope
  record to release evidence; public OCI readiness stays explicitly false until
  complete actual-image copyleft/source review.
- Bounded Redis queue and dead-letter storage, added fail-closed orphaned
  object-version discovery with durable exact-version evidence, and advanced
  the maintained PostgreSQL 16 and Redis 8 server pins.
- Replaced the Compose PostgreSQL runtime with a project-derived image that
  removes dormant `gosu`, runs intrinsically as UID/GID 70, and is verified by
  an immutable-identity, fresh-volume runtime security gate.
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
