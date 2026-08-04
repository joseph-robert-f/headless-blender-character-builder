# Backlog

This backlog records extension ideas after the v0.1 release boundary. It is
not a promise of implementation, compatibility, hosted availability, or a
physical-print outcome.

## Good first issues

| Proposed issue | Suggested labels | Acceptance outline |
|---|---|---|
| Add a third original `facet-bot` palette example | `good first issue`, `generator`, `documentation` | Valid v1 request, no new schema fields, passes contract tests, builds successfully, and documents visual differences without tracking generated binaries |
| Improve unsupported-platform troubleshooting | `good first issue`, `documentation` | Add evidence-based Linux/WSL2/Docker Desktop cases without claiming release support |
| Add bounded manifest-inspection CLI output | `good first issue`, `qa` | Read-only stdlib command, rejects oversized/noncanonical JSON, prints no paths or secrets, and has unit tests |
| Add release-audit failure fixtures | `good first issue`, `security`, `release` | Each fixture proves one prohibited tracked-file or credential pattern fails closed |
| Clarify one deployment error message | `good first issue`, `deployment` | Preserve exit contract, redact values, add focused test and runbook update |

Starter issues are created manually. Maintainers should copy the relevant row
into the repository issue template, confirm it still matches current code, and
apply the maintained labels below.

## Candidate extensions

### Generator and artifact work

- additional original geometric generator families;
- optional trusted turntable output after a bounded animation profile exists;
- 3MF export with explicit unit/material contracts;
- better structural regression summaries that remain renderer-independent;
- configurable but bounded preview composition and lighting.

### Print workflow

- explicit printer/material profiles;
- minimum wall and feature policies by process;
- pinned open-source slicer integration in a separate release gate;
- overhang/support and bed-contact evidence;
- a physical-print review protocol.

None of these would turn automated checks into a manufacturing, safety, or
fitness warranty.

### Optional planning and integrations

- an opt-in OpenAI prompt-to-spec planner with strict structured output and
  user confirmation before a paid or mutating build;
- a thin MCP adapter exposing create/get/cancel over the public service API;
- rights-cleared reference ingestion in a separately isolated pipeline;
- signed webhooks, quotas, and tenant-aware authorization.

OpenAI and MCP adapters must remain optional. Provider keys must never enter the
Blender child, artifacts, or logs.

### Operations and cloud

- one maintained managed-cloud reference target;
- per-build worker jobs and independent API scaling;
- metrics, budgets, abuse controls, and deletion workflows;
- multi-architecture images after equivalent Blender provenance exists;
- image-by-image corresponding-source packaging and retention automation before
  any public OCI publication;
- signed OCI images, provenance attestations, and automated GHCR publication.

## Explicit non-goals

- arbitrary customer- or model-authored Python;
- unrestricted uploaded `.blend` files, add-ons, or drivers;
- protected-character packs or automatic IP clearance;
- general organic sculpting or exact-likeness generation;
- a public unauthenticated demo;
- production billing or marketplace behavior in this repository.

## Issue label catalog

`bug`, `documentation`, `security`, `generator`, `component`, `exporter`, `qa`,
`deployment`, `release`, `schema`, `good first issue`, `help wanted`,
`needs-triage`, and `needs-design`. Repository settings—not local build or
release tooling—own this catalog.
