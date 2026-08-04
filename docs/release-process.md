# Release process

This document separates local release-candidate proof from external
publication. Local commands never push, tag, publish an image, create a GitHub
Release, deploy a VPS, or use registry/cloud credentials.

## Local release candidate

Prerequisites are Git, Docker Engine/Desktop, Docker Compose v2, GNU Make,
roughly four CPU cores, 8 GB RAM, and sufficient disk for pinned images plus
temporary build evidence.

1. Start from the intended signed-off commit with no unrelated changes.
2. Run `make release-check`. The wrapper audits the Git index, exports only
   indexed files with `git checkout-index`, and runs the complete gate from the
   temporary tree.
3. Review the final evidence directory printed by the command. It contains the
   optimized sample release bundle, checksums, SPDX SBOMs, image metadata, and
   sanitized gate summaries; it contains no `.env` or credentials.
4. Confirm `git status --short`, `git diff --check`, and
   `scripts/release-audit` remain clean after any repair.
5. Record exact evidence and any externally conditional checks in
   `docs/progress.md`.

The release check covers source/policy audits, ordinary unit and contract
tests, real headless Blender generation, fresh `.blend` reload and GLB/STL
import, hardened builder configuration, asynchronous service smoke, IAM and
Redis isolation, VPS topology/Caddy checks, isolated backup/restore, SBOM and
notice validation, documentation/workflow validation, versioned local image
tags, and deterministic release checksums.

## Version and local image identity

`VERSION` contains the base application version. Release-candidate local tags
use `0.1.0-rc.1`; a final publication may use `0.1.0` only after all required
reviews pass. A mutable tag is never sufficient deployment identity.

Record for each builder, API, and worker image:

- repository and version tag;
- OCI config image ID from `docker image inspect`;
- platform (`linux/amd64`);
- source commit and clean indexed-tree hash;
- builder source revision;
- manifest-list digest after registry publication;
- SPDX SBOM checksum.

Populate `deploy/vps/release.lock.env` from these reviewed values. Production
Compose accepts digest references, not a floating `latest` tag.

## Container corresponding-source gate

Source commits, source tags, and source/sample release assets may be published
after their own gates pass. Public builder and worker image distribution is a
separate gate because those images contain Blender and other independently
licensed binary components. The API image also contains GPL-covered project
source and is kept in the same release-source process.

Before any public OCI push, the operator must create and independently review an
image-by-image corresponding-source inventory from the exact SBOM and installed
notices, choose a GPL-compliant delivery method for every applicable component,
and record its availability and retention policy. The conservative project
default is to accompany the release with checksum-bound corresponding-source
archives for the exact conveyed versions. An upstream link or Dockerfile alone
is not accepted as proof that the obligation has been satisfied. If the required
source set or a reviewed distribution method is uncertain, image publication
stays blocked while source-repository publication may proceed.

The source package must be regenerated for the exact release commit and cover
the project source, the exact Blender 4.5.12 source, and every other component
for which the selected distribution method requires Corresponding Source. Keep
license texts and build/install information required by the applicable licenses,
record checksums beside the image digests, and retain the source for the required
period. This is a conservative release policy, not legal advice; obtain qualified
review for a different distribution method.

## Conditional publication

Publication requires explicit owner authorization and authenticated GitHub and
GHCR access. A release operator then:

1. verifies branch protection, required checks, CODEOWNERS, secret scanning,
   push protection, and private vulnerability reporting;
2. reruns the local release check on the exact commit;
3. creates a signed `v0.1.0-rc.1` tag;
4. builds `linux/amd64` builder, API, and worker images from that tag;
5. completes the container corresponding-source gate above;
6. pushes immutable version tags to GHCR, captures registry digests, and never
   deploys by `latest`;
7. attaches the generated sample bundle, checksums, SBOMs, notices,
   corresponding source, and release notes to a draft GitHub Release;
8. verifies the published image by digest in a clean environment;
9. publishes the release only after the digest-based smoke passes.

No step above is performed by `make release-check`. Exact registry and GitHub
commands are intentionally operator-run so credentials and irreversible public
actions cannot be triggered by a local test target. After reviewing every
placeholder and receiving explicit publication authorization, the command
shape is:

```sh
export RC_VERSION=0.1.0-rc.1
export GH_OWNER=joseph-robert-f
export RELEASE_DIR=build/release-check/g9-final/release

git tag -s "v${RC_VERSION}" -m "Headless Blender Character Builder ${RC_VERSION}"
git push origin "v${RC_VERSION}"

printf '%s' "$CR_PAT" | docker login ghcr.io -u "$GH_OWNER" --password-stdin
docker tag "headless-blender-character-builder:${RC_VERSION}" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"
docker tag "headless-blender-character-builder-api:${RC_VERSION}" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}"
docker tag "headless-blender-character-builder-worker:${RC_VERSION}" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"
docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"
docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}"
docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"

gh release create "v${RC_VERSION}" "$RELEASE_DIR"/* \
  --draft \
  --verify-tag \
  --title "Headless Blender Character Builder ${RC_VERSION}" \
  --notes-file docs/release-notes/v0.1.0-rc.1.md
```

`CR_PAT` is a short-lived operator-supplied token with only the package scope
needed for the target owner; do not write it to `.env`, shell history, logs, or
release evidence. Capture the pushed `RepoDigest` values, replace the VPS lock
examples with those immutable digests, and verify by digest before publishing
the draft Release. GitHub's current references are the
[Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
and [`gh release create` manual](https://cli.github.com/manual/gh_release_create).

## Rollback

For source and images, roll back by deploying a previously verified digest. Do
not move an existing version tag. Database migrations are forward-only: after
an upgrade enters its writable phase, retry the exact target or restore the
verified pre-upgrade backup into a validated empty namespace. See
[deployment.md](deployment.md).

## Final operator checklist

- [ ] Outside clean-room quickstart completed, if a reviewer is available.
- [ ] GitHub-hosted CI passed on the published commit.
- [ ] GitHub license detection recognizes GPL-3.0.
- [ ] Private vulnerability reporting and secret protection are enabled.
- [ ] The exact image corresponding-source inventory, delivery method,
      checksums, and retention policy passed independent review.
- [ ] GHCR digests and SBOM checksums match the draft release.
- [ ] Release assets contain no secrets, signed URLs, private references, or
      personal absolute paths.
- [ ] Any live VPS, DNS, ACME, firewall, provider IAM, and off-host backup test
      was separately authorized and recorded.
