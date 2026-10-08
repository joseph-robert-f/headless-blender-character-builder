<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental anime-cat print optimization

This experiment extends draft [PR #39](https://github.com/joseph-robert-f/headless-blender-character-builder/pull/39).
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

The user's printer, build volume, material, finished size, colors, and support preferences are unknown.
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

## Evidence boundary

Each sprint records its tests, review, draft PR, exact head, and terminal CI results.
Generated evidence stays in ignored output directories or CI artifacts.
Construction and tests use deterministic local inputs. No live model-provider request is required.
Do not merge, release, deploy, change credentials, or incur new costs.

Software and slicer passes establish provisional candidates.
Actual printer settings, print quality, strength, durability, and fit require physical tests on the user's equipment.
Keep those results pending until the tests occur.
