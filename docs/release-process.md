# Release process

This document separates local release-candidate proof from external
publication. Local commands never push, tag, publish an image, create a GitHub
Release, deploy a VPS, or use registry/cloud credentials.

## Local release candidate

Prerequisites are Git, Python 3.11+, Docker Engine/Desktop, Docker Compose
2.24.4+, GNU Make, roughly four CPU cores, and at least 12 GiB allocated to
Docker plus host overhead. Keep at least 20 GB free for the checkout and
evidence, and budget roughly 30 GB of Docker disk headroom when the image cache
is cold. If `python3` is older, select the supported interpreter for the whole
command, for example
`PYTHON=python3.11 HBCB_RELEASE_RUN_ID=review-1 make release-check`. The full gate also
needs outbound HTTPS to the
official Blender download host, unless
`HBCB_BLENDER_SOURCE_ARCHIVE=/absolute/path/to/blender-4.5.12.tar.xz` supplies
the already-downloaded exact archive; the same size and checksum policy applies.

1. Start from the intended signed-off commit with no unrelated changes. The
   full gate requires the Git index to equal `HEAD`; commit the reviewed change
   first rather than trying to release staged, uncommitted bytes.
2. Run `HBCB_RELEASE_RUN_ID=<unique-safe-run-id> make release-check`. The
   wrapper audits the Git index, exports only
   indexed files with `git checkout-index`, and runs the complete gate from the
   temporary tree. The run ID is mandatory and must be unique across every
   checkout using the same Docker daemon; use a new value for every retry. The
   wrapper refuses a pre-existing Compose project and reports failure unless
   the exact project, its volumes, and any temporary extraction container are
   absent after cleanup. It also holds the fixed private Docker volume
   `hbcb-release-check-claim` as an atomic daemon-wide claim, so only one full
   release check may run against a Docker daemon at a time. The random owner
   label prevents cleanup from taking over or deleting another process's claim.
3. Review the final evidence directory printed by the command. It contains the
   optimized sample release bundle, checksums, SPDX SBOMs, image metadata, and
   sanitized gate summaries; it contains no `.env` or credentials.
4. Confirm `git status --short`, `git diff --check`, and
   `scripts/release-audit` remain clean after any repair.
5. Record exact evidence and any externally conditional checks in
   `docs/progress.md`.

If the daemon-wide claim already exists, stop rather than deleting it. Inspect
`docker volume inspect hbcb-release-check-claim`, determine whether an earlier
release process is still active, and obtain maintainer approval before any
manual stale-claim recovery. The tool never automatically takes over an
existing claim.

The release check covers source/policy audits, ordinary unit and contract
tests, real headless Blender generation, fresh `.blend` reload and GLB/STL
import, hardened builder configuration, asynchronous service smoke, IAM and
Redis isolation, VPS topology/Caddy checks, isolated backup/restore, SBOM and
notice validation, documentation/workflow validation, versioned local image
tags, exact OCI source/version/revision labels, checksum-verified corresponding
source, and deterministic release checksums.

The manually dispatched GitHub release-candidate workflow assigns a unique
run/attempt evidence ID. After a successful full gate it uploads the complete
sanitized evidence directory as a GitHub Actions artifact for seven days. A
local run and a failed hosted run do not create any release automatically.

## Version and local image identity

`VERSION` contains the base application compatibility version. Ordinary local
builds label themselves `0.1.0-local` with revision `uncommitted`, so they do
not impersonate a release. The release gate injects `0.1.0-rc.1` and the exact
audited Git commit into builder, API, and worker OCI labels, gives all three the
matching candidate tag, then fails unless labels, tags, inspected image IDs,
release metadata, and corresponding-source inventory agree. A mutable tag is
never sufficient deployment identity.

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

The full release gate creates `corresponding-source.json`, an image-bound record
of the exact project and Blender source currently packaged, plus associated
SBOMs and notices. The record explicitly declares scope
`project-and-blender-source-only` and `public_oci_ready: false`; it is not a
claim that every copyleft/native/base-image source obligation has been
resolved. The gate fetches the 85,105,056-byte official Blender 4.5.12
source archive directly over HTTPS without proxy environment variables or
redirects, verifies the repository-pinned SHA-256, and includes the archive in
the release directory. The deterministic project source archive, Blender source
archive, inventory, SBOMs, notices, and sample archive are all covered by
`SHA256SUMS`. `HBCB_BLENDER_SOURCE_ARCHIVE=/absolute/path/to/blender-4.5.12.tar.xz`
may reuse an operator-supplied download, but it passes the identical byte-count
and SHA-256 gate. Missing or altered source fails closed.

Public OCI publication remains blocked. Before any push, an independent reviewer
must inventory the actual final images—including native Python wheels and
operating-system packages—identify every applicable copyleft/source-delivery
duty, add checksum-bound source material and a retention plan, and change the
machine-readable readiness flag through review. The existing assets must still
be co-published and retained with each eventual public image version. This is a
conservative release policy, not legal advice; obtain qualified review.

## Conditional publication

Publication requires explicit owner authorization, an installed and
authenticated GitHub CLI, authenticated GHCR access, and a tested Git tag-
signing key configured explicitly as `user.signingkey`. Identity and
corresponding-source evidence are automated locally, but public publication
remains an operator-reviewed, separately authorized act. A release operator:

1. verifies branch protection, required checks, CODEOWNERS, secret scanning,
   push protection, and private vulnerability reporting;
2. reruns the local release check on the exact commit;
3. runs `make dependency-scan` from that exact commit using a new output
   directory; requires exit `0`; reviews the retained reports; and performs
   publication no more than seven days after that scan;
4. confirms the local release check built `linux/amd64` builder, API, and
   worker images from that exact commit and verifies their local identities;
