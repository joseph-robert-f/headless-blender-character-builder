# Feature Testing and Owner Review Plan

Status: **Current verification plan. Historical G0–G9 evidence passed locally. New release changes must pass a new exact-commit gate.**

Last updated: **August 12, 2026**

> **v0.1 support boundary:** a gate result shows an engineering property.
> It does not increase product support. v0.1 supports the trusted local one-shot Docker
> builder. Compose is experimental and loopback-only. Public, hostile-input,
> multi-tenant, public-OCI, and VPS operation remain outside v0.1 support.

## 1. Purpose and authority

`PLAN.md` defines the v0.1 scope. This document defines the verification procedure
for the owner or an independent reviewer.
If these documents disagree, `PLAN.md` is authoritative until both documents change.

A test passes only if its specified command succeeds and gives evidence for review.
Use these statuses:

- `PASS`: The behavior agrees with the contract. Evidence is recorded.
- `FAIL`: The behavior does not agree with the contract.
- `BLOCKED`: The implementation exists, but an external prerequisite is unavailable.
- `NOT_IMPLEMENTED`: The feature does not exist yet. Use this initial status for absent v0.1 features.
- `CONDITIONAL`: The test is optional and uses a live VPS, slicer, physical print, or other external resource.
- `NOT_APPLICABLE`: The test does not apply to the selected platform or mode.

Do not use `BLOCKED` for an absent implementation.
Documentation or mock artifacts alone cannot establish `PASS`.

Historical results, recorded counts, completed decisions, commands, and evidence
paths below keep their original wording. The controlled-language revision covers maintained instructions.

## 2. Current state

<!-- ste-preserve:start historical completed G0–G9 implementation summary -->
Work packages G0 through G9 have passed every locally verifiable gate. The repository contains strict `BuildRequest`, `CharacterSpec`, QA, and manifest contracts plus a generic `geometric-character@1.0.0` registry/core. Two original requests generate real, materially different Blender geometry with stable structural fingerprints. The trusted builder saves `.blend`, exports display GLB and a raw-millimeter binary STL, renders four PNGs, measures complete geometry QA, verifies the model formats in a second fresh Blender process, and atomically publishes a success manifest last.
<!-- ste-preserve:end -->

The pass counts and `g9-final` record below describe the historical August 3 index.
They do not give evidence for later lifecycle, worker, dependency, OCI, or release-tool changes.
Each such PR must use `HBCB_RELEASE_RUN_ID=<unique-safe-id> make release-check`
against its last signed-off commit.
Record the unique run ID in the PR.
Do not put that result in this tracked plan, because the edit changes the commit under verification.

<!-- ste-preserve:start historical completed implementation and reviewer environment -->
The G4 `linux/amd64` image, narrow `builder build|verify` CLI, hardened one-shot Docker runtime, keyless Make targets, native fallback, baked provenance, notices, and SPDX SBOM are implemented and passed from a clean indexed source export. The current public-readiness layer adds request-only `builder validate` plus safe named Make outputs without changing the build/verify artifact contract. G5–G6 add Postgres/Redis/versioned-storage foundations, generated scoped configuration, the bounded authenticated FastAPI surface, durable repository, fenced concurrency-one worker, stale Redis claim recovery, complete nested-process termination, immutable artifact publication, fixed-region signing, and secret-free structured logs without changing the G4 builder revision. G7 packages those components into an experimental hardened local Compose service with convergent least-privilege initialization and a real HTTP-to-Blender-to-download gate. G8 validates a future digest-locked VPS design, HTTPS guidance, maintained external S3 boundary, retention, backup/restore, Redis reconstruction, upgrade/rollback handoff, and an isolated recovery drill; those tests do not make VPS operation a v0.1-supported path. G9 adds the public documentation, governance, fork-safe CI definitions, license/SBOM inventory, real-model preview, source audit, and deterministic local release bundle; the final clean-index rehearsal passed without a remote operation. The excluded hardcoded branded proof of concept is preserved baseline material, not v0.1 acceptance evidence.

Known local reviewer environment:

| Component | Observed value |
|---|---|
| Host | macOS on Apple Silicon (`arm64`) |
| Blender | 4.5.12 LTS |
| Docker client/server | 29.4.0 / 29.4.0; Docker Desktop Linux `arm64` host |
| Make | GNU Make 3.81 |
<!-- ste-preserve:end -->

## 3. What I need from the owner

### Initial GitHub publication (completed)

