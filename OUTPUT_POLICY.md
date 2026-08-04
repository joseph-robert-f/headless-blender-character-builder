<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Generated output policy

This policy describes the normal artifacts produced by Headless Blender
Character Builder v0.1. It does not change the source-code license in
`LICENSE`, the sample-asset policy in `ASSET_LICENSE.md`, or any rights that
apply to material supplied by a user.

## What v0.1 produces

The bounded `complete-v1` profile can publish an editable Blender file, GLB,
STL, preview and diagnostic renders, `manifest.json`, and `qa.json`. These
artifacts are generated from a strict declarative `BuildRequest`; the public
v0.1 interfaces do not accept uploaded `.blend` files, arbitrary Python,
add-ons, remote URLs, or reference-image ingestion.

The v0.1 project is intended for original geometric, chibi, and low-poly
characters assembled by the reviewed generator. It is not a general
text-to-3D, organic-sculpting, exact-likeness, or protected-character service.

## Rights and licensing

- Project source code is licensed under `GPL-3.0-or-later`.
- Normal artwork produced by running Blender is not automatically covered by
  Blender's GPL merely because Blender produced it.
- The maintainers do not claim ownership of a user's normal generated output.
  Whether an output is protected, who owns it, and what uses are permitted can
  depend on the inputs, generator assets, human contribution, contract terms,
  and applicable law.
- This project grants no rights to third-party characters, names, logos,
  brands, trade dress, reference material, or likenesses.
- Example assets supplied by this repository are governed separately by
  `ASSET_LICENSE.md` and any per-file manifest.
- If an output contains project source code or another independently licensed
  work, that embedded material keeps its own license. This policy does not
  override it.

Users and operators are responsible for submitting and publishing only
original or rights-cleared designs. Do not use the project to reproduce,
adapt, sell, or distribute a protected character, real-person likeness, or
brand asset without the permissions required for that use.

## QA is evidence, not a manufacturing warranty

A `passed` `geometry-v1` report means only that the artifact satisfied the
objective checks and thresholds recorded in that report, such as finite
geometry, manifoldness, normals, volume, dimensions, measured feature limits,
fresh reload, and GLB/STL re-import. It does **not** mean that:

- a particular printer, slicer, process, orientation, support strategy,
  nozzle, resin, material, or scale will succeed;
- the part is strong, stable, child-safe, food-safe, electrically safe, or fit
  for a particular purpose;
- manufacturing tolerances, clearances, overhangs, drainage, supports, or
  machine-specific constraints have been validated; or
- the design is suitable for medical, structural, protective, regulated, or
  other safety-critical use.

Before physical manufacture, the operator must inspect the artifact, use an
appropriate slicer and printer/material profile, and perform calibration and
test prints. A `needs_review` or `failed` result must never be represented as
a successful validated build.

## Privacy and publication

Generated artifacts may reveal character names, geometry, chosen colors,
dimensions, hashes, and build provenance. Treat outputs as private unless the
user has chosen to publish them. A hosted operator should use access controls,
short-lived version-pinned download URLs, documented retention, and secure
deletion; no hosted service is provided by this repository.

## No endorsement or clearance

An artifact is not endorsed, certified, or legally cleared by the project,
Blender, or any optional service provider. The software and outputs are
provided without warranty to the extent allowed by the applicable licenses
and law.
