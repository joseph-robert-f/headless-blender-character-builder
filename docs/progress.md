# v0.1 Build Progress

Last updated: 2026-08-02

Overall status: **in progress**

| Work package | Milestone | Status | Gate evidence |
|---|---|---|---|
| G0 | M0 foundation | passed | Baseline verified; defaults, neutral brief, ignores, preservation hashes, and intentional indexed source set audited |
| G1 | M1 contracts | passed | Four Draft 2020-12 schemas and immutable runtime models; 47 schema/policy tests plus independent final audit passed |
| G2 | M1 generator | passed | Generic registry/core plus two factory-start fixtures; four-process structural, topology, and determinism gate passed |
| G3 | M1 artifacts and QA | pending | — |
| G4 | M2 one-shot container | pending | — |
| G5 | M3 persistence interfaces | pending | — |
| G6 | M3 API and worker | pending | — |
| G7 | M3 Compose service | pending | — |
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