5. independently completes actual-image copyleft/source review, supplies every
   required source asset, changes `public_oci_ready` to true through a reviewed
   code change, and confirms every mapped asset will be retained;
6. confirms the GHCR packages remain private, pushes immutable version tags
   only after step 5 is complete, captures registry digests, and never deploys
   by `latest`;
7. creates and pushes the signed `v0.1.0-rc.1` Git tag only after all three
   private image pushes succeed;
8. creates a draft GitHub Release and uploads every generated top-level source,
   checksum, SBOM, notice, inventory, metadata, and sample archive asset;
9. verifies both the private pushed images by digest in a clean environment and
   the downloaded Release assets against `SHA256SUMS`;
10. publishes the source-bearing Release before separately changing the matched
    GHCR packages to public visibility. If that ordering cannot be guaranteed,
    image publication stays blocked.

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
(
set -eu

export RC_VERSION=0.1.0-rc.1
export GH_OWNER=joseph-robert-f
export RELEASE_RUN_ID=replace-with-reviewed-run-id
export RELEASE_DIR="$PWD/build/release-check/$RELEASE_RUN_ID/release"
export PYTHON=${PYTHON:-python3}

command -v gh >/dev/null
command -v docker >/dev/null
command -v "$PYTHON" >/dev/null
gh auth status --hostname github.com
test -n "$(git config --get user.signingkey)"
test -n "${CR_PAT:-}"
test "$(git rev-parse --show-toplevel)" = "$PWD"
test "$(git status --porcelain)" = ""
test -d "$RELEASE_DIR"
test ! -L "$RELEASE_DIR"

HBCB_SOURCE_INVENTORY="$RELEASE_DIR/corresponding-source.json" \
  "$PYTHON" - <<'PY'
import json
import os
from pathlib import Path

inventory = json.loads(Path(os.environ["HBCB_SOURCE_INVENTORY"]).read_text())
if inventory.get("public_oci_ready") is not True:
    raise SystemExit("public OCI publication remains blocked by source review")
PY

(
  cd "$RELEASE_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)

# Authenticate to GHCR before the first remote mutation. A missing or
# under-scoped token must not leave a pushed tag or partial draft Release.
printf '%s' "$CR_PAT" | docker login ghcr.io -u "$GH_OWNER" --password-stdin

docker tag "headless-blender-character-builder:${RC_VERSION}" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"
docker tag "headless-blender-character-builder-api:${RC_VERSION}" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}"
docker tag "headless-blender-character-builder-worker:${RC_VERSION}" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"

# Push private packages first. Do not change package visibility yet. This keeps
# a registry failure from leaving a Git tag or draft Release behind.
docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"
docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}"
docker push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"

git tag -s "v${RC_VERSION}" -m "Headless Blender Character Builder ${RC_VERSION}"
git tag -v "v${RC_VERSION}"
git push origin "v${RC_VERSION}"
gh release create "v${RC_VERSION}" \
  --draft \
  --verify-tag \
  --title "Headless Blender Character Builder ${RC_VERSION}" \
  --notes-file docs/release-notes/v0.1.0-rc.1.md
(
  set -eu
  for asset in "$RELEASE_DIR"/*; do
    test -f "$asset" || continue
    gh release upload "v${RC_VERSION}" "$asset"
  done
)

RELEASE_REVIEW_DIR=$(mktemp -d)
gh release download "v${RC_VERSION}" --dir "$RELEASE_REVIEW_DIR"
sample_archive="headless-blender-character-builder-${RC_VERSION}-sample.tar.gz"
(
  cd "$RELEASE_REVIEW_DIR"
  expected_sample=$(awk -v name="$sample_archive" \
    '$2 == name {print $1}' SHA256SUMS)
  test "${#expected_sample}" -eq 64
  case "$expected_sample" in *[!0-9a-f]*) exit 1 ;; esac
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s  %s\n' "$expected_sample" "$sample_archive" | sha256sum --check
  else
    printf '%s  %s\n' "$expected_sample" "$sample_archive" | shasum -a 256 --check
  fi
)
tar -xzf \
  "$RELEASE_REVIEW_DIR/$sample_archive" \
  -C "$RELEASE_REVIEW_DIR"
(
  cd "$RELEASE_REVIEW_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)

)
```

The top-level upload covers the checksum-bound 81 MiB Blender source archive as
well as the project archive, SBOMs, notices, inventory, deterministic sample
archive, and metadata. The local `sample/` evidence directory is represented by
that archive so GitHub asset naming does not flatten its paths. Review a fresh
download of the draft against `SHA256SUMS`; do not make the GHCR packages public
until the Release containing those source assets is public.

Remote publication is a fail-fast but non-atomic operator transaction. If the
block stops after its first `docker push`, keep every GHCR package private and
keep any Release as a draft. Do not blindly rerun from the top: inspect the
three private image tags, `git ls-remote --tags origin`, and
`gh release view "v${RC_VERSION}" --json isDraft,tagName`; compare every
observed identity with the locally verified candidate, then resume only the
failed and later steps. If an identity disagrees, stop and obtain explicit
maintainer approval before deleting or replacing a remote tag, draft, or
package version. Nothing in this procedure automatically rolls back remote
state or makes a package public.

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
- [ ] Actual final-image copyleft/source review is complete, every required
      source/delivery asset is checksum-bound, and `public_oci_ready` is true.
- [ ] GHCR digests and SBOM checksums match the draft release.
- [ ] Release assets contain no secrets, signed URLs, private references, or
      personal absolute paths.
- [ ] Any live VPS, DNS, ACME, firewall, provider IAM, and off-host backup test
      was separately authorized and recorded.
