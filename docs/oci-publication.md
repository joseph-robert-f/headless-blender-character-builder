# Conditional OCI image publication

This document gives the full image-publication procedure for builder,
API, and worker images. The procedure stays blocked. D-070 moved it from
the [release process](release-process.md) to keep that process suitable for
one maintainer. The transactions, gates, and recovery controls stay the same.
This procedure is separate from source publication.

Until all requirements that follow are satisfied, the corresponding-source record
must declare `public_oci_ready: false`. All transactions in this document
must stay blocked.

Before a push, a reviewer who acts independently of the publisher must examine the final images.
This inspection must include the project-derived PostgreSQL runtime, native
Python wheels, and operating-system packages. The reviewer must identify all
applicable copyleft and source-delivery duties. Add checksum-bound source
material and a retention plan. Change the machine-readable readiness flag
only through an examined change.

For each future public image version, publish and keep the existing assets
together with the image. This is a conservative release policy, not legal
advice. Get legal review from a person with the necessary legal qualifications.

## Image identity records

The release evidence records builder, API, and worker images. A full
future VPS release must also record the derived PostgreSQL image with the
same contract. Do this before you complete a release lock.
For each of the four project-built images, record these items:

- The repository and version tag
- The OCI config image ID from `docker image inspect`
- The platform (`linux/amd64`)
- The source commit and clean indexed-tree hash
- The builder or PostgreSQL recipe/source revision, as applicable
- The single-platform image-manifest digest after registry publication
- The SPDX SBOM checksum.

The three-image evidence cannot complete `deploy/vps/release.lock.env`.
PostgreSQL publication support is missing. After all four records
are available, use the examined values for the lock. Production Compose accepts
digest references. It does not accept a floating `latest` tag.

## Conditional publication

