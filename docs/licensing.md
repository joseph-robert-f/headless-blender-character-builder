<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Licensing guide

This guide explains the repository's adopted v0.1 licensing structure. It is
an operational summary, not legal advice and not a replacement for the license
texts that govern each work.

## Project source code

Unless a file says otherwise, repository source, schemas, scripts,
configuration, tests, and documentation are licensed under the GNU General
Public License, version 3 or any later version (`GPL-3.0-or-later`). The full
license text is in [`LICENSE`](../LICENSE); package and OCI metadata use the
same SPDX identifier.

The GPL permits use, study, modification, redistribution, and commercial use,
subject to its conditions. A distributor of a covered binary or container must
provide notices and Corresponding Source in a GPL-compliant way. Running a
modified service without conveying a copy is treated differently by GPLv3
from distributing that software; this project is not licensed under the AGPL.

## Blender and containers

Blender is independently distributed under the GPL with compatible bundled
components. The builder uses the official Blender 4.5.12 LTS Linux x64 binary
archive and records its checksum and corresponding-source locations in
[`docker/BLENDER_SOURCE_NOTICE.md`](../docker/BLENDER_SOURCE_NOTICE.md).

The image preserves Blender's copyright and machine-readable license
inventory. Anyone publishing or redistributing an image containing Blender
must satisfy the notices and corresponding-source duties for their own
distribution method; the project's source link does not transfer that
responsibility to the maintainers.

Blender's GPL does not automatically apply to normal artwork created with
Blender. See [`OUTPUT_POLICY.md`](../OUTPUT_POLICY.md) for the project's output
and no-warranty boundary.

## Sample assets

Project source and sample artwork are deliberately separated. Original sample
assets created for the project are intended to use `CC0-1.0` unless a per-file
manifest says otherwise. See [`ASSET_LICENSE.md`](../ASSET_LICENSE.md).

Before adding a sample model, render, texture, font, reference, or other asset:

1. confirm that the contributor created it or has redistribution rights;
2. use an original, neutral character rather than franchise or brand material;
3. record creator, source, license, modifications, and checksum;
4. preserve required attribution and license text; and
5. keep large generated artifacts in release assets rather than normal source
   history unless the maintainers approve a small documented preview.

CC0 does not grant permission to use a third party's trademark, personality,
privacy, publicity, patent, or other rights.

## User inputs and generated outputs

Users are responsible for rights to submitted names, designs, references,
logos, and likenesses. The project grants no rights to third-party characters
or brands and does not automatically determine whether an output is protected
or cleared for a proposed use.

The maintainers do not claim a user's normal generated output merely because
the project produced it. Rights and permitted uses can still depend on the
input, any embedded asset, the generator, human contribution, contracts, and
local law. Generated geometry QA is not a legal clearance or physical-print
guarantee.

## Third-party dependencies

[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) summarizes direct
dependencies and separately deployed services. Version locks, upstream
license files, installed package metadata, image notices, and the release SBOM
are authoritative for an exact build. Dependency upgrades must review both
license compatibility and redistribution obligations.

Project and upstream names identify provenance or compatibility only. No
trademark license, affiliation, sponsorship, or endorsement is implied.

## Contributions and DCO

Contributions remain copyrighted by their authors and are submitted under the
repository's applicable license. The project uses Developer Certificate of
Origin 1.1 sign-off rather than a Contributor License Agreement. Every commit
must include a valid `Signed-off-by` trailer as described in
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

DCO sign-off is a contributor attestation about the right to submit a change;
it is not copyright assignment and does not give maintainers unilateral rights
to relicense a contributor's work. A future license change may therefore need
permission from the relevant copyright holders.

## SPDX convention

New source files should carry `SPDX-License-Identifier: GPL-3.0-or-later` in a
language-appropriate comment. Separately licensed sample assets should use
their actual identifier and manifest entry. Do not add a license identifier to
a file unless the contributor has authority to apply it.

## Optional provider integrations

OpenAI planning and MCP integration are post-v0.1 and optional. They do not
change the deterministic builder's GPL license. Operators must bring their own
credentials, comply with applicable provider terms and usage policies, and
keep secrets out of repository history, browser code, Blender workers, logs,
manifests, and artifacts.
