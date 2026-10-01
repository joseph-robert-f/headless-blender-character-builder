<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Watering-can relationship regression

This fixture uses one independently authored watering can and two local source rebuilds.
It does tests for specific attachment, hollow-passage, and protected-region requirements.
It is not a general text-to-3D benchmark or print-readiness certification.

## Source and revisions

`source/` contains the modular Blender program from the independent experiment,
without changes. It imports no other model fixture.
The `vessel` semantic mesh uses a Boolean union of the hollow open-top body and handle.
The hollow `spout` is a different object that overlaps the vessel outlet.
Scene coordinates use the meter contract.

- `params/r0.json`: Initial open watering can. Handle radius .13
- `params/r1.json`: distal spout rises by `.30*s²`, with its first three ring stations
  and entire vessel preserved
- `params/r2.json`: handle radius .13→.18, with entire spout and body away from the
  handle attachment preserved

The controller owns `requirements.json`. This file is not in the author source bundle.
The five hard requirements use independently reviewed measurements:

1. Upper handle-to-body mesh-edge path, restricted to Z≥1.05
2. Lower handle-to-body mesh-edge path, restricted to Z≤.65
3. All 25 fluid-centerline segments unobstructed, plus sampled clearance ≥.10
4. Body world geometry in X≥-.75 preserved to 2e-6 on revisions, including selected
   vertices and wholly contained oriented triangles/material/normal evidence
5. Eighty specified inner-body first-hit ray distances preserved to 2e-6

The two paths connect a grip vertex at X≤-1.35 to a body vertex at X≥.5.
Each spout station uses 16 outer vertices in consecutive groups.
These selectors depend on this source topology.
If there is no parent, revision-only requirements are non-applicable.
They are not measured passes.

## Three saved-artifact negative cases

`mutate_saved.py` is the independent mutation fixture without changes.
It reads the saved last model and writes three different negative artifacts:

<!-- ste-preserve:start historical original watering-can mutations and verifier outcomes -->
- `detach_upper`: Boolean slot through only the upper handle neck. The vessel is
  still one connected component through its lower attachment, so a single global
  connected-component check is insufficient. Expected failures: `handle_upper` and strict protected-region topology. The
  Boolean recut also retessellates 124 protected triangles while preserving their
  vertex coordinates; the stronger topology requirement intentionally rejects it
- `block_spout`: closed .07-thick radius-.155 plug between stations18/19, retaining
  all original 800 spout vertices. Expected failure: `water_passage`
- `alter_body`: 42 protected body vertices shifted +.08Y, with spout and both handle
  attachments untouched. Expected failures: both protected-body requirements

These cases previously failed the original independent verifier at their intended
assertions while the baseline passed. The first-stage observer alone passed the
body mutation because it only gathered preservation samples: the subsequent
comparison stage rejected it. This is why a requirement report exposes
`requirements_satisfied`, not aggregate pipeline `machine_verified`.

<!-- ste-preserve:end -->

## Reproduce actual Blender tests

First examine the source and mutation code. Then use these commands from the repository root:

```sh
python tests/experimental_modeling/run_water_relations.py \
  --store /tmp/reviewed-water-relations --trusted-reviewed-source
RUN_TRUSTED_BLENDER_TESTS=1 python -m unittest discover \
  -s tests/experimental_modeling -p test_relations_blender.py -v
```

Use a new empty output directory.
The runner generates the three positive states and three mutants again.
New Blender processes examine their saved geometry.
The runner evaluates the pinned requirements and keeps reports, logs,
and durations for each case.

An unknown applicable result makes the regression fail.
It does not count as a detected defect.
Do not commit generated binaries or JSON evidence.

Native execution is reviewed development, **NOT SANDBOXED**.
The runner also accepts `--sandbox-image sha256:...` for the existing Docker backend.
This backend uses different author and observer stages.
It does not change automatically to native execution.
A local native result does not show Docker isolation.
Docker results must have their own execution evidence.

The runner does tests for source authoring, independent observation, and relationship predicates.
A relation-only result does not show full controller promotion, GLB roundtrip, or review-app approval.
The aggregate controller and report have independent integration tests.
The aggregate result must include all mandatory stages.

## Coverage and limits

<!-- ste-preserve:start historical earlier independent measurements -->
The earlier independent saved-geometry test measured minimum sampled fluid
clearance .13231, exact unchanged protected coordinates/ray hits, and handle radii
.129999995/.180000007. It additionally checked open mouth, hand gap and disposable
assembled Boolean connectivity. Those extra predicates are NOT silently claimed by
this five-requirement JSON file.

<!-- ste-preserve:end -->

Connectivity is a mesh-edge path in a region.
It does not show strength or watertightness.
The validator continuously compares centerline crossings with triangles.
Radial clearance uses samples.

Protected-region checks exclude faces that cross the region boundary.
Eighty rays do not show equality of the complete surface.
If a necessary index is not available, the measurement is unknown and cannot pass.
These coverage limits do not give permission to ignore hard requirements.

A visible seam stays between the vessel and spout because they are different semantic objects.
This fixture does not give flow simulation or show manufacturing suitability.
It does not show general geometry repair, adversarial security, or statistical generality.

<!-- ste-preserve:start historical degenerate-triangle correction evidence -->
Actual generic-validator regression also exposed initially unsupported degenerate
triangles in the positive fixture. The distance routine was fixed using segment/point
distances for collapsed triangles; model geometry, thresholds and selectors stayed
unchanged. Final native clearance is .1323107213 over 275 samples/25 segments.
<!-- ste-preserve:end -->
