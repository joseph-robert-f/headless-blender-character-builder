# v0.1 Build Progress

Last updated: 2026-08-03

Overall status: **in progress**

| Work package | Milestone | Status | Gate evidence |
|---|---|---|---|
| G0 | M0 foundation | passed | Baseline verified; defaults, neutral brief, ignores, preservation hashes, and intentional indexed source set audited |
| G1 | M1 contracts | passed | Four Draft 2020-12 schemas and immutable runtime models; 47 schema/policy tests plus independent final audit passed |
| G2 | M1 generator | passed | Generic registry/core plus two factory-start fixtures; four-process structural, topology, and determinism gate passed |
| G3 | M1 artifacts and QA | passed | Exact nine-file artifact publication, actual-shell QA, fresh reload/re-import, repeat, and fail-closed paths passed |
| G4 | M2 one-shot container | passed | Clean indexed source built and verified twice in a keyless hardened container; native parity, provenance/SBOM, exit contracts, and 62 clean-source tests passed |
| G5 | M3 persistence interfaces | passed | Postgres migration/constraints, transactional outbox semantics, Redis build-ID contract, version-bound storage, scoped generated config, 55 service tests, and real PostgreSQL 16.9 gate passed |
| G6 | M3 API and worker | passed | Auth-first bounded FastAPI, durable fenced worker lifecycle, exact immutable publication, stale-queue/outbox recovery, 154-test repository suite, Linux process-tree gate, and real PostgreSQL 16.9 gate passed |
| G7 | M3 Compose service | passed | Hardened local stack, convergent scoped identities, real HTTP-to-Blender smoke, restart/idempotency/cancellation, Redis recovery, seven IAM denials, and direct/service parity passed |
| G8 | M4 VPS package | pending | — |
| G9 | M5 release candidate | pending | — |

## Evidence log

### G0 — baseline and foundation

Files and contracts introduced:

- `docs/inventory.md` preserves file hashes, sizes, reusable-code notes, and baseline verification;
- `docs/decisions.md` records Section 17 defaults and execution conditions;
- `docs/facet-bot-brief.md` defines the neutral original example;
- this file establishes the package-by-package gate log.

Verification executed:

| Command | Result |
|---|---|
| Native Blender 4.5.12 fresh reload of `codex_self_portrait.blend` with `verify_codex_avatar.py` | exit `0`; `CODEX_AVATAR_VERIFICATION: PASS` |
| Native Blender 4.5.12 fresh reload of `codex_self_portrait_turntable.blend` with `verify_turntable_animation.py` | exit `0`; `TURN_TABLE_VERIFICATION: PASS` |
| SHA-256 and byte inventory of baseline scripts/models/renders | exit `0`; recorded in `docs/inventory.md` |

Evidence locations:

- ignored baseline artifacts remain in the workspace root;
- temporary smoke/audit renders were written under the operating-system temporary directory;
- source inventory and hashes are durable in `docs/inventory.md`.

Deviation/condition:

- A public `origin` was explicitly authorized and configured before this build goal; see the recorded execution conditions in `docs/decisions.md`. No new remote publication is authorized by this goal.

Gate verification:

| Command | Result |
|---|---|
| `git diff --cached --check` | exit `0` |
| `git ls-files` publication-source inventory | exit `0`; 16 intended text/policy files, no generated model/media or backup |
| `git check-ignore -v` against preserved scripts/models/renders/research | exit `0`; every baseline input remains ignored |
| tracked/intended-source credential and personal-path scan | exit `0`; only the documented regex example matched |
| Markdown fence-count audit | exit `0`; every nonzero count is even |
| baseline SHA-256 recheck | exit `0`; all 16 recorded source/artifact hashes unchanged |

G0 gate result: **passed**. G1 contract implementation may begin.

### G1 — versioned contracts and policy validation

Files and contracts introduced:

- `schemas/` contains Draft 2020-12 `BuildRequest`, `CharacterSpec`, QA, and success-manifest schemas;
- `shared/` contains strict JSON decoding, bounded canonicalization/hashing, immutable request/spec, QA, and manifest models;
- `examples/requests/` contains the original `facet-bot` and materially different `moss-hopper` requests;
- `tests/fixtures/rejected/` contains 11 hostile or invalid requests;
- `tests/unit/` and `tests/contract/` cover runtime semantics, schema execution, local `$ref` resolution, hostile inputs, defaults, hashes, QA status, and manifest policy;
- `pyproject.toml` defines Python 3.11+, the GPL project package, and pinned `jsonschema==4.26.0` test extra;
- `docs/character-spec.md` documents the implemented contract and contributor test path;
- Decisions D-015 through D-021 record identifiers, hashing, QA authority, units, Python support, and exact Blender provenance.

Verification executed:

