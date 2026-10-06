# Dependency maintenance without Dependabot

The repository has no configuration that asks Dependabot to change dependency
files. Maintainers use an offline consistency gate, read-only version
discovery, and a report-only vulnerability audit for usual work.
Before deployment or publication, a strict vulnerability decision gate applies.

Thus, lock regeneration, licensing, recovery evidence, and migration plans
stay coordinated. Each pull request does not make new risk decisions necessary.

The public-repository workflow uses no provider key, registry credential,
GitHub personal access token, or paid service. GitHub Actions supplies its own
read-only checkout token. Private registries can make an independently examined
authentication design necessary.

<a id="four-levels-of-checking"></a>
## Four check levels

| Command | Network | Docker | Function |
|---|---:|---:|---|
| `make dependency-check` | No | No | Stop if declarations, locks, hashes, notices, provenance, Compose recovery pins, or specified assertions disagree. |
| `make dependency-audit` | Yes | No | Do the offline gate. Report PyPI candidates, Docker Official Image support status, and tag-to-digest changes. Do not change files. |
| `./scripts/dependency-scan --report-only --output build/dependency-audit-review --images` | Yes | Yes | Make and scan all release images and Python locks. Do the PostgreSQL runtime test and keep reports. Vulnerabilities alone do not cause failure. This mode does not load or apply checked-in dispositions. Use a new output directory each time. |
| `make dependency-scan DEPENDENCY_OUTPUT=build/dependency-audit-release` | Yes | Yes | Do the same full scan in strict/default mode before deployment or publication. Each UNRATED/HIGH/CRITICAL finding must have a related active disposition with evidence. Keep and examine the reports. |

`make postgres-security-check` does only the specified PostgreSQL
fresh-volume test again. Use it for fixture diagnosis. It does not replace the
full dependency scan.

The full scan uses large downloads, disk space, and build time.
There must be no output directory before the scan. Select a new ignored `build/` path for
each stored local operation. The scanner uses one temporary Docker archive
at a time for each project and external image. Each archive has mode `0600`
and a strict 5 GiB limit. Keep sufficient more temporary disk space
for the largest selected image.

Audit, build, and scan commands use isolated process groups.
At a deadline or operator interrupt, the process gets a time-limited `SIGTERM`
grace period. Remaining descendants then get `SIGKILL`.
The wrapper reaps the group leader before return.

The offline check is part of `make check` and the clean-index release gate.
It is deterministic. It makes no vulnerability-database or registry requests.
Usual pull-request checks do not apply vulnerability decisions.
The online commands do not select or install an update.

The report-only scan can identify necessary work. An expired or missing
disposition does not stop a pull request in this mode.

## Hosted audit

`.github/workflows/dependency-audit.yml` operates each Monday.
You can also start it manually from the Actions tab.
Scheduled operations use the default branch. Manual operations use the
maintainer-selected ref.

The workflow gets `contents: read`. It does not keep checkout credentials.
It has no issue or pull-request write permission. Contributor pull requests
do not start this workflow.

The scheduled/manual workflow uses `dependency-scan --report-only`.
It keeps detailed report artifacts for seven days. It fails if the audit is
incomplete, the artifact is missing, or a dependency-maintenance/runtime
security gate fails. It does not load dispositions or evaluate their expiry.
Vulnerabilities alone do not cause workflow failure.

Before the next deployment or publication, examine the findings with the
strict/default scan.

After adoption, enable GitHub Actions and manually start `Dependency audit`
one time. Scheduled workflows are disabled on new forks.
GitHub can disable schedules after 60 days without public-repository activity.
At regular intervals, make sure that scheduled operations occur.

The workflow does this sequence:

1. Validate all synchronized dependency files and records.
2. Do checks of PyPI and maintained Docker Official Image metadata.
3. Download OSV-Scanner 2.3.8 from its official release. Verify the
   platform-specific SHA-256 in `scripts/dependency-scan`.
4. Do the trusted Dockerfile build steps with random per-run tags.
   Do not start the resulting project-built service containers.
   Then scan each final image with the image controls in the next section.
