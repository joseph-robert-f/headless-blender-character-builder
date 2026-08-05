# Changelog

All notable project changes are recorded here. The format follows Keep a
Changelog, and releases use Semantic Versioning.

## Unreleased

### Changed

- Reorganized public onboarding and documentation navigation, clarified
  path-specific prerequisites and troubleshooting, and aligned planning/test
  language with the completed local release candidate.
- Made image inspection compatible with pre-28.1 Docker clients while retaining
  explicit `linux/amd64` validation, kept local parent-image references portable
  across BuildKit, moved service smoke into pull-request CI, and aligned
  Dependabot with the supported Compose/workflow formats.

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
