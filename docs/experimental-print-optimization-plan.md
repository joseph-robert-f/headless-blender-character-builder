<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental anime-cat print optimization

This experiment extends [PR #39](https://github.com/joseph-robert-f/headless-blender-character-builder/pull/39), merged on 2026-10-07.
Its baseline head is `b8f3af4e80278a962d87d1e029e7a28afcd56abd`.
The original cat, hat, sunglasses, edit policies, and rejected-edit evidence stay intact.
Scene acceptance does not establish print acceptance.

## Provisional profile

The fixed test profile is [provisional_fdm_v1.json](../experimental_modeling/examples/anime_cat/print/provisional_fdm_v1.json).
Source coordinates use meters with Blender `scale_length = 1`.
The 3.15 m hat reference maps to 100 mm.
Every revision uses `100 / 3.15` millimeters per source meter.
The unchanged cat is approximately 92.2 mm tall.
Do not scale each revision to a separate target height.

The provisional FDM assumptions are PLA, a 0.4 mm nozzle, and 0.2 mm layers.
The minimum designed feature target is 1.35 mm.
The maximum dimension is 120 mm, and the height tolerance is 1.5 mm.
The final export budget is 500,000 triangles.
These values support repeatable software tests. They do not certify a physical print.

At the start of this v1 experiment, the user's printer, build volume, material, finished size, colors, and support preferences were unknown.
A later owner selection of X1C, PLA, a 0.4 mm nozzle, and a 100 mm bare cat uses a [separate v2 profile](experimental-x1c-print-profile.md).

A preset change requires a new reviewed profile version.
The parser rejects changes under the existing profile identifier.
The parsed profile stores immutable canonical bytes. Each `raw` access returns a separate copy.
Its SHA-256 identifies canonical JSON, rather than file whitespace or numeric spelling.

## Sprint 1: units and measurement contract

[print_contract.py](../experimental_modeling/print_contract.py) validates the fixed profile and bounded final-STL measurement reports.
Missing fields, unknown fields, duplicate profile keys, nonfinite numbers, conflicting units, and malformed hashes cause rejection.
Boolean values are invalid for numeric measurements.
The reserved controller `profile: "print"` remains unavailable.

Measurements must describe the independently reimported final STL in millimeters.
Reports identify the profile, source observation, derivation, observer, evaluated mesh, and STL with SHA-256 values.
Every evaluated, exported, and measured triangle must be counted.
A low-resolution construction mesh cannot replace evaluated final geometry.
The existing 4 MiB JSON observation bound is unchanged.

Required numeric checks cover connected shells, closed edges, manifold topology, winding, degeneracy, positive volume, dimensions, ground contact, and feature size.
Shell counts use face connectivity across shared edges, rather than contact at one vertex.
Nonmanifold vertices and loose vertices must also be absent.

Separate checks cover self-intersections, feature coverage, surface roundtrip, protected regions, and visual fidelity.
Each separate check must report `passed`, `failed`, or `unknown`.
A failure rejects the measurement report. An unknown result requires review.
A measurement pass always has `promotion_eligible: false` and `physical_validation: "pending"`.

Caller-supplied reports do not authenticate their geometry or hashes.
Sprint 1 validates a report contract only. It does not measure an STL or authorize artifact promotion.
Later work must connect trusted measurements and preservation checks before print acceptance can operate.
The recorded minimum feature and sample count alone do not establish complete feature coverage.

Run the focused contract and existing controller regressions:

```sh
python3 -m unittest tests.experimental_modeling.test_print_contract \
  tests.experimental_modeling.test_controller \
  tests.experimental_modeling.test_observation_serialization -v
```

On macOS, select Python 3.11 or newer and a temporary directory without symlink ancestors.
For example, set `TMPDIR=/private/tmp` before the command.
Do not change path validation to accommodate `/tmp` or `/var` aliases.

Acceptance requires strict negative-input tests, a known meter-to-millimeter conversion, immutable scale tests, independent review, and successful exact-head CI.
Publish a draft PR before the next sprint. Do not merge it during this experiment.

## Sprint 2: closed solids and attachments

Build a separate reproducible print candidate for `r0`, `r1`, and `r2` at the shared scale.
Use closed solids and intentional overlap for the cat, hat, and sunglasses joins.
Measure the complete result after modifiers.
Retain the recognizable ears, face, expression, paws, body, and tail.
Use geometry or monochrome relief for details previously conveyed by colors.

Redesign fragile whiskers, face details, hat joins, glasses bridge, lenses, and temples for the provisional feature target.
Provide a stable bed contact and orientation.
The final candidate must contain one connected solid, including its accessory.
The `r1` candidate must show a hat. The `r2` candidate must show sunglasses with no hat geometry.


The separate source is [print/source](../experimental_modeling/examples/anime_cat/print/source/builder.py).
It uses rounded closed primitives, thicker whiskers, raised face details, and a flat foot contact.
A voxel grid at 0.011 source meters joins the cat surfaces. The grid is approximately 0.349 mm after scaling.

No disconnected component is discarded. The observer rejects every extra shell, including microscopic internal surfaces.
The glasses use the same voxel grid to join closed lenses, rims, and capsule joints.
The cat and each accessory are scaled before final unions.
Boolean operations use Blender's manifold solver on explicitly triangulated closed operands.

Finalization welds duplicate cut vertices within 0.00001 mm and dissolves degenerate edges at that distance.
This is author-side numerical cleanup, far below the voxel grid spacing. The observer does not repair geometry.

Cleanup must retain the face-connected component count. A microscopic-component collapse regression must be rejected.
The author saves explicit triangles. Inspection, rendering, and later export therefore use the same facets.

The neutral candidate retains the primary eye-highlight relief. The smaller secondary highlight is omitted.
The glasses omit the decorative lens glints.
Cheek details are less visible in gray behind the thicker whiskers.

Some head and body faceting remains visible in the side and isometric previews.
These differences require review of the actual print surface. These are not physical test results.

The [independent observer](../experimental_modeling/examples/anime_cat/print/inspect_solid.py) opens each saved candidate in a separate process.
It measures every evaluated triangle in `PrintCandidate` and the hidden pre-union `PrintBase`.
Unsupported geometry, instances, and remaining modifiers cause rejection.
Non-triangular evaluated polygons also cause rejection.
This prevents a render-only modifier from substituting unmeasured geometry.

Each complete mesh has a separate bounded inspection stage. Docker limits and the 4 MiB report bound are unchanged.
Rendering uses a separate bounded job that checks the saved-file digest, every triangle's surface hash, and the measured bounds.
Each preview must bind to the complete observation before the runner can pass.

Intersection checks use bounding spheres, radius buckets, and AABB overlap to include coplanar candidate pairs.
Double-precision triangle checks distinguish valid shared edges and vertices from overlapping interiors.
Triangle areas also use double precision, to retain valid thin facets that float32 BMesh area calculations can classify as zero.
Coplanar checks clip triangle interiors with strict double-precision signs. Near-contact alone does not establish overlap.

The numerical contact tolerance is 0.00001 mm, and the candidate-pair budget is 20 million.
Exceeding a bound causes failure. A truncated intersection search cannot pass.
Real Blender regressions cover coplanar overlap, contained triangles, shared-vertex crossings, valid adjacency, and unsupported curves.

Feature evidence uses opposing first-exit surface rays at fixed whisker, brim, and bridge centers.
These local chords do not establish a global minimum thickness or full feature coverage.
The summary keeps feature coverage and final protected-region checks unresolved.
A pre-union base hash does not establish preservation of the final fused surface.
Sprint 3 must check that surface directly.

Set `MODELING_SANDBOX_IMAGE` to the full SHA-256 identity of an existing reviewed builder image.
Then run the complete offline Docker regression:

```sh
python3 tests/experimental_modeling/run_anime_cat_print.py \
  --store /absolute/new/print-evidence \
  --sandbox-image "$MODELING_SANDBOX_IMAGE"
```

The store must be new and empty. Keep at least 1 GiB of disk space free.

On macOS, use Docker. The native harness cannot enforce its address-space limit.
The runner does not call a model provider or enable the reserved controller print profile.
It records source hashes, runtime identity, independent observations, and four neutral preview views per revision.
A `closed_candidates` result has `promotion_eligible: false` and physical validation pending.

Acceptance requires measured bounds, topology, volume, attachments, and feature evidence.
Review front, side, top, and isometric images of the actual neutral-material print surface alongside the baseline.
Complete independent review, a dependent draft PR, and exact-head CI before sprint 3.

## Sprint 3: STL export and preservation

Export millimeter STL coordinates and independently reimport the final file.
Compare complete geometry, topology, connectedness, winding, volume, bounds, and thin features with explicit tolerances.
STL has no unit metadata.
Keep source cat fingerprints unchanged across the scene revisions.
Keep the printable base identical before accessory union.
Check protected regions of the fused surface directly.

Acceptance requires deterministic rebuilds and no hat geometry in `r2`.
Reject open seams, detached accessories, wrong scale, thin features, and hidden protected changes.
A shifted protected cat must leave the last-good history byte-identical.
Do not increase the observer limit or infer export safety from an unchanged construction mesh.
Complete independent artifact review, a dependent draft PR, and exact-head CI, including the offline Docker regression.

### Final STL observation and preservation implementation

[export_stl.py](../experimental_modeling/examples/anime_cat/print/export_stl.py) writes all evaluated, explicit source triangles as deterministic binary STL facets.
Coordinates already represent millimeters. The exporter does not multiply them by Blender's display-unit scale.
The independent observer reads the complete file with exact length and triangle-budget checks.
It rejects malformed counts, trailing bytes, nonfinite coordinates or normals, nonzero facet attributes, and collapsed facets.
It joins only identical encoded float32 coordinates and performs no tolerance repair.

Duplicate facets remain part of the complete measured triangle set and fail topology checks.

Source observation, export, and reimport must agree on every oriented facet using an exact float32 surface fingerprint.
The fingerprint normalizes signed zero. Vertex indices, face ordering, and cyclic vertex order do not affect it.
Reversed winding and a one-ULP coordinate change do affect it.

The prior six-decimal fingerprint remains available for earlier fixture evidence.
It does not establish exact roundtrip equality.
All file SHA-256 values and complete triangle counts are checked separately.
Every reimport receives complete topology, intersection, shell, winding, volume, bounds, and feature-probe measurements under the existing limits.

Accessory construction retains the finalized base facets outside fixed edit boxes:

| Revision | Minimum XYZ, mm | Maximum XYZ, mm |
| --- | --- | --- |
| `r1`, hat | `[-20, -20, 80]` | `[20, 20, 103]` |
| `r2`, glasses | `[-26, -32, 54]` | `[26, 2, 76]` |

A facet is excluded from the protected fingerprint only when all three vertices lie strictly inside the box.
Facets crossing or touching its exterior remain protected.
Construction uses the base's protected facets and the union's wholly interior facets.
Both operands must already contain one closed, consistently oriented shell.
The assembled result must retain that property through exact coordinate joins.
This prevents accessory Boolean retessellation from changing remote ground facets and fails on a changed interface or discarded component.

The independent final STL observer checks the actual fused result against the independently reimported hat-free `r0` baseline.
The hidden base is also linked through its separate complete source observation and the exporter to the same exact baseline.
The `r2` exclusion ends at Z=76 mm, so the former hat region remains protected.
These checks do not prove that every interior accessory detail matches a visual design.

Run the Docker regression with an immutable image and a fresh store:

```sh
python3 tests/experimental_modeling/run_anime_cat_print_export.py \
  --store /absolute/new/stl-evidence \
  --sandbox-image sha256:REVIEWED_IMAGE_DIGEST
```

The runner can reuse fully observed candidates with `--candidates` and an existing accepted original scene history with `--history`.
Otherwise it builds both from the deterministic local fixtures.
It compares a clean `r2` rebuild's complete STL bytes, renders four independently bound views of each actual STL, and measures damaged exports.
Open seams, detached shells, wrong scale, narrowed whiskers, and a shifted protected body must fail their specific measured gates.

After each rejection, the original scene controller's last-good pointer and complete accepted history must remain byte-identical and pass integrity verification.
That history belongs to the original decorative fixture. The runner does not promote STLs to it.
This verifies that standalone STL assessment leaves the accepted scene history intact.
It does not implement controller print acceptance or rejection rollback.

Successful geometry evidence remains `needs_review` because feature coverage is partial and visual fidelity needs independent review.
Physical validation remains `pending` until the user completes the tests.
The controller's print profile remains unavailable.

## Sprint 4: slicer evidence and physical handoff

Slice all three accepted STLs with an identified local slicer and a recorded provisional preset.
Examine orientation, bed contact, supports, path loss, gaps, islands, and repair warnings layer by layer.
Retain the slicer version, settings, dimensions, warnings, and representative layer or toolpath evidence.
If no slicer is available, record a blocker. Mesh checks cannot replace this gate.

Acceptance requires continuous plausible toolpaths without silent repair or missing signature details.
Document any slicer-specific exception. Complete independent review, a dependent draft PR, and exact-head CI.
Provide physical tests for dimensions, feature survival, accessory attachment, fit, surface quality, and strength in the intended orientation.

### Original slicer evidence and failed export gate

On 2026-10-07, all three complete sprint 3 STLs were sliced with [PrusaSlicer 2.9.6](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6).
The source revision was `fc25d8eccd3fab279cd4afb32f0b7e6d9d501ded`.
The original decorative fixture and the final STL bytes remained unchanged.

The [provisional preset](../experimental_modeling/examples/anime_cat/print/provisional_prusaslicer_v1.ini) uses PLA, a 0.4 mm nozzle, 0.2 mm layers, three perimeters, five top and bottom layers, and 15% gyroid infill.
It enables snug supports, three support interface layers, a 0.2 mm contact gap, and a 5 mm brim.
The 200 by 200 mm bed, 120 mm height, temperatures, Marlin 2 flavor, retraction, speeds, and inherited start and end commands are reference settings.
The user's printer, material, calibration, target size, and firmware remain unconfirmed.
Generated G-code is for inspection only. Re-slice a verified STL with the actual printer profile before any physical test.

The official macOS DMG was downloaded to a task-owned temporary directory and mounted read-only.
Its SHA-256 was `94fd7b8a9f87c9631e1c71739b15b184fc5f4c0ceabd69072f1c78f229a4fe40`, matching the release asset digest.
macOS signature verification and notarization assessment passed.
Execution used a separate task data directory, two threads, and a 300-second timeout per CLI action.
This was trusted native slicer execution, not a Docker security boundary.
It did not communicate with a printer.

The preset SHA-256 was `1ec85622ee198b76b26c45621aa4085f4c79c7c78b767852882b871bc3f50129`.
The complete 346-setting effective snapshot had SHA-256 `d84e7ecb0b2f16c0151c7812cd426ebd9a22b6d4d7b0a2ba9edc8dfe11347c8c`.
Save that snapshot with the identified slicer version. Partial presets inherit version-specific defaults.

Use a separate data directory and reject unknown configuration substitutions:

```sh
"$PRUSASLICER" --datadir "$TASK_SLICER_DATA" --threads 2 \
  --config-compatibility disable --load provisional_prusaslicer_v1.ini \
  --save effective-preset.ini
"$PRUSASLICER" --datadir "$TASK_SLICER_DATA" --threads 2 \
  --config-compatibility disable --loglevel 4 --load effective-preset.ini \
  --center 100,100 --scale 1 --rotate 0 \
  --export-gcode --output inspection-only.gcode model.stl
```

Set the executable and task data paths explicitly. The STL coordinates already represent millimeters.
Keep normal bed placement enabled for slicing.
Require a nonempty output file, unchanged input SHA-256, and full model-height coverage.
Exit code zero alone is insufficient.

An earlier invalid relative-extrusion preset returned zero without creating G-code.
The final preset adds `G92 E0` at each layer.
An earlier `--no-ensure-on-bed` slice included only half the model height. Those outputs were rejected and retained separately.

The corrected runs produced these complete toolpath inventories:

| Revision | Source height, mm | Model layers | Declared layers including support-only heights | Final model path Z, mm | Positive XY extrusion segments |
| --- | --- | --- | --- | --- | --- |
| `r0`, cat | 92.126564 | 460 | 516 | 92.0 | 571,100 |
| `r1`, hat | 100.0 | 500 | 556 | 100.0 | 612,896 |
| `r2`, glasses | 92.126564 | 460 | 524 | 92.0 | 627,842 |

Two separate complete G-code readers corroborated the counts and full heights.
Every declared layer contains positive XY extrusion, and model layers begin at Z=0.2 mm with gaps no greater than one 0.2 mm layer.
All positive extrusion segments lie within the provisional bed and height envelope.
The readers account for motion and extrusion modes, per-layer extrusion resets, finite coordinates, and millimeter units.
They reject unsupported arc or inch motion and exclude pure extrusion retraction recovery from path counts.

Actual layer plots show base contact and brim, supported facial features, four whisker probe regions, the hat brim and crown, and the glasses bridge.
All three six-panel plots received independent visual review.
Local signature probes intersect actual model toolpaths at the measured feature centers.
Separate upper-ear cross sections remain connected below. Support-only heights are included in the full inventory.
These checks do not prove global feature fidelity, support-removal clearance, interlayer strength, or physical print quality.

**The original sprint 4 exported-mesh geometry gate failed.**
PrusaSlicer reports one manifold part, but its exported mesh coordinates differ from the input.
Independent complete oriented-facet and bijective-vertex comparisons found a maximum coordinate change of 0.00000190735 mm on each axis.
Triangle counts remain 383,540 / 376,362 / 413,492. No facet collapsed and no degenerate facet appeared.
Exact surface equality is false.

The unchanged Docker observer then measured every re-exported triangle and found 4 / 4 / 7 self-intersections for `r0` / `r1` / `r2`.
The searches completed after 2,426,383 / 2,466,664 / 2,621,762 candidate pairs.
The meshes still have one closed shell and zero boundary, non-manifold, inconsistent-winding, or degenerate counts.
Independent exact rational checks corroborated a ground-facet overlap and the additional glasses-revision crossings.
Small coordinate displacement and unchanged topology therefore cannot establish geometric validity.
No observer tolerance, triangle budget, report limit, or acceptance threshold was relaxed.

This failure applies to the exported mesh adapter.
The exact internal representation consumed by the native slicing path has not been fully measured.
These exports do not prove that its slice geometry has the same crossings.
The versioned [model transformations](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/Model.cpp) and [slicing transformations](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/TriangleMeshSlicer.cpp) use different paths.
A diagnostic 3MF export also changed coordinates and did not resolve that evidence gap.
The native slice has not received geometry acceptance.

An isolated one-micron author-side weld and degenerate-edge cleanup prototype failed the closed-manifold guard before export.
It was rejected without changing the repository author source or accepted baseline.
A repair must preserve every component and signature feature and establish a new finalized base.
Rerun complete source, STL, protected-surface, deterministic-rebuild, damaged-export, history, and slicer checks.
An unchanged construction mesh or a slicer manifold label cannot replace those checks.

Local evidence is retained in `build/print-sprints/s4-final-local-evidence`, with the full post-export observations and independent proofs copied into its review directory.
It includes actual G-code, source hashes, the effective preset, logs, bound toolpath plots, complete layer inventories, failed-attempt references, and a SHA-256 manifest.
Generated evidence is ignored by Git.
Repository CI checks policies, documentation, and the existing geometry regression.
The task-mounted slicer provides the preset validation and actual slice evidence separately.

### Bounded diagonal repair and remaining evidence limits

A follow-up isolated the coordinate change to float32 centering and restoration.
The versioned [model loader](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/Model.cpp) centers each imported volume.
The [mesh translation](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.6/src/libslic3r/TriangleMesh.cpp) operates on float32 coordinates.
Re-export restores the volume position.

An arithmetic replay matched all 1,173,394 actual exported facets across the original three revisions, with zero coordinate mismatches.
A closed 12-facet prism retained valid adjacency at its own center.
The same ground patch with two closed bounding anchors reproduced the overlap at the full cat's center in a 20-facet diagnostic fixture.
The anchored control has three shells and is not a production candidate.

Exact rational checks independently corroborated the ground sign change and the additional glasses crossings.
The replay describes measured export behavior. It does not measure the native slicing buffers.

The separate author source now identifies derivation `anime-cat-cut-diagonals-v2`.
It rotates one ground diagonal and two local glasses diagonals after normal finalization.
Each rotation replaces two triangles while retaining all four vertices and the oriented quadrilateral boundary.
The ground quadrilateral is exactly planar and strictly convex, so its surface point set stays identical.

Its oriented-facet fingerprint changes. The new finalized base is frozen once and shared by all three revisions.
This is an explicit new base, not byte equality with the prior sprint 3 exports.

The two nonplanar glasses changes stay wholly inside the existing `r2` edit box.
Their conservative source-surface displacement bounds are 0.000003615 mm and 0.000001838 mm.
Every source vertex coordinate and the nominal model dimensions stay unchanged.
The complete revisions replace exactly 2 / 2 / 6 oriented facets relative to the original sprint 3 candidates.
There is no coordinate weld, component removal, facet-count reduction, rescaling, or feature redesign in this repair.

The author requires one reviewed ground target and one glasses target on each side.
All four patch vertices must lie inside the fixed local window, including the neighbor facet's opposite vertex.
Ground convexity, a missing replacement edge, improved sliver altitude, source and simulated-centered orientation, unchanged coordinates, closed winding, one shell, and positive volume are mandatory.
The author writes the replacement mesh only after every check passes.
Twenty real Blender integrity and scope probes include exact rejection of two right-side targets and an out-of-window fourth vertex.
Both failures leave the full object surface unchanged, including a failure after an earlier temporary rotation.

All three final candidates passed complete source, frozen-base, STL export, and independent reimport checks.
Exact protected regions passed against the new `r0` base.
The clean `r2` rebuild produced identical STL bytes.
All five damaged exports failed their specific measured gates, and all 65 accepted original-history files remained byte-identical.
Twelve source views and twelve actual STL views received independent review with no visible regression from the prior STL baseline.

The new canonical STL SHA-256 values are:

| Revision | SHA-256 |
| --- | --- |
| `r0` | `201e21f6161ad3774840ba65b48d560674da139bfb810cf76f6176c9056d0a03` |
| `r1` | `a49088cb4c7dccd45bef2a92ca7b532d345d91e9e74194fac05e563e045ceb46` |
| `r2` | `8d444f00bf66466931d1e78cb5741e88affb0fefa90545362584d5a17434fe5b` |

All three actual PrusaSlicer re-exports passed the unchanged complete observer with zero intersections and one closed shell.
The searches tested 2,426,404 / 2,466,685 / 2,621,791 pairs.
Boundary, nonmanifold, winding, and degenerate counts were zero.
Triangle counts remained 383,540 / 376,362 / 413,492.

A separate full facet and vertex comparison matched every exported coordinate to the arithmetic replay.
The maximum coordinate shift remained 0.00000190735 mm on each axis, and exact loader surface equality remained false.
This measures the exported mesh adapter. It does not establish exact equality or measure the native slicing buffers.

The repaired files also produced full-height toolpaths under the unchanged effective preset:

| Revision | Model layers | Declared layers | Final model path Z, mm | Positive XY extrusion segments |
| --- | --- | --- | --- | --- |
| `r0` | 460 | 516 | 92.0 | 571,023 |
| `r1` | 500 | 556 | 100.0 | 612,849 |
| `r2` | 460 | 524 | 92.0 | 627,928 |

Two complete G-code readers independently agreed on the inventories, heights, millimeter modes, extrusion resets, and provisional build envelope.
All local signature probes intersected model paths.
The three actual six-panel plots received independent review without visible omissions.

The source-to-STL-to-independent-reimport equality and protected-region gates remain exact.
No observer bound, geometry tolerance, acceptance status, or physical requirement was weakened.
Native slicing buffers remain unmeasured. Full feature coverage, support removal, strength, fit, and machine compatibility remain unresolved.
The controller print profile remains unavailable, and promotion remains false.

Original failing evidence remains in `build/print-sprints/s4-final-local-evidence`.
The reproducer, independent repair review, and rejected cleanup attempts remain separate from it.
Final repaired evidence uses `build/print-sprints/s4-diagonal-final-local-evidence`.
The official slicer was mounted read-only in task-owned temporary storage and detached after the final jobs.
No global installation or printer communication occurred.

### Physical test handoff

Resolve the remaining native-slicing geometry and feature-coverage evidence gaps before advancing to a print test.
Then identify the actual printer, nozzle, material, firmware, target height, and calibration, and re-slice using that hardware profile.
Record orientation, supports, temperature, layer height, line width, retraction, speed, cooling, and infill with the resulting G-code digest.
Review startup and shutdown commands, all layers, support contacts, facial clearances, whiskers, and accessory paths in that slicer.

The fixed-scale nominal dimensions are:

| Revision | Width X, mm | Depth Y, mm | Height Z, mm |
| --- | --- | --- | --- |
| `r0` | 70.698332 | 43.577799 | 92.126564 |
| `r1` | 70.698332 | 43.577799 | 100.000000 |
| `r2` | 70.698332 | 46.946047 | 92.126564 |

| Physical check | Evidence to record | Current result |
| --- | --- | --- |
| Dimensions and scale | Caliper measurements of X, Y, Z, actual scale and calibrated printer tolerances | Pending |
| Bed contact and orientation | First-layer and full-print photos, adhesion, stability, warping and support behavior | Pending |
| Feature survival | Before and after support-removal photos of whiskers, ears, eyes, cheeks, paws and tail | Pending |
| Accessory attachment | Hat and glasses interface photos, gentle handling and intended-use load observations | Pending |
| Fit and surface quality | Actual clearances, visible facets, blemishes and any sanding or finishing | Pending |
| Strength and durability | Failure location, intended-use load, orientation and repeated-handling results | Pending |

The hat and glasses are fused into their respective cat revisions. They are not separate removable accessory parts.
Do not infer mating-part fit or certified strength from their software attachment checks.
The software height tolerance is a geometry gate, not a measured manufacturing tolerance.
If a test fails, retain the last verified files and revise the derivation and printer settings before repeating the affected checks.
Physical results, promotion, and print readiness remain unclaimed.

## Evidence boundary

Each sprint records its tests, review, draft PR, exact head, and terminal CI results.
Generated evidence stays in ignored output directories or CI artifacts.
Construction and tests use deterministic local inputs. No live model-provider request is required.
Do not merge, release, deploy, change credentials, or incur new costs.

Software and slicer passes establish provisional candidates.
Actual printer settings, print quality, strength, durability, and fit require physical tests on the user's equipment.
Keep those results pending until the tests occur.
