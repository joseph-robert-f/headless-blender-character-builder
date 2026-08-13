# Backlog

This backlog records extension ideas after the v0.1 release boundary. It is
not a promise of implementation, compatibility, hosted availability, or a
physical-print outcome.

## Good first issues

No unclaimed good-first issues remain from the initial v0.1 review.

### Completed in this change

- added and gate-covered the Tidepool `facet-bot` palette example;
- expanded evidence-based Linux arm64, WSL2, and Docker Desktop troubleshooting;
- added bounded, canonical, path-free `make inspect` manifest summaries;
- added the hardened stdlib `make service-client` first-evaluation path;
- added runtime-created release-audit failure fixtures for every prohibited
  tracked-file and credential family;
- made the missing private storage-network error actionable without reflecting
  configured values;
- added read-only 8 GiB memory and 10 GiB disk quickstart advisories to the
  default doctor; and
- added exact selected-project service-image listing/removal while retaining
  named volumes and shared build cache and forbidding global prune.

The maintainer/security pass also:

- added a fail-closed, resumable private-publication transaction with
  commit-bound readiness, immediate per-push identity checks, checksum-bound
  registry manifests, isolated credentials, exact recovery inventory, and an
  explicit role-by-role visibility commit; the tracked public-OCI readiness
  gate remains false pending the separate corresponding-source review;
- reduced public image metadata to the three reviewed, registry-qualified
  release tags, exact image identities, allowlisted labels, and reviewed raw
  image-manifest digests, with coherent-removal/replacement and private-alias
  rejection tests;
- moved every recovery-drill child into an owned process group and deferred
  `HUP`, `INT`, and `TERM` until source recovery and disposable-target cleanup
  are certified;
- added an independent owner token to every orphan-lifecycle service, volume,
  and network and restricted cleanup to exact project-and-owner matches; and
- bound every short MinIO probe to a random owner label and immutable container
  ID, including ambiguous-create cleanup and same-name foreign-container
  preservation; and
- resolved the exact `linux/amd64` release-scan backlog with archive-only image
  scans, fail-closed UNRATED handling, maintained base/runtime upgrades,
  identity-bound 30-day dispositions, live MinIO/PostgreSQL gates, and two
  independent exit-zero candidate scans with 194/194 matches and no blockers.

Future starter issues are created manually. Maintainers should copy a reviewed
proposal into the repository issue template and apply the maintained labels
below.

## Maintainer and security issues

No unresolved maintainer/security issue from the full-system backlog review
remains. The completed release-scan evidence is recorded in the
[current vulnerability review](security/vulnerability-review-2026-08-12.md).
Public OCI publication remains separately blocked by its explicit tracked
readiness gate pending complete corresponding-source review; that release hold
is not an open source-implementation backlog item.

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
