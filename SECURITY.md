# Security policy

## Current status

This repository is an active pre-release implementation. The deterministic builder has passed G1–G4, including strict input rejection, private staging, atomic success publication, disabled embedded-script auto-execution, offline Blender processes, artifact hashes, fresh reload/re-import checks, a pinned non-root image, and a keyless one-shot runtime with no network, a read-only root, dropped capabilities, fixed mounts, and resource limits. G5–G7 add auth-first bounded HTTP handling, HMAC idempotency, fenced PostgreSQL leases, transactional outbox plus stale Redis claim recovery, cancellation-wins publication locking, complete nested-process termination, canonical attempt-scoped object keys, exact-body/versioned artifact evidence, short-lived version-pinned URLs, secret-free logs, distinct generated API/worker/migrator identities, and a tested local Compose boundary. There is still no supported production release, public ingress/TLS package, abuse control, or security-maintenance window. Do not expose the local development stack beyond its loopback bindings or to untrusted users; the remaining deployment and release security gates in `PLAN.md` must pass first.

## Reporting a vulnerability

Maintainers should enable GitHub private vulnerability reporting. Use the repository's **Security → Report a vulnerability** flow for suspected vulnerabilities. Do not publish exploit details, secrets, personal data, or signed artifact URLs in a public issue.

If private reporting is not yet enabled, open a minimal public issue requesting a private maintainer contact without including sensitive technical details.

## Security boundary

The intended public worker accepts strict declarative JSON only. Customer- or model-authored Python, arbitrary Blender commands, add-ons, uploaded `.blend` files, remote URLs, and host paths are outside the normal v0.1 boundary. See `PLAN.md` for the full threat model and release gates.

## Local Compose boundary

- The API and object-download endpoints bind only to `127.0.0.1`; PostgreSQL and Redis have no host-published port.
- The worker is attached only to an internal Docker network, has no public-internet route, runs non-root with a read-only root and dropped capabilities, and receives no Docker socket or provider key.
- The API image contains neither Blender nor the builder entrypoint. The worker receives only its database/storage role and launches Blender with a scrubbed child environment.
- Database initialization revokes accumulated memberships, public/current privileges, and API/worker defaults for future migrator-owned tables and sequences before applying explicit API, worker, and migrator grants. Storage initialization inventories and removes the exact `hbcb_api` / `hbcb_worker` identities plus their reserved `hbcb_api_*` / `hbcb_worker_*` legacy families, recreates only the configured pair, and attaches fixed read-only/API and read-write-without-delete/worker policies without deleting object data or versions.
- The release gate actively proves five forbidden PostgreSQL operations fail with `42501` and two forbidden object-storage operations fail with `AccessDenied`.
- The test-profile container intentionally receives both runtime identities solely to execute negative permission probes. It is one-shot, non-core, and should never be enabled as an application service.

The source-built MinIO Community image is a zero-account local compatibility fixture pinned to its final security release. Cache reuse requires the exact local Dockerfile recipe identifier as well as pinned upstream version/revision and a live binary check. Its upstream project is no longer a supported production distribution. Production operators must use a currently maintained managed or operator-supported S3-compatible service and follow the G8 deployment guidance.
