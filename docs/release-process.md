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

Release checkouts must use normal tracked-file index flags: sparse paths,
`skip-worktree`, and `assume-unchanged` can hide working-tree bytes from an
ordinary status check. Diagnose without changing files using
`git ls-files -v`; every tracked entry must have the normal uppercase `H`
prefix. For an accidentally flagged, explicitly reviewed path, normalize only
that path with
`git update-index --no-skip-worktree --no-assume-unchanged -- path/to/file`,
then re-review `git status`, the index, and the working-tree diff. Use a
separate full checkout if sparse-checkout is intentional. Do not use a broad
reset to make a release tree appear clean.

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
- single-platform image-manifest digest after registry publication;
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

Use a dedicated, single-operator release checkout and Docker host. The
procedure does not defend its temporary paths, Docker tags, or Git references
against a concurrent local process that already has the same account or Docker
authority; any such concurrency invalidates the run.

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

### Private push and draft transaction

This phase ends with private images, a signed tag, a draft Release, and a
locally reverified asset download. It cannot make a package or Release public.

```sh
(
set -eu

export RC_VERSION=0.1.0-rc.1
export GH_OWNER=joseph-robert-f
export RELEASE_RUN_ID=replace-with-reviewed-run-id
export RELEASE_DIR="$PWD/build/release-check/$RELEASE_RUN_ID/release"
export PYTHON=${PYTHON:-python3}
export HBCB_PUBLISH_DOCKER=${DOCKER:-docker}
export HBCB_CANONICAL_REPOSITORY=joseph-robert-f/headless-blender-character-builder
REMOTE_MANIFEST_DIR=
REMOTE_TAG_PROBE_DIR=
RELEASE_REVIEW_DIR=
HBCB_PUBLISH_DOCKER_CONFIG=
SIGNING_PROBE_TAG=
SIGNING_PROBE_TAG_OBJECT=
SIGNING_PROBE_NONCE=
SIGNING_PROBE_COMMIT=
SIGNING_PROBE_INTENT=0
HBCB_PUBLISH_TMP_ROOT=${TMPDIR:-/tmp}
HBCB_PUBLISH_TMP_ROOT=${HBCB_PUBLISH_TMP_ROOT%/}
case "$HBCB_PUBLISH_TMP_ROOT" in /*) ;; *) exit 1 ;; esac
test -n "$HBCB_PUBLISH_TMP_ROOT"
test -d "$HBCB_PUBLISH_TMP_ROOT"
test ! -L "$HBCB_PUBLISH_TMP_ROOT"
cleanup_publication_scratch() {
  status=$?
  trap '' 1 2 15
  if test "$SIGNING_PROBE_INTENT" = 1
  then
    current_tag_object=$(git rev-parse -q --verify \
      "refs/tags/$SIGNING_PROBE_TAG^{tag}" 2>/dev/null || true)
    if test -z "$current_tag_object"
    then
      :
    elif test -n "$SIGNING_PROBE_NONCE" && \
       test "$(git rev-parse -q --verify "refs/tags/$SIGNING_PROBE_TAG^{}")" = \
         "$SIGNING_PROBE_COMMIT" && \
       test "$(git for-each-ref --format='%(contents:subject)' \
         "refs/tags/$SIGNING_PROBE_TAG")" = \
         "HBCB signing preflight owner=$SIGNING_PROBE_NONCE" && \
       { test -z "$SIGNING_PROBE_TAG_OBJECT" || \
         test "$current_tag_object" = "$SIGNING_PROBE_TAG_OBJECT"; }
    then
      git tag -d -- "$SIGNING_PROBE_TAG" >/dev/null 2>&1 || \
        test "$status" -ne 0 || status=1
    else
      test "$status" -ne 0 || status=1
    fi
  fi
  for directory in \
    "${REMOTE_MANIFEST_DIR:-}" \
    "${REMOTE_TAG_PROBE_DIR:-}" \
    "${RELEASE_REVIEW_DIR:-}" \
    "${HBCB_PUBLISH_DOCKER_CONFIG:-}"
  do
    test -n "$directory" || continue
    case "$directory" in
      "$HBCB_PUBLISH_TMP_ROOT"/hbcb-remote-manifests.*|\
      "$HBCB_PUBLISH_TMP_ROOT"/hbcb-remote-tag-probe.*|\
      "$HBCB_PUBLISH_TMP_ROOT"/hbcb-release-review.*|\
      "$HBCB_PUBLISH_TMP_ROOT"/hbcb-docker-config.*) ;;
      *) exit 1 ;;
    esac
    test ! -L "$directory" || exit 1
    rm -rf -- "$directory" || test "$status" -ne 0 || status=1
  done
  unset DOCKER_CONFIG
  exit "$status"
}
trap cleanup_publication_scratch 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 143' 15

command -v gh >/dev/null
command -v "$HBCB_PUBLISH_DOCKER" >/dev/null
command -v "$PYTHON" >/dev/null
"$HBCB_PUBLISH_DOCKER" buildx version >/dev/null
gh auth status --hostname github.com
test "$(gh api user --jq .login)" = "$GH_OWNER"
test -n "$(git config --get user.signingkey)"
test -n "${CR_PAT:-}"
test "$(git rev-parse --show-toplevel)" = "$PWD"
test "$(git status --porcelain)" = ""
test -d "$RELEASE_DIR"
test ! -L "$RELEASE_DIR"
test "$(git ls-files -v | sed -n '/^[^H] /p')" = ""
test "$GH_OWNER" = joseph-robert-f
case "$(git remote get-url origin)" in
  "https://github.com/${HBCB_CANONICAL_REPOSITORY}"|\
  "https://github.com/${HBCB_CANONICAL_REPOSITORY}.git"|\
  "git@github.com:${HBCB_CANONICAL_REPOSITORY}"|\
  "git@github.com:${HBCB_CANONICAL_REPOSITORY}.git") ;;
  *) exit 1 ;;
esac
case "$(git remote get-url --push origin)" in
  "https://github.com/${HBCB_CANONICAL_REPOSITORY}"|\
  "https://github.com/${HBCB_CANONICAL_REPOSITORY}.git"|\
  "git@github.com:${HBCB_CANONICAL_REPOSITORY}"|\
  "git@github.com:${HBCB_CANONICAL_REPOSITORY}.git") ;;
  *) exit 1 ;;
esac

# Fail before any remote mutation if the configured signing key cannot create
# and verify an exact local annotated tag. Its exact tag object is recorded and
# cleanup removes it only while that immutable object remains at the name.
SIGNING_PROBE_NONCE=$("$PYTHON" -c 'import secrets;print(secrets.token_hex(12))')
SIGNING_PROBE_TAG="hbcb-signing-probe-$SIGNING_PROBE_NONCE"
SIGNING_PROBE_COMMIT=$(git rev-parse HEAD)
SIGNING_PROBE_INTENT=1
git tag -s "$SIGNING_PROBE_TAG" \
  -m "HBCB signing preflight owner=$SIGNING_PROBE_NONCE" \
  "$SIGNING_PROBE_COMMIT"
SIGNING_PROBE_TAG_OBJECT=$(git rev-parse "refs/tags/$SIGNING_PROBE_TAG^{tag}")
git tag -v "$SIGNING_PROBE_TAG"
test "$(git rev-parse "refs/tags/$SIGNING_PROBE_TAG^{tag}")" = \
  "$SIGNING_PROBE_TAG_OBJECT"
git tag -d "$SIGNING_PROBE_TAG"
SIGNING_PROBE_INTENT=0
SIGNING_PROBE_TAG=
SIGNING_PROBE_TAG_OBJECT=
SIGNING_PROBE_NONCE=
SIGNING_PROBE_COMMIT=

(
  cd "$RELEASE_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)

# Re-read checksum-bound evidence, current HEAD, and all three live local image
# IDs and OCI labels before authenticating. This also enforces
# public_oci_ready=true, so it intentionally fails today.
publication_preflight() {
  "$PYTHON" scripts/release-publication-preflight \
    --repo "$PWD" \
    --release-dir "$RELEASE_DIR" \
    --version "$RC_VERSION" \
    --docker "$HBCB_PUBLISH_DOCKER" \
    "$@"
}
publication_preflight
BUILDER_IMAGE_ID=$(publication_preflight --print-image-id builder)
API_IMAGE_ID=$(publication_preflight --print-image-id api)
WORKER_IMAGE_ID=$(publication_preflight --print-image-id worker)

# Authenticate to GHCR before the first remote mutation. A missing or
# under-scoped token must not leave a pushed tag or partial draft Release.
HBCB_PUBLISH_DOCKER_CONFIG=$(mktemp -d "$HBCB_PUBLISH_TMP_ROOT/hbcb-docker-config.XXXXXX")
chmod 0700 "$HBCB_PUBLISH_DOCKER_CONFIG"
export DOCKER_CONFIG=$HBCB_PUBLISH_DOCKER_CONFIG
printf '%s' "$CR_PAT" | "$HBCB_PUBLISH_DOCKER" login ghcr.io -u "$GH_OWNER" --password-stdin
unset CR_PAT

# A destination tag is either absent or already bound to this exact candidate.
# `image ls` exits nonzero on a daemon/query error and returns an empty string
# only for a genuine no-match, so local no-clobber does not confuse failure
# with absence.
for binding in \
  "$BUILDER_IMAGE_ID|ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}" \
  "$API_IMAGE_ID|ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}" \
  "$WORKER_IMAGE_ID|ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"
do
  expected_id=${binding%%|*}
  destination=${binding#*|}
  existing_ids=$("$HBCB_PUBLISH_DOCKER" image ls \
    --no-trunc --quiet "$destination")
  test -z "$existing_ids" || test "$existing_ids" = "$expected_id"
done

# A release version is immutable. Use the authenticated Packages API so a
# network, authorization, or server error fails closed instead of being
# mistaken for an absent tag. An existing package must be private; a package
# absent before its first push is permitted because GHCR creates personal
# container packages private by default, and is rechecked immediately after
# that push. Any existing version tag requires the recovery path.
REMOTE_TAG_PROBE_DIR=$(mktemp -d "$HBCB_PUBLISH_TMP_ROOT/hbcb-remote-tag-probe.XXXXXX")
chmod 0700 "$REMOTE_TAG_PROBE_DIR"
assert_remote_release_slot() {
  package=$1
  gh api --paginate --slurp \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    '/user/packages?package_type=container&per_page=100' \
    > "$REMOTE_TAG_PROBE_DIR/packages.json"
  visibility=$("$PYTHON" -c '
import json, sys
pages = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
    raise SystemExit(2)
matches = [item for page in pages for item in page
           if isinstance(item, dict) and item.get("name") == sys.argv[2]
           and item.get("package_type") == "container"]
if len(matches) > 1:
    raise SystemExit(2)
print("absent" if not matches else matches[0].get("visibility", "invalid"))
' "$REMOTE_TAG_PROBE_DIR/packages.json" "$package")
  case "$visibility" in
    absent) return 0 ;;
    private) ;;
    *) echo "existing GHCR package is not proven private" >&2; exit 1 ;;
  esac
  gh api --paginate --slurp \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "/user/packages/container/${package}/versions?per_page=100" \
    > "$REMOTE_TAG_PROBE_DIR/${package}-versions.json"
  "$PYTHON" -c '
import json, sys
pages = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
    raise SystemExit(2)
for item in (entry for page in pages for entry in page):
    tags = item.get("metadata", {}).get("container", {}).get("tags", []) \
        if isinstance(item, dict) else []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise SystemExit(2)
    if sys.argv[2] in tags:
        raise SystemExit("remote release tag already exists; use recovery")
' "$REMOTE_TAG_PROBE_DIR/${package}-versions.json" "$RC_VERSION"
}
assert_package_private() {
  package=$1
  gh api \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "/user/packages/container/${package}" \
    > "$REMOTE_TAG_PROBE_DIR/${package}-package.json"
  "$PYTHON" -c '
import json, sys
item = json.load(open(sys.argv[1], encoding="utf-8"))
if (not isinstance(item, dict) or item.get("name") != sys.argv[2]
        or item.get("package_type") != "container"
        or item.get("visibility") != "private"):
    raise SystemExit("pushed GHCR package is not proven private")
' "$REMOTE_TAG_PROBE_DIR/${package}-package.json" "$package"
}
for package in \
  headless-blender-character-builder \
  headless-blender-character-builder-api \
  headless-blender-character-builder-worker
do
  assert_remote_release_slot "$package"
done

"$HBCB_PUBLISH_DOCKER" tag "$BUILDER_IMAGE_ID" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"
"$HBCB_PUBLISH_DOCKER" tag "$API_IMAGE_ID" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}"
"$HBCB_PUBLISH_DOCKER" tag "$WORKER_IMAGE_ID" \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"

# Recheck the checksum-bound evidence, clean Git identity, source tags, all OCI
# labels, and the three exact outgoing GHCR tags immediately before the first
# remote push.
publication_preflight --registry-owner "$GH_OWNER"

# Push private packages first. Do not change package visibility yet. This keeps
# a registry failure from leaving a Git tag or draft Release behind.
publication_preflight --registry-owner "$GH_OWNER"
assert_remote_release_slot headless-blender-character-builder
"$HBCB_PUBLISH_DOCKER" push "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}"
assert_package_private headless-blender-character-builder
publication_preflight --registry-owner "$GH_OWNER"
assert_remote_release_slot headless-blender-character-builder-api
"$HBCB_PUBLISH_DOCKER" push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}"
assert_package_private headless-blender-character-builder-api
publication_preflight --registry-owner "$GH_OWNER"
assert_remote_release_slot headless-blender-character-builder-worker
"$HBCB_PUBLISH_DOCKER" push "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}"
assert_package_private headless-blender-character-builder-worker

# Capture the three exact raw private manifests. The finalizer rejects an
# index, wrong config/image ID, redirect-style layer, missing role, oversized
# input, existing output, or any manifest that does not match this candidate.
REMOTE_MANIFEST_DIR=$(mktemp -d "$HBCB_PUBLISH_TMP_ROOT/hbcb-remote-manifests.XXXXXX")
chmod 0700 "$REMOTE_MANIFEST_DIR"
"$HBCB_PUBLISH_DOCKER" buildx imagetools inspect --raw \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder:${RC_VERSION}" \
  > "$REMOTE_MANIFEST_DIR/builder.json"
"$HBCB_PUBLISH_DOCKER" buildx imagetools inspect --raw \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-api:${RC_VERSION}" \
  > "$REMOTE_MANIFEST_DIR/api.json"
"$HBCB_PUBLISH_DOCKER" buildx imagetools inspect --raw \
  "ghcr.io/${GH_OWNER}/headless-blender-character-builder-worker:${RC_VERSION}" \
  > "$REMOTE_MANIFEST_DIR/worker.json"

# Never rewrite the pre-push bundle. Create a new no-clobber bundle whose
# registry-qualified tags and raw manifest digests are covered by both
# release-metadata.json and SHA256SUMS, then verify it again before GitHub state
# is changed.
PUBLISHED_RELEASE_DIR="${RELEASE_DIR}.published"
publication_preflight \
  --finalize-output-dir "$PUBLISHED_RELEASE_DIR" \
  --remote-manifest "builder=$REMOTE_MANIFEST_DIR/builder.json" \
  --remote-manifest "api=$REMOTE_MANIFEST_DIR/api.json" \
  --remote-manifest "worker=$REMOTE_MANIFEST_DIR/worker.json" \
  --registry-owner "$GH_OWNER"
RELEASE_DIR=$PUBLISHED_RELEASE_DIR
publication_preflight --require-published-digests --registry-owner "$GH_OWNER"
rm -f -- \
  "$REMOTE_MANIFEST_DIR/builder.json" \
  "$REMOTE_MANIFEST_DIR/api.json" \
  "$REMOTE_MANIFEST_DIR/worker.json"
rmdir "$REMOTE_MANIFEST_DIR"
REMOTE_MANIFEST_DIR=

git tag -s "v${RC_VERSION}" -m "Headless Blender Character Builder ${RC_VERSION}"
git tag -v "v${RC_VERSION}"
git push origin "v${RC_VERSION}"
gh release create "v${RC_VERSION}" \
  --repo "$HBCB_CANONICAL_REPOSITORY" \
  --draft \
  --verify-tag \
  --title "Headless Blender Character Builder ${RC_VERSION}" \
  --notes-file docs/release-notes/v0.1.0-rc.1.md
(
  set -eu
  for asset in "$RELEASE_DIR"/*; do
    test -f "$asset" || continue
    gh release upload "v${RC_VERSION}" "$asset" \
      --repo "$HBCB_CANONICAL_REPOSITORY"
  done
)

RELEASE_REVIEW_DIR=$(mktemp -d "$HBCB_PUBLISH_TMP_ROOT/hbcb-release-review.XXXXXX")
chmod 0700 "$RELEASE_REVIEW_DIR"
gh release download "v${RC_VERSION}" \
  --repo "$HBCB_CANONICAL_REPOSITORY" \
  --dir "$RELEASE_REVIEW_DIR"
"$PYTHON" -c '
import os, stat, sys
local_names = sorted(
    entry.name for entry in os.scandir(sys.argv[1])
    if stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode)
)
downloaded = list(os.scandir(sys.argv[2]))
if any(not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode)
       for entry in downloaded):
    raise SystemExit("downloaded draft contains a non-regular top-level asset")
if local_names != sorted(entry.name for entry in downloaded):
    raise SystemExit("downloaded draft asset set differs from the local bundle")
' "$RELEASE_DIR" "$RELEASE_REVIEW_DIR"
cmp -- "$RELEASE_DIR/SHA256SUMS" "$RELEASE_REVIEW_DIR/SHA256SUMS"
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
"$PYTHON" -c '
import os, pathlib, re, stat, sys
root = pathlib.Path(sys.argv[1])
lines = (root / "SHA256SUMS").read_text(encoding="ascii").splitlines()
expected_files = {"SHA256SUMS"}
for line in lines:
    if not re.fullmatch(r"[0-9a-f]{64}  [A-Za-z0-9._/-]+", line):
        raise SystemExit("invalid checksum inventory")
    name = line[66:]
    if name.startswith("/") or ".." in pathlib.PurePosixPath(name).parts:
        raise SystemExit("unsafe checksum path")
    expected_files.add(name)
actual_files = set()
actual_dirs = set()
for base, dirs, files in os.walk(root, followlinks=False):
    for name in dirs:
        path = pathlib.Path(base, name)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise SystemExit("downloaded review tree contains an unsafe directory")
        actual_dirs.add(path.relative_to(root).as_posix())
    for name in files:
        path = pathlib.Path(base, name)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise SystemExit("downloaded review tree contains a non-regular file")
        actual_files.add(path.relative_to(root).as_posix())
expected_dirs = {
    parent.as_posix()
    for name in expected_files
    for parent in pathlib.PurePosixPath(name).parents
    if parent.as_posix() != "."
}
if actual_files != expected_files or actual_dirs != expected_dirs:
    raise SystemExit("downloaded review tree contains missing or extra paths")
' "$RELEASE_REVIEW_DIR"
(
  cd "$RELEASE_REVIEW_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)

rm -rf -- "$RELEASE_REVIEW_DIR"
RELEASE_REVIEW_DIR=

rm -rf -- "$REMOTE_TAG_PROBE_DIR"
REMOTE_TAG_PROBE_DIR=
rm -rf -- "$HBCB_PUBLISH_DOCKER_CONFIG"
HBCB_PUBLISH_DOCKER_CONFIG=
unset DOCKER_CONFIG
trap - 0 1 2 15

)
```

