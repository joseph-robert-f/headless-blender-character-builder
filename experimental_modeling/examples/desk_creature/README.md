<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Independent desk-creature modeling probe

This second, independently authored source program uses no robot-fixture imports
and needs no built-in shape registration. One novel scene is evidence beyond the
robot fixture, not statistical proof of general text-to-3D capability.

## Written brief

Create a faceted jade desk creature with mismatched dark eyes, three differently
posed legs, a tapered orange curved tail, and a separate lilac crescent-shaped
open container with a recessed floor. All three feet rest flat on the same Z=0
plane. Keep every part individually identifiable and editable. No external assets.

- r0: initial eight-part scene
- r1: lift only the tail centerline arch by `0.35*sin(pi*t)` at 17 stations; keep
  endpoint centers, station radii and all seven other parts fixed
- r2: increase only container rim height from 0.35 to 0.50; retain all XY geometry,
  0.08 floor and radial walls, and the other seven parts

The dimensions use the scene contract's meters, not a printable desk-toy scale.

## Program and policy separation

- `source/mesh_shapes.py`: independently authored swept tube and curved U-section vessel
- `source/composition.py`: semantic composition, editable arch/depth, flat ground caps
- `source/builder.py`: local Blender entrypoint and eight unique semantic IDs
- `params/`: three parameter states
- `policies/`: controller-owned policies, outside the author source bundle
- `tests/experimental_modeling/verify_desk_creature.py`: independent vertex assertions,
  with no author imports

Tail ring groups are indices `8*i .. 8*i+7`. Container sections are eight vertices
per station: outer bottom/top, outer inner-rim/top/floor, inner floor/top/rim/bottom.
The radial U section is swept through 240 degrees, with tapered width and capped
ends. The cavity remains open at the top. Measurements intentionally depend on
this reviewed topology; arbitrary remeshing would need new measurement definitions.

## Reproduce

From the repository root, review all source first and choose an empty external store:

```sh
python tests/experimental_modeling/run_desk_creature.py \
  --store /tmp/reviewed-desk-creature --trusted-reviewed-source
```

This is reviewed native development, **NOT SANDBOXED**. It must not be used for
unreviewed generated code. The runner also accepts the controller's `--sandbox-image`
option when a supported Docker backend is available; this probe's reported execution
was native and does not verify Docker containment. Omitting both modes fails closed.

The runner retains all three full-view builds, GLB and .blend reopen evidence,
independent assertions, a fresh clean final rebuild and a deliberately wrong
centroid-target negative control. The negative control must fail exactly its centroid
check. Generated binaries, renders and JSON evidence stay in the supplied store.

## Results and quality review

Native r0/r1/r2 each passed full pipeline acceptance. Independent measurements
confirmed 7 unchanged geometry/transform/material fingerprints per edit; maximum
tail station displacement error 5.44e-8 m and maximum radius error 1.39e-7 m;
all 200 vessel vertex XY coordinates preserved; floor and both radial walls .08 m.
All semantic meshes have closed edge incidence and positive signed volume.

Visual review of initial front/right/top/isometric and final top/isometric shows
curved tail, asymmetric eyes, distinct limb poses and a real vessel cavity. The right
projection overlaps the separate vessel and creature; top/isometric resolve their
separation. There is no rendered reference floor/shadow, so contact is checked from
geometry rather than pictures.

An earlier authored version used equal foot endpoint center heights, but sloped caps
had different minimum Z (0.0464, -0.0187, 0.0318). Independent QA caught the discrepancy.
This retained source flattens all three endpoint cap rings to Z=0, and the independent
verifier asserts every cap vertex and each limb minimum is exactly zero. Original
experimental outputs were preserved outside the repository.

The initial policy vocabulary could constrain only tail path length, not each desired
station position. That would permit unintended equal-length curves. The generic
centroid constraint now declares all 17 station locations, and the separate verifier
also checks the entire displacement/radius prescription. This is still a reviewed
indexed measurement contract, not a universal semantic shape validator.

Closed edges and positive signed volume do not rule out every self-intersection or
establish physical stability, stress limits, printing quality or manufacturing fitness.
The creature contains intersecting semantic parts. No print-ready, malicious-source
safety, broad artistic quality or cross-version determinism claim is made.
