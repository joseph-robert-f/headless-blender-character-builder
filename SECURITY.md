# Security policy

## Current status

This repository is a v0.1 pre-release candidate.
Tests of the deterministic builder show these controls:

- Strict input rejection and private staging
- Atomic publication of results that pass the tests
- Disabled automatic execution of embedded scripts
- Blender without network access
- Artifact hashes and new reload/re-import tests
- A pinned, non-root, one-shot runtime
- No network connection and a read-only root filesystem
- Dropped capabilities, fixed mounts, and resource limits.

The experimental local service adds these controls:

- Authentication before HTTP request processing with specified limits
- HMAC idempotency and fenced PostgreSQL leases
- Transactional outbox and recovery from stale Redis data
- Publication locks that give cancellation priority
- Termination of nested processes
- Immutable artifact versions and logs without secrets
- Different runtime and maintenance identities
- Tests for least-privilege denials.

The VPS reference is not in the supported scope.
Its tests include HTTPS configuration, digest locks, resource and log limits, and external-S3 guidance.
They also include retention, backup/restore with operations stopped, and forward-only recovery.

The first release, v0.1, supports one trusted user who makes a local model with the one-shot Docker builder.
This user controls the machine and makes or examines the JSON request before use.
The request must obey the specified limits.
The Compose service is experimental and local-only.
Internet-facing, multi-tenant, hostile-input, and VPS operation are not in v0.1 support.
There is no supported hosted service, security service-level agreement (SLA), or automatic patch service.

Local validation does not prove the configuration or procedures of a live operator.
This includes DNS, TLS issuance, firewall, S3-provider IAM, off-host backup, and incident procedures.
Do not give access to the local development stack through a connection other than its loopback bindings.
Do not give untrusted users access to it.

<a id="reporting-a-vulnerability"></a>
## Report a vulnerability

Use GitHub's **Security → Report a vulnerability** procedure or the direct [private report form](https://github.com/joseph-robert-f/headless-blender-character-builder/security/advisories/new).
Private vulnerability reporting is enabled for this repository.
This is a remote repository setting.
Local build and release commands do not control it.

If the private portal is not available, open only a minimal public issue to request private maintainer contact.
Do not include exploit details, credentials, personal data, private references, internal endpoints, logs, or signed artifact URLs.
`MAINTAINERS.md` identifies the current maintainer roles.

After a private report, these tasks are recommended for maintainers:

1. Acknowledge the report.
2. Reproduce the problem privately.
   Examine its effects.
3. Manage a correction and a security advisory together.
4. If the reporter requests credit, identify the reporter in the advisory.
5. Publish details only after an applicable correction is available.

Maintainers try to reply to reports and correct problems.
There is no security SLA for the pre-release project.

## Security boundary

The supported one-shot builder and experimental local worker accept only strict declarative JSON.
The usual v0.1 boundary excludes these inputs:

- Python written by a customer or model
- Arbitrary Blender commands or add-ons
- Uploaded `.blend` files
- Remote URLs or host paths.

Read `docs/threat-model.md` for the maintained threat model.
Read `PLAN.md` for release gates.

## Local Compose boundary

- The API and object-download endpoints bind only to `127.0.0.1`.
  PostgreSQL and Redis do not publish a host port.
- The worker connects only to an internal Docker network.
  It has no route to the public Internet.
  It operates as a non-root user with a read-only root filesystem and dropped capabilities.
  It receives no Docker socket or provider key.
- The API image contains no Blender program or builder entrypoint.
  The worker receives only its database/storage role.
  It starts Blender with a child environment from which other values are removed.
- Database initialization removes accumulated memberships and public/current privileges.
  It also removes API/worker defaults for future tables and sequences owned by the migrator.
  It then applies explicit grants for the API, worker, and migrator.
- Storage initialization inventories and removes the specified `hbcb_api` / `hbcb_worker` identities.
  It also removes their reserved `hbcb_api_*` / `hbcb_worker_*` legacy families.
  It creates only the configured pair again.
  It applies a fixed read-only policy for the API and a read-write-without-delete policy for the worker.
  It does not delete object data or versions.
- The release gate proves that ten prohibited PostgreSQL operations fail with `42501`.
  It proves that three prohibited object-storage operations fail with `AccessDenied`.
  These tests include artifact-digest changes and unversioned deletion.
- The test-profile container receives the two runtime identities only to test permission denials.
  This container is one-shot and non-core.
  Do not enable it as an application service.

The source-built MinIO Community image is a local compatibility test fixture.
An account is not necessary.
It is pinned to the last MinIO Community security release.
To use the cache again, the local Dockerfile recipe identifier must be the same.
The pinned upstream version/revision must also be the same.
The live binary check must pass.

The upstream project is no longer a supported production distribution.
Do not use this image as production storage.
Production storage and VPS operation are not in v0.1 support.
