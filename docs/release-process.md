# Release process

This document separates local release-candidate proof from external
publication. Local commands never push, tag, publish an image, create a GitHub
Release, deploy a VPS, or use registry/cloud credentials.

## Local release candidate

Prerequisites are Git, Docker Engine/Desktop, Docker Compose 2.24.4+, GNU Make,
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

The manually dispatched GitHub release-candidate workflow assigns a unique
run/attempt evidence ID. After a successful full gate it uploads the complete
sanitized evidence directory as a GitHub Actions artifact for seven days. A
local run and a failed hosted run do not create any release automatically.

## Version and local image identity

`VERSION` contains the base application version. Release-candidate local tags
use `0.1.0-rc.1`; a final publication may use `0.1.0` only after all required
reviews pass. Python metadata, service runtime metadata, and current OCI labels
record the base `0.1.0` application compatibility version; the `-rc.1` suffix
identifies the candidate distribution rehearsal. This distinction is recorded
for source-only evaluation, but public OCI publication stays blocked until the
candidate distribution identifier is injected into and checked against every
published image label, tag, and release metadata field. A mutable tag is never
sufficient deployment identity.

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
GHCR access. The candidate-identity binding described above is an additional
unimplemented publication prerequisite; the current repository is therefore
source-only. After that gate is implemented and reviewed, a release operator
then:

1. verifies branch protection, required checks, CODEOWNERS, secret scanning,
   push protection, and private vulnerability reporting;
2. reruns the local release check on the exact commit;
3. runs `make dependency-scan` from that exact commit using a new output
   directory; requires exit `0`; reviews the retained reports; and performs
   publication no more than seven days after that scan;
4. creates a signed `v0.1.0-rc.1` tag;
5. builds `linux/amd64` builder, API, and worker images from that tag;
6. completes the container corresponding-source gate above;
7. pushes immutable version tags to GHCR, captures registry digests, and never
   deploys by `latest`;
8. attaches the generated sample bundle, checksums, SBOMs, notices,
   corresponding source, and release notes to a draft GitHub Release;
9. verifies the published image by digest in a clean environment;
10. publishes the release only after the digest-based smoke passes.

Run the dependency-scan step from the clean release worktree with a unique,
ignored destination and retain that directory until publication review:

```sh
release_commit=$(git rev-parse HEAD)
dependency_evidence="$PWD/build/dependency-audit-release-${release_commit}"
test ! -e "$dependency_evidence"
make dependency-scan DEPENDENCY_OUTPUT="$dependency_evidence"
test "$(git rev-parse HEAD)" = "$release_commit"
```

`make release-check` performs only the local gate in step 2; it does not run the
networked dependency scan or any publication step. Exact registry and GitHub
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

## Dependency maintenance

`make dependency-check` is the offline, release-blocking consistency gate. It
binds Python declarations to hash locks and reviewed evidence, every Debian
base stage to OCI/SPDX provenance, and root PostgreSQL/Redis pins to recovery
Compose, exact assertions, and notices. It also binds the Caddy gate reference
to the operator lock example and notice. The scheduled/manual
`dependency-audit.yml` workflow has read-only repository permission. It reports
upstream status and vulnerability findings without creating branches, issues,
or pull requests.

Dependency updates are prepared as coordinated maintainer changes. A Compose
image update must synchronize `tests/deployment/g8_recovery_compose.yaml`, its
exact-pin assertions, migration/recovery behavior, and affected notice or
license evidence before merge. A database major version is a migration project,
not an automated image bump. The complete process and exit meanings are in
[dependency-maintenance.md](dependency-maintenance.md).

GitHub Actions remain full-commit-SHA pinned and are reviewed manually because
workflow permissions and external code require explicit trust review. Action-
pin changes must retain `persist-credentials: false`, pass the release-policy
tests, and record the reviewed upstream release/tag for the selected commit.

## Rollback

For source and images, roll back by deploying a previously verified digest. Do
not move an existing version tag. Database migrations are forward-only: after
an upgrade enters its writable phase, retry the exact target or restore the
verified pre-upgrade backup into a validated empty namespace. See
[deployment.md](deployment.md).

## Final operator checklist

- [ ] Outside clean-room quickstart completed, if a reviewer is available.
- [ ] GitHub-hosted CI passed on the published commit.
- [ ] A complete dependency scan exited `0` on this exact commit within the
      last seven days, and its reports were reviewed.
- [ ] GitHub license detection recognizes GPL-3.0.
- [ ] Private vulnerability reporting and secret protection are enabled.
- [ ] The exact image corresponding-source inventory, delivery method,
      checksums, and retention policy passed independent review.
- [ ] GHCR digests and SBOM checksums match the draft release.
- [ ] Release assets contain no secrets, signed URLs, private references, or
      personal absolute paths.
- [ ] Any live VPS, DNS, ACME, firewall, provider IAM, and off-host backup test
      was separately authorized and recorded.
