# Documentation

New here? Read the root [README](../README.md), then follow
[Installation](installation.md) from prerequisites through a verified first
model. You do not need to understand the service or release machinery to use
the one-shot builder.

## I want to build a model

- [Installation](installation.md) — macOS without Homebrew, Linux,
  experimental WSL2, first build and verification, opening artifacts, cleanup,
  updates, direct Docker, and native Blender
- [Examples and ideas](../examples/README.md) — passing and fail-closed
  requests, copy-paste commands, and original character-project themes
- [Configuration](configuration.md) — Make variables, safe output names, local
  service credentials, and the VPS/release boundary
- [Character and request contract](character-spec.md) — every supported JSON
  field, generator behavior, hashes, QA, and manifest contracts
- [Troubleshooting](troubleshooting.md) — success markers and common Docker,
  output-directory, native, service, and release-check failures
- [Compatibility](compatibility.md) — platform status, pinned versions, and
  resource expectations
- [Facet Bot brief](facet-bot-brief.md) — intent and constraints for the
  original bundled example

## I want to integrate or understand it

The HTTP material describes an experimental, loopback-only evaluation path
for one trusted operator; it is not an Internet-facing v0.1 service contract.

- [HTTP API v1](api.md) — authenticated asynchronous submission, status,
  cancellation, and artifact retrieval
- [Architecture](architecture.md) — execution lanes, components, network and
  trust boundaries, persistence, recovery, and repository map
- [Threat model](threat-model.md) — assets, actors, threats, controls, and
  review triggers
- [Vulnerability review](security/vulnerability-review-2026-08-12.md) —
  finding-by-finding record supporting the checked-in vulnerability policy's
  temporary dispositions
- [Licensing guide](licensing.md) — project, Blender, asset, output,
  dependency, and contribution licensing boundaries

## I want to operate or release it

The VPS material is a future design and validation reference outside v0.1
support, not a currently published deployment product. There is no release
archive, release lock, or published image set yet.

- [VPS deployment and recovery](deployment.md) — availability, topology,
  verified source installation, TLS, external S3, permissions, lifecycle,
  backup, restore, and upgrades
- [Release process](release-process.md) — local release proof, conditional
  publication, corresponding source, and operator checklist
- [Dependency maintenance](dependency-maintenance.md) — offline consistency,
  scheduled vulnerability reports, and coordinated manual updates
- [v0.1.0-rc.1 release notes](release-notes/v0.1.0-rc.1.md) — candidate scope
  and limitations

## I want to contribute or audit decisions

- [Contributing](../CONTRIBUTING.md), [governance](../GOVERNANCE.md), and
  [maintainers](../MAINTAINERS.md)
- [Implementation plan](../PLAN.md) and [test plan](../TEST_PLAN.md) — binding
  v0.1 scope and verification protocol
- [Progress log](progress.md) — exact gate evidence, deviations, and
  conditional checks
- [Decision ledger](decisions.md) — adopted technical and product decisions
- [Backlog](backlog.md) — post-v0.1 extensions and starter issue outlines
- [Workspace inventory](inventory.md) — preserved pre-project baseline and
  migration constraints

## Policies

- [Security policy](../SECURITY.md) and [support policy](../SUPPORT.md)
- [Generated output policy](../OUTPUT_POLICY.md)
- [Source license](../LICENSE), [asset license](../ASSET_LICENSE.md), and
  [third-party notices](../THIRD_PARTY_NOTICES.md)