The top-level upload covers the checksum-bound 81 MiB Blender source archive as
well as the project archive, SBOMs, notices, inventory, deterministic sample
archive, and metadata. The local `sample/` evidence directory is represented by
that archive so GitHub asset naming does not flatten its paths. Review a fresh
download of the draft against the *local* `SHA256SUMS`; do not make the GHCR
packages public until the Release containing those source assets is public.

### Mandatory clean-environment digest verification

The transaction deliberately stops with a draft Release and three private
packages. Its local daemon is not a clean-room verifier. Before making the
draft public, provision a fresh disposable VM with an empty Docker daemon and
no HBCB images, transfer the complete already verified review directory
(including the extracted `sample/` tree) through the reviewed handoff, and
send the local SHA-256 of its `SHA256SUMS` file through a separate authenticated
channel. Authenticate with a new short-lived read-only package token. On that
VM, run the following. Destroy the VM afterward; do not reuse the publishing
host's daemon or Docker configuration.

```sh
(
set -eu
export GH_OWNER=joseph-robert-f
export RC_VERSION=0.1.0-rc.1
export REVIEW_RELEASE_DIR=/absolute/path/to/verified-draft-download
export EXPECTED_SHA256SUMS_SHA256=replace-with-out-of-band-64-hex-digest
export PYTHON=${PYTHON:-python3}
export HBCB_VERIFY_DOCKER=${DOCKER:-docker}
verify_tmp_root=${TMPDIR:-/tmp}
verify_tmp_root=${verify_tmp_root%/}
case "$verify_tmp_root" in /*) ;; *) exit 1 ;; esac
test -n "$verify_tmp_root"
test -d "$verify_tmp_root"
test ! -L "$verify_tmp_root"
verify_docker_config=
cleanup_clean_verifier() {
  status=$?
  trap '' 1 2 15
  if test -n "$verify_docker_config"
  then
    case "$verify_docker_config" in
      "$verify_tmp_root"/hbcb-clean-docker.*) ;;
      *) exit 1 ;;
    esac
    test ! -L "$verify_docker_config" || exit 1
    rm -rf -- "$verify_docker_config" || test "$status" -ne 0 || status=1
  fi
  unset DOCKER_CONFIG
  exit "$status"
}
trap cleanup_clean_verifier 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 143' 15

command -v "$PYTHON" >/dev/null
command -v "$HBCB_VERIFY_DOCKER" >/dev/null
test -n "${CR_PAT:-}"
test -f "$REVIEW_RELEASE_DIR/image-metadata.json"
test ! -L "$REVIEW_RELEASE_DIR/image-metadata.json"
actual_checksum_inventory_sha256=$("$PYTHON" -c '
import hashlib,re,sys
expected=sys.argv[2]
if not re.fullmatch(r"[0-9a-f]{64}",expected):
    raise SystemExit("out-of-band checksum digest is invalid")
data=open(sys.argv[1],"rb").read()
print(hashlib.sha256(data).hexdigest())
' "$REVIEW_RELEASE_DIR/SHA256SUMS" "$EXPECTED_SHA256SUMS_SHA256")
test "$actual_checksum_inventory_sha256" = "$EXPECTED_SHA256SUMS_SHA256"
(
  cd "$REVIEW_RELEASE_DIR"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum --check SHA256SUMS
  else
    shasum -a 256 --check SHA256SUMS
  fi
)
verify_docker_config=$(mktemp -d "$verify_tmp_root/hbcb-clean-docker.XXXXXX")
chmod 0700 "$verify_docker_config"
export DOCKER_CONFIG=$verify_docker_config
printf '%s' "$CR_PAT" | "$HBCB_VERIFY_DOCKER" login ghcr.io \
  -u "$GH_OWNER" --password-stdin
unset CR_PAT

# This check must run against a genuinely empty daemon. A Docker command
# failure is fatal; it is never interpreted as an empty image inventory.
existing_image_ids=$("$HBCB_VERIFY_DOCKER" image ls --no-trunc --quiet)
test -z "$existing_image_ids"

for role in builder api worker
do
  case "$role" in
    builder) package=headless-blender-character-builder ;;
    api) package=headless-blender-character-builder-api ;;
    worker) package=headless-blender-character-builder-worker ;;
  esac
  record=$("$PYTHON" -c '
import json, re, sys
with open(sys.argv[1], "r", encoding="utf-8") as stream:
    root = json.load(stream)
record = root["images"][sys.argv[2]]
tag = f"ghcr.io/{sys.argv[3]}/{sys.argv[4]}:{sys.argv[5]}"
digest = record.get("published_digest")
image_id = record.get("image_id")
if record.get("expected_public_tag") != tag:
    raise SystemExit("registry tag differs from finalized metadata")
if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
    raise SystemExit("published digest is invalid")
if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
    raise SystemExit("image configuration ID is invalid")
print(digest + " " + image_id)
' "$REVIEW_RELEASE_DIR/image-metadata.json" "$role" \
    "$GH_OWNER" "$package" "$RC_VERSION")
  digest=${record%% *}
  expected_image_id=${record#* }
  reference="ghcr.io/${GH_OWNER}/${package}@${digest}"
  "$HBCB_VERIFY_DOCKER" pull "$reference"
  actual_image_id=$("$HBCB_VERIFY_DOCKER" image inspect \
    --format '{{.Id}}' "$reference")
  test "$actual_image_id" = "$expected_image_id"
done
echo 'HBCB_CLEAN_REGISTRY_VERIFY: PASS roles=3 platform=linux/amd64'
)
```