- [x] Create the public repository at <https://github.com/joseph-robert-f/headless-blender-character-builder>.
- [x] Confirm the authorized GitHub connector has administrator and push access.
- [x] Use `main` as the default branch.

The repository and project/package slug are both `headless-blender-character-builder`.
GitHub CLI is optional. For clone, branch, and pull-request operations,
use Git or an equivalent GitHub client.

### Confirm before v0.1 implementation reaches its release gate

- [x] Keep the working name **Headless Blender Character Builder**.
- [x] Keep GPL-3.0-or-later for code and CC0-1.0 for original samples.
- [x] Use the neutral original `facet-bot` example.
- [x] Treat Windows/WSL2 as experimental and non-release-blocking in v0.1.
- [ ] Identify an outside clean-room reviewer for the final quickstart, if available.

### Optional inputs needed only for later tests

- [ ] Printer technology, exact printer, material, nozzle/resin, slicer, layer profile, support strategy, and minimum feature requirements.
- [ ] VPS provider/OS, domain, TLS approach, and explicit authorization for a live deployment test.
- [ ] Physical-print reviewer and acceptance measurements.
- [ ] OpenAI API key only if the optional post-v0.1 prompt planner is later enabled. It is not needed for the deterministic release.

## 4. Evidence rules

For each completed test, record these data:

- test ID, date, reviewer, and result.
- commit SHA and builder image ID or digest.
- OS/architecture plus Docker, Compose, Make, and Blender versions.
- exact redacted command, exit code, and elapsed time.
- expected versus actual behavior.
- manifest, QA, sanitized logs, hashes, and artifact locations.
- issue link for every failure.

Published build/test evidence normally belongs under this ignored path:

```text
build/test-evidence/<commit-or-tree-hash>/<test-id>/
```

The native G2 and G3 harnesses are exceptions.
Use new temporary directories that you own outside the repository.
This prevents integration probes and generated artifacts from changing source files.
Record the temporary paths and persistent result summaries in `docs/progress.md`.
Do not commit generated JSON or model artifacts.

When implementation starts, record milestone summaries in `docs/progress.md`.
Do not attach `.env`, credentials, tokens, private references, signed URLs,
or environment dumps with secret data.

## 5. Test sequence

| Stage | PLAN dependency | Current status | Release purpose |
|---|---|---|---|
| T0 — repository and documentation | G0 | `PASS` locally | Prove the public scaffold contains only intended, safe files |
| T1 — schemas, generic engine, and artifacts | G1–G3 | `PASS` | Prove bounded requests create and independently verify real, varied Blender geometry |
| T2 — keyless container quickstart | G4 | `PASS` | Prove the primary public experience from a clean source tree |
| T3 — asynchronous service | G5–G7 | `PASS` | Prove durable API, queue, worker, auth, and artifacts |
| T4 — VPS and recovery | G8 | `PASS` locally / live `CONDITIONAL` | Validate the future VPS topology and recovery contracts without claiming a live deployment |
| T5 — release candidate | G9 | `PASS` locally | Prove tests, security, licenses, docs, and packaging together |

If a dependency gate fails, do not use later stages as replacement evidence.

## 6. T0 — repository publication tests

### PUB-01: intentional source set

From the repository root:

```sh
git status --short
git ls-files
git remote -v
```

The test passes only when all these conditions are true:

- Git tracks only intended source, policy, documentation, workflow, test,
  and separately licensed static-asset files.
- No generated model output, backup, credential, or private evidence is present.
- `origin` is the expected GitHub repository.

### PUB-02: local-path and secret scan

```sh
rg -n '/Users/|/home/|file://|BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9_-]+' \
  --hidden -g '!.git/**' .
```

Examine each result. Documentation examples can show prohibited patterns.
Git must not track real personal paths, credentials, signed URLs, or private values.
Do a conditional remote-repository check of GitHub secret scanning and push protection.

### PUB-03: truthful documentation

Make sure that README:

- labels the repository as a local v0.1 release candidate and distinguishes
  local proof from conditional hosted publication.
- describes the implemented one-shot Docker, native, asynchronous service,
  VPS reference, recovery, and release-check paths without advertising an
  unpublished container image or hosted service.
- links `PLAN.md`, this test plan, security, contribution, and license documents.
- distinguishes required no-key operation from optional future credentials.
- states IP, security, and physical-print limitations.

### PUB-04: license and policy files

Make sure that license detection identifies GPL-3.0-or-later for source.
Make sure that `ASSET_LICENSE.md` separately licenses the tracked original preview.
`docs/assets/manifest.json` records its provenance.
Make sure that `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SUPPORT.md`
show correctly on GitHub.

