<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Licensing guide

This guide explains the v0.1 licensing structure adopted by the repository.
It is a summary for project operations.
It is not legal advice and does not replace the license texts that control each work.

## Project source code

Unless a file specifies a different license, repository source, schemas, scripts, configuration, tests, and documentation use the GNU General Public License.
The version is 3 or any later version (`GPL-3.0-or-later`).
The full license text is in [`LICENSE`](../LICENSE).
Package and OCI metadata use the same SPDX identifier.

The GPL permits use, study, changes, redistribution, and commercial use subject to its conditions.
A distributor of a covered binary or container must supply notices and Corresponding Source as specified by the GPL.
GPLv3 treats operation of a modified service without conveyance differently from distribution of a software copy.
This project does not use the AGPL.

## Blender and containers

Blender is distributed independently under the GPL with compatible bundled components.
The builder uses the official Blender 4.5.12 LTS Linux x64 binary archive.
[`docker/BLENDER_SOURCE_NOTICE.md`](../docker/BLENDER_SOURCE_NOTICE.md) records its checksum and corresponding-source locations.
The image keeps Blender's copyright and machine-readable license inventory.

A person who publishes or redistributes an image with Blender must meet the notices and corresponding-source duties for that distribution method.
The project's source link does not give that responsibility to the maintainers.

`make release-check` packages the Blender 4.5.12 source archive with its pinned byte count and SHA-256.
The package also includes the project source for that version, dependency inventories, SBOMs, and notices.
The machine-readable inventory marks this material as `project-and-blender-source-only` and `public_oci_ready: false`.
This is useful release evidence.
It is not a complete corresponding-source decision for each native, base-image, or copyleft component in the completed containers.

Public OCI publication stays blocked until reviewers complete these tasks independently:

1. Start from the SBOMs of the actual completed images.
2. Identify each applicable source and delivery duty.
   Include LGPL/native and operating-system components.
3. Add the necessary material with checksum bindings.
4. Add the retention plan.

The future publication transaction must also include the project-derived PostgreSQL image.
It must inventory that image, make its SBOM, sign it, publish it, and lock its digest.
Current tools process only the builder, API, and worker images.
This guide is not legal advice.

Blender's GPL does not automatically apply to usual artwork made with Blender.
Read [`OUTPUT_POLICY.md`](../OUTPUT_POLICY.md) for the project's output policy and warranty limits.

## Sample assets

Project source and sample artwork have different license policies.
Original sample assets made for this project are intended to use `CC0-1.0` unless a file manifest specifies a different license.
Read [`ASSET_LICENSE.md`](../ASSET_LICENSE.md).

Before you add a sample model, render, texture, font, reference, or other asset, do these tasks:

1. Make sure that the contributor made it or has redistribution rights.
2. Use an original, neutral character.
   Do not use franchise or brand material.
3. Record the creator, source, license, changes, and checksum.
4. Keep the required attribution and license text.
5. Keep large generated artifacts in release assets, not in usual source history.
   Maintainers can approve a small preview with documentation as an exception.

CC0 gives no permission to use third-party trademark, personality, privacy, publicity, patent, or other rights.

## User inputs and generated outputs

Users are responsible for the rights to submitted names, designs, references, logos, and likenesses.
The project gives no rights to third-party characters or brands.
It does not automatically decide if an output is protected or cleared for a proposed use.

Maintainers do not claim a user's usual generated output only because the project made it.
Rights and permitted uses can depend on the input, embedded assets, generator, human contribution, contracts, and local law.
Geometry QA does not give legal clearance or a physical-print guarantee.

## Third-party dependencies

[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) summarizes direct dependencies and services deployed independently.
For a specified build, examine the version locks, upstream license files, installed package metadata, image notices, and release SBOM.
These records identify the components and licenses for that build.
For a dependency upgrade, review license compatibility and redistribution obligations.

Project and upstream names identify only provenance or compatibility.
They do not imply a trademark license, affiliation, sponsorship, or endorsement.

## Contributions and DCO

Contributions stay under their authors' copyright and use the applicable repository license.
The project uses Developer Certificate of Origin 1.1 sign-off, not a Contributor License Agreement.
Each commit must contain a valid `Signed-off-by` trailer.
Read [`CONTRIBUTING.md`](../CONTRIBUTING.md).

DCO sign-off is a contributor attestation about the right to submit a change.
It does not assign copyright to another person.
It does not give maintainers unilateral rights to change the license of a contributor's work.
A future license change can make permission from the applicable copyright holders necessary.

## SPDX convention

For new source files, this license comment is recommended: `SPDX-License-Identifier: GPL-3.0-or-later`.
Use the comment format for the applicable language.
For sample assets with a different license, the project recommends their correct identifier and manifest entry.
Do not add a license identifier unless the contributor has authority to apply it.

## Optional provider integrations

OpenAI planning and MCP integration are optional features for work after v0.1.
They do not change the deterministic builder's GPL license.
Operators must supply their own credentials and obey the applicable provider terms and use policies.
Do not put secrets in repository history, browser code, Blender workers, logs, manifests, or artifacts.