### Final visibility commit

This is the irreversible phase. It is permitted only after the source Release,
clean-room image check, and three private identities all agree.

Retain the clean-room transcript with the release review. Re-download and
recheck the draft assets after that PASS. Keep an exact empty scratch directory
for the following read-only check; for each role, `package` is the matching
name used above and `role` is `builder`, `api`, or `worker`:

```sh
set -eu
export GH_OWNER=joseph-robert-f
export RC_VERSION=0.1.0-rc.1
export RELEASE_DIR=/absolute/path/to/finalized-published-bundle
export PYTHON=${PYTHON:-python3}
export HBCB_PUBLISH_DOCKER=${DOCKER:-docker}
visibility_tmp_root=${TMPDIR:-/tmp}
visibility_tmp_root=${visibility_tmp_root%/}
case "$visibility_tmp_root" in /*) ;; *) exit 1 ;; esac
test -n "$visibility_tmp_root"
test -d "$visibility_tmp_root"
test ! -L "$visibility_tmp_root"
VISIBILITY_REVIEW_DIR=$(mktemp -d \
  "$visibility_tmp_root/hbcb-visibility-review.XXXXXX")
chmod 0700 "$VISIBILITY_REVIEW_DIR"
cleanup_visibility_review() {
  status=$?
  trap '' 1 2 15
  case "$VISIBILITY_REVIEW_DIR" in
    "$visibility_tmp_root"/hbcb-visibility-review.*) ;;
    *) exit 1 ;;
  esac
  test ! -L "$VISIBILITY_REVIEW_DIR" || exit 1
  rm -rf -- "$VISIBILITY_REVIEW_DIR" || test "$status" -ne 0 || status=1
  unset DOCKER_CONFIG
  exit "$status"
}
trap cleanup_visibility_review 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 143' 15
command -v gh >/dev/null
command -v "$PYTHON" >/dev/null
command -v "$HBCB_PUBLISH_DOCKER" >/dev/null
"$HBCB_PUBLISH_DOCKER" buildx version >/dev/null
gh auth status --hostname github.com
test "$(gh api user --jq .login)" = "$GH_OWNER"
test -n "${CR_PAT:-}"
export DOCKER_CONFIG=$VISIBILITY_REVIEW_DIR/docker-config
mkdir "$DOCKER_CONFIG"
chmod 0700 "$DOCKER_CONFIG"
printf '%s' "$CR_PAT" | "$HBCB_PUBLISH_DOCKER" login ghcr.io \
  -u "$GH_OWNER" --password-stdin
unset CR_PAT

verify_remote_manifest_digest() {
  role=$1
  package=$2
  raw_manifest="$VISIBILITY_REVIEW_DIR/${role}-manifest.json"
  "$HBCB_PUBLISH_DOCKER" buildx imagetools inspect --raw \
    "ghcr.io/${GH_OWNER}/${package}:${RC_VERSION}" > "$raw_manifest"
  expected_digest=$("$PYTHON" -c '
import json,re,sys
record=json.load(open(sys.argv[1],encoding="utf-8"))["images"][sys.argv[2]]
expected_tag=f"ghcr.io/{sys.argv[3]}/{sys.argv[4]}:{sys.argv[5]}"
value=record.get("published_digest")
if record.get("expected_public_tag") != expected_tag:
    raise SystemExit("published tag is invalid")
if not isinstance(value,str) or not re.fullmatch(r"sha256:[0-9a-f]{64}",value):
    raise SystemExit("published digest is invalid")
print(value)
' "$RELEASE_DIR/image-metadata.json" "$role" \
    "$GH_OWNER" "$package" "$RC_VERSION")
  actual_digest=$("$PYTHON" -c \
    'import hashlib,sys; print("sha256:"+hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' \
    "$raw_manifest")
  test "$actual_digest" = "$expected_digest"
}
verify_private_remote_role() {
  role=$1
  package=$2
  package_record="$VISIBILITY_REVIEW_DIR/${package}-package.json"
  gh api \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "/user/packages/container/${package}" > "$package_record"
  "$PYTHON" -c '
import json,sys
item=json.load(open(sys.argv[1],encoding="utf-8"))
if (not isinstance(item,dict) or item.get("name")!=sys.argv[2]
        or item.get("package_type")!="container"
        or item.get("visibility")!="private"):
    raise SystemExit("package is not proven private")
' "$package_record" "$package"
  verify_remote_manifest_digest "$role" "$package"
}
verify_release_assets() {
  expected_draft=$1
  release_state="$VISIBILITY_REVIEW_DIR/release-state.json"
  download_dir="$VISIBILITY_REVIEW_DIR/release-download"
  test ! -e "$download_dir"
  gh release view "v${RC_VERSION}" \
    --repo joseph-robert-f/headless-blender-character-builder \
    --json assets,isDraft,tagName,url > "$release_state"
  "$PYTHON" -c '
import json,sys
item=json.load(open(sys.argv[1],encoding="utf-8"))
expected=sys.argv[2]=="true"
if (not isinstance(item,dict) or item.get("tagName")!=f"v{sys.argv[3]}"
        or item.get("isDraft") is not expected or not isinstance(item.get("assets"),list)):
    raise SystemExit("Release state differs from the reviewed phase")
' "$release_state" "$expected_draft" "$RC_VERSION"
  mkdir "$download_dir"
  chmod 0700 "$download_dir"
  gh release download "v${RC_VERSION}" \
    --repo joseph-robert-f/headless-blender-character-builder \
    --dir "$download_dir"
  "$PYTHON" -c '
import os,stat,sys
local_entries=list(os.scandir(sys.argv[1]))
if any(not (stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode)
            or stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode))
       for entry in local_entries):
    raise SystemExit("finalized local evidence contains an unsafe entry")
local_names=sorted(
    entry.name for entry in local_entries
    if stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode)
)
downloaded=list(os.scandir(sys.argv[2]))
if any(not stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode)
       for entry in downloaded):
    raise SystemExit("Release asset set contains a non-regular entry")
if local_names!=sorted(entry.name for entry in downloaded):
    raise SystemExit("Release asset set differs from finalized local evidence")
' "$RELEASE_DIR" "$download_dir"
  for local_asset in "$RELEASE_DIR"/*
  do
    test -d "$local_asset" && continue
    test -f "$local_asset"
    test ! -L "$local_asset"
    cmp -- "$local_asset" "$download_dir/$(basename "$local_asset")"
  done
  rm -rf -- "$download_dir"
}
verify_public_remote_role() {
  role=$1
  package=$2
  public_record="$VISIBILITY_REVIEW_DIR/${package}-public.json"
  gh api \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "/users/${GH_OWNER}/packages/container/${package}" > "$public_record"
  "$PYTHON" -c '
import json,sys
item=json.load(open(sys.argv[1],encoding="utf-8"))
if (not isinstance(item,dict) or item.get("name")!=sys.argv[2]
        or item.get("package_type")!="container"
        or item.get("visibility")!="public"):
    raise SystemExit("package public-visibility confirmation failed")
' "$public_record" "$package"
  verify_remote_manifest_digest "$role" "$package"
}
verify_private_remote_role builder headless-blender-character-builder
verify_private_remote_role api headless-blender-character-builder-api
verify_private_remote_role worker headless-blender-character-builder-worker
verify_release_assets true
echo 'HBCB_PRIVATE_VISIBILITY_REVIEW: PASS roles=3'
```

