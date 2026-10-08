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