## 7. T1 — schema, engine, and authenticity tests

ENG-01 through ENG-06 are runnable and passed after G1–G3.

Use the containerized unit target for the complete test tree.
The root and service packages have separate dependency environments.
Use these contract and engine commands:

```sh
make test-unit

export PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'

"$PYTHON" tests/blender_integration/g2_gate.py \
  --blender /absolute/path/to/blender \
  --evidence-dir /absolute/path/to/new-temporary-directory

"$PYTHON" tests/blender_integration/g3_gate.py \
  --blender /absolute/path/to/blender \
  --work-dir /absolute/path/to/dedicated-temporary-directory
```

The two direct Blender commands are contributor probes.
Use the documented native Python/Blender environment for them.
`make test-blender` is the authoritative containerized integration command.
Do not run unrestricted `unittest discover -s tests` after you install only the root package.

| ID | Status | Required proof |
|---|---|---|
| ENG-01 | `PASS` | Valid `BuildRequest v1` and nested `CharacterSpec v1` fixtures pass. Properties not in the schema, presets that are not compatible, and hostile fields fail before Blender starts |
| ENG-02 | `PASS` | Two different requests build from factory startup through the same generator |
| ENG-03 | `PASS` | Repeated requests keep the same canonical hashes and structural fingerprint. They do not have to give byte-identical `.blend` or PNG files |
| ENG-04 | `PASS` | New-process `.blend` reload succeeds and lists mesh objects, vertices, faces, materials, transforms, and three-dimensional bounds |
| ENG-05 | `PASS` | Front, side, and back diagnostics come from the saved scene. Validation covers PNG structure/variation, geometry, and absence of external texture dependencies |
| ENG-06 | `PASS` | GLB and STL re-import into clean scenes and match evaluated `.blend` bounds in the greater of 0.2 mm or 0.5% for each axis |

Required artifact tree:

```text
model.blend
model.glb
model.stl
preview.png
diagnostics/front.png
diagnostics/side.png
diagnostics/back.png
manifest.json
qa.json
```

Make sure that artifact verification gives these results:

- both JSON files validate against versioned schemas.
- every non-manifest artifact byte count and SHA-256 hash recomputes correctly.
- evaluated triangles do not exceed 500,000.
- STL is one connected watertight shell with positive volume and outward normals.
- non-manifold edges and zero-area faces equal zero.
- coordinates and transforms are finite.
- minimum wall thickness is at least 1.2 mm.
- freestanding features and connections are at least 2.0 mm.
- unmeasurable mandatory geometry becomes `needs_review`, not `succeeded`.

<!-- ste-preserve:start historical G3 measured artifact results -->
Final G3 evidence is under `/private/tmp/hbcc-g3-final-topology.PMFshx/`. Facet Bot published the exact tree twice with matching stable probe SHA-256 `726060b092c8168e0a57477116a4c715e1b6f21d48c6d65fe7ca2be500652ccc`. Its STL has 316,172 triangles, one face-connected closed positive shell, zero non-manifold edges or vertices, and conservative lower bounds of 2.3001 mm wall and 2.3089 mm feature. A synthetic pair of closed tetrahedra touching at one bow-tie vertex proves production QA rejects vertex-pinched shells. Moss Hopper intentionally exits `11` as `needs_review` and publishes nothing because its wall evidence is ambiguous. Invalid CLI, oversized/invalid/unresolvable input, an existing caller-owned output, and a corrupted private STL also followed their fixed failure contracts without publishing success.
<!-- ste-preserve:end -->

## 8. T2 — zero-key single-container quickstart

<!-- ste-preserve:start historical G4 execution environment -->
G4 passed these tests on August 3, 2026, from a temporary `git checkout-index` export containing 94 tracked files. The release image ran as `linux/amd64` under Docker Desktop emulation; no registry login, `.env`, provider key, Compose stack, host Blender, database, queue, or object store was available to the container path.
<!-- ste-preserve:end -->

Golden commands:

```sh
make demo
make verify-demo
```