Run that block in a dedicated review shell and keep the shell open. It creates
and owns a mode-`0700` scratch directory and authenticates with an isolated
Docker configuration. After the first three-role PASS, publish the
source-bearing draft with
`gh release edit "v${RC_VERSION}" --draft=false --repo joseph-robert-f/headless-blender-character-builder`,
then follow this exact sequence in that same shell. Each checkpoint revalidates
the Release assets, every package already made public, and the next private
package before another irreversible visibility change:

```sh
# Before changing the builder package:
verify_release_assets false
verify_private_remote_role builder headless-blender-character-builder
# In that exact package's GitHub settings, choose Change visibility → Public,
# type the package name, and confirm. Then prove both state and digest again:
verify_release_assets false
verify_public_remote_role builder headless-blender-character-builder

# Before changing the API package:
verify_release_assets false
verify_public_remote_role builder headless-blender-character-builder
verify_private_remote_role api headless-blender-character-builder-api
# Change only the API package to Public in GitHub, then run:
verify_release_assets false
verify_public_remote_role builder headless-blender-character-builder
verify_public_remote_role api headless-blender-character-builder-api

# Before changing the worker package:
verify_release_assets false
verify_public_remote_role builder headless-blender-character-builder
verify_public_remote_role api headless-blender-character-builder-api
verify_private_remote_role worker headless-blender-character-builder-worker
# Change only the worker package to Public in GitHub, then run the final proof:
verify_release_assets false
verify_public_remote_role builder headless-blender-character-builder
verify_public_remote_role api headless-blender-character-builder-api
verify_public_remote_role worker headless-blender-character-builder-worker
echo 'HBCB_PUBLIC_VISIBILITY_COMMIT: PASS roles=3 release_assets=verified'
```

