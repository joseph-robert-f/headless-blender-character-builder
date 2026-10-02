<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Translation verification, version 2

This experiment tests the translation check before authoring tools are connected.
It does not call a model provider.
It does not start automatic repairs.
The stable builder does not change.

## Select the contract

Use policy `schema_version: 2` in a new evidence store.
Do not change the policy version in an existing store.
This restriction includes rejected and interrupted attempts.
Version-1 stores and saved reports keep their original checks and text.

The review program uses the bound policy to select the report version.
It does not let a saved report select its own checks.
Project requirement locks do not change.

A version-2 `translated` constraint requires `delta`, `tolerance`, and
`normal_tolerance_radians` in `data`.
The distance tolerance is in meters.
The normal tolerance is an angle in radians from 0 to 0.01.
The policy must select this value explicitly.
There is no default angle.

The observer records polygon material indices and world-space corner normals.
Version-2 revisions require this evidence from a version-2 baseline.
Missing evidence gives an unknown result.
The program does not supply missing materials or normals.
There is no automatic migration of old evidence.

## Check scope

The check requires the same vertex indices in both models.
Each vertex must move by the declared translation within the distance tolerance.
The check also compares these data:

- Oriented polygon cycles
- The material assigned to each polygon
- The normal direction at each polygon corner
- Indexed edges, including repeated edges
- The ordered material list

These representation changes are permitted:

- Change the polygon order with its material and corner data
- Change the starting corner of a polygon with its corner data
- Change edge order or reverse the two indices of an edge

Do not reverse polygon winding.
Do not change vertex indices or material list order.
The check does not establish equivalence after remeshing or new tessellation.
A failed indexed comparison does not prove that two surfaces look different.

Whole-part preservation still uses the original geometry, transform, and material hashes.
These hashes come from the trusted inspector and are bound by the artifact manifest.
A valid hash format alone does not verify a saved mesh.
The protected-region and ray checks do not change.

Repeated oriented polygons are outside this version's coverage.
They give an unknown result.
Invalid indices, missing arrays, invalid normals, and exceeded limits also give unknown results.
Each polygon boundary must have an entry in the edge data.
An applicable hard check with an unknown result cannot publish an accepted model.

## Numeric rules and limits

The distance decision uses exact squared arithmetic on the stored binary64 values.
It includes the stored translation and tolerance values.
The reported distance is rounded for display.
A rounded display value does not control acceptance.
The inclusive distance limit has tests immediately below, at, and above its boundary.

The angle uses normalized vectors and binary64 `atan2` arithmetic.
This is a numeric direction comparison, not an exact real-number angle proof.
A normal must have length 1 within 0.00001 before normalization.
The angular boundary has separate tests.
Normals are not rounded into comparison keys.

Each part can have at most 100,000 vertices, 30,000 polygons, and 120,000 edges.
A polygon can have at most 256 distinct corners.
A part can have at most 120,000 polygon corners.

Coordinates and translation components are limited to 1,000,000,000 meters in magnitude.
A policy can have at most 32 constraints.
A check can compare at most 100,000 translated vertices across all constraints.
The current and parent surfaces can contain at most 250,000 vertices, edges, and face corners in total.
The existing file and runtime limits still apply.

## Validate the verifier

Run the offline tests:

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
```

The golden fixtures have two separate purposes.
Hand-derived geometry defines the expected version-2 results.
Frozen version-1 reports test compatibility with the recorded contract.
A recorded incorrect version-1 pass is not a correct geometry result.

The isolated CI test builds a two-material tetrahedron.
It tests a valid translation, changed face assignments, changed normals, and a repair.
A separate probe reads the actual authored scene, saved scene, and GLB.
The probe does not use production comparison functions.
Its expected face colors and normals come from a hand-derived fixture.
The observer and probe still share Blender as a dependency.

The CI test also reconstructs the lamp's original polygon order in a new source copy.
It does not change the recorded lamp example or delivered evidence.
The test must show that the corrected check accepts the measured translation.

The extended test adds a transformed quad box and a concave L prism.
Each has a separate protected base.
Each sequence has five revisions: a baseline, a translation, two rejected
attempts, and a repair from the accepted translated parent.
The box has nonuniform scale, rotation, and one oblique corner normal.
Its body defect changes the local height by 4 mm, which changes world height by 6 mm.

The L-prism body attempt changes one cap from a polygon to four triangles.
It preserves the solid but falls outside the indexed contract.
Its rejection does not establish geometric damage or a separate material defect.
Both fixtures also test a 5 mm movement of the protected base.
Each rejection must preserve the accepted parent's files and last-good pointer.

The independent geometry oracle checks named surfaces, materials, corner normals,
area, volume, and complete triangle coverage.
Separate synthetic mutations test the oracle itself.
The raw GLB probe uses Blender's importer.
It is not an independent GLB decoder.

The same analytic oracle also checks the stored production observation values.
This detects a consistently wrong observer even if its revision comparisons pass.
The oracle requires each fixture's fixed transform and its declared translation.
An identity transform with the same world geometry cannot satisfy that check.

Production artifact comparison still requires the same triangle decomposition
within each candidate's export roundtrip.
An export failure or an unknown result cannot satisfy an expected rejection.
No tolerance, production comparison, or supported representation changes.

The committed case manifest specifies ten additional live outcomes.
The complete corpus targets 17 outcomes: 11 accepted and 6 rejected,
with 68 controller stages and 51 artifact probes.
These counts are expectations until the isolated run completes.
Use the run summary's completed counts and source hashes as execution evidence.
Four separate offline tests cover incomplete or excessive multipart evidence.
They do not add live outcomes.

The test policy uses an explicit angle of 0.001 radians.
Treat this value as provisional until the isolated positive cases run.
Record their maximum measured angle before calling this fixture tolerance calibrated.
Do not infer that the same tolerance is correct for other runtimes or models.
Docker is required for live evidence.
There is no automatic native fallback.

Keep hypotheses, observations, and verified results separate.
A proposed explanation is a hypothesis until evidence supports it.
A measured value must identify its artifact and runtime.
A verified claim must state its check version and coverage.
A repair requires a new inspected proposal and revision ID.
Keep the rejected evidence and the accepted parent unchanged.

## Research basis

[ReviveBench](https://arxiv.org/html/2609.36161v1) reports verifier defects and recommends checks from submitted artifacts.
[Coding Agents for Coding Theory](https://arxiv.org/html/2609.39081v1) describes incorrect intermediate conclusions that were not rechecked.
[ParallelPilot](https://arxiv.org/html/2609.33113v1) studies supervision support.
Its study does not establish verification accuracy or safer autonomous execution.