<!-- ste-preserve:start historical G4 observed results and summary -->
| ID | Status | Observed proof |
|---|---|---|
| QKS-01 | `PASS` | A clean indexed export built the production image and completed `make demo && make verify-demo` with Docker and GNU Make 3.81 |
| QKS-02 | `PASS` | The gate used an empty Docker credential/config home and scanned credential canaries from image metadata, logs, evidence, and artifacts |
| QKS-03 | `PASS` | Runtime asserted no network, non-root `501:20`, read-only root, `cap-drop=ALL`, no-new-privileges, 512 PIDs, 4 CPUs, 4 GiB RAM, 2 GiB no-exec scratch, and exactly two fixed mounts |
| QKS-04 | `PASS` | Both first and repeat verification used a fresh hardened container and loaded `.blend` plus imported GLB/STL in Blender 4.5.12 LTS |
| QKS-05 | `PASS` | Invalid request exited `3`; `moss-hopper` mandatory-unknown QA exited `11`; neither published output; fixed exits `2`, `4`, and `12` also passed |
| QKS-06 | `PASS` | Two container runs produced matching stable probe SHA-256 `726060b092c8168e0a57477116a4c715e1b6f21d48c6d65fe7ca2be500652ccc` and an unchanged image ID |
| QKS-07 | `PASS` | G2 proves the two requests are materially different; G4 independently exercised the second request through the same container CLI and preserved its fail-closed QA result |
| QKS-08 | `PASS` | The fixed launcher budget is 15 minutes, scratch is capped at 2 GiB, and the successful nine-file output totaled 21,515,028 bytes |

The passing summary is `/private/tmp/hbcb-g4-final.ovZDPq/g4-summary.json`. It records production image ID `sha256:49cb24b22ea569bfe9db3a7ad5532d1270c765439a7c293515b9e833fb655b13`, a 166-package SPDX 2.3 SBOM, exact source/Blender binary hashes, container/native structural parity, and fixed application exit coverage. `make test-unit` passed all 62 clean-source unit, contract, launcher, and runtime-policy tests. The full `make check` target is implemented; its final clean release invocation remains part of G9.
<!-- ste-preserve:end -->

For optional human evidence, open a copy of `model.blend`.
Hide or move a component. Examine the solid and wireframe views.
Human examination does not replace automatic tests.

## 9. T3 — asynchronous Compose service

G5–G7 passed. The persistence, API/worker lifecycle, hardened Compose runtime, and end-to-end HTTP/storage/Blender path are implemented.

G5 verification already completed:

```sh
PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 \
  python3.11 -m unittest discover -s tests/service_unit -v

HBCB_G5_POSTGRES_DSN=<local-test-dsn> PYTHONPATH=.:service/src \
  python3.11 tests/service_integration/g5_postgres_gate.py
```

<!-- ste-preserve:start historical G5 and G6 observed results -->
Observed G5 proof: 55 focused service tests passed. PostgreSQL 16.9 applied the foundation migration, exposed all required tables/constraints, and rejected invalid durable states. Storage tests hash uploaded and stored bytes, require version IDs, pin signed downloads, and reject forged metadata. Generated role mappings parse independently.

Observed G6 proof: 154 repository tests were discovered; 153 passed locally and the sole Linux-only nested-process test separately passed under the hardened `linux/amd64` image in 2.201 seconds. The authenticated API covers async submission/replay, uniform errors, cancellation, readiness, and exact signed artifacts. The worker covers fenced leases/heartbeats, retries, timeout, dead-letter, cancellation-wins, lease recovery, stale Redis pending-entry recovery, complete process-tree cleanup, and manifest-last versioned publication. A real PostgreSQL gate applied `0001_g5_foundation` plus `0002_g6_outbox_counter`, published exactly nine artifacts, and recovered from dispatch counts above 100.
<!-- ste-preserve:end -->

Passing G7 end-to-end service path:

```sh
make init-env
make service-up
make service-smoke
make service-down
```

<!-- ste-preserve:start historical G7 observed service results -->
The service gate proved:

- `/healthz`, private `/readyz`, and bearer-token enforcement;
- protected endpoints reject absent or invalid credentials;
- `POST /v1/builds` returns `202` before Blender completes;
- polling reports valid state transitions;
- successful artifacts download and hash correctly;
- identical idempotency key/request returns the original build;
- the same key with a different request returns `409`;
- cancellation plus the already-gated timeout/retry lifecycle, live stale-claim recovery, and dead-letter behavior;
- API restart preserves durable state; G6 process/lease tests and the live Redis claim gate cover interrupted-worker recovery;
- partial artifacts never appear successful;
- one-shot and service artifacts retain contract and structural parity;
- worker concurrency remains one;
- core Compose starts without `OPENAI_API_KEY` or another provider key;
- Blender receives no service credential, while the supervisor has only allowlisted internal access and no public-internet egress.

