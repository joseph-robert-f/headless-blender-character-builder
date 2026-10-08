<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental Bambu floor repair

The additive v3 profile retains the X1C PLA, 0.4 mm nozzle and bare-cat 100 mm targets from the [v2 experiment](experimental-x1c-print-profile.md).
The default v1 and published v2 profile files, authors and canonical STL bytes remain unchanged.
This experiment does not grant controller print acceptance or physical print validation.

## Reproducer and exact source change

Actual Bambu Studio v02.08.02.61 exports had four measured intersections for the bare cat and hat, and zero for the glasses.
The canonical input geometry passed the same gate.
An unchanged fresh control reproduced the original bare-cat native STL bytes and all four failures.

The saved source, local 3MF and native export support a complete float32 arithmetic replay.
The final bed-space rounding reverses a very thin planar underside triangle.
Exact rational witnesses establish real overlap and contacts outside normal mesh adjacency.
This finding does not measure the raw three-dimensional buffers consumed by slicing.

The new [author helper](../experimental_modeling/examples/anime_cat/print/source/x1c_bambu_solids.py) first calls the unchanged completed v2 author.
It replaces one floor diagonal in both the candidate and its hidden base.
Exactly two oriented facets are removed and two are added.
All encoded vertex coordinates, counts, bounds, positive solid topology and the directed outer patch boundary must remain identical.
Exact rational convexity and area checks prove the same planar source surface and volume.

Both meshes pass every preparation guard before either mesh or profile tag is replaced.
An unexpected pair, orientation, coordinate, diagonal incidence or source profile is rejected.

The source facet hashes change even though the physical planar surface is identical.
Thus v3 freezes its own shared base and uses its own identity:

- Profile: `anime-cat-x1c-pla-04-bare100-v3`.
- Canonical profile SHA-256: `8283c21798d388a16f979b085ca0940707bf0f0367630ec59b5643464efe0f7b`.
- Fixture: [x1c_pla_bare100_v3.json](../experimental_modeling/examples/anime_cat/print/x1c_pla_bare100_v3.json).
- Author: [builder_x1c_v3.py](../experimental_modeling/examples/anime_cat/print/source/builder_x1c_v3.py).

Every revision receives the same floor change.
The scale factor, dimensions, protected boxes, 4 MiB report bound, 500,000-facet limit, intersection thresholds and minimum feature target retain their v2 values.
A v1 or v2 base is not a valid preservation reference for v3.

## Verification

Run the fixed-profile tests:

```sh
python3 -m unittest tests.experimental_modeling.test_x1c_bambu_profile -v
```

Run the complete candidate and STL checks with a fresh evidence store and the existing isolated builder image:

```sh
python3 tests/experimental_modeling/run_anime_cat_print.py \
  --store build/x1c-v3-candidates --sandbox-image "$MODELING_SANDBOX_IMAGE" \
  --profile-id anime-cat-x1c-pla-04-bare100-v3
python3 tests/experimental_modeling/run_anime_cat_print_export.py \
  --store build/x1c-v3-stl --candidates build/x1c-v3-candidates \
  --sandbox-image "$MODELING_SANDBOX_IMAGE" \
  --profile-id anime-cat-x1c-pla-04-bare100-v3
```

The candidate runner includes real failed-author transaction probes and complete geometry observations of each visible candidate and hidden base.
The STL runner retains complete source/export/reimport identity, shared-base and protected-region checks, five invalid exports, fixture-history preservation and a clean glasses rebuild.
The legacy runners check all v1 and v2 canonical STL hashes.
CI retains separate v3 evidence alongside the historical runners and keeps live provider calls disabled.

## Acceptance limits

Private two-facet STL prototypes passed complete canonical and actual native export geometry for all three revisions, with zero measured intersections.
These prototypes establish repair feasibility.
New-version author and preservation results must be recorded separately at the reviewed commit.
Import, arrangement and export tests did not invoke slicing or a printer.

Actual consumed slicing buffers, complete feature and support accounting, independent visual acceptance and physical print validation remain pending.
Generic PLA and Textured PEI Plate remain explicit assumptions.
Actual filament, plate and calibration are unconfirmed.
All reports retain `promotion_eligible: false` and `physical_validation: "pending"`.
The software release verification and OCI copyleft publication hold remain separate gates.