| Command | Result |
|---|---|
| Temporary Blender-Python 3.11 venv plus `python -m pip install jsonschema==4.26.0` | exit `0`; pinned Draft 2020-12 validator installed outside the repository |
| `PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests -v` | exit `0`; 47 tests passed, including metaschema checks and local `$ref` resolution |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.contract.test_json_schemas tests.unit.test_request_contract tests.unit.test_quality_manifest -v` | exit `0`; 41 standard-library/runtime tests passed on system Python 3.9 |
| Native Blender factory-startup query of `bpy.app.version_string` | exit `0`; exact value `4.5.12 LTS` accepted by manifest schema/runtime |
| Strict JSON/Python/TOML compile and Markdown fence audit | exit `0`; all intended source documents parsed and fences were balanced |
| Intended-source personal-path, private-key, AWS-key, and provider-key scan | exit `0`; no match outside deliberate plans/inventory/rejection fixtures |
| Independent final G1 gate audit | `PASS`; 47/47 required tests, schema/runtime parity, immutability, packaging, and publication scope confirmed |

Deterministic request evidence:

| Example | Canonical request SHA-256 | Canonical spec SHA-256 |
|---|---|---|
| `facet-bot.json` | `d1a549e1ee667b3c8e841e2bf2337ae1293ee3ab478949c3801543fee700fb23` | `ec6c66e75eb94a46c0b99ffd5b993a02f9fba9436e77db3952a9f40e87e9ff7f` |
| `moss-hopper.json` | `7e5464c54478398b0e0bc4b37c6be96dd454cac224fa266a797a259880724dcb` | `83c02355356ddeaee33112512d38417808408d441aaab6d91bb0b230d7c91253` |

Security and policy outcomes:

- the complete request is limited to 64 KiB before parsing;
- duplicate keys, invalid UTF-8, non-finite/pathological numbers, extra fields, paths, URLs, code, Blender flags, unsafe slugs, and duplicate allowlist values fail before Blender;
- mandatory unknown QA maps to `needs_review`, exit `11`, with no success manifest;
- `passed` requires measurable evidence, at least four triangles, one object/material, bounded counts, one shell, zero non-manifold/zero-area findings, and all mandatory checks true;
- requested height and GLB/STL round trips use the greater of 0.2 mm or 0.5% tolerance;
- success manifests allow exactly eight hashed artifacts, exclude their own hash, and enforce the aggregate 2 GiB runtime budget.

Deviation/condition:

- JSON Schema handles portable structure and directly expressible pass constraints. `QualityReport` remains normative for cross-field tolerance arithmetic and exact terminal-status derivation, as recorded in D-017. Both layers have executable tests.

G1 gate result: **passed**. G2 generic scene and generator implementation may begin.

### G2 — deterministic generic Blender generator

Files and contracts introduced:

- `blender/core/` contains millimeter primitives, bounded native materials, factory-scene setup, printable-shell derivation, and canonical structural evidence;
- `blender/generators/registry.py` exposes the closed `generate_character(BuildRequest) -> GenerationResult` registry API;
- `blender/generators/geometric_character_v1/` composes the schema controls into separate semantic display components and one voxel-unioned printable shell;
- `tests/blender_integration/g2_probe.py` inspects real source/evaluated Blender meshes, procedural materials, collections, roles, topology, dimensions, and hashes inside Blender;
- `tests/blender_integration/g2_gate.py` launches both examples twice in four isolated processes and compares only declared stable evidence;
- `pyproject.toml` now packages both `shared*` and `blender*` modules;
- Decisions D-022 through D-025 record the display/print split, structural determinism evidence, pre-scene semantic rejection boundary, and mutually exclusive tail presets.

Implemented scene contract:

- exact top-level collections `CAMERAS`, `CHARACTER`, `LIGHTS`, `PRINT`, and `SET`;
- material-bearing procedural display meshes only in `CHARACTER` and exactly one hidden `PrintableShell` only in `PRINT`;
- total requested height includes the base; display base dimensions are exact;
- deterministic semantic component roles/presets, bounded scene counts, no images, external textures, fonts, paths, network calls, saves, exports, or rendering;
- schema-valid but impossible height/base layouts are rejected before factory reset or scene mutation.

Verification executed:

| Command | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests -v` | exit `0`; all 48 contract/runtime tests passed |
| `PYTHONPYCACHEPREFIX=/private/tmp/hbcc-g2-compile-cache /Applications/Blender.app/Contents/Resources/4.5/python/bin/python3.11 -m compileall -q -f blender tests/blender_integration shared` | exit `0`; all G2 and shared Python parsed under Blender's Python 3.11 |
| `PYTHONDONTWRITEBYTECODE=1 python3 tests/blender_integration/g2_gate.py --blender /Applications/Blender.app/Contents/MacOS/Blender --evidence-dir /private/tmp/hbcc-g2-index-gate.wVkbjR --timeout-seconds 900` | exit `0`; `G2_BLENDER_INTEGRATION: PASS` across four fresh Blender 4.5.12 LTS processes from the final staged source |
| `cmp -s /private/tmp/hbcc-g2-index-gate.wVkbjR/facet-bot-run-1.json /private/tmp/hbcc-g2-index-gate.wVkbjR/facet-bot-run-2.json` and the equivalent `moss-hopper` comparison | both exited `0`; each fixture's declared stable report was byte-identical across fresh processes |