Observed G7 proof on August 3, 2026:

- a new submission returned `202` in `0.071811` seconds, later succeeded, and exposed exactly nine version-pinned artifacts totaling `21,521,731` bytes;
- the service manifest SHA-256 was `89dfe2713ac4cdd7f3884fd81e559bcec9a7f7e0af692c5509bb05baa9c7c522`;
- exact replay returned the original build, a conflicting replay returned `409`, a sibling build canceled, and the successful build remained available across API restart;
- a second fresh Blender process reloaded the downloaded `.blend`, re-imported GLB/STL, and passed the published artifact verifier; direct and service outputs retained the same canonical/structural contract;
- runtime inspection found one worker, a read-only non-root service boundary, no Docker socket, no provider key, loopback-only host ports, and no public route from the worker network;
- `G7_REDIS_GATE` recovered a 60,000 ms stale pending entry and produced one dead-letter containing only `build_id`;
- `G7_IAM_GATE` required five PostgreSQL operations to fail with SQLSTATE `42501` and two MinIO operations to fail with `AccessDenied`;
- the complete Python regression run discovered 157 tests, passed 156 on macOS, and skipped only the Linux `/proc` case that already passed separately in the release image.

Ignored local evidence is under `build/service-smoke/run.Lw4H0h/`, including direct and service artifact trees plus `g7-service-summary.json`. Credentials, signed URLs, request bodies, and child logs are absent from the summary. `make service-down` preserves the PostgreSQL, Redis, and object-storage volumes.
<!-- ste-preserve:end -->

## 10. T4 — VPS, slicer, and physical-print tests

<!-- ste-preserve:start historical G8 topology and recovery results -->
G8 passed locally. The gate validated the merged VPS topology, Caddy 2.11.4
configuration, digest-only release locks, root trust and operator locking,
authenticated internal readiness, one deployment namespace, bounded resources
and logs, distinct private/public S3 endpoints, least-privilege maintenance,
retention, quiesced backup, empty-target restore, Redis reconstruction, and the
target-bound forward-only upgrade handoff.

The final isolated recovery run restored 72 exact-version artifacts totaling
172,159,264 bytes, remapped all 72 version IDs, reconstructed one Redis item,
deleted nine exact versions during retention, left the source database
unchanged, restarted the source service, exposed no target host port, and
removed the disposable target. The final IAM gate proved ten PostgreSQL and
three storage denials. Evidence is recorded in `docs/progress.md`; ignored run
outputs are under `build/g8-recovery/` and `build/service-smoke/`.
<!-- ste-preserve:end -->

A live deployment must have owner-supplied infrastructure and explicit authorization.
Local success does not establish DNS, ACME issuance, firewall, provider IAM/egress,
off-host backup, or public HTTPS behavior.

Slicer and physical-print trials give separate conditional evidence.
The owner must supply the exact printer technology, material, nozzle/resin,
layer profile, orientation, support strategy, and calibration data.
These trials do not prevent geometry-only v0.1 completion.
They cannot give a print warranty.

## 11. T5 — release candidate

Run G9 from the final intended Git index:

```sh
make release-static
HBCB_RELEASE_RUN_ID=<unique-safe-id> make release-check
```

The static gate exports the Git index. Files and modes must agree exactly.
It rejects tracked secrets, environment files, credentials in URLs, personal paths,
unsafe symlinks or modes, backups, generated output, and excessive binary sizes.
Then it validates licenses, the CC0 preview manifest, workflows, SBOM inputs, and release tools.

The full gate uses a second clean indexed export.
It must pass the demo and new-process verifier, ordinary and real-Blender tests,
asynchronous service, IAM/Redis, and VPS/Caddy/recovery checks.
It must also pass builder/API/worker SPDX generation, normalized local image evidence,
deterministic source/sample package creation, and SHA-256 validation.
These gates use no remote operation.

Give each run a unique ID under `build/release-check/<run-id>/`.
The historical evidence below used `g9-final`.
Do not use that ID again.
External GitHub-hosted CI, license detection, registry publication/digests,
Release publication, and a live VPS are conditional operator checks.

<!-- ste-preserve:start historical security reporting activation -->
GitHub private
vulnerability reporting was enabled and verified on August 4, 2026.
<!-- ste-preserve:end -->

Public OCI publication is also blocked.
The current inventory covers only project and Blender source.
It sets `public_oci_ready: false` until review of the actual final image completes
all applicable native, base-image, and copyleft source/delivery obligations.
The publication transaction must also support the derived PostgreSQL image.
This includes inventory, SBOM, signing, publication, and digest-lock support.
See `docs/oci-publication.md`.

