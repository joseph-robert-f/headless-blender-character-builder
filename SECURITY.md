# Security policy

## Current status

This repository is a planning and prototype scaffold. There is no supported production release, hosted service, or security-maintenance window yet. Do not expose the planned API or worker to untrusted users until the v0.1 security gates in `PLAN.md` pass.

## Reporting a vulnerability

After the GitHub repository is created, maintainers should enable GitHub private vulnerability reporting. Use the repository's **Security → Report a vulnerability** flow for suspected vulnerabilities. Do not publish exploit details, secrets, personal data, or signed artifact URLs in a public issue.

If private reporting is not yet enabled, open a minimal public issue requesting a private maintainer contact without including sensitive technical details.

## Security boundary

The intended public worker accepts strict declarative JSON only. Customer- or model-authored Python, arbitrary Blender commands, add-ons, uploaded `.blend` files, remote URLs, and host paths are outside the normal v0.1 boundary. See `PLAN.md` for the full threat model and release gates.