Deterministic geometry evidence:

| Example | Structural fingerprint | Geometry signature | Character + print triangles | Requested / observed height |
|---|---|---|---:|---:|
| `facet-bot` | `3169d1d4ed734038990e9433b8d27a2f61bbd7f48c2ea3a5e43461087c5957cc` | `462e1165793489cb21a22f5c229bbf908778a5f7ca9c6885c38529dc332c9ef9` | 320,672 | 95 / 94.984509 mm |
| `moss-hopper` | `b520ad9a6dad96e567c14bdc1237f9677f9dc17d9e76643a119c64d23c4b1178` | `aa7932f058e2d9b964bb5e852298d0e95bfac865f24657d2978389724eaddce6` | 318,786 | 125 / 125 mm |

Both print shells have one face-connected and vertex-connected component, zero boundary edges, zero non-manifold edges or vertices, zero non-contiguous edges, zero near-zero-area faces, and positive signed volume. Display bounds are exactly `52 × 52 × 95 mm` and `68 × 58 × 125 mm`; requested versus evaluated base dimensions differ by at most `0.000005 mm`, and printable bounds remain within the Section 8 tolerance. The fixtures differ in topology, object/role inventory, dimensions, pose, style, components, and palette rather than recoloring one hardcoded mesh.

Evidence location:

- `/private/tmp/hbcc-g2-index-gate.wVkbjR/` contains the final four path-free run reports and `g2-summary.json` with explicit base-dimension, face/vertex connectivity, boundary, manifold-vertex, winding, area, and volume evidence;
- `/private/tmp/hbcc-g2-consistency-final.4jcrX1/` contains an independent exact-source gate rerun whose five reports are byte-identical to the final primary evidence;
- generated evidence remains outside the publication tree.

Iteration and remaining risk:

- The first full probe correctly rejected detached `moss-hopper` top components. Their reviewed attachment depth was increased, after which both fixtures passed one-shell topology and repeatability checks.
- Independent generic-domain review found that selecting both tail presets could collide after scene creation. JSON Schema, runtime validation, and generator preflight now reject that pair before Blender mutation; a hostile fixture and regression test cover the rule.
- The final independent re-audit covered every compatible style/pose/eye/base/component composition for construction/name safety and built real low-poly, heroic, visor, square-base, no-base, horn, round-ear, and stub-tail variants not present in the two release fixtures; no further G2 blocker remained.
- Print-focused review found that the initial brief described future STL measurements as current facts and that base dimensions, face-connected shells, boundary edges, and manifold vertices were observed but not gate assertions. The brief now labels those measurements as G3 targets, and the strengthened inner/outer gate asserts and emits each G2-measurable property.
- G2 records construction-time feature minima but does not yet claim measured wall/accessory thickness. G3 must add authoritative geometry measurements, saving, rendering, GLB/STL export, fresh reload, and re-import checks before any build can publish passing QA.

G2 gate result: **passed**. G3 artifact, render, export, and complete QA implementation may begin.

### G3 — artifacts, rendering, complete QA, and fresh verification

Files and contracts introduced:

- `blender/runner.py` exposes only `--request PATH --output PATH` after Blender's `--` boundary, validates before scene creation, and maps the fixed application exits;
- `blender/core/camera.py`, `blender/render/`, and `blender/exporters/` create four fixed 512 px/32-sample renders, save a relative-path `.blend`, export display-only GLB, and export one binary raw-millimeter STL;
- `blender/qa/geometry.py` measures topology, every final-shell triangle for conservative wall evidence, and actual `PrintableShell` semantic cross-sections for feature evidence;
- `blender/verifier.py` runs in a second fresh Blender process and independently reloads `.blend` plus re-imports GLB/STL;
- `tests/blender_integration/g3_gate.py`, `g3_artifact_probe.py`, and `g3_qa_regression.py` validate contracts, hashes, provenance, PNG/GLB/STL framing, dimensions, topology, external-resource absence, repeat stability, failure publication rules, and rejection of vertex-pinched shells;
- Decisions D-026 through D-030 record atomic publication, actual-shell thickness evidence, palette persistence, diagnostic lighting, and face-connected/manifold-vertex shell semantics.

Implemented artifact contract:

```text
model.blend
model.glb
model.stl
preview.png
diagnostics/front.png
diagnostics/side.png
diagnostics/back.png
qa.json
manifest.json
```

The output must not already exist. A mode-`0700` sibling stage is atomically renamed only after mandatory QA passes, the child verifier succeeds, `qa.json` validates, and the success manifest is written last. Private verifier evidence is removed before publication. Failure removes staging and never publishes a manifest.

Verification executed:

| Command | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests -v` | exit `0`; all 48 contract/runtime tests passed |
| `PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python tests/blender_integration/g3_gate.py --blender /Applications/Blender.app/Contents/MacOS/Blender --work-dir /private/tmp/hbcc-g3-final-topology.PMFshx --timeout-seconds 1800` | exit `0`; `G3_BLENDER_INTEGRATION: PASS` on the final audited source after bounded request reading, explicit exit-contract coverage, and production topology hardening |
| Native visual review of the four final Facet Bot PNGs | passed; preview/front/side/back are distinct, framed, path-free 512 px geometry renders without intersection-shadow stippling |
| Independent pre-fix G3 gate at `/private/tmp/hbcc-g3-final.je4GsE` | exit `0` in approximately 82.1 seconds; independently confirmed the same geometry/QA/failure invariants |

Final Facet Bot evidence:

| Property | Observed result |
|---|---:|
| Evaluated printable dimensions | `51.9795 × 51.9795 × 94.9845 mm` |
| Display GLB dimensions | `52 × 52 × 95 mm` |
| Total evaluated scene triangles | `320,672` |
| Binary STL triangles | `316,172` |
| Wall lower bound | `2.3001 mm` |
| Semantic feature lower bound | `2.3089 mm` |
| Connected shells / non-manifold edges / non-manifold vertices / zero-area faces | `1 / 0 / 0 / 0` |
| Stable repeat probe SHA-256 | `726060b092c8168e0a57477116a4c715e1b6f21d48c6d65fe7ca2be500652ccc` |
| First final-run artifact bytes excluding the self-excluded manifest | `21,496,427` |

Both final Facet runs published exactly nine files. Their stable probe evidence, QA fields, dimensions, topology, GLB/STL structure, and manifest stable fields match; binary hashes are recorded but not promised identical. Fresh `.blend` reload, GLB import, and STL import all passed. The independent binary STL reader proved one face-connected and vertex-connected closed shell, two oppositely oriented uses per edge, finite coordinates, outward-consistent normals, and positive volume.

Fail-closed outcomes:

- the hostile request exits `3` before output creation;
- an unsupported CLI option exits `2`, and an oversized request is read only to the 64 KiB contract boundary before exiting `3`;
- a request path whose home expansion cannot resolve exits `4` rather than falling through to an internal-error code;
- a pre-existing caller-owned output exits `4` without modifying its sentinel file;
- a synthetic pair of closed tetrahedra sharing one bow-tie vertex retains zero non-manifold edges but is correctly measured as two face-connected shells with a non-manifold vertex, so the production success predicate rejects it;
- `moss-hopper` measures a passing `2.0719 mm` feature lower bound, but 14 unresolved strict wall candidates plus one ray miss make wall evidence unknown, so it exits `11` as `needs_review` with no output or staging residue;
- a privately truncated STL fails the child verifier and produces neither verifier success evidence nor a manifest;
- no private verifier files appear in a successful tree.

Evidence locations:

- `/private/tmp/hbcc-g3-final-topology.PMFshx/` contains the final current-tree two-run artifact trees, independent probes, topology regression, all negative-path fixtures, corruption fixture, and path-free `g3-summary.json`;
- `/private/tmp/hbcc-g3-final.je4GsE/` contains the independent agent gate evidence;
- both remain outside the publication tree.

Deviation/condition:

- The G3 gate deliberately treats the materially different Moss Hopper fixture as `needs_review` rather than weakening the wall algorithm or claiming a false pass. G2 remains the proof that both specs generate materially different real geometry; G3 proves success publication with Facet Bot and the required mandatory-unknown no-publication path with Moss Hopper.
- Thickness numbers are conservative geometry diagnostics with a two-voxel uncertainty deduction. They are not slicer evidence or a physical-print warranty.

G3 gate result: **passed**. G4 pinned builder image, trusted CLI adapter, hardened one-shot runtime, native fallback, and Make targets may begin.

### G4 — pinned one-shot container, trusted CLI, and native fallback

Files and contracts introduced:

- `docker/builder.Dockerfile` builds the production `linux/amd64` image from a digest-pinned Debian snapshot and the checksum-verified official Blender 4.5.12 LTS archive; its separate test target adds only hash-locked wheels and tracked test inputs;
- `scripts/builder` and `builder_cli/` expose only `builder build --request PATH --output PATH` and `builder verify --request PATH --output PATH`, with bounded input/evidence, a fixed Blender argv/environment, process-group timeout handling, redacted unexpected failures, and the application exit contract;
- `blender/published_verifier.py` freshly loads the published `.blend`, resets and imports GLB/STL, and validates the exact artifact, scene, geometry, topology, hash, provenance, and QA contract;
- `shared/source_revision.py` produces framed, content-addressed native/container source revisions; the image bakes its source revision, Blender version and binary hash, upstream notices, and an SPDX 2.3 SBOM;
- `Makefile` provides the keyless `demo`/`verify-demo`, native fallbacks, isolated test-image targets, and the fixed one-shot runtime envelope;
- `tests/container/` and `tests/security/` verify clean-index builds, Docker command policy, immutable image metadata, canary non-disclosure, exact publication, native parity, fixed exits, repeat stability, and supply-chain evidence;
- Decisions D-031 through D-033 record the atomic parent mount, image supply-chain policy, and tested resource envelope.

Verification executed:

| Command | Result |
|---|---|
| `python3 tests/container/g4_gate.py --work-dir /private/tmp/hbcb-g4-final.ovZDPq --docker docker --make make --git git --blender /Applications/Blender.app/Contents/MacOS/Blender --platform linux/amd64 --timeout-seconds 1800` | exit `0`; `G4_GATE: PASS` from a 94-file `git checkout-index` export |
| clean-export `make demo` followed by `make verify-demo` | exit `0` twice; each build published exactly nine files and each verification used a fresh Blender process |
| clean-export `make test-unit` in the hash-locked test image | exit `0`; all 62 contract, policy, launcher, provenance, and runtime tests passed |
| native `make demo-native` followed by `make verify-demo-native` | exit `0`; no Docker invocation and stable geometry matched both container runs |
| `git diff --check` and staged-source parse checks | exit `0`; no whitespace or Python syntax errors |

Final container and artifact evidence:

| Property | Observed result |
|---|---|
| Production image | `sha256:49cb24b22ea569bfe9db3a7ad5532d1270c765439a7c293515b9e833fb655b13`; 1,094,010,880 bytes; `amd64/linux`; default user `65532:65532` |
| Test image | `sha256:037dd91b8fd95e5bbb7518cf4cf809ad25715ed22cb3fe3e59b0305621b5c290`; 1,095,280,652 bytes |
| Baked Blender provenance | `4.5.12 LTS`; binary SHA-256 `33ac108ebce3c271f5357e5c664d0488717263bcf2145c80300edd0b12c31880` |
| Baked source revision | `4e6f85a64fae06b15fe40787a50becb7aa53d0f96896dca5c26db9314a7e8968` |
| SPDX 2.3 SBOM | 166 packages; SHA-256 `9ca9b78dcd1d8bc41bcc22c9a38eba271b0a925d1fb91e0e0d9b36dd60ba6dd2` |
| Runtime | no network; read-only root; all capabilities dropped; no-new-privileges; 512 PIDs; 4 CPUs; 4 GiB RAM; 2 GiB no-exec tmpfs; exactly request and output mounts |
| Published output | 21,515,028 bytes across the exact nine-file tree; manifest/artifact hashes and fresh `.blend`/GLB/STL checks passed |
| Repeat and native parity | stable probe SHA-256 `726060b092c8168e0a57477116a4c715e1b6f21d48c6d65fe7ca2be500652ccc` for first container, repeat container, and native fallback |
| Application exits | black-box `2`, `3`, `4`, `11`, and `12` passed; unit-isolated `10` and `124` mappings passed; failures published no success output |

Evidence location:

- `/private/tmp/hbcb-g4-final.ovZDPq/` contains canary-scanned local command logs, both container artifacts, the native artifact, independent probes, image/provenance evidence, negative-path evidence, and `g4-summary.json`;
- evidence remains outside the publication tree, while the durable result and immutable identifiers are recorded here.

Deviation/condition:

- The direct-container example now mounts the caller-owned `build/` parent and requests nonexistent `/output/demo`, rather than precreating and mounting `build/demo`. D-031 records why this is required for private sibling staging and atomic publication.
- The release image is intentionally `linux/amd64`. This gate ran it under Docker Desktop emulation on an Apple Silicon host; native Linux `amd64` remains the release-reference CI path for G9.
- The first login-free Docker configuration selected Docker's legacy builder. Removing frontend-only `COPY --chmod` syntax made the same pinned Dockerfile portable to that path; checksum-verified `ADD`, the final permissions, image contents, and runtime policy remain enforced.
- The local Make path records the independently inspected image ID and leaves registry digest null. A later service must inject its separately pinned OCI digest through the reserved supervisor channel.
- No image, release, or source update was pushed remotely.

G4 gate result: **passed**. G5 persistence models, migrations, queue contract, storage interface, MinIO adapter, and generated local configuration may begin.

### G5 — persistence, queue, storage, authorization, and local configuration

Files and contracts introduced:

- `service/src/hbcb_service/` contains immutable build/attempt/artifact/event models, bearer authorization, canonical idempotency fingerprints, role-scoped configuration, a forward-only migration runner, Postgres schema, Redis Streams queue contract, state reference semantics, and local/MinIO-compatible storage adapters;
- PostgreSQL is authoritative for builds, attempts, events, artifact versions, idempotency keys, and the transactional queue outbox; Redis messages contain exactly one canonical build UUID and are only at-least-once wakeups;
- artifact keys are generated from the deployment namespace plus build/attempt UUIDs and the fixed nine-path allowlist; storage publication requires versioning, hashes the exact upload stream and the stored version body, stores the version ID, and signs that exact version;
- invalid object versions are left unreferenced for a separately scoped retention janitor rather than granting the long-lived worker deletion authority;
- `.env.example`, `scripts/init-env`, and `make init-env` provide placeholder-only documentation and an atomic mode-`0600` generator for distinct API, worker, migrator, Redis, Postgres, and storage credentials, with no provider key;
- `tests/service_unit/` covers state, idempotency, authorization, configuration, queue, migration, and storage behavior; `tests/service_integration/g5_postgres_gate.py` executes the migration runner twice and runs negative constraints against real PostgreSQL;
- Decisions D-034 through D-038 record source isolation, authority/outbox policy, version-bound artifacts, opaque builder progress, and per-role secret mapping.

Verification executed:

| Command | Result |
|---|---|
| `PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests/service_unit -v` | exit `0`; all 55 service state/idempotency/auth/config/queue/migration/storage tests passed |
| `PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests -v` | exit `0`; all 117 repository Python tests passed after the final G5 change |
| `HBCB_G5_POSTGRES_DSN=<redacted-local-test-dsn> PYTHONPATH=.:service/src /private/tmp/hbcc-g1-schema-venv/bin/python tests/service_integration/g5_postgres_gate.py` | exit `0`; migration applied once, second pass was current, seven durable tables and required constraints were present, and `G5_POSTGRES_CONTRACT: PASS` was reached on PostgreSQL 16.9 |
| `git diff --check`, Python AST parse of service/test sources, and `sh -n scripts/init-env` | exit `0`; whitespace, Python syntax, and POSIX shell syntax passed |
| independent adversarial G5 review and focused re-audit | passed after fixes for canonical spec provenance, SQL three-valued NULL checks, cross-build attempt ownership, exact-body/versioned storage evidence, attempt-bound publication, role config mapping, and in-memory version parity |

Durable evidence:

| Property | Observed result |
|---|---|
| PostgreSQL image | `postgres:16.9-bookworm`; registry digest `sha256:253815cf7579ffa05e1673d92e78d37273e61be0e4414e9a1449337d7925be94` |
| Migration | `0001_g5_foundation`; SHA-256 `51f59637237ae5d25534a03d742d595f71700595f233b803c10c8996d4d41696` |
| Real database | PostgreSQL `16.9 (Debian 16.9-1.pgdg120+1)`; success-evidence NULLs, invalid terminal/event state, second active attempt, cross-build event attempt, and mismatched artifact content type all rejected |
| Builder isolation | G4 container source revision remains `4e6f85a64fae06b15fe40787a50becb7aa53d0f96896dca5c26db9314a7e8968`; service code lives outside every G4 revision input |
| Local credentials | atomic new `.env`, mode `0600`, distinct random 64-hex secrets, no overwrite/symlink following, no secret output, and no `OPENAI_API_KEY` |

The concise local gate record is `/private/tmp/hbcb-g5-final-summary.json`; it contains no credentials or signed URLs.

Deviation/condition:

- G5 defines and tests the persistence and adapter contracts but does not expose an HTTP process or run a worker. FastAPI routes, Postgres repository transactions, leases/heartbeats, Blender subprocess supervision, retries, cancellation completion, and structured logs remain G6.
- The trusted G4 builder reports only a terminal outcome. The service may publish success directly from `running` when it has exact immutable artifact evidence; it must not fabricate `geometry_qa` or `rendering` progress that the builder did not emit.
- The MinIO-compatible adapter requires bucket versioning and exact version IDs. G7 must initialize a versioned bucket and use scoped credentials; unreferenced failed versions are retention data, never successful artifacts.
- No image, source update, database, artifact, or credential was published remotely. The PostgreSQL container and credentials used by the gate were synthetic and removed after the test.

G5 gate result: **passed**. G6 FastAPI routes, durable Postgres repository, worker leases/heartbeats, fresh Blender subprocess lifecycle, retry/cancellation/timeout behavior, immutable publication transaction, and structured logs may begin.

### G6 — asynchronous API and worker lifecycle

Files and contracts introduced:

- `service/src/hbcb_service/api.py` and `api_main.py` expose the auth-first `/healthz`, `/readyz`, build submission/status/artifact, and cancellation surface documented in `docs/api.md`;
- `repository.py` implements transaction-per-operation PostgreSQL authority for submission, HMAC idempotency, leases, fenced heartbeats/completion, cancellation, retry, recovery, exact-nine publication, and one-row-per-call outbox dispatch;
- `worker.py`, `worker_main.py`, and `launcher.py` implement a concurrency-one supervisor, fresh `builder build` process per attempt, bounded child environment/log tail, cancellation/timeout/lease-loss handling, retry/dead-letter policy, immutable upload verification, and scoped scratch cleanup;
- Linux supervisor termination freezes and enumerates a bounded `/proc` descendant tree before signaling it, so the immutable G4 wrapper and its separately-sessioned Blender child are both terminated before cleanup;
- `queue.py` reclaims the Redis claim-before-lease crash window with bounded `XAUTOCLAIM`, while PostgreSQL remains authoritative and safely rejects duplicate leasing;
- `runtime.py`, `structured_log.py`, and the API/worker/migrator entrypoints provide bounded dependency clients, full private readiness, fixed-region public signing, role separation, and allowlisted secret-free JSON Lines;
- forward migration `0002_g6_outbox_counter` replaces the original 100-attempt smallint ceiling with a nonnegative bigint, and domain/SQL updates saturate at the bigint maximum;
- `tests/service_unit/` adds API, lifecycle, runtime/logging, worker, stale-queue, and outbox recovery coverage; `tests/service_integration/g6_postgres_gate.py` executes the production repository against real PostgreSQL.

Verification executed:

| Command | Result |
|---|---|
| `PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests/service_unit -v` | exit `0`; 92 tests discovered, 91 passed locally, and the one Linux-only `/proc` process-tree case was skipped on macOS |
| Networkless/read-only/resource-limited `linux/amd64` G4-image run of `FreshSubprocessLauncherTests.test_cancellation_terminates_nested_builder_group_and_cleanup_is_scoped` | exit `0`; passed in `2.201s` with the nested child in another session and ignoring `SIGTERM` |
| `PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests -v` | exit `0`; 154 tests discovered, 153 passed on macOS, with only the separately-passed Linux case skipped |
| `HBCB_G6_POSTGRES_DSN=<redacted-local-test-dsn> ... tests/service_integration/g6_postgres_gate.py` | exit `0`; `G6_POSTGRES_GATE` passed on PostgreSQL 16.9 with 5 builds, 5 attempts, 21 events, exactly 9 published artifacts, and migrations `0001` plus `0002` |
| `git diff --check`, Python compilation, POSIX shell syntax, and independent G6 P0/P1 audit | exit `0`; audit signoff approved with no remaining P0/P1 finding |

Durable evidence:

| Property | Observed result |
|---|---|
| Frozen builder revision | `4e6f85a64fae06b15fe40787a50becb7aa53d0f96896dca5c26db9314a7e8968`, unchanged from G4 |
| PostgreSQL image | `postgres:16.9-bookworm`; registry digest `sha256:253815cf7579ffa05e1673d92e78d37273e61be0e4414e9a1449337d7925be94` |
| Forward migration | `0002_g6_outbox_counter`; SHA-256 `521292f93aed06aa691c466a137d83aff15de9b069c774bf1f03526d2ae22df4` |
| Outbox outage recovery | dispatch count moved from `100` through a failed `101`st attempt to successful immutable dispatch at `102` |
| Process cleanup | separately-sessioned, `SIGTERM`-ignoring nested child was force-terminated well below its 30-second fixture sleep |
| API/runtime safety | authentication precedes parsing; raw 64 KiB streaming cap; generic error envelopes; no-store/request IDs; fixed MinIO region; 3–5 second dependency timeouts; no signed URLs or child logs emitted |

The concise machine-readable record is `/private/tmp/hbcb-g6-final-summary.json`. It contains no credentials, requests, child output, endpoints, or signed URLs. Every disposable PostgreSQL gate container and anonymous volume was removed after its run; the synthetic test data is intentionally nonrecoverable.

Deviation/condition:

- The G4 builder entrypoint and source revision remain immutable. Full process-tree cleanup therefore lives only in the separately identified G6 supervisor layer, as recorded in D-041.
- G6 proves API and worker components independently plus real PostgreSQL behavior. G7 must still construct scoped roles, a versioned MinIO bucket, real Redis stale-claim behavior, and the complete HTTP-to-Blender-to-download path in Compose.
- Local MinIO uses its default `us-east-1` signing region. G8 must split internal and public TLS settings before a reverse-proxied HTTPS deployment; this is not needed by the HTTP-only local Compose gate.
- No source, image, database, artifact, credential, or service was published or deployed remotely.

G6 gate result: **passed**. G7 Compose images, initialization, service Make targets, end-to-end smoke, restart persistence, and builder-contract parity may begin.

### G7 — hardened local Compose service

Files and contracts introduced:

- `compose.yaml` defines pinned PostgreSQL and Redis services, the source-built local S3 fixture, one-shot database/storage initializers, a Blender-free API, the G4-derived concurrency-one worker, and an isolated test profile;
- `docker/service.Dockerfile` and `docker/service-requirements.lock` create separately identified API, worker, and test images from exact hash-locked wheels while preserving the immutable G4 builder contract;
- `docker/minio.Dockerfile` source-builds the final MinIO Community security release with pinned Debian snapshot, Go archive, source archive, client binary, hashes, upstream license/notices, and local-only OCI labeling;
- `service/src/hbcb_service/database_bootstrap.py` plus `initialize_main.py` create and converge distinct migrator/API/worker roles, revoke accumulated/public authority, apply the forward-only migrations, and grant only explicit runtime privileges;
- `compose/minio-init.sh` and the two fixed policies create a versioned bucket, remove reserved current/legacy identities, recreate distinct API/worker identities, and converge read/API versus read-write-without-delete/worker access without deleting durable objects or versions;
- `scripts/service-compose`, `scripts/service-smoke`, and the Make targets provide configuration, start, stop, direct/service parity, and black-box service gates; a cached MinIO fixture is reused only after its OCI version/revision, exact Dockerfile recipe identifier, and live binary provenance match;
- `tests/service_integration/g7_service_smoke.py`, `g7_redis_gate.py`, and `g7_iam_gate.py` exercise the real HTTP/storage/Blender path, runtime isolation, stale Redis claims/dead-lettering, and forbidden database/storage operations;
- README, API, security, test-plan, and decision-ledger updates document the local path, loopback/internal network split, source-built local fixture, and production boundary; Decisions D-045 through D-047 record the deviations and convergence policy.

Verification executed:

| Command | Result |
|---|---|
| `./scripts/service-compose config` with the immutable G4 builder image | exit `0`; resolved Compose configuration accepted without contacting a cloud provider |
| `make service-up BUILDER_IMAGE=headless-blender-character-builder:g4-37a4c1ed71ac-5ad78018` | exit `0`; verified MinIO fixture reused, both initializers converged, PostgreSQL/Redis/MinIO/API were healthy, and the worker was running |
| `make service-smoke BUILDER_IMAGE=headless-blender-character-builder:g4-37a4c1ed71ac-5ad78018` | exit `0`; `G7_SERVICE_SMOKE`, fresh `BUILDER_VERIFY`, `G7_REDIS_GATE`, and `G7_IAM_GATE` all passed |
| `PYTHONPATH=.:service/src PYTHONDONTWRITEBYTECODE=1 /private/tmp/hbcc-g1-schema-venv/bin/python -m unittest discover -s tests -v` | exit `0`; 157 tests discovered, 156 passed on macOS, and the already-passed Linux `/proc` case was the sole skip |
| exact-recipe label plus networkless/read-only `minio --version` cache gate | exit `0`; Dockerfile Git blob `d66f4c2c1edbcbe13a525a5decd9434790e89e5b`, release `RELEASE.2025-10-15T17-29-55Z`, and commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a` matched |
| `git diff --check`, Python AST/compilation, POSIX shell syntax, Compose validation, and independent G7 P0/P1 audit | exit `0`; no remaining P0/P1 finding |

