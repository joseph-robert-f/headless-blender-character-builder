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
Neither the local gate nor the hosted release-candidate workflow runs the
networked vulnerability scan. Routine pull requests can merge with reported
vulnerabilities; the strict scan is a separate pre-publication/deployment step.

## Version and local image identity

`VERSION` contains the base application compatibility version. Ordinary local
builds label themselves `0.1.0-local` with revision `uncommitted`, so they do
not impersonate a release. The release gate injects `0.1.0-rc.1` and the exact
audited Git commit into builder, API, and worker OCI labels, gives all three the
matching candidate tag, then fails unless labels, tags, inspected image IDs,
release metadata, and corresponding-source inventory agree. A mutable tag is
never sufficient deployment identity.

Publishing container images is a separate, currently blocked transaction. The
per-image identity records it must capture and the VPS `release.lock.env` it
would populate are specified in
[Conditional OCI image publication](oci-publication.md).

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

Public OCI publication stays blocked until the independent actual-image review
specified in [Conditional OCI image publication](oci-publication.md) completes
and flips `public_oci_ready` to `true` through a reviewed change. The source
and sample assets above must still be co-published and retained with each
eventual public image version. This is a conservative release policy, not
legal advice; obtain qualified review.

## Source-only v0.1 release

The v0.1 support boundary ships reviewed source for one trusted user building
locally; it does not promise a published container image. This transaction
publishes the signed `v0.1.0-rc.1` Git tag and a source-bearing GitHub
Release. It never authenticates to GHCR, never pushes an image, and never
changes any package visibility. It is the authorized v0.1 publication path
while `public_oci_ready` is `false` in
`release/corresponding-source-policy.json`.

This transaction does not run `scripts/release-publication-preflight`: that
preflight exists to verify local image identity immediately before a GHCR
push and, by design, fails unless `public_oci_ready` is `true`, so it would
reject a source-only run for a reason unrelated to publishing source. Skipping
it here does not weaken it or the Conditional publication gate below, which is
unchanged and stays hard-blocked until its own requirements are met.

Use a dedicated, single-operator release checkout for this transaction too. It
does not defend its temporary paths, Git references, or Release draft against
a concurrent local process that already has the same push authority or GitHub
CLI session; any such concurrency invalidates the run.

A release operator:

1. confirms GitHub-hosted CI is green on the exact intended commit. Repository
   hardening — branch protection, secret scanning, push protection, and
   private vulnerability reporting — is a standing owner setting reviewed when
   it changes, not re-verified inside every release;
2. reruns the complete local release check on that commit with a fresh run ID
   (`HBCB_RELEASE_RUN_ID=<unique-safe-run-id> make release-check`), confirms
   `git status --short`, `git diff --check`, and `scripts/release-audit`
   remain clean afterward, and records the exact evidence path and run ID in
   `docs/progress.md`;
3. runs the strict/default networked dependency scan from that exact commit
   shortly before publishing, requires exit `0`, and reviews the retained
   reports; unlike the scheduled report-only audit, this checks the dependency
   policy's per-finding `expires_on` dispositions at scan time:
   ```sh
   make dependency-scan \
     DEPENDENCY_OUTPUT="$PWD/build/dependency-audit-release-$(git rev-parse HEAD)"
   ```
   The operator must retain this result and verify it before publication;
   `make release-check` and the source-only transaction do not verify a recent
   scan artifact automatically.
4. verifies the release assets with `RELEASE_DIR` set to the `release/`
   directory inside the evidence path that `make release-check` printed as
   `evidence=.../release-check/<run-id>` (`scripts/release-artifacts`
   populates it). The upload set is every top-level regular file in that
   directory: the deterministic project source archive, the deterministic
   sample bundle (the `sample/` evidence subdirectory is represented by its
   archive so GitHub asset naming does not flatten its paths), the
   checksum-verified official Blender source archive, the notices, the SPDX
   SBOMs, the inventory and metadata records, and `SHA256SUMS`. Never use a
   `.published` finalized bundle; one cannot exist for a source-only run.
   `image-metadata.json` records each role's local `image_id` with
   `published_digest: null`, plainly, because no image is pushed. Verify
   every asset before upload:
   ```sh
   (
     cd "$RELEASE_DIR"
     if command -v sha256sum >/dev/null 2>&1; then
       sha256sum --check SHA256SUMS
     else
       shasum -a 256 --check SHA256SUMS
     fi
   )
   ```