<!-- ste-preserve:start historical G9 measured results and release bundle -->
The historical final G9 index passed the complete gate on August 3, 2026. The staged
rehearsal covered 23 release tests, 64 builder unit/contract/container/security
tests, 121 service tests, 49 deployment/recovery tests, real Blender G2/G3
generation and fresh-process verification, a live HTTP-to-Blender service build,
Redis recovery, ten PostgreSQL and three storage denials, and the isolated G8
backup/restore/retention drill. The service returned nine exact-version artifacts
totaling 21,517,610 bytes, with no provider key in Blender and no public worker
egress. The SBOM stage produced three SPDX documents—a 166-package builder SBOM
and separate 26-package API and worker SBOMs—plus the reviewed service notices.

The release bundle contains the 210-file audited source tree, the nine-file
Blender sample, normalized `linux/amd64` evidence for three distinct images, and
verified `SHA256SUMS`. The source archive contains only regular files and
directories with normalized `0644`/`0755` modes. Exact indexed-tree byte count,
hashes, image identities, gate summaries, artifacts, and checksums are kept in
the ignored machine-readable `g9-final` evidence rather than copied into this
indexed file, which would recursively change the candidate it describes.
<!-- ste-preserve:end -->

## 12. Security tests

- Scan tracked files and history for secrets and personal paths.
- Make sure that Git ignores `.env` and that `.env.example` contains only placeholders.
- Make sure that logs, manifests, images, diagnostics, and delivered artifacts contain no secrets.
- Use a canary service credential to show that Blender does not inherit it.
- Make sure that no Docker socket, SSH agent, device, home directory,
  repository root, or arbitrary host path is mounted.
- Make sure that the one-shot container has no network access.
- Make sure that the Compose worker has only internal-service access and no public route.
- Make sure that API/MinIO host ports bind only to loopback.
- Reject Python, shell fragments, paths, URLs, add-ons, environment variables,
  Blender flags, extra properties, traversal, symlinks, excessive payloads, and decompression abuse.
- Validate the pinned Blender checksum, release image digest, and SBOM.
- Do dependency, container, and license scans.
- Make sure that CI is safe for forks and uses minimum permissions.

## 13. Platform matrix

| Platform | Target | Required coverage |
|---|---|---|
| Linux `amd64` | Release-blocking | Builder image, quickstart, service, security, and release checks |
| macOS Apple Silicon + Docker Desktop | Manual evaluator path | Quickstart and verification. Record emulation and timing |
| Native macOS Blender 4.5 | Contributor path | Native engine and Blender integration tests |
| Native Linux `amd64` Blender 4.5 | Reference contributor path | Native engine and integration tests |
| Linux `arm64` | Best effort | No support claim until checksum-pinned Blender distribution passes |
| Windows/WSL2 | Owner decision | Experimental until Make, mounts, UID/GID, demo, and verification pass |

A platform has no support claim until its test record is available.
This matrix covers v0.1 generation. The [read-only review preview](docs/review-preview.md) has a separate platform scope.

## 14. Failure report template

```markdown
### Test ID

### Commit and image digest

### Environment
- OS/architecture:
- Docker/Compose:
- Blender:
- CPU/RAM:

### Exact command
Redact credentials and signed URLs.

### Expected result

### Actual result

### Exit code, duration, and resource use

### Reproduction steps

### Evidence
Manifest, QA, checksums, screenshots, and sanitized logs.

### Severity
Release-blocking / regression / documentation / platform-specific

### Suspected component
Schema / generator / exporter / QA / container / API / supervisor / storage / security
```

## 15. Release verdict

Local v0.1 has status `PASS` only when all these conditions are true:

- every G0–G9 locally verifiable gate is recorded as passed.
- a clean indexed source export passes `make demo && make verify-demo`.
- two requests give different schema-driven geometry.
- artifact, authenticity, geometry, and print-QA checks pass.
- `make service-smoke`, `make orphan-minio-check`, `make security-check`, and a uniquely named full `make release-check` pass.
- the local `linux/amd64` image gates pass without repository secrets. Native
  GitHub-hosted Linux CI remains a conditional publication check.
- no mandatory test has status failed, blocked, unimplemented, or skipped without an explanation.
- external-only VPS and physical-print checks are explicitly conditional.
- no secret, local path, generated backup, or large binary is tracked.
