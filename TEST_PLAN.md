# Feature Testing and Owner Review Plan

Status: **living verification plan; G0–G4 passed, G5–G9 pending**

Last updated: **August 3, 2026**

## 1. Purpose and authority

`PLAN.md` defines what v0.1 must build. This document defines how an owner or independent reviewer proves those requirements. If the documents conflict, `PLAN.md` remains authoritative until both are intentionally updated.

A test passes only when its documented command actually runs successfully and leaves reviewable evidence. Use these statuses:

- `PASS` — expected behavior was observed and evidence was recorded.
- `FAIL` — behavior differed from the contract.
- `BLOCKED` — the implementation exists, but an external prerequisite is unavailable.
- `NOT_IMPLEMENTED` — the feature has not been built yet; this is the correct initial status for most v0.1 tests.
- `CONDITIONAL` — an optional live VPS, slicer, physical-print, or other external test.
- `NOT_APPLICABLE` — the test does not apply to the selected platform or mode.

Do not call an unimplemented feature blocked, and do not mark a gate passed from documentation or mock artifacts alone.

## 2. Current state

Work packages G0 through G4 have passed. The repository contains strict `BuildRequest`, `CharacterSpec`, QA, and manifest contracts plus a generic `geometric-character@1.0.0` registry/core. Two original requests generate real, materially different Blender geometry with stable structural fingerprints. The trusted builder saves `.blend`, exports display GLB and a raw-millimeter binary STL, renders four PNGs, measures complete geometry QA, verifies the model formats in a second fresh Blender process, and atomically publishes a success manifest last.

The G4 `linux/amd64` image, narrow `builder build|verify` CLI, hardened one-shot Docker runtime, keyless Make targets, native fallback, baked provenance, notices, and SPDX SBOM are implemented and passed from a clean indexed source export. G5 and later remain unimplemented: no API, Compose service, VPS package, or release CI exists yet. The local research workspace still contains an excluded hardcoded branded proof of concept; it is preserved baseline material, not v0.1 acceptance evidence.

Known local reviewer environment:

| Component | Observed value |
|---|---|
| Host | macOS on Apple Silicon (`arm64`) |
| Blender | 4.5.12 LTS |
| Docker client/server | 29.4.0 / 29.4.0; Docker Desktop Linux `arm64` host |
| Make | GNU Make 3.81 |
| GitHub CLI | Not installed; the initial publication uses the authorized GitHub connector instead |

## 3. What I need from the owner

### Initial GitHub publication (completed)

- [x] Create the public repository at <https://github.com/joseph-robert-f/headless-blender-character-builder>.
- [x] Confirm the authorized GitHub connector has administrator and push access.
- [x] Use `main` as the default branch.

The repository and project/package slug are both `headless-blender-character-builder`. Installing and authenticating the GitHub CLI is optional for the initial connector-backed publication, but contributors will still need Git or an equivalent GitHub client for normal clone, branch, and pull-request work.

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
- [ ] OpenAI API key only if the optional post-v0.1 prompt planner is later enabled; it is not needed for the deterministic release.

## 4. Evidence rules

For every executed test, record:

- test ID, date, reviewer, and result;
- commit SHA and builder image ID or digest;
- OS/architecture plus Docker, Compose, Make, and Blender versions;
- exact redacted command, exit code, and elapsed time;
- expected versus actual behavior;
- manifest, QA, sanitized logs, hashes, and artifact locations;
- issue link for every failure.

Published build/test evidence normally belongs under this ignored path:

```text
build/test-evidence/<commit-or-tree-hash>/<test-id>/
```

The explicit native G2 and G3 harnesses are exceptions: they require caller-owned new temporary directories outside the repository so integration probes and generated artifacts cannot pollute or overwrite source. Record those temporary paths and durable result summaries in `docs/progress.md`; do not commit generated JSON or model artifacts.

Record milestone summaries in `docs/progress.md` once implementation begins. Never attach `.env`, credentials, tokens, private references, signed URLs, or unredacted environment dumps.

## 5. Test sequence

