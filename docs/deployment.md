# VPS deployment and operations

This runbook describes a production-oriented v0.1 reference topology: one
`linux/amd64` Linux VPS running the reviewed Docker Compose overlay, with one
API process, one concurrency-one worker, local PostgreSQL and Redis, Caddy at
the public edge, and an external versioned S3-compatible artifact service. It
is designed for a single operator and one deployment namespace. It is not a
multi-tenant platform, high-availability design, or managed-cloud template.

## Availability

The repository currently contains source, container build definitions, local
release tooling, and the deployment reference. It does **not** publish the
three required application images, a populated digest release lock, a signed
source release, or a live service. Consequently, these instructions are not yet a copy-paste
path to a public production deployment.

Do not substitute mutable images, a locally edited all-zero lock example, or a
Git clone of `main` for those missing release inputs. Until a publisher makes
the complete matching set available, use the
[locally verifiable deployment package](#locally-verifiable-deployment-package)
only. When a release is published, its notes must identify the exact verified
source package, image digests, release lock, checksum/signature process, and
corresponding-source materials before the live steps below become actionable.

Running `up`, changing DNS or firewall rules, issuing certificates, pulling
private images, operating storage, and running an external smoke build are
operator actions against explicitly authorized infrastructure. Local G8
validation does not perform any of those actions.

## Supported topology

```text
Internet
   |
   | TCP 80/443; optional UDP 443
   v
Caddy (only published host ports)
   |
   | api-ingress: internal Docker network
   v
API -------------------------+
   |                          |
   | db / queue               | storage-private: external, Internal=true
   v                          v
PostgreSQL     Redis       S3 gateway ---- private/VPN/allowlisted path ---- S3
                              ^                                      |
                              |                                      |
one worker -------------------+                          public TLS endpoint
                                                                  for signed URLs
```

The production services are:

- `caddy`: TLS termination and reverse proxy. It alone publishes host ports.
- `api`: bearer-authenticated asynchronous build API. It cannot reach the
  public edge directly.
- `worker`: one long-running, concurrency-one supervisor. It launches one
  fresh Blender child per attempt.
- `postgres`: authoritative build, attempt, event, artifact, outbox, and
  maintenance state.
- `redis`: at-least-once wake-up and short-lived coordination. It is not the
  authoritative job database.
- `database-init`: one-shot role and forward-migration initializer.
- `maintenance`: explicit-only retention, exact-version artifact deletion,
  backup inventory/export, restore, and Redis queue-rebuild process. It is not
  started with the normal stack.

The bundled MinIO services are local compatibility fixtures. They are behind
local-only profiles and are not a supported VPS object store. Do not enable
`local-fixture` or `local-test` on a live deployment.

The worker is deliberately fixed at one replica. Do not use `--scale worker`,
edit `deploy.replicas`, or run a second VPS against the same namespace. Scaling
and multi-host coordination are post-v0.1 work.

API, worker, initializer, and maintenance containers run as UID/GID
`65532:65532` with a read-only root, every capability dropped, and
`no-new-privileges`. Caddy runs as `1000:1000` with a read-only root and
`no-new-privileges`; it drops all capabilities and retains only
`NET_BIND_SERVICE`, which the official Caddy binary's file capability requires
at exec time. The worker has no host mount, Docker socket, device, SSH agent,
or edge network; only its bounded tmpfs is writable. The supervisor can reach
PostgreSQL, Redis, and the private S3 gateway, but it starts Blender with a
scrubbed environment that contains no database, Redis, storage, or API
credential and with all nonstandard inherited descriptors closed. At startup
the supervisor must mark itself non-dumpable—the Linux setting that prevents
another process from inspecting it—and disable core dumps. The launcher
verifies and reasserts that state before every child; startup fails closed if
the kernel control is unavailable. Together with the dropped `CAP_SYS_PTRACE`,
this prevents a same-UID Blender descendant from reading the supervisor's
procfs environment or memory.

Maintainers can exercise that boundary directly with
`make worker-boundary-check`. The target builds the production worker stage,
runs it as UID/GID `65532:65532` with no network or capabilities, and uses only
a fixed synthetic canary—never `.env` credentials. It also confirms that
nested-process cancellation still works after the process protection is set.

## Prerequisites

Bring all of the following before a live preflight:

- A dedicated `linux/amd64` VPS with a maintained Docker Engine and
  Docker Compose 2.24.4 or newer. The minimum is required for the `!reset` and
  `!override` tags used by the overlay; see Docker's
  [Compose merge reference](https://docs.docker.com/reference/compose-file/merge/).
  The host must enforce its CPU, memory, PID, disk, and network controls.
- Python 3.11 or newer as `python3`; the fail-closed `scripts/vps` operator
  wrapper checks this before parsing configuration or contacting Docker. Verify
  it with `python3 --version` before installing the release tree.
- Capacity for the configured limits plus host overhead. The planning baseline
  is 8 vCPU and 32 GiB RAM for one ordinary worker.
- A reviewed source release installed in a root-owned, non-writable release
  directory, plus the publisher-supplied digest release lock for that exact
  source release.
- A DNS hostname for the API, an ACME contact email, and inbound TCP 80 and 443.
  UDP 443 is optional for HTTP/3. PostgreSQL, Redis, and the API container port
  must never be opened on the host.
- A separately maintained S3-compatible service with bucket versioning
  enabled, exact-version GET/HEAD/DELETE behavior, returned version IDs on
  writes, and presigned exact-version GET support.
- A separately operated S3 gateway attached to an external Docker network
  whose `Internal` property is `true`. That gateway is the only storage path
  for API and worker containers. It must forward only the required
  S3-compatible operations over a private, VPN, or destination-allowlisted
  path; it must not provide general Internet egress.
- Three distinct S3 identities: API read/sign, worker read/write-without-delete,
  and maintenance read/copy/delete-exact-version. None may administer the
  bucket, users, or policies.
- An encrypted off-host backup destination. VPS-local backup files alone do
  not protect against host loss.
- Correct host time synchronization. ACME and short-lived signed URLs depend
  on accurate time.

Use a host firewall and the Docker `DOCKER-USER` path, or an equivalent control,
so Docker cannot bypass the intended ingress and egress policy. SSH should be
restricted to the operator's administration network. The reference overlay
does not configure the host firewall, DNS, the S3 gateway, or provider IAM.

## Filesystem layout and permissions

The following is the reference layout. Substitute paths only by changing
`vps.env` consistently.

| Path | Owner | Mode | Purpose |
|---|---:|---:|---|
| `/opt/hbcb/release` | `root:root` | `0755` | Reviewed immutable source release |
| `/opt/hbcb/release/scripts/vps` | `root:root` | `0555` | Fail-closed operator wrapper |
| `/opt/hbcb/release/scripts/operator-smoke` | `root:root` | `0555` | Conditional external smoke client |
| `/etc/hbcb` | `root:root` | `0700` | Operator configuration parent |
| `/etc/hbcb/vps.env` | `root:root` | `0644` | Exact non-secret deployment configuration |
| `/etc/hbcb/release.lock.env` | `root:root` | `0644` | Exact non-secret digest lock |
| `/etc/hbcb/secrets` | `root:root` | `0700` | Role-separated secret files |
| `/etc/hbcb/secrets/*.env` | `root:root` | `0600` | One regular, non-symlink file per role |
| `/var/lib/hbcb` | `root:root` | `0755` | Caddy state parent |
| `/var/lib/hbcb/operator.lock` | `root:root` | `0600` | Persistent fail-fast operator mutex; created by the wrapper |
| `/var/lib/hbcb/upgrade-handoff.json` | `root:root` | `0600` | Durable quiesced-upgrade state; created and consumed by the wrapper |
| `/var/lib/hbcb/caddy-data` | UID/GID `1000:1000` | `0700` | Certificates and Caddy data |
| `/var/lib/hbcb/caddy-config` | UID/GID `1000:1000` | `0700` | Caddy runtime state |
| `/var/backups/hbcb` | `root:root` | `0700` | Protected staging for backup bundles |

Create the parent directories before installing a release:

```sh
sudo install -d -o root -g root -m 0755 /opt/hbcb
sudo install -d -o root -g root -m 0755 /opt/hbcb/release
sudo install -d -o root -g root -m 0700 /etc/hbcb /etc/hbcb/secrets
sudo install -d -o root -g root -m 0755 /var/lib/hbcb
sudo install -d -o 1000 -g 1000 -m 0700 \
  /var/lib/hbcb/caddy-data /var/lib/hbcb/caddy-config
sudo install -d -o root -g root -m 0700 /var/backups/hbcb
```

For an initial installation, `/opt/hbcb/release` must be empty. First verify
the publisher's exact source package using the checksum/signature procedure in
that release's notes. Then copy the already extracted, verified tree into the
root-owned directory. The path below is intentionally a placeholder;
no such published source package exists yet:

```sh
test -f /absolute/path/to/verified-source/VERSION
test -x /absolute/path/to/verified-source/scripts/vps
sudo cp -a /absolute/path/to/verified-source/. /opt/hbcb/release/
sudo chown -R root:root /opt/hbcb/release
sudo chmod -R go-w /opt/hbcb/release
sudo chmod 0555 /opt/hbcb/release/scripts/vps
sudo chmod 0555 /opt/hbcb/release/scripts/operator-smoke
```

Do not copy a working tree with uncommitted changes, clone a moving branch on
the VPS, or overlay new source on an existing release directory. Upgrades use a
separately staged exact release and the forward-only handoff procedure.

Next install the non-secret configuration template from the installed release
and the publisher-supplied lock for that exact release as regular files, not
symlinks:

```sh
cd /opt/hbcb/release
sudo install -o root -g root -m 0644 deploy/vps/vps.env.example \
  /etc/hbcb/vps.env
sudo install -o root -g root -m 0644 \
  /absolute/path/to/publisher-supplied/release.lock.env \
  /etc/hbcb/release.lock.env
```

Edit `/etc/hbcb/vps.env` for the authorized host. Do not install
`deploy/vps/release.lock.env.example`: its zero digests are deliberately
invalid and preflight rejects them. Populate the protected role files exactly
as described in [VPS secret files](../deploy/vps/SECRETS.md).

When it runs as root, the wrapper rejects a release tree, VPS configuration,
release lock, secrets directory or file, state parent, backup root, or backup
bundle whose numeric owner does not match the contract. It also rejects
symlinks and group/world-writable components in the root trust path. Secret
directories must be exactly `0700`, secret files exactly `0600`, and Caddy
state directories exactly `0700` and owned by UID 1000. Configuration values
use plain `NAME=value` syntax. Do not use quotes, interpolation, backticks,
surrounding whitespace, duplicate keys, or multiline values.

See [VPS secret files](../deploy/vps/SECRETS.md) for the exact role files and
named values that must match across them. Use independent URL-safe random
values; 64 lowercase hexadecimal characters are a safe representation for
database and Redis passwords. `HBCB_API_TOKEN` and
`HBCB_IDEMPOTENCY_SECRET` must each be exactly 64 lowercase hexadecimal
characters and must be different from every other secret.

## External storage and network contract

Create the named network outside this Compose project with the Docker
`Internal` property set to `true`, then attach the separately maintained S3
gateway to it. For the example name:

```sh
sudo docker network create --driver bridge --internal hbcb-storage-private
sudo docker network inspect \
  --format '{{.Name}} internal={{.Internal}}' hbcb-storage-private
```

Attach only the storage gateway and HBCB services to this network. The gateway
needs a second, separately controlled route to the storage service, but the
HBCB API and worker must not receive that route or any default/general egress.
Live preflight checks that the named network exists and reports
`Internal=true`; it cannot prove the gateway's upstream ACL, TLS policy, or IAM.
Those remain operator controls.

The storage settings have distinct purposes:

- `HBCB_STORAGE_INTERNAL_ENDPOINT` is the private TLS endpoint used for bucket
  checks, uploads, reads, and verification. In the reference configuration it
  is `s3-gateway:443`.
- `HBCB_STORAGE_PUBLIC_ENDPOINT` is the public TLS hostname embedded in signed
  download URLs. It must be reachable by clients, not by the worker.
- Both `*_SECURE` values must be `true` on VPS.
- `HBCB_STORAGE_REGION` must be the actual bucket region. It is pinned so URL
  signing does not need a public-endpoint region lookup.
- Both endpoints must identify the same logical versioned bucket and accept
  the same API signing identity. They must be different hostnames.

Endpoint values are `host` or `host:port`, without a scheme, path, credentials,
or query string. The internal gateway must present a certificate trusted by
the release images and valid for the configured internal hostname. Do not set
the public endpoint as the worker's internal endpoint to make readiness pass.

Enable versioning before first startup and verify it independently with the
provider's tooling. Every successful upload must return a nonempty version ID.
Do not configure a generic lifecycle expiry on the live namespace: it can
delete an exact version still referenced by PostgreSQL. Provider cleanup of
incomplete multipart uploads is acceptable.

The maintenance identity inventories object versions only under the canonical
`<namespace>/v1/builds/` prefix. On a VPS, preview old versions which are absent
from PostgreSQL through the operator wrapper so the inventory participates in
the host mutex and command deadline:

```sh
sudo ./scripts/vps orphan-discovery-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --limit 100 \
  --scan-limit 100000
```

The preview prints bounded counts and a scope-bound token such as
`discover-orphans:100:100000`. Only after reviewing those counts, queue the
same bounded scope by supplying both acknowledgements:

```sh
sudo ./scripts/vps orphan-discovery-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --limit 100 \
  --scan-limit 100000 \
  --confirm \
  --confirmation-token discover-orphans:100:100000
```

Changing either bound changes the required token and requires a new preview.
The accepted range is 1–1,000 candidates and 1–100,000 scanned versions.
Apply records exact bucket, key, version ID, digest, byte size, object
timestamp, and discovery origin in PostgreSQL; it does not delete storage. Run
`artifact-deletion-preview` separately, then run `artifact-deletion-apply`
with `--confirm` to claim and delete exact versions. The deletion queue applies
the configured grace period again from discovery time, so a newly queued
candidate normally will not appear in deletion preview immediately. This
second review window is intentional. Both phases are bounded. Fresh versions,
versions referenced by `hbcb.artifacts`, and versions owned by active builds
are never selected. A delete marker, unversioned object, noncanonical key,
missing digest/version/timestamp, changing listing, duplicate, incomplete
listing, or exceeded scan ceiling stops the whole discovery without queuing
partial results.

Redis contains wake-ups, not authoritative build state. Settled entries are
removed from the main Stream after group acknowledgement, and the dead-letter
Stream keeps at most the newest 10,000 build IDs. The server uses AOF with
`appendfsync everysec`, automatic AOF rewrite, a 384 MiB dataset ceiling, and
`noeviction`; this caps the dataset and reclaims settled AOF history over time
without silently evicting coordination state. Capacity alerts must still cover
the Redis data volume, pending-entry count, and AOF rewrite failures.

## DNS, TLS, and the public edge

Before `up`:

1. Point the API hostname's `A` record, and `AAAA` only when IPv6 is fully
   configured, to the VPS.
2. Confirm public TCP 80 and 443 reach the VPS. UDP 443 is optional.
3. Confirm no host mapping exposes ports 5432, 6379, 8080, or the storage
   gateway.
4. Set `HBCB_API_DOMAIN` to the hostname only and set a real
   `HBCB_ACME_EMAIL`.
5. Verify the separate artifact hostname in
   `HBCB_STORAGE_PUBLIC_ENDPOINT` resolves to the storage service.

Caddy obtains and renews certificates and persists ACME state in the two
UID-1000 state directories. Its admin API and dynamic-config persistence are
disabled. The public edge permits `/healthz` and `/v1/*`; every other path,
including `/readyz`, returns `404`. Readiness is an internal Compose/service
health concern because it reveals dependency state.

The API bearer token is still required on build and artifact routes. TLS does
not replace API authentication. Do not place tokens in URLs.

## Release lock

`release.lock.env` is an immutable bill of materials for one release. Obtain it
with the corresponding reviewed source release. Do not assemble a lock by
mixing images from different tags.

The lock pins:

- API and worker images by OCI digest;
- Caddy by OCI digest;
- the builder provenance reference and image configuration ID;
- the frozen G4 source revision;
- the exact migration-catalog SHA-256; and
- a semantic release version.

All-zero digests, mutable tags, a source-revision mismatch, a migration digest
that does not match the installed source tree, extra keys, and missing keys are
rejected. The builder image and worker supervisor must come from the same
reviewed release lineage. Keep every deployed lock with backups and upgrade
records; the lock is required for exact recovery and rollback.

## Safe lifecycle commands

Run the wrapper from the installed release tree and pass absolute configuration
paths. It validates exact keys, file shape and permissions, digest pins,
migration catalog, the merged Compose model, and, unless offline, the private
storage network. Its errors do not print secret values.

First validate without inspecting live infrastructure:

```sh
cd /opt/hbcb/release
sudo ./scripts/vps preflight \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --offline
```

After the internal storage network and gateway exist, run live preflight:

```sh
sudo ./scripts/vps preflight \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

If this stops with `private storage network is unavailable`, create the
configured Docker-internal network and attach the private S3 gateway described
in [External storage and network contract](#external-storage-and-network-contract), then rerun live
preflight. The wrapper deliberately omits the configured network name and
captured Docker output from this error.

`config` performs the same safe, quiet validation and prints only a pass/fail
marker. Do not run raw `docker compose config`: resolved service configuration
can contain credentials from role env files.

Root execution does not trust the caller's Docker or Compose control
environment. The wrapper rejects inherited `DOCKER_*`, `COMPOSE_*`,
`BUILDX_*`, and `BUILDKIT_*` variables, uses a bounded system `PATH`, and fixes
the Compose project name. By default it accepts Docker only at a reviewed
root-owned system path. If Docker Compose is installed elsewhere, set
`HBCB_COMPOSE_BIN` to its absolute executable path; every path component and
the executable must be root-owned and not group/world writable. Put any
private-registry authentication in root's protected Docker configuration, not
in an operator shell variable or repository file.

Start the reviewed images:

```sh
sudo ./scripts/vps up \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

`up` pulls the digest-pinned images, starts PostgreSQL and Redis, and runs the
one-shot database initializer. Before it can start the API, worker, or Caddy,
the wrapper proves that namespace-bearing database metadata is either empty or
contains exactly `HBCB_DEPLOYMENT_NAMESPACE`; a second or foreign namespace
fails closed. It then starts exactly one API, one worker, and Caddy, waits for
health checks, and fails nonzero if startup is incomplete.

Stop while preserving named volumes, Caddy state, backups, and external
artifacts:

```sh
sudo ./scripts/vps down \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

Never add `--volumes`, run `docker volume prune`, or delete the state/backup
directories as a troubleshooting shortcut. A normal `down` is not a backup.
`down` deliberately skips the live storage-network inspection so an operator
can stop safely during a gateway outage; it is the only mutating action that
accepts `--offline`. Other mutating wrapper actions reject that flag.

Every action other than `preflight` and `config` requires root and holds the
same nonblocking host mutex at `/var/lib/hbcb/operator.lock` from before its
first operational command through completion. If another wrapper action is
running, the new action fails immediately instead of racing it. The lock file
is a persistent root-owned mode-`0600` inode inside the validated state parent;
do not delete, replace, relax, or manually lock it. Scheduled retention,
artifact deletion, queue reconstruction, backups, upgrades, and lifecycle
commands must all use this wrapper so they participate in the same exclusion
boundary.

Every Docker/Compose child command has a fail-closed wall-clock deadline. The
default is 900 seconds for lifecycle and health commands and 14,400 seconds for
image pulls, database dumps/restores, and object transfers. An authorized
operator may select a value from 30 through 86,400 seconds with
`--command-timeout-seconds SECONDS` or `--transfer-timeout-seconds SECONDS`.
The wrapper streams large backup/restore payloads directly to their protected
file or container input, bounds all captured stdout/stderr, and never includes
captured command output in its error messages. At a deadline or output-limit
failure it terminates the command's entire process group, waits a short grace,
then kills any survivors before cleanup proceeds. The host mutex remains held
through that teardown and recovery path. `Ctrl-C`/`SIGINT`, `SIGTERM`, and `SIGHUP` use the same
child-tree teardown before the wrapper unwinds and releases the mutex; a
terminated operation still fails closed and may require the documented
recovery or retry procedure.

## Logs and observability

All production containers use Docker's `json-file` driver with `max-size=10m`
and `max-file=5`, limiting each service to approximately 50 MiB of retained
container logs. The API disables Uvicorn access logging and Caddy has no access
log directive. Normal logs are bounded lifecycle metadata, not HTTP request
records.

Do not enable access or debug logging on a public deployment without a separate
privacy and redaction review. Authorization headers, request bodies, prompts,
object credentials, signed URLs, and artifact bytes must never be logged.
Inspect only a bounded tail during diagnosis; do not publish raw logs in an
issue without reviewing them.

## Retention

Retention is database-aware and defaults to preview. The reference policy is:

| Build status | Default age | Eligibility |
|---|---:|---|
| `succeeded` | 30 days | Terminal builds only, measured from completion |
| `failed` | 7 days | Terminal builds only, measured from completion |
| `canceled` | 7 days | Terminal builds only, measured from completion |
| `needs_review` | 7 days | Terminal builds only, measured from completion |
| Any nonterminal status | Never by age policy | Must first reach a terminal state |
| Queued exact artifact version | 7-day grace | Measured from durable deletion-queue insertion |

Preview with the deployed release and review counts before deletion:

```sh
sudo ./scripts/vps retention-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

Apply only after reviewing the preview and confirming that no backup, restore,
or upgrade is active:

```sh
sudo ./scripts/vps retention-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

Retention apply first copies every affected artifact's bucket, key, version ID,
SHA-256, and byte count into the durable deletion queue, then removes the
terminal build row transactionally. It does not immediately remove bucket
bytes. After the orphan grace period, the separate artifact-deletion operation
previews or processes that queue and deletes only each recorded exact version,
never an unversioned key. A failed exact-version deletion remains durable work
and is safe to retry.

Preview the second stage after the configured grace period:

```sh
sudo ./scripts/vps artifact-deletion-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

Apply it only after reviewing the preview:

```sh
sudo ./scripts/vps artifact-deletion-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

Do not schedule either apply stage until at least one manual preview and apply
cycle has been reviewed. Never substitute a provider-wide bucket lifecycle
rule for this process.

## Quiesced backup

A coherent application backup contains four coordinated pieces:

1. A transaction-consistent PostgreSQL dump.
2. A catalog and protected copy of every exact S3 object version referenced by
   the dump, including object key, source version ID, SHA-256, and byte count.
3. The release lock, non-secret VPS configuration, backup metadata, and
   checksums. Retain the matching reviewed source release separately; it is
   deliberately not copied into the bundle.
4. A separate encrypted backup of role secrets. Secrets are never placed in
   the application-data bundle.

Redis is deliberately not authoritative and is not restored from its AOF.
Caddy state may be copied separately while Caddy is stopped; losing it does
not lose builds, but can require ACME reissuance and encounter provider rate
limits.

Use the release's backup action only on an authorized live target. It requires
a root operator and explicit acknowledgement because ingress is interrupted:

```sh
sudo ./scripts/vps backup \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

The worker drain timeout defaults to 3,600 seconds. To choose another value in
the enforced 30-to-86,400-second range, add
`--drain-timeout-seconds SECONDS`. This is one total drain deadline, not a
per-poll timeout: every quiescence probe receives only the remaining time.
Timing out during an ordinary backup removes the unpublished partial bundle
and attempts to reconverge the original live service set. Timing out after an
upgrade handoff has begun keeps ingress stopped and the database resealed
read-only; the durable handoff remains for exact-target retry or documented
empty-target rollback.

The wrapper performs this sequence:

1. Pass live preflight and verify the installed release lock.
2. Stop Caddy and the API so no new submission can enter, but leave the single
   worker running to drain existing work.
3. Poll the backup inventory until no build remains in `validating`, `queued`,
   `running`, `geometry_qa`, or `rendering`; then stop the worker and repeat the
   quiescence check.
4. Immediately before and after the dump, prove that the distinct namespace
   set across `builds`, `idempotency_keys`, `artifact_deletion_queue`, and
   `artifact_restore_remaps` is exactly the configured namespace (or empty).
   Then create a custom-format, data-only dump of the `hbcb` schema. Dependent
   build-attempt, event, artifact, and outbox rows are constrained through
   namespace-owned parent rows. Schema migrations and artifact deletion
   queue/attempt data are excluded because the matching release recreates
   schema and stale exact-version deletion work must not be replayed on a
   restored namespace.
5. Export every exact S3 version referenced by the same quiesced database
   state, verifying SHA-256 and byte count, and write `objects/inventory.json`.
6. Copy `release.lock.env` and `vps.env`, record hashes, counts, release,
   migration catalog, namespace, bucket, and creation time in
   `backup-manifest.json`, then atomically publish a direct-child bundle below
   `HBCB_BACKUP_ROOT`.
7. For an ordinary backup, restart the unchanged PostgreSQL, Redis,
   initializer, API, worker, and Caddy whether the backup succeeds or fails. A
   restart failure is itself fatal.

On success, stdout ends with `VPS_BACKUP: PASS bundle=/absolute/path`. Record
that exact path. A valid bundle contains only `backup-manifest.json`,
`database.dump`, `objects/`, `release.lock.env`, and `vps.env`; directories are
mode `0700` and files are mode `0600`. The bundle directory and its four
top-level files are owned by UID 0. The `objects/` directory and every directory
and file below it are owned by numeric UID 65532 so the unprivileged maintenance
container can read a direct, read-only bind mount without traversing the
root-only bundle parent. It does not contain the source tree, secret files,
Redis AOF, or Caddy state.

Copy the bundle and separately encrypted role-secret backup off the VPS with a
root-operated archive or transfer that preserves numeric owners and modes (for
example, an archive or `rsync` workflow configured for numeric IDs), and test
restoration periodically. An ordinary recursive copy that collapses every
entry to root or to the receiving account is not a restorable bundle and is
rejected. When returning a bundle to `HBCB_BACKUP_ROOT`, restore the recorded
numeric ownership and modes before running `preflight` or `restore`; do not
make the root-only bundle directory traversable as a workaround.

For a pre-upgrade handoff, add `--leave-ingress-down` to the backup command.
On success, the wrapper leaves Caddy, API, and worker stopped, switches the
database to default read-only, binds its system identifier and database OID to
the exact bundle and source-lock hash, and atomically writes
`/var/lib/hbcb/upgrade-handoff.json`. Success reports
`handoff=ready ingress=stopped`. While that marker exists, unrelated lifecycle
and maintenance actions fail closed; follow the upgrade or handoff-abort
procedure below. Do not edit or delete the marker.

Object-store versioning is not, by itself, a backup. A provider failure,
credential compromise, or account deletion can remove all versions. Back up
the exact referenced bytes to a separate failure domain. Do not run retention
while a backup is being assembled.

## Empty-target restore

Restore is fail-closed and ingress-stopped; `--offline` is not valid for this
mutating action. Never restore over a serving deployment. The target must have
a fresh PostgreSQL database, empty Redis database, and no object versions under
the configured deployment namespace. Use the same namespace, bucket, and
canonical object keys recorded in the backup.

First install the exact reviewed source release separately retained for the
backup, and install the bundle's archived `release.lock.env` as the current
lock. The wrapper requires the current lock's file hash to match the archived
lock exactly. Restore role secrets from their separate encrypted backup;
preserve `HBCB_IDEMPOTENCY_SECRET` so existing idempotency keys retain their
meaning. Rotate the public API token only as an intentional client migration.

The backup path must be absolute and name one direct child of
`HBCB_BACKUP_ROOT`. After keeping DNS away from the target, run as root with
both acknowledgements:

```sh
sudo ./scripts/vps restore \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --backup /var/backups/hbcb/EXACT-BUNDLE-DIRECTORY \
  --confirm \
  --confirm-empty-target
```

The wrapper validates all bundle hashes and metadata, stops Caddy/API/worker,
starts only PostgreSQL, Redis, and the initializer, and proves that every
application table, Redis database 0, and the target S3 namespace are empty. It
bind-mounts the validated UID-65532-owned `objects/` directory directly and
read-only at `/backup`; it never exposes the root-owned bundle directory to the
maintenance container. It then restores the data-only PostgreSQL dump. For
each artifact it uploads the
verified bytes to the canonical key, captures the newly returned version ID,
verifies SHA-256 and byte count through that exact version, updates the artifact
row, and appends the source-to-restored version mapping to
`artifact_restore_remaps`. Any missing object, hash/size mismatch, unexpected
target data, or incomplete remap fails the operation.

If restore fails after any object upload, treat the target as contaminated and
keep ingress down. Preserve the wrapper's bounded error and sanitized evidence,
then discard and recreate the target PostgreSQL database, Redis database 0, and
the complete configured object namespace. Do not resume at an object index, do
not manually rewrite a version mapping, and do not guess which uploaded
versions are safe to delete: an interrupted request may have committed remotely
without returning its version ID. After proving the replacement target empty,
rerun the entire restore from the same verified bundle. If the target cannot be
made provably empty, create a new empty target instead.

Redis is rebuilt only from build IDs whose authoritative current PostgreSQL
status is `queued`; no source AOF is copied. At-least-once delivery makes a
duplicate wake-up safe. The wrapper then starts PostgreSQL, Redis, initializer,
API, and the single worker, but deliberately leaves Caddy stopped and reports
`VPS_RESTORE: PASS ingress=stopped`.

Verify migrations, internal readiness, an exact-version artifact download,
and a known manifest hash before explicitly starting the public stack with the
normal `up` action or changing DNS. Then run the conditional operator smoke.

Keep the old target and backup read-only until the restored service has passed
verification. A restore test is successful only when exact-version artifact
downloads, manifest hashes, database state, and Redis reconstruction all pass.

## Upgrade and rollback

Migrations are checksum-verified and forward-only. Treat every upgrade as a
state transition, not an image-tag change.

Upgrade procedure:

1. Read the release notes and obtain the complete new source release and its
   lock in a separate versioned directory. While the old release remains the
   live installation, run the new release's offline preflight against that
   exact staged source/lock pair. Do not run its initializer yet.
2. From the still-installed old release and old lock, create the quiesced
   handoff backup and record its printed absolute bundle path:

   ```sh
   sudo ./scripts/vps backup \
     --config /etc/hbcb/vps.env \
     --release-lock /etc/hbcb/release.lock.env \
     --confirm \
     --leave-ingress-down
   ```

   Continue only after success reports `handoff=ready ingress=stopped`. Retain
   the bundle, old source tree, exact old lock, and separately encrypted secret
   backup. The database is now read-only and the durable handoff blocks other
   operator actions.
3. Within four hours, install/switch to the staged new source and lock as one
   controlled release change, then run:

   ```sh
   sudo ./scripts/vps upgrade \
     --config /etc/hbcb/vps.env \
     --release-lock /etc/hbcb/release.lock.env \
     --backup /var/backups/hbcb/EXACT-PRE-UPGRADE-BUNDLE \
     --confirm
   ```

   The bundle path must be absolute and a direct child of the configured backup
   root and must exactly equal the bundle bound into the handoff. The command
   proves the source-lock hash, manifest hash, database system identifier/OID,
   namespace, read-only state, and quiescence. It then atomically changes the
   marker to `upgrading` and binds the exact target-lock hash *before* making
   the database writable. Images are pulled while it is still read-only; only
   then may the initializer run migrations. The wrapper starts and checks the
   private application, starts Caddy, and consumes the handoff only after the
   complete startup succeeds.
4. Verify internal readiness, public `/healthz`, public `/readyz` returning
   `404`, authentication failures without a token, and the conditional operator
   smoke before declaring the upgrade complete.

If the handoff is still `preparing` or `ready` and no migration attempt has
started, reinstall/select the exact old source and old lock and explicitly
abort it:

```sh
sudo ./scripts/vps handoff-abort \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

The old lock hash must exactly match the source lock stored in the marker. Once
the marker is `upgrading`, this abort is permanently forbidden because a
migration may already have committed. A failed or interrupted attempt is
resealed read-only and keeps its target binding: retry `upgrade` only with the
same target source/lock and bound bundle. The other safe recovery is the
empty-target `rollback` below using that bound pre-upgrade bundle and exact old
source/lock. Never delete or edit the marker to force an in-place downgrade.

Rollback is the same exact empty-target recovery contract, not an image-only
reversal. Prepare a provably empty target with the separately retained old
source and the exact old lock archived in the pre-upgrade bundle, then run:

```sh
sudo ./scripts/vps rollback \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --backup /var/backups/hbcb/EXACT-PRE-UPGRADE-BUNDLE \
  --confirm \
  --confirm-empty-target
```

Like `restore`, success reports `ingress=stopped`; verify privately before an
explicit `up`. Merely swapping old image digests back is unsafe after a
migration or newer writer has changed state, and the wrapper does not offer
that shortcut. Never edit migration records or database rows by hand to force
an older image to start.

## Failure recovery

| Symptom | Safe response |
|---|---|
| Preflight rejects a file, digest, or permission | Correct the named input. Do not bypass the wrapper or relax a mode. |
| `private storage network is unavailable` | Create or repair the configured external `Internal=true` network and attach the private S3 gateway before rerunning live preflight. Do not attach API or worker to a default-egress network. |
| API is healthy but not ready internally | Check PostgreSQL, Redis, migration catalog, bucket versioning, private TLS/DNS, and scoped storage IAM. Do not expose `/readyz`. |
| Caddy cannot obtain a certificate | Verify DNS, host time, TCP 80/443, ACME email, and UID-1000 Caddy state ownership. Keep the API unexposed. |
| Worker exits during a build | Preserve PostgreSQL and Redis. Restart the single worker; lease expiry and at-least-once delivery permit recovery. Do not publish scratch output manually. |
| Redis is lost | Start empty Redis, run `queue-rebuild-preview`, then `queue-rebuild-apply --confirm`; it derives wake-ups only from PostgreSQL rows whose current status is `queued`. Do not promote Redis data to authority or restore an AOF. |
| PostgreSQL or artifact storage is lost | Keep ingress down and perform the empty-target restore. Both database metadata and exact artifact bytes are required. |
| An exact artifact version is missing | Mark recovery failed and restore that verified version from backup. Do not silently sign the latest key version. |
| Restore fails during object upload | Keep ingress down. Preserve sanitized evidence, discard and recreate all three target stores, prove them empty, and rerun the whole verified bundle. Never resume or hand-edit version remaps. |
| Handoff is `preparing`, `ready`, or stale before upgrade starts | Keep ingress down. With the exact source release/lock selected, use `handoff-abort --confirm`; do not delete the marker. |
| Upgrade startup fails or is interrupted after the marker becomes `upgrading` | Keep ingress down and preserve the marker. Retry only the exact target lock and bound bundle. Source abort/in-place downgrade is forbidden because migration commit state is not safely knowable. |
| Upgrade cannot be recovered with the exact target | On a provably empty target, run `rollback` with the exact old source/lock and the marker-bound pre-upgrade bundle. Do not downgrade the existing database in place. |
| Host disk is full | Keep ingress down, preserve named volumes, and free only independently verified expendable data. Never prune volumes or active backup files. |

If the normal wrapper cannot run because the release tree or storage network is
damaged, first copy and protect the state, lock, configuration, and logs. Any
manual Compose recovery is an incident action and must preserve volumes; do
not improvise destructive commands from this runbook.

The explicit Redis-loss sequence is:

```sh
sudo ./scripts/vps queue-rebuild-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
sudo ./scripts/vps queue-rebuild-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

## Conditional operator smoke

The external operator smoke is conditional because it creates a real build and
contacts an authorized public deployment. Run it only when an operator supplies
the VPS/domain, valid bearer credential, and explicit authorization. It is not
part of offline package validation and must never run automatically from a fork
or untrusted CI job.

With no target, the script records a successful conditional skip and performs
no network request:

```sh
./scripts/operator-smoke
```

For an authorized live target, place only the raw bearer token in a dedicated
regular, non-symlink file with mode `0600`. Do not pass the token on the command
line and do not pass `api.env`, which contains assignments rather than one raw
token. Allowlist each cross-origin artifact authority explicitly:

```sh
sudo ./scripts/operator-smoke \
  --target https://builder.example.com \
  --token-file /etc/hbcb/operator-smoke.token \
  --allow-artifact-host artifacts.example.com:443 \
  --evidence /var/backups/hbcb/operator-smoke.json
```

The evidence file is sanitized, written atomically, and mode `0600`. A
non-loopback target must use HTTPS with normal certificate verification. The
loopback-only HTTP switch exists for automated tests and is not a VPS option.

The smoke must:

- require `https://` and normal certificate verification;
- confirm `/healthz` succeeds and public `/readyz` returns `404`;
- confirm an unauthenticated build request is rejected;
- submit the bundled request with an idempotency key and receive `202`;
- replay the same key/request and reject a same-key/different-request conflict;
- poll by build ID to a terminal state without holding the submit request open;
- download every exact-version artifact through the public signed endpoint;
- verify the manifest, artifact hashes, and expected artifact set; and
- redact the bearer token and signed URLs from stdout, stderr, and logs.

A smoke-created build remains normal retained data. Record its build ID and let
the configured retention policy remove it; do not delete unversioned object
keys manually.

## Locally verifiable deployment package

These checks validate the package without contacting a cloud provider or live
VPS:

```sh
python3 -m unittest \
  tests.deployment.test_vps \
  tests.deployment.test_maintenance_policy \
  tests.deployment.test_g8_recovery_drill \
  tests.deployment.test_operator_smoke
python3 tests/deployment/g8_static_gate.py
make g8-gate
git diff --check
```

The static gate renders the merged Compose model with temporary fixture values
and checks digest pins, service set, private networks, one worker, hardening,
bounded logs, and local-fixture isolation. `make g8-gate` also exercises the
pinned Caddy image and an isolated disposable recovery drill; depending on the
local image cache, it may pull the digest-pinned public image. None of these
commands deploys to a VPS. They do not prove live DNS, ACME, firewall rules,
gateway egress ACLs, provider IAM, storage compatibility, off-host backup
durability, or a public smoke build. Those checks remain explicitly
conditional on operator infrastructure and authorization.
