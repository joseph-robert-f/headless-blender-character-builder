# Dependency maintenance without Dependabot

This repository contains no configuration that asks Dependabot to rewrite
dependency files. Maintainers use one offline consistency gate and one
read-only networked audit so version discovery, security review, lock
regeneration, licensing, recovery evidence, and migration planning stay
coordinated.

No provider key, registry credential, GitHub personal access token, or paid
service is required for the public-repository workflow. GitHub Actions supplies
its own read-only checkout token. Private registries would require a separately
reviewed authentication design.

## Three levels of checking

| Command | Network | Docker | Purpose |
|---|---:|---:|---|
| `make dependency-check` | No | No | Fail when declarations, locks, hashes, notices, provenance, Compose recovery pins, or exact assertions disagree. |
| `make dependency-audit` | Yes | No | Run the offline gate, then report PyPI candidates, Docker Official Image support status, and tag-to-digest drift. It never edits files. |
| `make dependency-scan DEPENDENCY_OUTPUT=build/dependency-audit-review` | Yes | Yes | Download a checksum-pinned OSV-Scanner, build the four project images, scan all three Python locks and every release image, run the isolated PostgreSQL runtime proof, then enforce the checked-in UNRATED/HIGH/CRITICAL disposition policy while retaining the detailed reports. |

`make postgres-security-check` reruns only the exact PostgreSQL fresh-volume
proof. It is useful while diagnosing that fixture, but it does not replace the
complete dependency scan.

The complete scan requires substantial downloads, disk, and build time. Its
output directory must not already exist. Choose a new ignored `build/` path for
each retained local run. Every project and external image is scanned from one
mode-`0600` temporary Docker archive at a time, with a hard 2 GiB limit; allow
enough additional temporary disk for the largest selected image.
Audit, build, and scan commands run in isolated process groups. A deadline or
operator interrupt applies a bounded `SIGTERM` grace period, escalates surviving
descendants to `SIGKILL`, and reaps the group leader before returning.

The offline check is part of `make check` and the clean-index release gate. It
is deterministic and makes no vulnerability-database or registry requests.
The online commands are advisory discovery tools: they can identify work, but
they never select or install an update.

## Hosted audit

`.github/workflows/dependency-audit.yml` runs every Monday and supports manual
dispatch from the Actions tab. Scheduled runs use the current default branch;
manual runs use the maintainer-selected ref. The workflow receives
`contents: read`, persists no checkout credentials, has no issue or pull-request
write permission, and is never triggered by a contributor pull request.

After adopting this workflow, enable GitHub Actions and manually dispatch
`Dependency audit` once. Forks start with scheduled workflows disabled, and
GitHub can disable schedules in a public repository after 60 days without
repository activity, so maintainers must periodically confirm that scheduled
runs still occur.

The workflow:

1. validates every synchronized dependency surface;
2. checks PyPI and maintained Docker Official Image metadata;
3. downloads OSV-Scanner 2.3.8 from its official release and verifies the
   platform-specific SHA-256 recorded in `scripts/dependency-scan`;
4. executes the trusted Dockerfile build steps under random per-run tags, but
   never starts the resulting project-built service containers, then scans each
   final image.
   Each project tag is inspected once, exported by the resulting immutable
   image ID, and accepted only when the archive is `linux/amd64` and its config
   digest and complete label set match that inspection. Its policy identity
   hashes every runtime layer member's bytes, path, type, mode, ownership,
   link/device metadata, and non-time PAX metadata plus the complete runtime
   config and labels. Wall-clock config/history and tar timestamps are excluded
   so two otherwise identical clean BuildKit rebuilds have one identity. The
   final disposition identity additionally hashes the exact repository runtime
   controls used by that target's review. API and worker bind the base/VPS
   Compose models and Caddyfile; MinIO binds those models, both disposable
   integration models, and its runtime security gate; PostgreSQL binds every
   Compose model that can start it plus its fresh-volume runtime gate; and Caddy
   binds its VPS Compose model and Caddyfile. A relevant configuration or gate
   change therefore cannot reuse an earlier disposition. The per-run tags are removed in reverse build order
   even after a build or scan failure. For every external image, the scanner
   verifies the pinned registry index bytes,
   requires exactly one `linux/amd64` child, verifies that child's manifest and
   config digests, and pulls and inspects that exact child. OSV-Scanner receives
   only validated, size-capped private archives—not mutable local tags or
   multi-architecture registry references. After the exact PostgreSQL image is
   scanned, one random owner-labelled, network-disabled fixture proves that a
   fresh volume initializes as UID/GID 70 while a mounted `gosu` sentinel would
   fail if invoked. Cleanup removes only the exact labelled container and
   volume, including after failure or interruption;