5. creates and verifies the signed tag only after steps 1-4 pass:
   `git tag -s "v0.1.0-rc.1" -m "Headless Blender Character Builder
   0.1.0-rc.1"`, then `git tag -v "v0.1.0-rc.1"`, then `git push origin
   "v0.1.0-rc.1"`. Any configured Git signing method satisfies this step:
   GPG, or SSH signing via `git config gpg.format ssh` with `user.signingkey`
   naming the public key (upload the same key to GitHub as a signing key for
   tag verification there; local `git tag -v` under SSH also needs
   `gpg.ssh.allowedSignersFile`). Any failure before the tag push aborts the
   transaction with nothing published. A pushed tag is never reused or
   force-moved; a superseded or failed candidate gets a new release, never a
   moved tag;
6. creates a draft GitHub Release for the tag, uploads the assets, confirms
   the draft's asset names and count against step 4, then publishes:
   ```sh
   gh release create "v0.1.0-rc.1" \
     --repo joseph-robert-f/headless-blender-character-builder \
     --draft --verify-tag \
     --title "Headless Blender Character Builder 0.1.0-rc.1" \
     --notes-file docs/release-notes/v0.1.0-rc.1.md
   for asset in "$RELEASE_DIR"/*; do
     test -f "$asset" || continue
     gh release upload "v0.1.0-rc.1" "$asset" \
       --repo joseph-robert-f/headless-blender-character-builder
   done
   gh release view "v0.1.0-rc.1" \
     --repo joseph-robert-f/headless-blender-character-builder \
     --json assets,isDraft,tagName,url
   gh release edit "v0.1.0-rc.1" --draft=false \
     --repo joseph-robert-f/headless-blender-character-builder
   ```
   On any missing, extra, or misnamed draft asset, delete the draft with
   `gh release delete`, keep the tag, and re-create the draft from the same
   verified evidence;
7. updates the now-superseded "no release" statements in
   `docs/installation.md`, `docs/architecture.md`, and `docs/README.md` to
   record that a source-only Release exists and that container images remain
   unpublished, and records the publication in `docs/progress.md`, through the
   same commit-reviewed flow as any other documentation change.

The future image-publication path is specified separately in
[Conditional OCI image publication](oci-publication.md). It is unchanged by
this section and stays blocked until its own requirements — derived PostgreSQL
image support and an independent copyleft/source review that flips
`public_oci_ready` to `true` — are met.

## Dependency maintenance

`make dependency-check` is the offline, release-blocking consistency gate. It
binds Python declarations to hash locks and reviewed evidence, every Debian
base stage to OCI/SPDX provenance, and root PostgreSQL/Redis pins to recovery
Compose, exact assertions, and notices. It also binds the Caddy gate reference
to the operator lock example and notice. The scheduled/manual
`dependency-audit.yml` workflow has read-only repository permission. It reports
upstream status and vulnerability findings in report-only mode without
creating branches, issues, or pull requests. It fails when the scan is
incomplete, but findings and expired dispositions do not block routine work.
Before publication or deployment, run strict/default `make dependency-scan`
on the exact candidate and review its retained evidence.

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

The items below gate the Source-only v0.1 release transaction above; confirm
them before considering that transaction complete. The image-publication
checklist lives in [Conditional OCI image publication](oci-publication.md).

- [ ] GitHub-hosted CI passed on the published commit.
- [ ] A fresh `make release-check` passed on the exact released commit, and
      its run ID and evidence path are recorded in `docs/progress.md`.
- [ ] The dependency scan exited `0` on that commit and its reports were
      reviewed.
- [ ] Every uploaded asset matched the evidence directory's `SHA256SUMS`.
- [ ] Release assets contain no secrets, signed URLs, private references, or
      personal absolute paths.
- [ ] The signed tag verifies (`git tag -v`) and the Release is no longer a
      draft.
- [ ] The availability statements and `docs/progress.md` record the
      publication.
