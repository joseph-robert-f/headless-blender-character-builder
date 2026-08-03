# Security policy

## Current status

This repository is an active pre-release implementation. The deterministic builder has passed G1–G4, including strict input rejection, private staging, atomic success publication, disabled embedded-script auto-execution, offline Blender processes, artifact hashes, fresh reload/re-import checks, a pinned non-root image, and a keyless one-shot runtime with no network, a read-only root, dropped capabilities, fixed mounts, and resource limits. G5 persistence foundations also enforce bearer/idempotency policy, transactional-outbox state, canonical attempt-scoped object keys, exact-body SHA-256 checks, version-pinned artifact URLs, and distinct generated API/worker/migrator credentials. There is still no supported production release, running HTTP service, or security-maintenance window. Do not expose the planned service to untrusted users until its remaining service and release security gates in `PLAN.md` pass.

## Reporting a vulnerability

Maintainers should enable GitHub private vulnerability reporting. Use the repository's **Security → Report a vulnerability** flow for suspected vulnerabilities. Do not publish exploit details, secrets, personal data, or signed artifact URLs in a public issue.

If private reporting is not yet enabled, open a minimal public issue requesting a private maintainer contact without including sensitive technical details.

## Security boundary

The intended public worker accepts strict declarative JSON only. Customer- or model-authored Python, arbitrary Blender commands, add-ons, uploaded `.blend` files, remote URLs, and host paths are outside the normal v0.1 boundary. See `PLAN.md` for the full threat model and release gates.
