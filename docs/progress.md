# v0.1 Build Progress

Last updated: 2026-08-02

Overall status: **in progress**

| Work package | Milestone | Status | Gate evidence |
|---|---|---|---|
| G0 | M0 foundation | passed | Baseline verified; defaults, neutral brief, ignores, preservation hashes, and intentional indexed source set audited |
| G1 | M1 contracts | passed | Four Draft 2020-12 schemas and immutable runtime models; 47 schema/policy tests plus independent final audit passed |
| G2 | M1 generator | passed | Generic registry/core plus two factory-start fixtures; four-process structural, topology, and determinism gate passed |
| G3 | M1 artifacts and QA | passed | Exact nine-file artifact publication, actual-shell QA, fresh reload/re-import, repeat, and fail-closed paths passed |
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