If any command fails, stop. Never use a bulk visibility control. GitHub warns
that a public package cannot be made private again. Exit the dedicated review
shell afterward so its exact trap removes the temporary Docker credentials,
asset downloads, and manifest copies.

The registry digests also enable a publisher-supplied
`release.lock.env`. Populate every nonzero value in
`deploy/vps/release.lock.env.example` from this single reviewed release,
including the three project image identities and separately pinned Caddy and
migration identities. Validate it through the documented offline VPS preflight
from the exact extracted source tree before delivery. The release transaction
does not synthesize or deploy this operator artifact; automated propagation
remains a candidate extension.

### Recovery and bounded cleanup

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

Use this bounded recovery inventory before deciding whether to resume or clean
up. It is read-only. Save the three `docker push` digest lines with the release
review record and compare each raw private manifest digest with the recorded
value:

```sh
set -eu
export GH_OWNER=joseph-robert-f
export RC_VERSION=0.1.0-rc.1
HBCB_PUBLISH_DOCKER=${DOCKER:-docker}
PYTHON=${PYTHON:-python3}
HBCB_CANONICAL_REPOSITORY=joseph-robert-f/headless-blender-character-builder
recovery_tmp_root=${TMPDIR:-/tmp}
recovery_tmp_root=${recovery_tmp_root%/}
case "$recovery_tmp_root" in /*) ;; *) exit 1 ;; esac
test -n "$recovery_tmp_root"
test -d "$recovery_tmp_root"
test ! -L "$recovery_tmp_root"
recovery_inventory=$(mktemp -d "$recovery_tmp_root/hbcb-publication-recovery.XXXXXX")
chmod 0700 "$recovery_inventory"
cleanup_recovery_inventory() {
  status=$?
  trap '' 1 2 15
  case "$recovery_inventory" in
    "$recovery_tmp_root"/hbcb-publication-recovery.*) ;;
    *) exit 1 ;;
  esac
  test ! -L "$recovery_inventory" || exit 1
  rm -rf -- "$recovery_inventory" || test "$status" -ne 0 || status=1
  unset DOCKER_CONFIG
  exit "$status"
}
trap cleanup_recovery_inventory 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 143' 15
command -v "$HBCB_PUBLISH_DOCKER" >/dev/null
command -v "$PYTHON" >/dev/null
command -v gh >/dev/null
command -v curl >/dev/null
gh auth status --hostname github.com
test "$(gh api user --jq .login)" = "$GH_OWNER"
test -n "${CR_PAT:-}"
recovery_docker_config="$recovery_inventory/docker-config"
mkdir "$recovery_docker_config"
chmod 0700 "$recovery_docker_config"
export DOCKER_CONFIG=$recovery_docker_config
printf '%s' "$CR_PAT" | "$HBCB_PUBLISH_DOCKER" login ghcr.io \
  -u "$GH_OWNER" --password-stdin
unset CR_PAT
test "$(git rev-parse --show-toplevel)" = "$PWD"
case "$(git remote get-url origin)" in
  "https://github.com/${HBCB_CANONICAL_REPOSITORY}"|\
  "https://github.com/${HBCB_CANONICAL_REPOSITORY}.git"|\
  "git@github.com:${HBCB_CANONICAL_REPOSITORY}"|\
  "git@github.com:${HBCB_CANONICAL_REPOSITORY}.git") ;;
  *) exit 1 ;;
esac
inventory_complete=1
gh api --paginate --slurp \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  '/user/packages?package_type=container&per_page=100' \
  > "$recovery_inventory/packages.json"
for package in \
  headless-blender-character-builder \
  headless-blender-character-builder-api \
  headless-blender-character-builder-worker
do
  package_state=$("$PYTHON" -c '
import json, sys
pages=json.load(open(sys.argv[1],encoding="utf-8"))
if not isinstance(pages,list) or any(not isinstance(page,list) for page in pages):
    raise SystemExit(2)
matches=[item for page in pages for item in page if isinstance(item,dict)
         and item.get("name")==sys.argv[2] and item.get("package_type")=="container"]
if len(matches)>1: raise SystemExit(2)
print("absent" if not matches else matches[0].get("visibility","invalid"))
' "$recovery_inventory/packages.json" "$package")
  case "$package_state" in
    absent) echo "ghcr.io/${GH_OWNER}/${package}:${RC_VERSION} absent"; continue ;;
    private) ;;
    *) echo "package is not proven private" >&2; exit 1 ;;
  esac
  versions="$recovery_inventory/${package}-versions.json"
  gh api --paginate --slurp \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "/user/packages/container/${package}/versions?per_page=100" \
    > "$versions"
  version_count=$("$PYTHON" -c '
import json,sys
pages=json.load(open(sys.argv[1],encoding="utf-8"))
if not isinstance(pages,list) or any(not isinstance(page,list) for page in pages):
    raise SystemExit(2)
found=[]
for item in (entry for page in pages for entry in page):
    tags=item.get("metadata",{}).get("container",{}).get("tags",[]) \
        if isinstance(item,dict) else []
    if not isinstance(tags,list) or any(not isinstance(tag,str) for tag in tags):
        raise SystemExit(2)
    if sys.argv[2] in tags: found.append(item.get("id"))
print(len(found))
' "$versions" "$RC_VERSION")
  case "$version_count" in
    0) echo "ghcr.io/${GH_OWNER}/${package}:${RC_VERSION} absent"; continue ;;
    1) ;;
    *) echo "remote release tag is ambiguous" >&2; exit 1 ;;
  esac
  reference="ghcr.io/${GH_OWNER}/${package}:${RC_VERSION}"
  manifest="$recovery_inventory/${package}.json"
  if "$HBCB_PUBLISH_DOCKER" buildx imagetools inspect --raw "$reference" \
    > "$manifest"
  then
    test -s "$manifest"
    "$PYTHON" -c \
      'import hashlib,sys; data=open(sys.argv[1],"rb").read(); print(sys.argv[2], "sha256:" + hashlib.sha256(data).hexdigest())' \
      "$manifest" "$reference"
  else
    echo "$reference unavailable-or-absent; inventory is incomplete" >&2
    inventory_complete=0
  fi
done
git ls-remote --tags origin \
  "refs/tags/v${RC_VERSION}" "refs/tags/v${RC_VERSION}^{}"
release_headers="$recovery_inventory/release-headers.txt"
release_body="$recovery_inventory/release-body.json"
release_curl_config="$recovery_inventory/release-curl.conf"
gh auth token | "$PYTHON" -c '
import re,sys
token=sys.stdin.buffer.read(1025).decode("ascii").strip()
if not re.fullmatch(r"[A-Za-z0-9_.-]{1,512}",token):
    raise SystemExit("GitHub token has an unsafe representation")
sys.stdout.write(f"header = \"Authorization: Bearer {token}\"\n")
' > "$release_curl_config"
chmod 0600 "$release_curl_config"
set +e
curl --fail-with-body --silent --show-error --location \
  --max-redirs 0 \
  --connect-timeout 15 --max-time 30 \
  --config "$release_curl_config" \
  -H 'Accept: application/vnd.github+json' \
  -H 'X-GitHub-Api-Version: 2022-11-28' \
  --dump-header "$release_headers" \
  --output "$release_body" \
  "https://api.github.com/repos/${HBCB_CANONICAL_REPOSITORY}/releases/tags/v${RC_VERSION}"
release_api_status=$?
rm -f -- "$release_curl_config"
set -e
release_http_count=$(awk '/^HTTP\// {count++} END {print count+0}' "$release_headers")
release_http_status=$(awk '/^HTTP\// {status=$2} END {print status}' "$release_headers")
test "$release_http_count" = 1
case "$release_http_status:$release_api_status" in
  200:0)
    gh release view "v${RC_VERSION}" \
      --repo "$HBCB_CANONICAL_REPOSITORY" \
      --json assets,isDraft,tagName,url
    ;;
  404:22) echo "draft Release absent" ;;
  *) echo "draft Release inventory failed" >&2; inventory_complete=0 ;;
esac
test "$inventory_complete" = 1
```

