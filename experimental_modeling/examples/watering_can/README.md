<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Watering-can relationship regression

One independently authored watering can and two local source rebuilds test a narrow
set of attachment, hollow-passage and protected-region requirements. This is not a
general text-to-3D benchmark or print-readiness certification.

## Source and revisions

`source/` is the original modular Blender program, copied unchanged from the
independent experiment. It imports no other modeling fixture. The `vessel` semantic
mesh Boolean-unions the hollow open-top body with the handle. The separate hollow
`spout` overlaps the vessel outlet. Scene coordinates follow the meter contract.

- `params/r0.json`: original open watering can; handle radius .13
- `params/r1.json`: distal spout rises by `.30*s²`, with its first three ring stations
  and entire vessel preserved
- `params/r2.json`: handle radius .13→.18, with entire spout and body away from the
  handle attachment preserved

`requirements.json` is controller-owned and outside the author source bundle.
The five hard requirements come from independently reviewed measurements:

1. Upper handle-to-body mesh-edge path, restricted to Z≥1.05
2. Lower handle-to-body mesh-edge path, restricted to Z≤.65
3. All 25 fluid-centerline segments unobstructed, plus sampled clearance ≥.10
4. Body world geometry in X≥-.75 preserved to 2e-6 on revisions, including selected
   vertices and wholly contained oriented triangles/material/normal evidence
5. Eighty specified inner-body first-hit ray distances preserved to 2e-6

Both paths connect a grip vertex at X≤-1.35 to a body vertex at X≥.5. Each spout
station uses 16 outer vertices in consecutive groups; these selectors depend on
this source topology. Revision-only requirements are explicitly non-applicable
when there is no parent, never represented as measured passes.

## Three saved-artifact negative cases

`mutate_saved.py` is the unchanged independent mutation fixture. It reads the saved
final model and writes three separate negative artifacts:

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

## Reproduce actual Blender tests

From the repository root, after reviewing source and mutation code:

```sh
python tests/experimental_modeling/run_water_relations.py \
  --store /tmp/reviewed-water-relations --trusted-reviewed-source
RUN_TRUSTED_BLENDER_TESTS=1 python -m unittest discover \
  -s tests/experimental_modeling -p test_relations_blender.py -v
```

Use a fresh empty output directory. The runner regenerates all three positive
states and three mutants, observes actual saved geometry in fresh Blender
processes, evaluates pinned requirements, and retains detailed per-case reports,
logs and timings. Unknown applicable results fail the regression rather than
counting as detected defects. No generated binary or JSON evidence is committed.

Native execution is explicitly reviewed development, **NOT SANDBOXED**. The runner
also accepts `--sandbox-image sha256:...` using the existing Docker backend with
separate author and observer stages; it never falls back to native. Local reported
proof is native unless separately accompanied by Docker execution evidence.

The runner exercises source authoring and independent observation plus relationship
predicates. It does not claim full controller promotion, GLB roundtrip, or review-app
approval from a relation-only result. The aggregate controller/report has separate
integration tests and must combine all required stages.

## Coverage and limits

The earlier independent saved-geometry test measured minimum sampled fluid
clearance .13231, exact unchanged protected coordinates/ray hits, and handle radii
.129999995/.180000007. It additionally checked open mouth, hand gap and disposable
assembled Boolean connectivity. Those extra predicates are NOT silently claimed by
this five-requirement JSON file.

Connectivity is a mesh-edge path within a region, not strength or watertightness.
Centerline crossings are checked continuously against triangles, but radial
clearance remains sampled. Protected-region checks exclude boundary-crossing faces;
80 rays do not establish exhaustive surface equality. A required index that no
longer exists is an unknown measurement, not a permissive pass. These statements
are specific coverage limits, not permission to waive hard requirements.

The visual seam between vessel and spout remains because they are separate
semantic objects. No flow simulation, manufacturing suitability, broad geometric
repair capability, adversarial security or statistical generality is established.

Actual generic-validator regression also exposed initially unsupported degenerate
triangles in the positive fixture. The distance routine was fixed using segment/point
distances for collapsed triangles; model geometry, thresholds and selectors stayed
unchanged. Final native clearance is .1323107213 over 275 samples/25 segments.
