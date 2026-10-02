# Documentation

Read the root [README](../README.md) first.
Then use [Installation](installation.md) for the prerequisites and first model verification.
Service and release procedures are not necessary for the one-shot builder.

## I want to build a model

- [Installation](installation.md): macOS without Homebrew, Linux, experimental WSL2, first build, verification, artifacts, cleanup, updates, direct Docker, and native Blender
- [Examples and ideas](../examples/README.md): requests, QA rejection examples, commands, and original character ideas
- [Configuration](configuration.md): Make variables, output names, local service credentials, and VPS and release limits
- [Character and request contract](character-spec.md): JSON fields, generator behavior, hashes, QA, and manifests
- [Troubleshooting](troubleshooting.md): success markers and Docker, output-directory, native, service, and release-check failures
- [Compatibility](compatibility.md): platforms, pinned versions, and resources
- [Facet Bot brief](facet-bot-brief.md): purpose and limits for the supplied example.

## I want to integrate or understand it

The HTTP documents describe an experimental evaluation workflow.
It uses loopback only and one trusted operator.
It is not an Internet-facing v0.1 service contract.

- [HTTP API v1](api.md): authentication, asynchronous requests, status, cancellation, and artifact downloads
- [Architecture](architecture.md): execution, components, networks, trust boundaries, storage, recovery, and repository structure
- [Threat model](threat-model.md): assets, actors, threats, controls, and conditions for a new assessment
- [Vulnerability review](security/vulnerability-review-2026-08-12.md): historical evidence for temporary vulnerability-policy decisions
- [Licensing guide](licensing.md): licenses for project code, Blender, assets, outputs, dependencies, and contributions.

## I want to operate or release it

The VPS documents give a future design and validation reference.
VPS operation is outside v0.1 support.
The project does not yet publish a release archive, release lock, or image set.

- [VPS deployment and recovery](deployment.md): availability, topology, source installation, TLS, external S3, permissions, lifecycle, backup, restore, and upgrades
- [Release process](release-process.md): local evidence, source-only publication, corresponding source, and release checklist
- [Conditional OCI image publication](oci-publication.md): the blocked future publication procedure, verification done independently, and recovery
- [Dependency maintenance](dependency-maintenance.md): offline consistency checks, scheduled vulnerability reports, and coordinated manual updates
- [v0.1.0-rc.1 release notes](release-notes/v0.1.0-rc.1.md): historical candidate scope and limits.

## I want to contribute or audit decisions

- [Contributing](../CONTRIBUTING.md), [governance](../GOVERNANCE.md), and [maintainers](../MAINTAINERS.md)
- [Implementation plan](../PLAN.md): historical v0.1 scope and decisions
- [Test plan](../TEST_PLAN.md): verification procedures
- [Progress log](progress.md): historical test evidence, deviations, and conditional checks
- [Decision ledger](decisions.md): historical technical and product decisions
- [Backlog](backlog.md): possible work after v0.1
- [Workspace inventory](inventory.md): original project evidence and preservation rules
- [Documentation language](documentation-language.md): writing rules, scope, technical terms, and review limits.

## Experimental project tooling

The experimental tools are not part of the stable v0.1 generator.
Read the applicable guide before use:

- [Source-directed modeling](experimental-source-modeling.md): source inputs, trust boundaries, constraints, evidence, and benchmark reproduction
- [Docker backend](EXPERIMENTAL_MODELING_SANDBOX.md): container controls, limits, and cleanup
- [External model requests](model-request-bridge.md): prepare a brief, inspect external source, and execute one verified proposal
- [Local model review](local-model-review.md): geometry inspection, requirements, decisions, and change requests
- [Local project launcher](local-project-launcher.md): portable project metadata, runtime readiness, and Linux-only generation
- [HBCB REVIEW PREVIEW](review-preview.md): the unsigned, read-only Windows x64 and Mac arm64 packages.

## Policies

- [Security policy](../SECURITY.md) and [support policy](../SUPPORT.md)
- [Generated output policy](../OUTPUT_POLICY.md)
- [Source license](../LICENSE), [asset license](../ASSET_LICENSE.md), and [third-party notices](../THIRD_PARTY_NOTICES.md).

- [Translation verification, version 2](verifier-validation.md): bounded checks, test evidence, and version-1 compatibility
