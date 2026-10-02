# Backlog

This backlog records ideas for extensions after v0.1.
It does not promise implementation, compatibility, a hosted service, or a physical-print result.

## v0.1 release boundary

- **Supported:** one trusted local user with the one-shot Docker builder.
  The user has control of the machine and writes or reviews each JSON request.
  Requests have limits.
- **Experimental:** the optional Compose service on loopback for one trusted
  operator.
- **Out of scope:** Internet-facing, hostile-input, multi-tenant, public OCI,
  and VPS operation.

Tests for an experimental or future mode do not increase v0.1 support.

## Good first issues

The initial v0.1 review has no unclaimed good-first issues.

<!-- ste-preserve:start historical completed v0.1 changes -->
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
  gate remains false pending complete image source/delivery review and derived-
  PostgreSQL publication support;
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
  scans, fail-closed UNRATED handling, maintained base/runtime upgrades, and
  identity-bound 30-day dispositions. Two independent post-PostgreSQL-change
  candidate scans and a final exact-policy scan passed with 155/155 matches,
  no unused dispositions, no unresolved blockers, and no scan errors.

<!-- ste-preserve:end -->

Maintainers create future starter issues manually.
Copy a reviewed proposal into the repository issue template.
Apply the maintained labels below.

## Maintainer and security issues

- Before a VPS/public-OCI release, add the derived PostgreSQL image to the release inventory.
  Include its SBOM, signing, push, corresponding-source/notices, and digest-lock generation.
  Current publication tools cover only builder, API, and worker.
  Thus, `public_oci_ready` must stay false.

## Candidate extensions

### Generator and artifact work

- more original geometric generator families.
- optional trusted turntable output after a bounded animation profile exists.
- 3MF export with explicit unit/material contracts.
- better structural regression summaries that are renderer-independent.
- configurable but bounded preview composition and lighting.

### Print workflow

- explicit printer/material profiles.
- minimum wall and feature policies by process.
- pinned open-source slicer integration in a different release gate.
- overhang/support and bed-contact evidence.
- a physical-print review protocol.

These features cannot make automatic checks a manufacturing, safety, or fitness warranty.

### Optional planning and integrations

- an opt-in OpenAI prompt-to-spec planner with strict structured output and
  user confirmation before a paid or mutating build.
- a thin MCP adapter exposing create/get/cancel over the versioned service API.
- rights-cleared reference ingestion in a independently isolated pipeline.
- signed webhooks, quotas, and tenant-aware authorization.

OpenAI and MCP adapters must stay optional.
Do not put provider keys in the Blender child, artifacts, or logs.

### Operations and cloud

- propagate a reviewed candidate identity into production release locks after
  registry publication supplies immutable image digests.
- one maintained managed-cloud reference target.
- per-build worker jobs and independent API scaling.
- metrics, budgets, abuse controls, and deletion workflows.
- multi-architecture images after equivalent Blender provenance exists.
- automated validation that a draft public Release contains each locally
  generated corresponding-source asset before an associated OCI package is
  made public.
- signed OCI images, provenance attestations, and automated GHCR publication.

## Explicit non-goals

- arbitrary customer- or model-authored Python.
- unrestricted uploaded `.blend` files, add-ons, or drivers.
- protected-character packs or automatic IP clearance.
- general organic sculpting or exact-likeness generation.
- a public unauthenticated demo.
- Internet-facing, hostile-input, or multi-tenant service operation in v0.1.
- production VPS deployment in v0.1.
- production billing or marketplace behavior in this repository.

## Issue label catalog

`bug`, `documentation`, `dependencies`, `security`, `generator`, `component`,
`exporter`, `qa`, `deployment`, `release`, `schema`, `good first issue`,
`enhancement`, `help wanted`, `needs-triage`, and `needs-design`. Repository settings—not local
build or release tooling—own this catalog.
