<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Generated output policy

This policy describes the usual artifacts from Headless Blender Character Builder v0.1.
It does not change the source-code license in `LICENSE` or the sample-asset policy in `ASSET_LICENSE.md`.
It does not change rights that apply to material supplied by a user.

## What v0.1 produces

The `complete-v1` profile, with its specified limits, can publish these artifacts:

- An editable Blender file
- GLB and STL files
- Preview and diagnostic renders
- `manifest.json` and `qa.json`.

These artifacts come from a strict declarative `BuildRequest`.
The public v0.1 interfaces do not accept uploaded `.blend` files, arbitrary Python, add-ons, remote URLs, or reference-image inputs.
The reviewed generator assembles original geometric, chibi, and low-poly characters.
The project is not a general text-to-3D, organic-sculpting, exact-likeness, or protected-character service.

## Rights and licensing

- Project source code uses the `GPL-3.0-or-later` license.
- Blender's GPL does not automatically apply to usual artwork only because Blender made it.
- Maintainers do not claim ownership of a user's usual generated output.
  Output protection, ownership, and permitted uses can depend on the inputs, generator assets, human contribution, contract terms, and applicable law.
- This project gives no rights to third-party characters, names, logos, brands, trade dress, references, or likenesses.
- `ASSET_LICENSE.md` and each applicable file manifest control the example assets supplied by the repository.
- If an output contains project source code or another work with its own license, that material keeps its license.
  This policy does not replace that license.

Users and operators must submit and publish only original designs or designs with the necessary rights clearance.
Do not reproduce, adapt, sell, or distribute protected characters, real-person likenesses, or brand assets without permission for that use.

## QA is evidence, not a manufacturing warranty

A `passed` `geometry-v1` report shows only that the artifact met the checks and limits recorded in that report.
Examples include finite geometry, manifoldness, normals, volume, dimensions, measured feature limits, new reload, and GLB/STL re-import.
A report with that status does not prove these results:

- Print success with a specified printer, slicer, process, orientation, support strategy, nozzle, resin, material, or scale
- Strength, stability, child safety, food safety, electrical safety, or fitness for a specified purpose
- Manufacturing tolerances, clearances, overhangs, drainage, supports, or machine-specific constraints are validated
- Fitness for medical, structural, protective, regulated, or other safety-critical use.

Before physical manufacture, examine the artifact.
Use an applicable slicer and printer/material profile.
Do the calibration and test prints.
Do not represent a `needs_review` or `failed` result as a validated build with a `passed` result.

## Privacy and publication

Generated artifacts can show character names, geometry, selected colors, dimensions, hashes, and build provenance.
Keep outputs private unless the user selects publication.
This repository supplies no hosted service.
Access controls and short-lived download URLs pinned to artifact versions are recommended for hosted operators.
Documented retention and secure deletion are also recommended.

## No endorsement or clearance

The project, Blender, and optional service providers do not endorse, certify, or give legal clearance for an artifact.
The software and outputs have no warranty to the extent permitted by the applicable licenses and law.