5. retains per-file and aggregate size-capped JSON and Markdown reports for
   seven days; and
6. normalizes aliases into advisory families, reports every severity, and fails
   for an undispositioned UNRATED/HIGH/CRITICAL family, an unmaintained image tag,
   mutable-tag digest drift, inconsistent repository evidence, an invalid or
   expired disposition, a failed PostgreSQL runtime proof, or an incomplete
   scan.

An informational newer version or a LOW or MODERATE advisory family does not
fail the workflow by itself. UNRATED fails closed because absence of a score is
not evidence of absence of impact. Every family remains counted in
`scan-summary.md`, and the complete OSV JSON remains in the artifact. A failed
run therefore means either an actionable policy/security finding or that the
audit could not complete; inspect the summary first and then the named raw
report.

The workflow pins `actions/checkout` v6.0.2 at
`de0fac2e4500dabe0009e67214ff5f5447ce83dd` and `actions/upload-artifact`
v7.0.1 at `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`. Treat any future action pin as
an executable supply-chain update and verify its release mapping before merge.

### Disable automatic Dependabot pull requests

Deleting `.github/dependabot.yml` disables configured Dependabot version-update
pull requests; it does not disable repository-level Dependabot security-update
pull requests. If the repository owner wants this audit to be the only PR-free
dependency workflow, open **Settings → Security → Advanced Security** and
disable **Dependabot security updates**. Keep **Dependabot alerts** enabled if
you want GitHub's read-only alerting in addition to this workflow. An
organization policy may enforce security updates; when the control is locked,
the repository cannot promise that Dependabot will create no PRs.

## Coordinated update procedure

Create one focused maintainer branch per dependency family. Do not copy a
version from an automated report directly into one file.

### Python packages

1. Update the exact direct requirement in `pyproject.toml` or
   `service/pyproject.toml`.
2. Resolve wheels for CPython 3.11 on `linux/amd64`, verify them, and regenerate
   the applicable hash lock under `docker/`.
3. For service runtime packages, update
   `release/service-dependency-licenses.json`, including the lock SHA-256 and
   reviewed license/source metadata.
4. Update the direct-dependency table in `THIRD_PARTY_NOTICES.md`.
5. Run `make dependency-check`, `make check`, the service smoke gate when
   applicable, a full `make dependency-scan` using a new output path, and
   `make release-check` before merge.

`psycopg[binary]` deliberately binds both the `psycopg` and
`psycopg-binary` distributions to the same version. Test-only locks remain
separate from production images.

To create reproducible lock candidates, first update the direct versions in the
appropriate TOML file, build the reviewed `linux/amd64` test stage, and download
the resolver's selected CPython 3.11 wheels into a new directory. The test stage
deliberately retains `pip` for offline test and maintenance tooling; the final
builder strips `pip` and must not be used as a networked resolver. The arguments
below must exactly match the TOML declarations after your edit:

```sh
make test-image
lock_work=build/dependency-lock-review-YYYYMMDD
test ! -e "$lock_work"
mkdir -p "$lock_work/builder-wheels" "$lock_work/runtime-wheels" "$lock_work/service-test-wheels"

download_wheels() {
  wheel_dir=$1
  shift
  docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    --network bridge \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 256 \
    --tmpfs /tmp:rw,nosuid,nodev,size=512m \
    --env HOME=/tmp \
    --mount "type=bind,src=$PWD/$wheel_dir,dst=/wheels" \
    --entrypoint /opt/blender/4.5/python/bin/python3.11 \
    headless-blender-character-builder:dev-test \
    -m pip download --disable-pip-version-check --no-cache-dir \
    --only-binary=:all: \
    --dest /wheels "$@"
}

download_wheels "$lock_work/builder-wheels" 'jsonschema==4.26.0'
download_wheels "$lock_work/runtime-wheels" \
  'async-timeout==5.0.1' 'fastapi==0.141.1' 'minio==7.2.20' \
  'psycopg[binary]==3.3.4' 'redis==8.1.0' 'uvicorn==0.52.1'
download_wheels "$lock_work/service-test-wheels" 'httpx2==2.10.0'

./scripts/dependency-lock-from-wheels \
  --wheels "$lock_work/builder-wheels" \
  --output "$lock_work/test-requirements.candidate"
./scripts/dependency-lock-from-wheels \
  --wheels "$lock_work/runtime-wheels" \
  --output "$lock_work/service-requirements.candidate"
./scripts/dependency-lock-from-wheels \
  --wheels "$lock_work/service-test-wheels" \
  --output "$lock_work/service-test-requirements.candidate"
```

