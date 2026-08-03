# Security policy

## Current status

This repository contains an early v0.1 local builder. There is no supported production release, hosted service, or security-maintenance window. There is also no network-facing component: the builder is a command-line tool, and the HTTP API described in `PLAN.md` has not been built. Do not expose any part of this to untrusted users.

The builder does not read from the network at any point. `hbcb build` accepts a local JSON file and writes to a local directory; the container runs unprivileged with `--network none` and all capabilities dropped.

## Reporting a vulnerability

After the GitHub repository is created, maintainers should enable GitHub private vulnerability reporting. Use the repository's **Security → Report a vulnerability** flow for suspected vulnerabilities. Do not publish exploit details, secrets, personal data, or signed artifact URLs in a public issue.

If private reporting is not yet enabled, open a minimal public issue requesting a private maintainer contact without including sensitive technical details.

## Security boundary

The builder accepts strict declarative JSON only, enforced by the schemas in `schemas/` rather than by convention. Every object rejects properties it does not declare, so an unrecognised field is an error rather than a silently ignored value.

Explicitly outside the boundary, and rejected before Blender starts: caller-authored Python, Blender command-line flags, add-ons, geometry-node graphs, shaders, uploaded `.blend` files, remote URLs, host paths, output paths, and environment or container settings. Display names cannot influence where files are written — the filesystem slug derived from a name is restricted to lowercase alphanumerics and hyphens, and `tests/unit/test_validation.py` asserts that traversal attempts cannot escape a directory.

Request documents are capped at 64 KiB and every numeric field has an explicit range.

See `PLAN.md` for the longer-range threat model, and `docs/REVIEW.md` for what has actually been verified.
