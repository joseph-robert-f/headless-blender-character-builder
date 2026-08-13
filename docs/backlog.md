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
| Add a lightweight local service client | `good first issue`, `service`, `documentation` | One request/output command replaces the long first-evaluation block while preserving private-env checks, loopback-only no-proxy/no-redirect downloads, bounded polling/cancellation, exact hashes, and no-clobber publication |
| Add release-audit failure fixtures | `good first issue`, `security`, `release` | Each fixture proves one prohibited tracked-file or credential pattern fails closed |
| Clarify one deployment error message | `good first issue`, `deployment` | Preserve exit contract, redact values, add focused test and runbook update |
| Add quickstart capacity advisories to the doctor | `good first issue`, `documentation`, `qa` | Report bounded, read-only Docker-memory and checkout-disk notes for the documented one-shot baseline without turning imperfect host measurements into false failures |
| Document exact service-image cleanup | `good first issue`, `documentation`, `deployment` | Give platform-neutral commands for only the wrapper-reported checkout image tags and caches; retain named volumes and explicitly forbid global prune |

Starter issues are created manually. Maintainers should copy the relevant row
into the repository issue template, confirm it still matches current code, and
apply the maintained labels below.

## Maintainer and security issues

| Proposed issue | Suggested labels | Acceptance outline |
|---|---|---|
| Harden the future public-release transaction | `security`, `release`, `needs-design` | Immediately before any registry push, re-inspect each local image tag against checksum-bound release metadata and the exact current commit/version; document bounded resume/cleanup for partial private-image, Git-tag, or draft-Release state; keep `public_oci_ready` false until independently reviewed |
| Minimize public image metadata | `security`, `release` | Emit only the expected public release tag and reviewed published digest; prove extra private local aliases or registry names cannot enter uploaded metadata |
| Resolve exact `linux/amd64` release-scan findings | `security`, `dependencies`, `release` | Run the archive-bound scanner on the exact candidate; upgrade reachable components or add narrow identity-bound, expiring, independently reviewed dispositions; require an exit-zero scan before merge or publication |
| Harden recovery-drill interruption cleanup | `security`, `deployment`, `release` | Run every bounded child in an owned process group; defer `HUP`, `INT`, and `TERM` through source recovery and target cleanup; prove a signal cannot leave the source quiesced or the disposable recovery project running |
| Add independent ownership to the orphan-lifecycle project | `security`, `service`, `qa` | Label every disposable service, volume, and network with a second random owner token; compare the project and owner inventories before teardown; prove a foreign same-name resource is never removed |
| Bind short MinIO probes to owned container identities | `security`, `qa` | Give each version probe a random name and owner label, discover its immutable container ID after ambiguous Docker failures, and verify exact cleanup without touching a same-name foreign container |

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

- propagate a reviewed candidate identity into production release locks after
  registry publication supplies immutable image digests;
- one maintained managed-cloud reference target;
- per-build worker jobs and independent API scaling;
- metrics, budgets, abuse controls, and deletion workflows;
- multi-architecture images after equivalent Blender provenance exists;
- automated validation that a draft public Release contains every locally
  generated corresponding-source asset before any associated OCI package is
  made public;
- signed OCI images, provenance attestations, and automated GHCR publication.

## Explicit non-goals

- arbitrary customer- or model-authored Python;
- unrestricted uploaded `.blend` files, add-ons, or drivers;
- protected-character packs or automatic IP clearance;
- general organic sculpting or exact-likeness generation;
- a public unauthenticated demo;
- production billing or marketplace behavior in this repository.

## Issue label catalog

`bug`, `documentation`, `dependencies`, `security`, `generator`, `component`,
`exporter`, `qa`, `deployment`, `release`, `schema`, `good first issue`,
`enhancement`, `help wanted`, `needs-triage`, and `needs-design`. Repository settings—not local
build or release tooling—own this catalog.