The helper is offline: it reads only the downloaded wheels, validates their
metadata identity and bounds, hashes their exact bytes, sorts normalized names,
and refuses to overwrite an existing candidate. Review the resolver diff and
wheel licenses before copying a candidate to `docker/`. For the runtime lock,
update every dependency and the new lock hash in
`release/service-dependency-licenses.json`; `make dependency-check` rejects an
incomplete or stale inventory.

### Debian base image

Update all literal Debian `FROM` references together across the builder,
service, and MinIO Dockerfiles. In the same change, update the snapshot
arguments, builder OCI base labels, embedded SPDX base package checksum, and
Debian notice. Then rebuild and vulnerability-scan every affected final image.
The full `make dependency-scan` result is required before merge.

### Dockerfile frontend

The service and MinIO Dockerfiles use one exact-version, manifest-digest-pinned
`docker/dockerfile` frontend. Update both first-line directives and the reviewed
reference in `release/dependency-policy.json` together. Confirm the digest from
Docker's verified-publisher registry metadata, review the required BuildKit
version and release notes, then run the offline gate and rebuild every affected
target. The build engine itself remains a manually reviewed tool boundary.

### PostgreSQL or Redis

Update `compose.yaml`, `tests/deployment/g8_recovery_compose.yaml`, the exact
assertions in `tests/deployment/test_g8_recovery_drill.py`, and
`THIRD_PARTY_NOTICES.md` together. Run the service and G8 recovery gates plus a
full `make dependency-scan` using a new output path before merge.

Do not treat a PostgreSQL major release as an image update. It requires a
separately designed backup, migration, rollback, and existing-volume rehearsal.
For Redis, review persistence format, UID, configuration, and the documented
empty-queue reconstruction path even though PostgreSQL remains authoritative.

### Caddy

Keep the exact Caddy tag and digest in `tests/deployment/g8_caddy_gate.py`
synchronized with the tag and explicit zero-digest placeholder in
`deploy/vps/release.lock.env.example` and the notice table. Run `make g8-caddy`
and the full dependency scan before selecting the updated operator example.

### Manually reviewed inputs

Blender archives and corresponding source, the source-built MinIO/Go/mc
fixture, the BuildKit engine, GitHub Action commits, hosted runners,
OSV-Scanner release assets, and the ranged Python build backend are
intentionally listed under
`manual_review` in `release/dependency-policy.json`. Version services cannot
safely decide their
compatibility, licensing, provenance, or migration policy.

The MinIO image recipe label is the SHA-256 emitted by
`scripts/minio-recipe-id`. It binds the Dockerfile plus both MinIO and `mc`
`go.mod`/`go.sum` overlays. Service builds, release validation, and dependency
scan builds must all use that helper. A dependency-scan run computes the value
once, passes that exact value into the build, and verifies it again in the
archived config; hashing only the Dockerfile would permit a changed module
graph to reuse stale scan/release identity.

## Vulnerability decision policy

`release/vulnerability-policy.json` is deliberately separate from the
dependency inventory. The scanner owns the enforcement rules: UNRATED, HIGH,
and CRITICAL block by default, and the policy cannot weaken that threshold.
LOW, MODERATE, and NONE remain counted in each target's summary and remain
present in the detailed OSV report. The checked-in policy starts with no
dispositions and an immutable `"default_action": "deny"`; do not populate it
merely to make a scheduled scan green.

OSV can publish the same issue under ecosystem, CVE, GHSA, and language IDs.
The evaluator uses OSV-Scanner's package groups, validates their coverage, and
canonicalizes every ID and alias into one sorted advisory family. A disposition
therefore applies to one exact tuple only:

- scan target, such as `osv-image-minio`;
- exact target `image_identity.policy_digest` for every image scan (source
  dispositions use JSON `null`);
- ecosystem, package name, installed version, and package source revision (or
  explicit JSON `null` when the report has none);
- complete canonical advisory family; and
- exact scanner score (or `null` when unrated), matching-ecosystem fixed-version
  union, and normalized UNRATED, HIGH, or CRITICAL severity.

The fixed-version union includes both ordinary OSV ranges and
`ecosystem_specific.custom_ranges`. This matters for release-named or
pseudo-version projects such as MinIO; omitting a custom bound would make two
different advisory states look identical.