If finalization completed but the shell stopped before Git tagging, resume from
the completed no-clobber bundle instead of running the finalizer again:

```sh
ORIGINAL_RELEASE_DIR="$PWD/build/release-check/$RELEASE_RUN_ID/release"
PUBLISHED_RELEASE_DIR="${ORIGINAL_RELEASE_DIR}.published"
test -d "$PUBLISHED_RELEASE_DIR"
test ! -L "$PUBLISHED_RELEASE_DIR"
"${PYTHON:-python3}" scripts/release-publication-preflight \
  --repo "$PWD" \
  --release-dir "$PUBLISHED_RELEASE_DIR" \
  --version "$RC_VERSION" \
  --docker "${DOCKER:-docker}" \
  --registry-owner "$GH_OWNER" \
  --require-published-digests
RELEASE_DIR=$PUBLISHED_RELEASE_DIR
# Continue at the signed Git-tag step only after the read-only inventory agrees.
```

A failed finalization deliberately quarantines its owned partial directory as
`.release.published.failed-<random>` beside the intended output instead of
deleting through a replaceable pathname. It is never a candidate or resume
source. List only that parent-scoped pattern:

```sh
published_parent=$(dirname "$PUBLISHED_RELEASE_DIR")
published_name=$(basename "$PUBLISHED_RELEASE_DIR")
find "$published_parent" -maxdepth 1 -type d \
  -name ".${published_name}.failed-*" -print
```