Durable evidence:

| Property | Observed result |
|---|---|
| Frozen deterministic base | G4 image `sha256:49cb24b22ea569bfe9db3a7ad5532d1270c765439a7c293515b9e833fb655b13`; source revision `4e6f85a64fae06b15fe40787a50becb7aa53d0f96896dca5c26db9314a7e8968`, unchanged |
| Final local service images | MinIO `sha256:240b20b5b3f01bfeb11d0a9c6ecde62252bac1a4d12dca26f5e0f9d0a46aac78`; API `sha256:41a72196e064a65ecdf7720600cffa14669881c641b4644b3e3e4e4bfea0fc24`; worker `sha256:05e357a38362dc4bb1f3ee45bdfb3824a33ec5f9c0e2d7285daf75ec84dbf638`; test `sha256:fec194dc2631a83c5dbdb2bb08aaf35213e0840bb6cf50bb6dfd580fce69a8dd` |
| Async service | `202` in `0.071811s`; exact replay reused the build, conflicting replay returned `409`, an in-flight connection race during deliberate API restart was retried within the readiness bound, state persisted, and the sibling build canceled |
| Published result | 9 artifacts, 21,521,731 bytes, manifest SHA-256 `89dfe2713ac4cdd7f3884fd81e559bcec9a7f7e0af692c5509bb05baa9c7c522`; fresh `.blend`/GLB/STL verification and direct/service structural parity passed |
| Runtime boundary | one worker; non-root/read-only/capability-dropped services; no Docker socket or provider key; API/MinIO host ports on loopback; worker only on the internal network with no public route |
| Recovery and least privilege | one 60-second-stale Redis claim recovered and dead-lettered with only `build_id`; five PostgreSQL `42501` denials and two storage `AccessDenied` denials passed |

Ignored evidence remains at `build/service-smoke/run.Lw4H0h/`, with direct/service artifact trees and `g7-service-summary.json`. The summary contains no credentials, endpoints, signed URLs, request bodies, or child output.

Deviation/condition:

- D-045 supersedes the generic MinIO-image assumption for the local fixture. The old registry image predates the final security release, and the replacement distribution is account/license-gated; v0.1 therefore source-builds the final Community release for local evaluation only. G8 must recommend a maintained managed/operator S3 service for production.
- D-046 uses a dedicated host-ingress bridge for API/MinIO because Docker's internal network does not provide host NAT. Only the worker carries the strict no-public-egress claim.
- The smoke restarts the API and separately proves the Redis claim-before-lease failure window; the G6 lifecycle and Linux process-tree tests remain the authority for supervisor crash, lease expiry, retry, timeout, and nested-child termination.
- The successful local stack is not a production exposure: it has no TLS ingress, domain, backup runbook, retention operator, or upgrade/rollback package. Those remain G8.
- No source, image, release, credential, artifact, or service was pushed, published, or deployed remotely.

G7 gate result: **passed**. G8 VPS Compose overlay, TLS/auth guidance, resource and retention policy, backup/restore, upgrade/rollback, and operator smoke may begin.
