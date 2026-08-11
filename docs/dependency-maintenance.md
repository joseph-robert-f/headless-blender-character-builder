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
| `make dependency-scan DEPENDENCY_OUTPUT=build/dependency-audit-review` | Yes | Yes | Download a checksum-pinned OSV-Scanner, build the four project images, scan all three Python locks, and scan the builder, API, worker, MinIO, PostgreSQL, Redis, Debian, and Caddy images. |

The complete scan requires substantial downloads, disk, and build time. Its
output directory must not already exist. Choose a new ignored `build/` path for
each retained local run.

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
4. executes the trusted Dockerfile build steps, but never starts the resulting
   service containers, then scans each final image;
5. retains per-file and aggregate size-capped JSON and Markdown reports for
   seven days; and
6. fails when it finds a known vulnerability, an unmaintained image tag,
   mutable-tag digest drift, inconsistent repository evidence, or an incomplete
   scan.

An informational newer version does not fail the workflow by itself. A failed
run therefore means either an actionable policy/security finding or that the
audit could not complete; inspect `scan-summary.md` first and then the named
JSON report artifact.

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
appropriate TOML file, build the reviewed `linux/amd64` builder, and download
the resolver's selected CPython 3.11 wheels into a new directory. The arguments
below must exactly match the TOML declarations after your edit:

```sh
make image
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
    headless-blender-character-builder:dev \
    -m pip download --disable-pip-version-check --no-cache-dir \
    --only-binary=:all: \
    --dest /wheels "$@"
}

download_wheels "$lock_work/builder-wheels" 'jsonschema==4.26.0'
download_wheels "$lock_work/runtime-wheels" \
  'async-timeout==4.0.3' 'fastapi==0.139.2' 'minio==7.2.20' \
  'psycopg[binary]==3.3.4' 'redis==8.0.1' 'uvicorn==0.51.0'
download_wheels "$lock_work/service-test-wheels" 'httpx2==2.7.0'

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

## Exit meanings

| Exit | Meaning |
|---:|---|
| `0` | The requested audit completed without blocking findings. Informational candidates may still be listed. |
| `1` | A consistency, maintenance, or vulnerability finding needs review. |
| `2` | The audit was incomplete because an input, network request, build, scanner, or report failed. Do not interpret this as clean. |

OSV-Scanner's detailed reports remain authoritative for package findings. The
repository summary intentionally records only bounded target/status metadata;
it does not paste untrusted upstream vulnerability descriptions into the
rendered GitHub summary.

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