Inspect each exact path and confirm it is neither a symlink nor the completed
candidate. After explicit maintainer approval, remove only that reviewed
absolute quarantine path; never use a parent wildcard or global cleanup.

If a draft already exists, inventory its names and byte counts with
`gh release view "v${RC_VERSION}" --repo joseph-robert-f/headless-blender-character-builder --json assets,isDraft,tagName,url`.
Download existing assets to a new empty directory and compare them with the
local finalized set and local `SHA256SUMS`. Upload only an absent exact local
asset. Never use `--clobber`; an existing asset with a different size or hash
is an identity conflict, not a retry.

If all existing identities match, rerun the local publication preflight and
resume at the first missing step. If cleanup is explicitly approved instead,
delete only the exact draft first with
`gh release delete "v${RC_VERSION}" --yes --repo joseph-robert-f/headless-blender-character-builder`;
verify an existing remote annotated
tag peels to the reviewed commit before using
`git push origin --delete "v${RC_VERSION}"`. Delete a private GHCR package
version only through its exact version ID after confirming both its package
visibility is `private` and its sole reviewed version tag is `${RC_VERSION}`.
Never use a package-wide delete, wildcard, `latest`, or global prune during
recovery. Re-run the read-only inventory afterward and retain the transcript in
the release review.

The pre-push `image-metadata.json` deliberately contains only each expected
local release tag and `published_digest: null`. After all three private pushes,
the no-clobber finalizer creates the bundle that is actually uploaded: every
tag becomes the exact registry-qualified GHCR tag and every
`published_digest` is the SHA-256 of a raw manifest whose config digest matches
the checksum-bound local image ID. The new image metadata, updated release
metadata, and complete file set are covered by a rebuilt `SHA256SUMS`. Docker's
daemon-global `RepoTags` and `RepoDigests` arrays are never copied, so an
unrelated private alias cannot leak into uploaded evidence. Public visibility
remains blocked until these digests and the complete source-delivery review are
independently approved.

`CR_PAT` is a short-lived operator-supplied token with only the package scope
needed for the target owner; do not write it to `.env`, shell history, logs, or
release evidence. Capture the pushed `RepoDigest` values, replace the VPS lock
examples with those immutable digests, and complete the fresh-environment
verification before making the draft Release non-draft/public. GitHub's
current references are the
[Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
the [Packages REST API](https://docs.github.com/en/rest/packages/packages?apiVersion=2022-11-28),
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

- [ ] Mandatory fresh-VM image pull/config-ID verification completed and its
      transcript retained.
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