| Stage | PLAN dependency | Current status | Release purpose |
|---|---|---|---|
| T0 — repository and documentation | G0 | `PASS` locally | Prove the public scaffold contains only intended, safe files |
| T1 — schemas, generic engine, and artifacts | G1–G3 | `PASS` | Prove bounded requests create and independently verify real, varied Blender geometry |
| T2 — keyless container quickstart | G4 | `PASS` | Prove the primary public experience from a clean source tree |
| T3 — asynchronous service | G5–G7 | `NOT_IMPLEMENTED` | Prove durable API, queue, worker, auth, and artifacts |
| T4 — VPS and recovery | G8 | `NOT_IMPLEMENTED` / `CONDITIONAL` | Prove deployability without making live infrastructure mandatory |
| T5 — release candidate | G9 | `NOT_IMPLEMENTED` | Prove tests, security, licenses, docs, and packaging together |

Do not execute later stages to compensate for a failed dependency gate.

## 6. T0 — repository publication tests

### PUB-01: intentional source set

From the repository root:

```sh
git status --short
git ls-files
git remote -v
```

Pass when only the intentional planning/publication files are tracked, no generated model/media or backup is present, and `origin` is the expected GitHub repository.

### PUB-02: local-path and secret scan

```sh
rg -n '/Users/|/home/|file://|BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9_-]+' \
  --hidden -g '!.git/**' .
```

Review every result. Documentation examples may mention prohibited patterns, but no real personal path, credential, signed URL, or private value may be tracked. Enable GitHub secret scanning and push protection after publication.

### PUB-03: truthful documentation

Verify that README:

- labels the repository planning/prototype status;
- reports the current passed milestone and distinguishes implemented Docker/artifact paths from the pending API, Compose, VPS, and release work;
- links `PLAN.md`, this test plan, security, contribution, and license documents;
- distinguishes required no-key operation from optional future credentials;
- states IP, security, and physical-print limitations.

### PUB-04: license and policy files

Verify GPL-3.0-or-later is detected for source and `ASSET_LICENSE.md` states that no sample asset is initially included. Confirm `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SUPPORT.md` render correctly on GitHub.

## 7. T1 — schema, engine, and authenticity tests

ENG-01 through ENG-06 are runnable and passed after G1–G3.

Current contract and engine commands:

```sh
python3.11 -m unittest discover -s tests -v

python3 tests/blender_integration/g2_gate.py \
  --blender /absolute/path/to/blender \
  --evidence-dir /absolute/path/to/new-temporary-directory

python3 tests/blender_integration/g3_gate.py \
  --blender /absolute/path/to/blender \
  --work-dir /absolute/path/to/dedicated-temporary-directory
```

| ID | Status | Required proof |
|---|---|---|
| ENG-01 | `PASS` | Valid `BuildRequest v1` and nested `CharacterSpec v1` fixtures pass; extra properties, incompatible presets, and hostile fields fail before Blender starts |
| ENG-02 | `PASS` | Two materially different requests build from factory startup through the same generator |
| ENG-03 | `PASS` | Repeated requests retain the same canonical hashes and structural fingerprint without requiring byte-identical `.blend` or PNG files |
| ENG-04 | `PASS` | Fresh-process `.blend` reload succeeds and enumerates real mesh objects, vertices, faces, materials, transforms, and three-dimensional bounds |
| ENG-05 | `PASS` | Front, side, and back diagnostics come from the saved scene; PNG structure/variation, real geometry, and absence of external texture dependencies are checked |
| ENG-06 | `PASS` | GLB and STL re-import into clean scenes and match evaluated `.blend` bounds within the greater of 0.2 mm or 0.5% per axis |

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

Artifact verification must confirm:

- both JSON files validate against versioned schemas;
- every non-manifest artifact byte count and SHA-256 hash recomputes correctly;
- evaluated triangles do not exceed 500,000;
- STL is one connected watertight shell with positive volume and outward normals;
- non-manifold edges and zero-area faces equal zero;
- coordinates and transforms are finite;
- minimum wall thickness is at least 1.2 mm;
- freestanding features and connections are at least 2.0 mm;
- unmeasurable mandatory geometry becomes `needs_review`, not `succeeded`.

Final G3 evidence is under `/private/tmp/hbcc-g3-final-topology.PMFshx/`. Facet Bot published the exact tree twice with matching stable probe SHA-256 `726060b092c8168e0a57477116a4c715e1b6f21d48c6d65fe7ca2be500652ccc`. Its STL has 316,172 triangles, one face-connected closed positive shell, zero non-manifold edges or vertices, and conservative lower bounds of 2.3001 mm wall and 2.3089 mm feature. A synthetic pair of closed tetrahedra touching at one bow-tie vertex proves production QA rejects vertex-pinched shells. Moss Hopper intentionally exits `11` as `needs_review` and publishes nothing because its wall evidence is ambiguous. Invalid CLI, oversized/invalid/unresolvable input, an existing caller-owned output, and a corrupted private STL also followed their fixed failure contracts without publishing success.

