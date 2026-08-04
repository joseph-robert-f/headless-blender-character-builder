# Security policy

## Current status

This repository is a v0.1 pre-release candidate. The deterministic builder has
passed strict input rejection, private staging, atomic success publication,
disabled embedded-script auto-execution, offline Blender, artifact hashing,
fresh reload/re-import, and a pinned non-root one-shot runtime with no network,
a read-only root, dropped capabilities, fixed mounts, and resource limits.
The service adds auth-first bounded HTTP handling, HMAC idempotency, fenced
PostgreSQL leases, transactional outbox plus stale Redis recovery,
cancellation-wins publication locking, nested-process termination, immutable
versioned artifacts, secret-free logs, distinct runtime/maintenance identities,
and tested least-privilege denials. The VPS package adds HTTPS configuration,
digest locks, bounded resources/logs, supported external-S3 guidance,
retention, quiesced backup/restore, and forward-only recovery.

There is still no supported hosted service, public multi-tenant abuse-control
plane, security SLA, or automatic patch service. Local validation does not
prove a live operator's DNS, TLS issuance, firewall, S3-provider IAM, off-host
backup, or incident process. Do not expose the local development stack beyond
its loopback bindings or to untrusted users.

## Reporting a vulnerability

GitHub private vulnerability reporting is a repository setting, not a local
capability. Maintainers must verify it is enabled before directing reporters to
the repository's **Security → Report a vulnerability** flow. The local release
gate does not inspect or change that remote setting.

If private reporting is not yet available, open only a minimal public issue
requesting private maintainer contact. Do not include exploit details,
credentials, personal data, private references, internal endpoints, logs, or
signed artifact URLs. Current maintainer roles are listed in `MAINTAINERS.md`.

After receiving a private report, maintainers should acknowledge it, reproduce
and assess it privately, coordinate a fix and advisory, credit the reporter
when requested, and publish details only after an appropriate remediation is
available. Response and remediation are best effort; there is no security SLA
for the pre-release project.

## Security boundary

The intended public worker accepts strict declarative JSON only. Customer- or model-authored Python, arbitrary Blender commands, add-ons, uploaded `.blend` files, remote URLs, and host paths are outside the normal v0.1 boundary. See `docs/threat-model.md` for the maintained threat model and `PLAN.md` for release gates.

## Local Compose boundary

- The API and object-download endpoints bind only to `127.0.0.1`; PostgreSQL and Redis have no host-published port.
- The worker is attached only to an internal Docker network, has no public-internet route, runs non-root with a read-only root and dropped capabilities, and receives no Docker socket or provider key.
- The API image contains neither Blender nor the builder entrypoint. The worker receives only its database/storage role and launches Blender with a scrubbed child environment.
- Database initialization revokes accumulated memberships, public/current privileges, and API/worker defaults for future migrator-owned tables and sequences before applying explicit API, worker, and migrator grants. Storage initialization inventories and removes the exact `hbcb_api` / `hbcb_worker` identities plus their reserved `hbcb_api_*` / `hbcb_worker_*` legacy families, recreates only the configured pair, and attaches fixed read-only/API and read-write-without-delete/worker policies without deleting object data or versions.
- The release gate actively proves ten forbidden PostgreSQL operations fail
  with `42501` and three forbidden object-storage operations fail with
  `AccessDenied`, including artifact-digest mutation and unversioned deletion.
- The test-profile container intentionally receives both runtime identities solely to execute negative permission probes. It is one-shot, non-core, and should never be enabled as an application service.

The source-built MinIO Community image is a zero-account local compatibility fixture pinned to its final security release. Cache reuse requires the exact local Dockerfile recipe identifier as well as pinned upstream version/revision and a live binary check. Its upstream project is no longer a supported production distribution. Production operators must use a currently maintained managed or operator-supported S3-compatible service and follow the G8 deployment guidance.
