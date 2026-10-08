<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental X1C PLA profile

The owner selected a Bambu Lab X1 Carbon, PLA, a 0.4 mm nozzle, and a 100 mm tall cat.
This follow-on uses 100 mm for the bare cat. The hat adds height.
The existing [four-sprint experiment](experimental-print-optimization-plan.md) and its v1 evidence remain the historical baseline.
This work does not enable controller print acceptance or certify a physical print.

## Versioned geometry

The new fixed profile is [x1c_pla_bare100_v2.json](../experimental_modeling/examples/anime_cat/print/x1c_pla_bare100_v2.json).
Its identifier is `anime-cat-x1c-pla-04-bare100-v2`.
Its canonical SHA-256 is `7c7f84e3749e08d24bb163e3364e4831278ba3908f780f1b44ac2b0a928da915`.
The original v1 profile remains the default, with unchanged canonical bytes and geometry.

The final mapping multiplies every old candidate and frozen base coordinate by `100 / 92.1265640258789`, then stores the result once as a binary32 coordinate.
The factor comes from the reviewed v1 bare-cat height at `dd5c8b4f93bf0f2dd5f3c25180a075355f1199a6`.
It does not come from a fresh candidate measurement.
Every revision uses the same mapping. The protected boxes and feature centers use that mapping too.
The v1 base is not a valid preservation baseline for v2.

The new [builder](../experimental_modeling/examples/anime_cat/print/source/builder_x1c.py) calls the unchanged v1 derivation, then applies the fixed mapping.
Binary32 rounding reverses two microscopic hat facets.
The [v2 helper](../experimental_modeling/examples/anime_cat/print/source/x1c_solids.py) rotates exactly two identified interior hat diagonals after validating both patches.

This replaces exactly four oriented facets inside the reviewed hat box.
It retains all vertex coordinates, vertex and facet counts, and protected surfaces outside the box.
The two patches are noncoplanar, so their interior surfaces do change.
The bare cat, sunglasses, and hidden base receive only the fixed coordinate mapping.
A failed precondition leaves the candidate mesh and its profile tag unchanged.

These local guards do not replace complete independent geometry measurements.

Complete saved-candidate and hidden-base observations passed for all three revisions:

| Revision | Accessory | Final height (mm) | Candidate facets |
|---|---|---:|---:|
| `r0` | none | 100.0 | 383,540 |
| `r1` | hat | 108.54632568359375 | 376,362 |
| `r2` | sunglasses | 100.0 | 413,492 |

Each measured mesh has one closed face-connected solid, positive volume, zero measured self-intersections, and no manifold, winding, loose-vertex, or degeneracy failures.
The complete hidden base is identical across revisions.
Source, export, reimport, preservation baseline, and render evidence must bind to the selected profile identifier and canonical hash.
The 4 MiB observation bound, 500,000-facet limit, geometry thresholds, and minimum feature target remain unchanged.
Complete feature coverage remains unknown.

## Offline slicer inspection