5. Keep JSON and Markdown reports for seven days. Apply per-file and aggregate
   size limits.
6. Normalize aliases into advisory families and report each severity.

A full report-only scan succeeds even with vulnerabilities.
An incomplete build, scan, report, or PostgreSQL runtime test causes failure.
Strict/default mode also applies the specified vulnerability dispositions
before deployment or publication.

### Image scan controls

The scanner examines each project tag one time. It exports the resulting
immutable image ID. It accepts an archive only with `linux/amd64`, the same
config digest, and the same full label set as that inspection.

The policy identity hashes each runtime-layer member's bytes, path, type,
mode, ownership, link/device metadata, and non-time PAX metadata.
It also hashes the full runtime config and labels. It excludes wall-clock
config/history and tar timestamps. Thus, clean BuildKit
builds with no other differences have the same identity.

Strict-mode disposition identity also hashes the repository runtime controls
used for that target's inspection:

- API and worker: The base/VPS Compose models and Caddyfile
- MinIO: Those models, the two disposable integration models, and its runtime
  security gate
- PostgreSQL: Its Dockerfile, each Compose model that can start it, and its
  fresh-volume runtime gate
- Caddy: Its VPS Compose model and Caddyfile.

A related configuration or gate change cannot use an earlier disposition.
The scanner removes per-run tags in reverse build order, including after
build or scan failure.

For each external image, the scanner verifies the specified registry index
bytes. The index must have only one `linux/amd64` child.
The scanner verifies that child's manifest and config digests.
It pulls and examines that child.

OSV-Scanner gets only validated, size-limited private archives.
It does not get mutable local tags or multi-architecture registry references.
The scanner evaluates the official PostgreSQL base for maintenance and digest
changes as provenance. That base is not the runtime scan target.

The scanner makes the repository's derived image after `gosu` deletion.
It exports by immutable image ID and scans that image.
Then one random owner-labelled fixture does a runtime test of the same derivative.
The fixture has no network. It makes sure that there is no `gosu` and a new
volume initializes as UID/GID 70.

Cleanup removes only the specified labelled container and volume.
This also applies after failure or interruption.

Each advisory family stays counted in `scan-summary.md`.
The full OSV JSON stays in the artifact.
Report-only success means that the scanner completed the scan. It does not mean
vulnerability-free images or deployment approval.

First, examine the summary. Then examine the named raw report.
In strict/default mode, UNRATED stops the gate. A missing score does not
show an absence of impact.

The workflow pins `actions/checkout` v6.0.2 at
`de0fac2e4500dabe0009e67214ff5f5447ce83dd` and `actions/upload-artifact`
v7.0.1 at `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`.
Treat a new action pin as an executable supply-chain update.
Before merge, verify its release mapping.

### Disable automatic Dependabot pull requests

Removal of `.github/dependabot.yml` disables configured Dependabot
version-update pull requests. It does not disable repository-level Dependabot
security-update pull requests.

If the owner wants only this PR-free audit, open
**Settings → Security → Advanced Security**.
Disable **Dependabot security updates**. Keep **Dependabot alerts** enabled
if you want more read-only GitHub alerts.
An organization policy can enforce security updates. If the control is
locked, the repository cannot guarantee an absence of Dependabot PRs.

## Coordinated update procedure

Make one maintainer branch per dependency family.
Do not put a reported version directly into one file without the related changes.

### Python packages

1. Update the specified direct requirement in `pyproject.toml` or
   `service/pyproject.toml`.
2. Resolve and verify wheels for CPython 3.11 on `linux/amd64`.
   Generate the applicable hash lock under `docker/` again.
3. For service runtime packages, update `release/service-dependency-licenses.json`.
   Include the lock SHA-256 and examined license/source metadata.
4. Update the direct-dependency table in `THIRD_PARTY_NOTICES.md`.
5. Before a usual pull-request merge, do `make dependency-check`, `make check`,
   applicable service smoke tests, and `make release-check`.
   A report-only scan can show new findings. Neither that scan nor disposition
   renewal is a PR merge requirement. Before deployment or publication,
   use strict `make dependency-scan`.

