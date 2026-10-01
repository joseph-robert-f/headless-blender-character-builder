# Release process

This document gives separate procedures for local release-candidate evidence
and external publication. Local commands do not push, tag, publish an image,
make a GitHub Release, deploy a VPS, or use registry/cloud credentials.

## Local release candidate

The local release candidate has these prerequisites:

- Git and Python 3.11+
- Docker Engine/Desktop and Docker Compose 2.24.4+
- GNU Make
- Approximately four CPU cores
- A minimum of 12 GiB for Docker, plus host overhead
- A minimum of 20 GB of free space for the checkout and evidence
- Approximately 30 GB of free Docker disk space if the image cache is empty.

If `python3` is older, select a compatible interpreter for the full command.
For example, use
`PYTHON=python3.11 HBCB_RELEASE_RUN_ID=review-1 make release-check`.
The full gate also uses outbound HTTPS to the official Blender download host.
As an alternative, set
`HBCB_BLENDER_SOURCE_ARCHIVE=/absolute/path/to/blender-4.5.12.tar.xz`
to supply the specified archive after download. The same size and checksum
policy applies.

1. Start from the intended signed-off commit without unrelated changes.
   The Git index must equal `HEAD`. Commit the examined change first.
   Do not try to release staged, uncommitted bytes.
2. Use `HBCB_RELEASE_RUN_ID=<unique-safe-run-id> make release-check`.
   The wrapper audits the Git index. It exports only indexed files with
   `git checkout-index`. It does the full gate from the temporary tree.

   The run ID is mandatory. It must be unique across all checkouts with the
   same Docker daemon. Use a new value for each retry.
   The wrapper rejects an existing Compose project.

   After cleanup, the specified project, its volumes, and temporary extraction
   containers must be removed. If they stay, the wrapper reports a failure.
   It also holds the fixed private Docker volume `hbcb-release-check-claim`
   as an atomic daemon-wide claim. Only one full release check can use the
   daemon at a time. The random owner label prevents cleanup of a different
   process's claim.
3. Examine the output evidence directory printed by the command.
   It contains the optimized sample release bundle, checksums, SPDX SBOMs,
   image metadata, and sanitized gate summaries. It contains no `.env` or credentials.
4. After repairs, make sure that `git status --short`, `git diff --check`,
   and `scripts/release-audit` stay clean.
5. Record the specified evidence and externally conditional checks in `docs/progress.md`.

Release checkouts must use usual tracked-file index flags.
Sparse paths, `skip-worktree`, and `assume-unchanged` can hide worktree bytes
from a usual status check. Use `git ls-files -v` for read-only diagnosis.
Each tracked entry must have the usual uppercase `H` prefix.

If an examined path accidentally has different flags, change only that path with
`git update-index --no-skip-worktree --no-assume-unchanged -- path/to/file`.
Then examine `git status`, the index, and the worktree diff again.
If sparse-checkout is intentional, use a separate full checkout.
Do not use a general reset to make a release tree look clean.

If there is a daemon-wide claim, stop. Do not delete it.
Examine `docker volume inspect hbcb-release-check-claim`.
Find whether a previous release process stays active.
Get maintainer approval before manual stale-claim recovery.
The tool does not automatically take over an existing claim.

The release check includes these tests and evidence:

- Source/policy audits and ordinary unit/contract tests
- Headless Blender execution for generation
- A new `.blend` reload and GLB/STL import
- Builder security configuration
- Asynchronous service smoke, IAM, and Redis isolation checks
- VPS topology/Caddy checks and isolated backup/restore
- SBOM and notice validation
- Documentation and workflow validation
- Versioned local image tags and OCI source/version/revision labels
- Checksum-verified corresponding source and deterministic release checksums.

The manually started GitHub release-candidate workflow sets a unique
run/attempt evidence ID. After the full gate passes, it uploads the sanitized
evidence directory as a GitHub Actions artifact. Artifact retention is seven
days. A local operation or failed hosted operation does not automatically
make a release.

Neither the local gate nor the hosted release-candidate workflow does the
networked vulnerability scan. Usual pull requests can merge with reported
vulnerabilities. Before publication or deployment, do the separate strict scan.

## Version and local image identity

`VERSION` contains the base application compatibility version.
Ordinary local builds use `0.1.0-local` and revision `uncommitted`.
Thus, they do not identify themselves as releases.