The separate [printer setup record](../experimental_modeling/examples/anime_cat/print/x1c_generic_pla_textured_v1.json) identifies the official presets and local overrides.
Inspection uses official [Bambu Studio v02.08.02.61](https://github.com/bambulab/BambuStudio/releases/tag/v02.08.02.61), source commit `926a7192574bcb9b3a732e1ec59a46d79cb45466`.
Official machine, filament, and process files and their inheritance chains were checked against that commit's Git blob identities.
The selected names are `Bambu Lab X1 Carbon 0.4 nozzle`, `Generic PLA`, and `0.20mm Standard @BBL X1C`.

Generic PLA and Textured PEI Plate are explicit assumptions.
Filament brand, the actual plate, firmware, and calibration are unconfirmed.
Inherited settings include 0.2 mm layers, 15% infill, 220 C nozzle temperature, and 55 C textured-plate temperature.
Local overrides select three walls, gyroid infill, automatic tree supports, Textured PEI Plate, and no model arc fitting.
The machine preset has a 256 by 256 mm print area, 250 mm printable height, and an excluded lower-left 18 by 28 mm region.
These settings are an inspection configuration, not a validated printer recipe.

The task-local macOS DMG SHA-256 is `cf648a95858fb630e1353c4987038df60d6caab693f18411fb95fb809f2d6926`.
It was mounted read-only. Strict signature verification and notarization assessment passed with the trusted Developer ID `Shanghai Lunkuo Technology (T3UBR9Y3B2)`.
No global application installation or network plugin was required.

The native CLI runs under an operating-system policy that denies all networking.
It uses fresh data and output directories, loaded settings, preset checks, `--arrange 1`, `--orient 0`, `--scale 1`, and `--slice 0`.
Automatic arrangement can change the object's in-plane placement or rotation.
Canonical source-coordinate preservation checks cannot be applied directly to bed-space exports.

The official [CLI documentation](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage) describes settings, slicing, and exports.
For this pinned build, register `--export-slicedata` before `--slice`.
The opposite action order produced an empty cache despite exit code zero.

The actual hat inspection produced G-code, effective settings, a 3MF, a native STL, 543 object layers, and 442 support layers in its slice cache.
The cache contains slice polygons and extrusion records, rather than the raw three-dimensional buffers consumed by slicing.
Its presence and a successful exit do not prove complete feature, path, or support accounting.
Machine startup commands also include arcs and motions outside model bounds.
A model-only G-code reader must retain their modal effects.

Complete independent native-export observations measured these results after arrangement into bed coordinates:

| Revision | Object layers | Support layers | Native self-intersections | Complete intersection pairs |
|---|---:|---:|---:|---:|
| `r0` | 500 | 310 | 4 | 2,430,487 |
| `r1` | 543 | 442 | 4 | 2,470,153 |
| `r2` | 500 | 359 | 0 | 2,626,215 |

All three canonical input STLs passed the same intersection gate.
Thus a successful native slice does not establish native geometry acceptance.
The native exports and complete measurements remain retained, including both failures.
No geometry threshold or coordinate tolerance was relaxed.

An initial bare-cat cache export failed because the cache parent directory did not exist.
The fresh retry created that directory before execution and passed native slicing and cache export.
The failed attempt remains retained too.

## Verification and remaining gates

Run the focused version and preservation tests:

```sh
TMPDIR=/private/tmp python3 -m unittest \
  tests.experimental_modeling.test_x1c_print_profile \
  tests.experimental_modeling.test_print_contract \
  tests.experimental_modeling.test_anime_cat_print \
  tests.experimental_modeling.test_print_preservation \
  tests.experimental_modeling.test_print_export_history -v
```

Run both complete offline runners with `--profile-id anime-cat-x1c-pla-04-bare100-v2`:

```sh
python3 tests/experimental_modeling/run_anime_cat_print.py \
  --store build/x1c-candidates --sandbox-image "$MODELING_SANDBOX_IMAGE" \
  --profile-id anime-cat-x1c-pla-04-bare100-v2
python3 tests/experimental_modeling/run_anime_cat_print_export.py \
  --store build/x1c-stl --candidates build/x1c-candidates \
  --sandbox-image "$MODELING_SANDBOX_IMAGE" \
  --profile-id anime-cat-x1c-pla-04-bare100-v2
```

The geometry runner includes eight real Blender rejection and transaction probes.
The STL runner measures every final facet and compares exact source and reimported surfaces.
It checks the frozen v2 base and rebuilds the glasses STL.
Five specific invalid exports must be rejected without changing accepted fixture history.
The default v1 STL runner also checks all three original canonical STL hashes.
CI retains separate v1 and v2 evidence and leaves live model calls disabled.

Native consumed-buffer fidelity, complete feature and support accounting, independent visual acceptance, and physical validation remain pending.
Printer parameters do not approve a numeric fidelity tolerance or an upstream instrumented slicer build.
All reports retain `promotion_eligible: false` and `physical_validation: "pending"`.
No printer connection, cloud operation, G-code upload, or physical print was performed.