Severity precedence is deliberately conservative. Normally the evaluator takes
the maximum of OSV-Scanner's group CVSS score, database severity labels, and
ecosystem urgency labels. There is one narrowly scoped vendor override: an
official `DEBIAN-*` advisory whose affected entry exactly matches the reported
`Debian:<release>` package and says `urgency: unimportant` is reported as LOW.
Debian uses that state for issues its security team has determined do not
warrant a security update for that exact distribution package. The override
does not apply to missing or conflicting metadata, generic advisories, other
ecosystems, or Debian `not yet assigned`, `low`, `none`, or `not affected`
states. Those continue to use the maximum severity; a distro backport or
not-affected determination requires an exact evidence-backed disposition.

There are no target globs, package prefixes, advisory prefixes, severity-wide
exceptions, or permanent exceptions. Each disposition also requires a
decision (`accepted-risk`, `mitigated`, or `not-affected`), a substantive
rationale, review and expiry dates, and at least one repository-relative
evidence file with its exact SHA-256. Evidence cannot point back to the policy
itself. Review cannot be future-dated, an entry is invalid beginning on its
expiry date, and the review window cannot exceed 90 days.

Example shape (illustrative hashes and identifiers must never be copied into a
real decision):

```json
{
  "advisory_family": [
    "CVE-2099-1234",
    "GHSA-AAAA-BBBB-CCCC"
  ],
  "disposition": "mitigated",
  "evidence": [
    {
      "path": "docs/security/review-2099-1234.md",
      "sha256": "<exact 64-character lowercase SHA-256>"
    }
  ],
  "expires_on": "2099-02-15",
  "fixed_versions": [
    "1.2.4"
  ],
  "image_identity": "sha256:<exact policy_digest from this target's scan summary>",
  "package": {
    "ecosystem": "Go",
    "name": "example.invalid/module",
    "source_revision": "<exact reported revision or null>",
    "version": "1.2.3"
  },
  "rationale": "Explain why this exact deployed component is temporarily safe.",
  "reviewed_on": "2099-01-15",
  "score": "8.1",
  "severity": "HIGH",
  "target": "osv-image-minio"
}
```

Add the object to the policy's `dispositions` array only after reviewing a new
scan from the exact candidate revision. Alias, severity, package, version,
source-revision, target-image-identity, evidence-digest, or date drift makes
the disposition stop matching or makes the scan incomplete. An active disposition which no longer
matches anything on an evaluated target is itself a policy finding, so resolved
exceptions cannot silently accumulate. Do not seed dispositions from an older
artifact: rebuilt images can change the installed package inventory even when
their Dockerfile text is unchanged.

The target identity is not a substitute for the evidence file. It is a
canonical digest over stable image provenance shown in `scan-summary.json`.
For project-built images it includes the normalized runtime-layer content
digest, normalized runtime-config digest, complete-label digest,
`linux/amd64`, and verified OCI source revision. The source-built MinIO fixture
also includes the composite `io.hbcb.recipe-id`. Raw image config/descriptor
digests and private archive hashes remain visible operational evidence but are
excluded from the policy digest because BuildKit timestamps and Docker archive
layout are not runtime identities. Any file bytes, path, type, mode, ownership,
link/device metadata, non-time PAX metadata, runtime config, label, revision, or
MinIO recipe change produces a different image identity. For API, worker,
MinIO, PostgreSQL, and Caddy, that image identity is then combined with the
exact disposition-context digest described above. Changing any reviewed
runtime control produces a different final policy identity even when the image
bytes are unchanged.

The raw scanner exit remains recorded. Exit `1` from OSV-Scanner only means it
found at least one family; after evaluation, that target may pass when every
UNRATED/HIGH/CRITICAL family has an exact active disposition and all remaining
families are lower. A scanner/report disagreement, malformed inner report,
missing policy, bad evidence digest, or expired disposition is incomplete—not
clean.

## Exit meanings

| Exit | Meaning |
|---:|---|
| `0` | The requested audit completed without blocking findings. Informational candidates may still be listed. |
| `1` | A consistency/maintenance finding or undispositioned UNRATED/HIGH/CRITICAL advisory family needs review. |
| `2` | The audit was incomplete because an input, network request, build, scanner, or report failed. Do not interpret this as clean. |

OSV-Scanner's detailed reports remain authoritative for package findings. The
repository summary records bounded per-severity and policy-decision counts; it
does not paste untrusted upstream vulnerability descriptions into the rendered
GitHub summary.

## Adding another dependency surface

Update `release/dependency-policy.json`, extend `scripts/dependency-audit`, and
add a mutation test under `tests/release/` in the same pull request. If the new
surface introduces network access, credentials, parsing, execution, or CI
permissions, update the threat model before enabling it.

References: [OSV-Scanner supported inputs](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/),
[container image scanning](https://google.github.io/osv-scanner/usage/scan-image),
[GitHub Actions workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
and [Dependabot security-update settings](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-security-updates).