`psycopg[binary]` binds `psycopg` and `psycopg-binary` distributions to the
same version. Test-only locks stay separate from production images.

To make reproducible lock candidates, first update direct versions in the
applicable TOML file. Make the examined `linux/amd64` test stage.
Download the resolver-selected CPython 3.11 wheels into a new directory.

The test stage keeps `pip` for offline tests and maintenance tools.
The final builder removes `pip`. Do not use it as a networked resolver.
After your change, the arguments in the next command block must agree with the TOML declarations:

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
download_wheels "$lock_work/service-test-wheels" 'httpx2==2.12.0'

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

The offline helper reads only the downloaded wheels.
It validates their metadata identity and limits. It hashes their bytes and
sorts normalized names. It does not overwrite an existing candidate.

Examine the resolver diff and wheel licenses before you copy a candidate to
`docker/`. For the runtime lock, update each dependency and the new lock
hash in `release/service-dependency-licenses.json`.
`make dependency-check` rejects an incomplete or stale inventory.

### Debian base image

Update all literal Debian `FROM` references together in the builder, service,
and MinIO Dockerfiles. In the same change, update snapshot arguments, builder
OCI base labels, the embedded SPDX base-package checksum, and Debian notice.

Make the affected final images again. Examine a report-only scan if available.
A usual pull-request merge does not make vulnerability decisions or a full
scan necessary. Before deployment or publication, use strict `make dependency-scan`.

### Dockerfile frontend

The service, MinIO, and PostgreSQL Dockerfiles use the same specified
`docker/dockerfile` frontend version and manifest digest.
Update their three first-line directives and the examined reference in
`release/dependency-policy.json` together.

Verify the digest with Docker verified-publisher registry metadata.
Examine the necessary BuildKit version and release notes.
Then do the offline gate and make each affected target again.
The build engine stays a manually examined tool boundary.

### PostgreSQL or Redis

For PostgreSQL, update these items together:

- The specified official base in `docker/postgres.Dockerfile`
- Its provenance labels
- `release/dependency-policy.json`
- Each local/recovery Compose image expression
- The digest-pinned VPS lock example
- The runtime gate
- `THIRD_PARTY_NOTICES.md`.

Redis stays a direct external image. Update its Compose pins and recovery
assertions together. Before a usual pull-request merge, do the service and
G8 recovery gates. Examine a report-only scan if available.
Vulnerability decisions and a full scan are not merge requirements.
Before deployment or publication, use strict `make dependency-scan`.

A PostgreSQL major release is not a simple image update.
Make a separate backup, migration, rollback, and existing-volume test plan.
Do the same tests for a base OS or runtime UID change, even without a
major-version change. Examples include Debian-to-Alpine and gosu removal.

