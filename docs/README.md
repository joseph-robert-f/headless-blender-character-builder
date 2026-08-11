# Documentation

Start with the root [README](../README.md) for the keyless one-shot build and a
plain-language project overview. The guides below separate user, contributor,
operator, and project-history material so a newcomer does not need to read the
implementation plan in order to build a model.

## Build and integrate

- [Character and request contracts](character-spec.md) — supported JSON fields,
  generator behavior, hashes, QA, and manifest contracts
- [HTTP API v1](api.md) — authenticated asynchronous submission, status,
  cancellation, and artifact retrieval
- [Compatibility](compatibility.md) — supported platforms, pinned versions, and
  resource expectations
- [Troubleshooting](troubleshooting.md) — expected success markers and common
  Docker, output-directory, service, and release-check failures
- [Facet Bot brief](facet-bot-brief.md) — intent and constraints for the original
  bundled example

## Architecture and security

- [Architecture](architecture.md) — execution lanes, components, trust
  boundaries, persistence, recovery, and repository map
- [Threat model](threat-model.md) — assets, actors, threats, controls, and review
  triggers
- [Licensing guide](licensing.md) — project, Blender, asset, output, dependency,
  and contribution licensing boundaries

## Operate and release

- [Deployment and recovery](deployment.md) — VPS topology, TLS, external S3,
  permissions, lifecycle operations, backup, restore, and upgrades
- [Release process](release-process.md) — local release proof, conditional
  publication, corresponding source, and operator checklist
- [Dependency maintenance](dependency-maintenance.md) — offline consistency,
  scheduled vulnerability reports, and coordinated manual updates
- [v0.1.0-rc.1 release notes](release-notes/v0.1.0-rc.1.md) — candidate scope and
  limitations

## Scope, evidence, and project history

- [Implementation plan](../PLAN.md) — authoritative v0.1 scope and completed
  G0–G9 work packages
- [Test plan](../TEST_PLAN.md) — owner/reviewer verification protocol
- [Progress log](progress.md) — exact gate evidence, deviations, and conditional
  checks
- [Decision ledger](decisions.md) — adopted technical and product decisions
- [Backlog](backlog.md) — post-v0.1 extensions and starter issue outlines
- [Workspace inventory](inventory.md) — preserved pre-project baseline and
  migration constraints

## Policies and contribution

- [Contributing](../CONTRIBUTING.md), [governance](../GOVERNANCE.md), and
  [maintainers](../MAINTAINERS.md)
- [Security policy](../SECURITY.md) and [support policy](../SUPPORT.md)
- [Generated output policy](../OUTPUT_POLICY.md)
- [Source license](../LICENSE), [asset license](../ASSET_LICENSE.md), and
  [third-party notices](../THIRD_PARTY_NOTICES.md)