## 8. T2 — zero-key single-container quickstart

G4 passed these tests on August 3, 2026, from a temporary `git checkout-index` export containing 94 tracked files. The release image ran as `linux/amd64` under Docker Desktop emulation; no registry login, `.env`, provider key, Compose stack, host Blender, database, queue, or object store was available to the container path.

Golden commands:

```sh
make demo
make verify-demo
```

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

Human Blender inspection is useful optional evidence: open a copy of `model.blend`, hide or move a component, and inspect solid/wireframe views. It never replaces the automated tests.

## 9. T3 — asynchronous Compose service

These tests become runnable after G7.

```sh
make init-env
make service-up
make service-smoke
make service-down
```

The service gate must prove:

- `/healthz`, private `/readyz`, and bearer-token enforcement;
- protected endpoints reject absent or invalid credentials;
- `POST /v1/builds` returns `202` before Blender completes;
- polling reports valid state transitions;
- successful artifacts download and hash correctly;
- identical idempotency key/request returns the original build;
- the same key with a different request returns `409`;
- cancellation, timeout, crash, lease expiry, retry, and dead-letter behavior;
- API and supervisor restarts preserve durable state;
- partial artifacts never appear successful;
- one-shot and service artifacts retain contract and structural parity;
- worker concurrency remains one;
- core Compose starts without `OPENAI_API_KEY` or another provider key;
- Blender receives no service credential, while the supervisor has only allowlisted internal access and no public-internet egress.

## 10. T4 — VPS, slicer, and physical-print tests

VPS packaging is locally release-blocking after G8; a live deployment is conditional on owner-supplied infrastructure and authorization. Validate configuration, TLS/auth instructions, resource caps, retention, backup/restore, and upgrade/rollback locally before any live smoke test.

Slicer and physical-print trials are separate conditional evidence. They require the owner's exact printer technology, material, nozzle/resin, layer profile, orientation, support strategy, and calibration data. They do not block geometry-only v0.1 and cannot create a print warranty.

## 11. Security tests

- Scan tracked files and history for secrets and personal paths.
- Confirm `.env` is ignored and `.env.example` contains placeholders only.
- Confirm secrets never appear in logs, manifests, images, diagnostics, or delivered artifacts.
- Use a canary service credential to prove Blender does not inherit it.
- Confirm no Docker socket, SSH agent, device, home directory, repository root, or arbitrary host path is mounted.
- Confirm one-shot has no network; Compose has no public egress and only allowlisted internal access.
- Reject Python, shell fragments, paths, URLs, add-ons, environment variables, Blender flags, extra properties, traversal, symlinks, oversized payloads, and decompression abuse.
- Verify pinned Blender checksum, release image digest, SBOM, dependency/container/license scans, and fork-safe least-privilege CI.

## 12. Platform matrix

| Platform | Target | Required coverage |
|---|---|---|
| Linux `amd64` | Release-blocking | Builder image, quickstart, service, security, and release checks |
| macOS Apple Silicon + Docker Desktop | Manual evaluator path | Quickstart and verification; record emulation and timing |
| Native macOS Blender 4.5 | Contributor path | Native engine and Blender integration tests |
| Native Linux `amd64` Blender 4.5 | Reference contributor path | Native engine and integration tests |
| Linux `arm64` | Best effort | No support claim until checksum-pinned Blender distribution passes |
| Windows/WSL2 | Owner decision | Experimental until Make, mounts, UID/GID, demo, and verification pass |

A platform is unsupported until a test record is attached.

## 13. Failure report template

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

## 14. Release verdict

Local v0.1 is `PASS` only when:

- every G0–G9 locally verifiable gate is recorded as passed;
- a clean indexed source export passes `make demo && make verify-demo`;
- two requests prove genuinely varied schema-driven geometry;
- artifact, authenticity, geometry, and print-QA checks pass;
- `make service-smoke`, `make security-check`, and `make release-check` pass;
- Linux `amd64` CI passes without repository secrets;
- no required test is failed, blocked, unimplemented, or silently skipped;
- external-only VPS and physical-print checks are explicitly conditional;
- no secret, local path, generated backup, or large binary is tracked.