If an existing `postgres-data` volume is not compatible, `make service-up` stops.
Operators must use the documented dump/restore procedure in
[Troubleshooting](troubleshooting.md#postgresql-image-upgrade-and-existing-volumes).
Do not attach the existing data volume to the new image.
For Redis, examine the persistence format, UID, configuration, and documented
empty-queue reconstruction. PostgreSQL stays authoritative.

### Caddy

The upstream Caddy tag and digest in `tests/deployment/g8_caddy_gate.py`
are build inputs. They are not the release image.
`docker/caddy.Dockerfile` makes a custom Caddy binary and copies it into
that specified runtime base.

The dependency scan makes and scans the resulting image.
`make g8-caddy` does checks of the upstream base identity and custom binary.
It validates the Caddyfile with the custom image.

The recipe verifies and vendors the reviewed upstream Go module graph.
Caddy 2.11.7 includes the two CEL `NewCall` argument-slice fixes.
It uses `cel.dev/cel-go` 0.32.0.
The recipe checks both fixed call sites and the new CEL import path.
It rejects the old call sites and import path without changing the source.

The earlier module overrides and CEL source patch are no longer necessary.
The recipe checks specified module versions and compiles only the verified vendor tree.

The [Caddy 2.11.6 release notes](https://github.com/caddyserver/caddy/releases/tag/v2.11.6)
list changes from 2.11.4 that also apply to 2.11.7.
The default request-header limit is 16 KiB.
Idle request reads and response writes have a one-minute timeout.
Header names with dots are dropped unless explicitly permitted.

The [Caddy 2.11.7 release notes](https://github.com/caddyserver/caddy/releases/tag/v2.11.7)
describe the related HTTP/2 and streaming-timeout corrections.
Before deployment, test representative uploads, headers, and streaming responses.
The pinned Go 1.26.8 toolchain meets the upstream Go 1.26 minimum.

Update the source, Go modules, build recipe, runtime base, notice, and the two
checks together. The build stage records the binary SHA-256.
The final image and G8 gate compare the installed binary with that record.
Thus, version text alone cannot hide a missing binary copy.

`HBCB_CADDY_IMAGE` in `deploy/vps/release.lock.env.example` is a placeholder
for a future published digest of the custom image.
Do not use it as a deployment reference. The project stays local-only.
Do not replace the placeholder with the official Caddy digest.

Do not deploy the VPS stack before the custom image has an examined,
published digest. Strict `make dependency-scan` must pass on the same release
commit. A blocking finding must have a documented disposition with evidence.
A source rebuild does not give approval for a risk decision.

### Manually reviewed inputs

`manual_review` in `release/dependency-policy.json` lists these inputs:

- Blender archives and corresponding source
- The source-built MinIO/Go/mc fixture
- The BuildKit engine
- GitHub Action commits and hosted runners
- OSV-Scanner release assets
- The ranged Python build backend.

Version services cannot safely select compatibility, licensing, provenance,
or migration policy for these inputs.

The MinIO recipe label is the SHA-256 from `scripts/minio-recipe-id`.
It binds the Dockerfile and the two MinIO and `mc` `go.mod`/`go.sum` overlays.
Service builds, release validation, and dependency scans must use that helper.

A dependency scan calculates the value one time. It gives that value to the
build and verifies it again in the archived config.
A Dockerfile-only hash can let changed module graphs use stale scan/release identity.

## Vulnerability decision policy

`release/vulnerability-policy.json` is separate from the dependency inventory.
Only the strict/default scan loads and reconciles this policy.
Before deployment or publication, UNRATED, HIGH, and CRITICAL findings stop
the gate by default. The policy cannot decrease that threshold.

LOW, MODERATE, and NONE stay counted in each target's summary and detailed
OSV report. The checked-in policy has immutable `"default_action": "deny"`.
Do not add dispositions or extend their expiry only to get usual pull-request
or scheduled scans to pass. Report-only scans ignore checked-in decisions and expiry dates.

OSV can publish one issue under ecosystem, CVE, GHSA, and language IDs.
The evaluator uses OSV-Scanner package groups and validates their coverage.
It normalizes each ID and alias into one sorted advisory family.
A disposition applies only to one specified tuple with these components:

- The scan target, for example `osv-image-minio`
- The target `image_identity.policy_digest` for each image scan.
  Source dispositions use JSON `null`.
- The ecosystem, package name, installed version, and package source revision.
  Use explicit JSON `null` if the report has no source revision.
- The full canonical advisory family
- The scanner score, or `null` if unrated, matching-ecosystem fixed-version
  union, and normalized UNRATED, HIGH, or CRITICAL severity.

The fixed-version union includes ordinary OSV ranges and
`ecosystem_specific.custom_ranges`. Release-named or pseudo-version projects,
for example MinIO, use these custom ranges. Without a custom limit, two
different advisory states could look the same.

Severity precedence is conservative. Usually, the evaluator takes the
maximum of the OSV-Scanner group CVSS score, database severity labels,
and ecosystem urgency labels.

There is one specified vendor override. An official `DEBIAN-*` advisory must
have an affected entry for the same reported `Debian:<release>` package.
If that entry says `urgency: unimportant`, the evaluator reports LOW.
Debian uses this state when its security team decides that a security update
is not necessary for that distribution package.

The override does not apply to missing or conflicting metadata, general
advisories, other ecosystems, or these Debian states:

- `not yet assigned`
- `low`
- `none`
- `not affected`.

These cases use maximum severity. A distribution backport or
not-affected decision must have a related disposition with evidence.

The policy has no target globs, package prefixes, advisory prefixes,
severity-wide exceptions, or permanent exceptions.
Each disposition must include these items:

- A decision: `accepted-risk`, `mitigated`, or `not-affected`
- A substantive rationale
- Review and expiry dates
- A minimum of one repository-relative evidence file and its SHA-256.

Evidence cannot point to the policy itself. The review date cannot be in the
future. An entry becomes invalid on its expiry date.
The maximum review period is 90 days.

The next example shows the format. Do not copy its example hashes or
identifiers into a release decision:

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

Before you add the object to `dispositions`, examine a new scan from the
same candidate revision. Changes to aliases, severity, package, version,
source revision, target image identity, evidence digest, or dates can invalidate
the disposition. It then no longer matches, or makes the scan incomplete.

An active disposition without a related finding on an evaluated target is
itself a policy finding. Thus, resolved exceptions cannot stay unnoticed.
Do not make dispositions from an older artifact. A rebuilt image can have
a different installed-package inventory with unchanged Dockerfile text.

The target identity does not replace the evidence file.
It is a canonical digest of stable image provenance in `scan-summary.json`.
For project-built images, it includes these items:

- The normalized runtime-layer content digest
- The normalized runtime-config digest
- The full label digest
- `linux/amd64`
- The verified OCI source revision.

The source-built MinIO fixture also includes the composite `io.hbcb.recipe-id`.
Raw image config/descriptor digests and private archive hashes stay visible
runtime evidence. They are outside the policy digest.
BuildKit timestamps and Docker archive layout are not runtime identities.

A change to any file bytes, path, type, mode, ownership, or link/device
metadata changes the image identity. So do changes to non-time PAX metadata,
runtime config, labels, revision, or the MinIO recipe.

For API, worker, MinIO, PostgreSQL, and Caddy, the combined policy identity also
includes the specified disposition-context digest from the Image scan controls section.
A changed runtime control gives a different combined identity, even with unchanged
image bytes.

The raw scanner exit stays recorded. OSV-Scanner exit `1` means only that it
found a minimum of one advisory family. Report-only mode records these
families and succeeds when the full scan finishes.

Strict/default mode evaluates each target. It can pass with findings only
if each UNRATED/HIGH/CRITICAL family has a related active disposition.
All remaining families must have lower severity.

Scanner/report disagreement or a malformed inner report makes either mode
incomplete. In strict/default mode, missing policy, an incorrect evidence
digest, or an expired disposition also makes the scan incomplete.
Do not interpret an incomplete scan as clean.

## Exit meanings

| Exit | Meaning |
|---:|---|
| `0` | Report-only: The scanner completed the scan, possibly with vulnerabilities. Strict/default: The scanner completed the scan without blocking findings. Examine the reports in either mode. |
| `1` | Strict/default: A consistency/maintenance finding or UNRATED/HIGH/CRITICAL family without a disposition makes inspection necessary. |
| `2` | An input, network request, build, scanner, or report failure made the audit incomplete. In strict/default mode, an invalid disposition also gives this result. Do not interpret it as clean. |

Detailed OSV-Scanner reports stay authoritative for package findings.
The repository summary records size-limited per-severity counts.
Strict/default mode also records policy-decision counts.
The rendered GitHub summary does not include untrusted upstream vulnerability descriptions.

<a id="adding-another-dependency-surface"></a>
## Add a different dependency input

Update `release/dependency-policy.json` and extend `scripts/dependency-audit`.
Add a mutation test under `tests/release/` in the same pull request.
Before new network access, credentials, parsing, execution, or CI permissions,
update the threat model. Do this before you enable the new input.

Refer to these sources:

- [OSV-Scanner supported inputs](https://google.github.io/osv-scanner/supported-languages-and-lockfiles/)
- [Container image scanning](https://google.github.io/osv-scanner/usage/scan-image)
- [GitHub Actions workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Dependabot security-update settings](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-security-updates).