> **Do not do this transaction at this time.** It includes only builder, API, and worker.
> Keep `public_oci_ready` false until the derived PostgreSQL image has the
> same inventory, SBOM, signing, publication, source/notice, and digest-lock support.
> A reviewer must also examine source/delivery duties independently.
> The approved v0.1 procedure is the
> [Source-only v0.1 release](release-process.md#source-only-v01-release).

Publication is a separate operator action with explicit owner authorization.
It also makes these prerequisites necessary:

- An installed, authenticated GitHub CLI
- Authenticated GHCR access
- A tested Git tag-signing key explicitly configured as `user.signingkey`.

Local tools automate identity and corresponding-source evidence. They do not
give public-publication authorization. Use a dedicated release checkout and
Docker host with one operator.

The procedure does not isolate temporary paths, Docker tags, or Git
references from concurrent processes with the same account or Docker authority.
Such concurrent activity makes the results invalid.

Use this operator procedure:

1. Examine branch protection, required checks, CODEOWNERS, secret scanning,
   push protection, and private vulnerability reporting.
2. Do the local release check again on the specified commit.
3. Use `make dependency-scan` on that commit with a new output directory and
   strict/default mode. Exit `0` is necessary. Examine the stored reports.
   Publish no more than seven days after the scan.
4. Make sure that the local release check made all four `linux/amd64` project
   images from that commit. Do checks of their local identities.
   This step cannot pass at this time. The transaction includes only three images.
   PostgreSQL inventory, SBOM, signing, push, and release-lock support are missing.
5. Complete the actual-image copyleft/source review with a reviewer who acts independently. Supply all
   necessary source assets. Change `public_oci_ready` to true through an
   examined code change. Make sure that the retention plan includes each mapped asset.
6. Make sure that the GHCR packages stay private. After step 5, push only
   immutable version tags and record registry digests. Do not deploy by `latest`.
7. After all three private image pushes succeed, make and push the signed
   `v0.1.0-rc.1` Git tag.
8. Make a draft GitHub Release. Upload all generated top-level source,
   checksum, SBOM, notice, inventory, metadata, and sample archive assets.
9. Verify the private pushed images by digest in a clean environment.
   Compare the downloaded Release assets with `SHA256SUMS`.
10. Publish the source-bearing Release. Then, as a separate operation, change the related
    GHCR packages to public visibility. If this sequence is not guaranteed,
    keep image publication blocked.

Use a unique, ignored destination for the dependency scan from the clean
release worktree. Keep the output directory until publication review:

```sh
release_commit=$(git rev-parse HEAD)
dependency_evidence="$PWD/build/dependency-audit-release-${release_commit}"
test ! -e "$dependency_evidence"
make dependency-scan DEPENDENCY_OUTPUT="$dependency_evidence"
test "$(git rev-parse HEAD)" = "$release_commit"
```

The scheduled report-only audit cannot replace this strict scan.
The operator must apply this gate. `make release-check` and
`scripts/release-publication-preflight` do not automatically validate the
scan artifact or its age.

`make release-check` does only the local gate in step 2. It does not do the
networked dependency scan or a publication step. The operator must use the
registry and GitHub commands. Thus, a local test target cannot start
credential use or irreversible public actions.

Examine each placeholder first. Get explicit publication authorization.
Only then can the command templates that follow apply.

### Private push and draft transaction

This phase ends with private images, a signed tag, a draft Release, and
locally verified asset downloads. It cannot make a package or Release public.

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

The top-level upload includes the checksum-bound 81 MiB Blender source archive.
It also includes the project archive, SBOMs, notices, inventory, deterministic
sample archive, and metadata. The archive contains the local `sample/`
evidence tree. Thus, GitHub asset names do not flatten its paths.

Download a new copy of the draft. Compare it with the *local* `SHA256SUMS`.
Keep GHCR packages private until the Release with those source assets is public.

### Mandatory clean-environment digest verification

The transaction stops with a draft Release and three private packages.
Its local daemon is not a clean-environment verifier. Before draft publication,
prepare a new disposable VM. Its Docker daemon must be empty, without HBCB images.

Through the examined transfer procedure, send the full verified directory,
including the extracted `sample/` tree. Send the local SHA-256 of its
`SHA256SUMS` file through a separate authenticated channel.
Authenticate with a new, short-term, read-only package token.
Use these commands on the VM:

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

Delete the VM after the checks. Do not use the publication host's daemon or
Docker configuration as an alternative.

### Final visibility commit

This phase is irreversible. It is permitted only when the source Release,
clean-environment image check, and three private identities agree.

Keep the clean-environment transcript with the release inspection record.
After PASS, download and examine the draft assets again. Use an empty
temporary directory for the read-only check that follows. For each role, `package`
is the related name from the previous commands. `role` is `builder`, `api`, or `worker`:

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

Use that block in a dedicated inspection shell. Keep the shell open.
The block makes and owns a temporary directory with mode `0700`.
It authenticates with an isolated Docker configuration.

After the first three-role PASS, publish the source-bearing draft with
`gh release edit "v${RC_VERSION}" --draft=false --repo joseph-robert-f/headless-blender-character-builder`.
Then use this sequence in the same shell. Each checkpoint validates the
Release assets, each public package, and the next private package again.
Only then can the next irreversible visibility change occur:

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

If a command fails, stop. Do not use a bulk visibility control.
GitHub warns that a public package cannot become private again.
Exit the dedicated shell afterward. Its trap removes the specified temporary
Docker credentials, asset downloads, and manifest copies.

The registry digests also make a publisher-supplied `release.lock.env` possible.
Use this single examined release for each nonzero value in
`deploy/vps/release.lock.env.example`. Include the four project image
identities and independently specified Caddy and migration identities.
Before delivery, validate the lock with offline VPS preflight from the
related extracted source tree.

The release transaction does not make or deploy this operator artifact.
Automatic propagation stays future work.

### Recovery and bounded cleanup

Remote publication stops at a failure, but the transaction is not atomic.
If it stops after the first `docker push`, keep each GHCR package private.
If there is a Release, keep it as a draft. Do not do the full procedure again without
inspection of remote state.

Examine the three private image tags, `git ls-remote --tags origin`, and
`gh release view "v${RC_VERSION}" --json isDraft,tagName`.
Compare each identity with the locally verified candidate. Continue only
from the failed step and subsequent steps.

If an identity disagrees, stop. Get explicit maintainer approval before you
delete or replace a remote tag, draft, or package version.
This procedure does not automatically reverse remote state or make packages public.

Use this scope-limited, read-only recovery inventory before continuation or cleanup.
Keep the three `docker push` digest lines with the release inspection record.
Compare each raw private manifest digest with the recorded value:

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

If finalization finished before a shell failure at Git tagging, use the
completed no-clobber bundle. Do not start the finalizer again:

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

After failed finalization, the finalizer quarantines its partial directory.
The name is `.release.published.failed-<random>`, beside the intended output.
It does not delete data through a replaceable pathname. This directory is
not a candidate or a continuation source. List only this pattern in that parent:

```sh
published_parent=$(dirname "$PUBLISHED_RELEASE_DIR")
published_name=$(basename "$PUBLISHED_RELEASE_DIR")
find "$published_parent" -maxdepth 1 -type d \
  -name ".${published_name}.failed-*" -print
```

Examine each specified path. Make sure that it is not a symlink or the
completed candidate. Get explicit maintainer approval before removal.
Remove only that examined absolute quarantine path. Do not use a parent
wildcard or global cleanup.

If there is a draft, get its names and byte counts with
`gh release view "v${RC_VERSION}" --repo joseph-robert-f/headless-blender-character-builder --json assets,isDraft,tagName,url`.
Download existing assets into a new empty directory. Compare them with the
local finalized set and local `SHA256SUMS`. Upload only a specified local
asset that is missing remotely.

Do not use `--clobber`. An existing asset with a different size or hash is
an identity conflict. It is not a retry condition.

If all existing identities agree, do local publication preflight again.
Continue at the first missing step. If cleanup has explicit approval as an alternative,
first delete only the specified draft with
`gh release delete "v${RC_VERSION}" --yes --repo joseph-robert-f/headless-blender-character-builder`.

Make sure that the remote annotated tag peels to the examined commit.
Only then use `git push origin --delete "v${RC_VERSION}"`.
Before deletion of a private GHCR package version, verify its version ID,
`private` visibility, and sole examined version tag `${RC_VERSION}`.
Delete only that version ID.

Do not use package-wide deletion, a wildcard, `latest`, or global prune during
recovery. Do the read-only inventory again afterward. Keep the transcript with
the release inspection record.

Before push, `image-metadata.json` contains only expected local release tags
and `published_digest: null`. After all three private pushes, the no-clobber
finalizer makes the upload bundle. Each tag becomes the specified
registry-qualified GHCR tag.

Each `published_digest` is the SHA-256 of a raw manifest. Its config digest
must agree with the checksum-bound local image ID. A new `SHA256SUMS` covers
the new image metadata, updated release metadata, and full file set.

The finalizer does not copy Docker's daemon-global `RepoTags` or `RepoDigests`
arrays. Thus, unrelated private aliases do not enter uploaded evidence.
Public visibility stays blocked until reviewers independently approve the digests
and full source-delivery review.

`CR_PAT` is a short-term, operator-supplied token. Give it only the necessary
package scope for the target owner. Do not write it to `.env`, shell history,
logs, or release evidence. Record the pushed `RepoDigest` values.
Replace the VPS lock examples with those immutable digests.
Complete fresh-environment verification before you make the draft Release public.

Refer to the GitHub
[Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[Packages REST API](https://docs.github.com/en/rest/packages/packages?apiVersion=2022-11-28),
and [`gh release create` manual](https://cli.github.com/manual/gh_release_create).

## Image-publication operator checklist

Complete these checks before the Conditional publication transaction:

- [ ] The mandatory fresh-VM image pull/config-ID verification passed.
      Its transcript is stored.
- [ ] GitHub-hosted CI passed on the published commit.
- [ ] A full dependency scan exited `0` on the same commit within the
      last seven days. The reports passed inspection.
- [ ] GitHub license detection identifies GPL-3.0.
- [ ] Private vulnerability reporting and secret protection are enabled.
- [ ] The reviewer completed the final-image copyleft/source review. All necessary
      source/delivery assets are checksum-bound. `public_oci_ready` is true.
- [ ] GHCR digests and SBOM checksums agree with the draft release.
- [ ] Release assets contain no secrets, signed URLs, private references,
      or personal absolute paths.
- [ ] Each live VPS, DNS, ACME, firewall, provider IAM, and off-host backup
      test has separate recorded authorization.