The release gate puts `0.1.0-rc.1` and the audited Git commit into builder,
API, and worker OCI labels. It gives all three the related candidate tag.
Labels, tags, examined image IDs, release metadata, and corresponding-source
inventory must agree. If they do not agree, the gate stops.
A mutable tag alone is not a sufficient deployment identity.

Container image publication is separate and blocked.
[Conditional OCI image publication](oci-publication.md) specifies the
necessary per-image identity records and future VPS `release.lock.env`.

## Container corresponding-source gate

Source commits, source tags, and source/sample release assets can be published
after their gates pass. Public builder and worker image distribution has a
separate gate. Those images contain Blender and other independently licensed
binary components. The API image contains GPL-covered project source.
It uses the same release-source process.

The full release gate makes `corresponding-source.json`.
This image-bound record identifies the packaged project and Blender source,
with related SBOMs and notices. The record declares the scope
`project-and-blender-source-only` and `public_oci_ready: false`.
It does not declare that all copyleft, native, or base-image source obligations
are satisfied.

The gate gets the official Blender 4.5.12 source archive directly through HTTPS.
It does not use proxy environment variables or redirects.
It verifies the archive's 85,105,056-byte size and repository-pinned SHA-256.
Then it includes the archive in the release directory.

`SHA256SUMS` covers the deterministic project source archive, Blender source
archive, inventory, SBOMs, notices, and sample archive.
`HBCB_BLENDER_SOURCE_ARCHIVE=/absolute/path/to/blender-4.5.12.tar.xz`
can supply an operator download. The same byte-count and SHA-256 gate applies.
Missing or changed source stops the gate.

Public OCI publication stays blocked until a reviewer independently completes the
actual-image review in [Conditional OCI image publication](oci-publication.md).
An examined change must then set `public_oci_ready` to `true`.
Publish and keep the source and sample assets with each future public image version.
This is a conservative release policy, not legal advice. Get legal review from a person with the necessary legal qualifications.

## Source-only v0.1 release

The v0.1 support boundary includes examined source for one trusted user's
local builds. It does not promise a published container image.
This transaction publishes the signed `v0.1.0-rc.1` Git tag and a
source-bearing GitHub Release.

It does not authenticate to GHCR, push an image, or change package visibility.
It is the approved v0.1 publication procedure while `public_oci_ready`
is `false` in `release/corresponding-source-policy.json`.

This transaction does not use `scripts/release-publication-preflight`.
That preflight verifies local image identity immediately before a GHCR push.
It stops unless `public_oci_ready` is `true`.
Thus, it can reject a source-only operation for an unrelated image-publication condition.

Its exclusion here does not decrease its controls or change the Conditional
publication gate. That gate stays blocked until its requirements are satisfied.

Use a dedicated release checkout with one operator.
The transaction does not isolate temporary paths, Git references, or Release
drafts from concurrent processes with the same push authority or GitHub CLI session.
Such concurrent activity makes the result invalid.

Use this release procedure:

1. Make sure that GitHub-hosted CI passed on the intended commit.
   Branch protection, secret scanning, push protection, and private
   vulnerability reporting are persistent owner settings.
   Examine these settings when they change. Each release does not include
   this inspection internally.
2. Do the full local release check again on that commit with a new run ID:
   `HBCB_RELEASE_RUN_ID=<unique-safe-run-id> make release-check`.
   Afterward, make sure that `git status --short`, `git diff --check`,
   and `scripts/release-audit` stay clean.
   Record the evidence path and run ID in `docs/progress.md`.
3. Shortly before publication, do the strict/default networked dependency scan
   from the same commit. Exit `0` is necessary. Examine the stored reports.
   Unlike the scheduled report-only audit, this scan evaluates each finding's
   `expires_on` disposition at scan time:
   ```sh
   make dependency-scan \
     DEPENDENCY_OUTPUT="$PWD/build/dependency-audit-release-$(git rev-parse HEAD)"
   ```

   Keep the result and examine it before publication.
   `make release-check` and the source-only transaction do not automatically
   verify a recent scan artifact.
