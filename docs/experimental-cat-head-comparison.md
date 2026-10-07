<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental cat head comparison

This comparison uses a separate identifier: `anime-cat-head-comparison-v1`.
It does not replace the tested [Bambu v3 baseline](experimental-x1c-bambu-repair.md).
It does not add a print profile or enable controller print acceptance.
The owner must review the shape, visible details, and actual print surface.
The proposed numeric and native coordinate acceptance changes remain pending.

The [builder](../experimental_modeling/examples/anime_cat/head_comparison_v1/builder.py)
copies the finalized 100 mm bare cat before it changes the head.
It uses final millimeter coordinates and the same fixed scale for every revision.
The head box is `x=(-36,36), y=(-36,24), z=(54,100.5)` mm.
Every triangle that touches or lies outside this box stays exact.
The builder pins its incident vertices before it moves the remaining head vertices.

It adds cheek and muzzle fullness, smooths broad head surfaces, and rounds the ear transitions.
Fixed masks protect eye relief, nose, smile, and whisker-root regions.
These modeling controls do not establish complete detail coverage.
The bare cat retains its 100 mm ear tips, body, paws, feet, floor, and tail.

The builder freezes the new bare cat before it adds an accessory.
It uses the existing closed hat and glasses constructors at the same fixed scale.
The new base must stay identical across the bare, hat, and glasses revisions.
The final accessory unions must retain the exact surfaces outside their existing edit boxes.

The glasses revision contains no hat geometry.
Accessories are editable in the source. The exported model is one fused solid.

The independent inspector uses the unchanged complete geometry observer.
It retains the 500,000-triangle, 20-million intersection-pair, and 4 MiB report limits.
It measures all final source and reimported STL triangles.
Source and STL surfaces must have identical exact fingerprints and bounds.

Whisker, hat-brim, glasses-bridge, and added ear checks are partial surface probes.
They do not establish full feature coverage or complete minimum thickness.
All results keep physical validation pending and promotion disabled.

The gray front, side, and three-quarter views use the same camera, scale, and lighting.
Each image must bind to its complete saved-source observation.
The camera center is `(0,-3,76)` mm and its orthographic scale is 74 mm.
These views compare real geometry. A smooth shading normal cannot establish a smooth print surface.

Run the comparison against a complete v3 candidate store:

```sh
python3 tests/experimental_modeling/run_anime_cat_head_comparison.py \
  --store /absolute/new/head-comparison \
  --candidates /absolute/existing/v3-candidates \
  --sandbox-image "$MODELING_SANDBOX_IMAGE"
```

Use Python 3.11 or newer and an existing reviewed Linux builder image.
The comparison uses fresh offline Docker jobs with the existing limits.
It makes no model-provider calls and connects to no printer.
Hosted checks use a separate offline job with an unchanged 120-minute limit.
That job independently rebuilds and inspects the v3 baselines before it compares the heads.

## Physical validation handoff

An actual print is needed to judge surface appearance, fragile features, support removal, and handling strength.
Geometry measurements and a slicer preview cannot prove these results.
Printer, filament, orientation, and calibration can change the result.
The official [modeling guide](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135)
recommends test prints before a final print and explains these dependencies.

Use this sequence after the owner selects the geometry:

1. Confirm the actual PLA brand and type, plate, nozzle, firmware, and calibration.
   The selected hardware is X1C, PLA, and a 0.4 mm nozzle.
   Generic PLA and Textured PEI remain inspection assumptions.
2. Inspect the selected STL in Bambu Studio at scale 1.
   The bare and glasses models are 100 mm tall. The hat adds height at the same scale.
   Keep the flat feet on the plate and retain the final upright orientation.
   Review every layer around the ears, facial relief, whisker roots, muzzle, glasses bridge, and temples.
   Check for lost details, unsupported islands, inaccessible supports, and supports trapped between facial features.
3. Have the modeling workflow prepare a closed coupon from the selected head at its final scale and upright orientation.
   Include an ear, eye and muzzle relief, a whisker root, and the glasses bridge and temple if selected.
   Do not reduce its scale to save material.
   The coupon needs its own geometry and sliced-layer review before printing.

   The owner selects the head before that preparation. This comparison does not include a validated coupon.
   Its changed lower geometry can change supports. It cannot prove support removal on the full cat.
4. Print the coupon only after that review.
   Record the exact STL, slicer version, plate, filament, and effective settings.
   Photograph it before and after support removal with a ruler and the same front, side, and three-quarter views.
   Record lost relief, scars, fusing, failed whiskers, weak joins, and any damage during ordinary handling.
5. After the coupon passes owner review, print the selected full 100 mm bare cat.
   Test the hat and glasses revisions at the same shared scale.
   Review their support removal and attachment strength separately.

   Do not shrink each accessory revision back to 100 mm.
   Keep physical acceptance pending until the actual observations are recorded.

The existing inspection setup starts with 0.20 mm layers, three walls, 15 percent gyroid infill,
automatic tree supports, and a 30-degree support threshold.
Nominal support gaps are 0.35 mm in XY, 0.20 mm at the first-layer XY contact,
and 0.20 mm above and below support interfaces.

The inherited Generic PLA setup uses a 220 C nozzle and 55 C Textured PEI plate.
These values are inspection settings, not a tested printer recipe.
The actual filament and plate guidance must be checked before a physical test.
Larger support separation can help removal, but support contacts can leave rough surfaces.
The official [support guide](https://help.prusa3d.com/article/support-material_1698) explains those tradeoffs.

This comparison has no current native slice, full path or support-clearance proof, or physical test.
It does not approve the old baseline detail omissions or a native bit-equality tolerance.