4. Set `RELEASE_DIR` to `release/` inside the evidence path from
   `make release-check`. The printed path is `evidence=.../release-check/<run-id>`.
   `scripts/release-artifacts` makes that directory.
   Verify each asset before upload:
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

   The upload set is each top-level regular file in that directory:

   - The deterministic project source archive
   - The deterministic sample bundle
   - The checksum-verified official Blender source archive
   - The notices and SPDX SBOMs
   - The inventory and metadata records
   - `SHA256SUMS`.

   The sample archive contains the `sample/` evidence subdirectory.
   Thus, GitHub asset names do not flatten its paths.
   Do not use a `.published` finalized bundle. A source-only operation cannot
   make one. `image-metadata.json` records each role's local `image_id`
   with `published_digest: null`, because no image is pushed.
5. After steps 1–4 pass, make and verify the signed tag.
   Use `git tag -s "v0.1.0-rc.1" -m "Headless Blender Character Builder
   0.1.0-rc.1"`, then `git tag -v "v0.1.0-rc.1"`, then `git push origin
   "v0.1.0-rc.1"`.

   You can use configured GPG signing or SSH signing.
   For SSH signing, use `git config gpg.format ssh` and set `user.signingkey`
   to the public key. Upload the same key to GitHub as a signing key for
   GitHub tag verification. Local `git tag -v` with SSH also uses
   `gpg.ssh.allowedSignersFile`.

   A failure before tag push stops the transaction without publication.
   Do not use a pushed tag again or force-move it. For a replaced or failed
   candidate, make a new release. Do not move its tag.
6. Make a draft GitHub Release for the tag. Upload the assets.
   Compare the draft asset names and count with step 4. Then publish:
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

   If draft asset names or counts disagree with step 4, delete
   the draft with `gh release delete`. Keep the tag. Make the draft again
   from the same verified evidence.
7. Update the previous "no release" statements in `docs/installation.md`,
   `docs/architecture.md`, and `docs/README.md`.
   Record that a source-only Release is available and container images stay unpublished.
   Record publication in `docs/progress.md`.
   Use the usual commit inspection process for these documentation changes.

The future image-publication procedure stays in
[Conditional OCI image publication](oci-publication.md).
This section does not change it. It stays blocked until derived PostgreSQL
image support is available and a reviewer independently approves `public_oci_ready` as `true`
after the copyleft/source review.

## Dependency maintenance

`make dependency-check` is the offline consistency gate that can stop a release.
It binds Python declarations to hash locks and examined evidence.
It binds Debian base stages to OCI/SPDX provenance.
It binds root PostgreSQL/Redis pins to recovery Compose, specified assertions,
and notices. It also binds the Caddy gate reference to the operator lock
example and notice.

The scheduled/manual `dependency-audit.yml` workflow has read-only repository
permission. It reports upstream status and vulnerabilities in report-only
mode. It makes no branches, issues, or pull requests.
An incomplete scan causes failure. Findings and expired dispositions do not
stop usual work.

Before publication or deployment, use strict/default `make dependency-scan`
on the candidate. Examine its stored evidence.

Dependency updates are coordinated maintainer changes.
A Compose image update must also update `tests/deployment/g8_recovery_compose.yaml`,
its exact-pin assertions, migration/recovery behavior, and affected notice or
license evidence. Complete this work before merge. A database major-version
change is a migration project. Do not treat it as an automatic image update.
Refer to [dependency-maintenance.md](dependency-maintenance.md) for the full
process and exit meanings.

GitHub Actions stay pinned to full commit SHAs. Examine them manually because
workflow permissions and external code make explicit trust review necessary.
Keep `persist-credentials: false` during Action-pin changes.
Pass the release-policy tests. Record the examined upstream release/tag for
the selected commit.

## Rollback

For source and images, use a previously verified digest for rollback.
Do not move an existing version tag. Database migrations operate only in the
forward direction. After an upgrade starts its writable phase, retry the same target.
As an alternative, restore the verified pre-upgrade backup into a validated empty namespace. Refer to [deployment.md](deployment.md).

## Final operator checklist

Complete these checks for the Source-only v0.1 release transaction.
The image-publication checklist is in
[Conditional OCI image publication](oci-publication.md).

- [ ] GitHub-hosted CI passed on the published commit.
- [ ] A new `make release-check` passed on the released commit.
      `docs/progress.md` records its run ID and evidence path.
- [ ] The dependency scan exited `0` on that commit. The reports passed inspection.
- [ ] Each uploaded asset agreed with the evidence directory's `SHA256SUMS`.
- [ ] Release assets contain no secrets, signed URLs, private references,
      or personal absolute paths.
- [ ] The signed tag passes `git tag -v`. The Release is no longer a draft.
- [ ] The availability statements and `docs/progress.md` record publication.
