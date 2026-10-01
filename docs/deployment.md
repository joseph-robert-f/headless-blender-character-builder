# VPS deployment and operations

> **Outside the v0.1 support boundary:** This document is a future design and
> validation reference for experienced operators. It is not a v0.1 installation
> procedure. Do not give the Internet access to this system. Do not accept
> hostile or multi-tenant workloads. Successful local recovery tests do not
> give authorization for deployment.

The reference configuration uses one `linux/amd64` Linux VPS and the Docker
Compose overlay. It has one API process, one worker with concurrency one,
local PostgreSQL and Redis, and Caddy at the public edge. Artifacts use an
external, versioned S3-compatible service.

The design is for one operator and one deployment namespace. It is not a
multi-tenant platform, high-availability design, or managed-cloud template.

## Availability

The repository contains source files, container build definitions, local
release tools, and this deployment reference. It does not publish these items:

- The four project-built images: builder, API, worker, and derived PostgreSQL runtime
- A completed digest release lock
- A signed source release
- A live service.

Thus, these instructions cannot at this time give a full public production
deployment. The publication tools record only builder, API, and worker images.
They do not at this time inventory, make an SBOM for, sign, push, or lock the derived
PostgreSQL image.

Do not use mutable images, a changed all-zero lock example, or a Git clone
of `main` as replacement release inputs. Until the publisher supplies the
full related set, use only the
[locally verifiable deployment package](#locally-verifiable-deployment-package).

Before the live procedures can apply, published release notes must identify
these items:

- The specified verified source package
- The image digests
- The release lock
- The checksum/signature procedure
- The corresponding-source materials.

Before these operations, the operator must have explicit infrastructure authorization: `up`, DNS or firewall changes, certificates, private-image
pulls, storage operation, and external smoke builds. Local G8 validation does
none of these actions.

## Reference topology

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

The future reference services are:

- `caddy`: TLS termination and reverse proxy. Only Caddy publishes host ports.
- `api`: Bearer-authenticated asynchronous build API. It has no direct access
  to the public edge.
- `worker`: One supervisor with concurrency one. It starts a new Blender
  child process for each attempt.
- `postgres`: The authoritative state for builds, attempts, events, artifacts,
  the outbox, and maintenance.
- `redis`: At-least-once wake-ups and short-term coordination. It is not the
  authoritative job database.
- `database-init`: The one-shot initializer for roles and forward migrations.
- `maintenance`: Explicit retention, exact-version artifact deletion,
  backup inventory/export, restore, and Redis queue reconstruction. The
  usual stack does not start this service.

The included MinIO services are local compatibility fixtures. They use
local-only profiles. They are not a supported VPS object store.
Do not enable `local-fixture` or `local-test` on a live deployment.

The worker has one replica. Do not use `--scale worker`, change
`deploy.replicas`, or operate a second VPS with the same namespace.
Scaling and multi-host coordination are future work after v0.1.

The API, worker, initializer, and maintenance containers use UID/GID
`65532:65532`, a read-only root, no capabilities, and `no-new-privileges`.
Caddy uses `1000:1000`, a read-only root, and `no-new-privileges`.
Caddy keeps only `NET_BIND_SERVICE`. The official Caddy binary's file
capability makes this necessary at exec time.

The worker has no host mount, Docker socket, device, SSH agent, or edge
network. Only its size-limited tmpfs is writable. The supervisor can connect
to PostgreSQL, Redis, and the private S3 gateway. It starts Blender without
database, Redis, storage, or API credentials in the environment.
It also closes all nonstandard inherited descriptors.

At startup, the supervisor must set the Linux non-dumpable state and disable
core dumps. This state prevents other processes from inspection of its
memory. Before each child, the launcher does a check of this state and sets
it again. If the kernel control is not available, startup stops.
Together with the dropped `CAP_SYS_PTRACE`, this prevents same-UID Blender
descendants from access to the supervisor's procfs environment or memory.

Use `make worker-boundary-check` to do a test of this boundary. The target
makes the production worker stage. It operates as UID/GID `65532:65532`
without a network or capabilities. It uses only a fixed synthetic canary,
not `.env` credentials. The test also makes sure that nested-process
cancellation operates after the process controls are set.

## Prerequisites

Before live preflight, make sure that these requirements are satisfied:

- A full `make dependency-scan` has exit `0` for the specified release
  commit and image set. Examine its stored reports. Correct each release-blocking
  finding, or document it in the release vulnerability policy. The scheduled
  report-only audit does not replace this gate. Refer to
  [Dependency maintenance](dependency-maintenance.md) and
  [Release process](release-process.md).
- The dedicated `linux/amd64` VPS has an updated Docker Engine and Docker
  Compose 2.24.4 or newer. This minimum version is necessary for the overlay's
  `!reset` and `!override` tags. Refer to the
  [Compose merge reference](https://docs.docker.com/reference/compose-file/merge/).
  The host must apply CPU, memory, PID, disk, and network controls.
- Python 3.11 or newer is available as `python3`. The `scripts/vps` wrapper
  does this check before it parses configuration or contacts Docker.
  Use `python3 --version` before you install the release tree.
- Host capacity is sufficient for the configured limits and host overhead.
  The planning baseline is 8 vCPU and 32 GiB RAM for one ordinary worker.
- The source release passed inspection. Its installation directory is
  root-owned and non-writable. The publisher supplied the related digest
  release lock.
- The API has a DNS hostname, an ACME contact email, and inbound TCP 80 and 443.
  UDP 443 is optional for HTTP/3. Do not open PostgreSQL, Redis, or the API
  container port on the host.
- An independently maintained S3-compatible service has bucket versioning enabled.
  It gives exact-version GET/HEAD/DELETE behavior, version IDs on writes,
  and presigned exact-version GET support.
- An independently operated S3 gateway connects to an external Docker network
  with the `Internal` property set to `true`. This gateway is the only storage route for API and
  worker containers. It forwards only necessary S3-compatible operations
  through a private, VPN, or destination-allowlisted route. It must not give
  general Internet egress.
- Three separate S3 identities are necessary: API read/sign, worker
  read/write-without-delete, and maintenance read/copy/delete-exact-version.
  None has administration permissions for the bucket, users, or policies.
- An encrypted off-host backup destination is available. VPS-local backup
  files cannot prevent data loss when the host is lost.
- Host time synchronization is correct. ACME and short-term signed URLs
  depend on accurate time.

Use a host firewall and the Docker `DOCKER-USER` path, or an equivalent
control. Docker must not bypass the ingress and egress policy.
We recommend SSH access only through the operator's administration network. The reference
overlay does not configure the host firewall, DNS, S3 gateway, or provider IAM.

## Filesystem layout and permissions

Use this reference layout. To use different paths, change all applicable
values in `vps.env`.

| Path | Owner | Mode | Purpose |
|---|---:|---:|---|
| `/opt/hbcb/release` | `root:root` | `0755` | Immutable source release after inspection |
| `/opt/hbcb/release/scripts/vps` | `root:root` | `0555` | Fail-closed operator wrapper |
| `/opt/hbcb/release/scripts/operator-smoke` | `root:root` | `0555` | Conditional external smoke client |
| `/etc/hbcb` | `root:root` | `0700` | Operator configuration parent |
| `/etc/hbcb/vps.env` | `root:root` | `0644` | Specified non-secret deployment configuration |
| `/etc/hbcb/release.lock.env` | `root:root` | `0644` | Specified non-secret digest lock |
| `/etc/hbcb/secrets` | `root:root` | `0700` | Separate secret files for each role |
| `/etc/hbcb/secrets/*.env` | `root:root` | `0600` | One regular, non-symlink file per role |
| `/var/lib/hbcb` | `root:root` | `0755` | Caddy state parent |
| `/var/lib/hbcb/operator.lock` | `root:root` | `0600` | Persistent fail-fast operator mutex from the wrapper |
| `/var/lib/hbcb/upgrade-handoff.json` | `root:root` | `0600` | Durable state for the quiesced upgrade handoff |
| `/var/lib/hbcb/caddy-data` | UID/GID `1000:1000` | `0700` | Certificates and Caddy data |
| `/var/lib/hbcb/caddy-config` | UID/GID `1000:1000` | `0700` | Caddy runtime state |
| `/var/backups/hbcb` | `root:root` | `0700` | Access-controlled staging area for backup bundles |

Before release installation, make the parent directories:

```sh
sudo install -d -o root -g root -m 0755 /opt/hbcb
sudo install -d -o root -g root -m 0755 /opt/hbcb/release
sudo install -d -o root -g root -m 0700 /etc/hbcb /etc/hbcb/secrets
sudo install -d -o root -g root -m 0755 /var/lib/hbcb
sudo install -d -o 1000 -g 1000 -m 0700 \
  /var/lib/hbcb/caddy-data /var/lib/hbcb/caddy-config
sudo install -d -o root -g root -m 0700 /var/backups/hbcb
```

For the first installation, `/opt/hbcb/release` must be empty. First, do the
checksum/signature procedure in the publisher's release notes on the specified
source package. Then copy the extracted, verified tree into the root-owned
directory. The path in the next command is a placeholder. No such published source package
is available:

```sh
test -f /absolute/path/to/verified-source/VERSION
test -x /absolute/path/to/verified-source/scripts/vps
sudo cp -a /absolute/path/to/verified-source/. /opt/hbcb/release/
sudo chown -R root:root /opt/hbcb/release
sudo chmod -R go-w /opt/hbcb/release
sudo chmod 0555 /opt/hbcb/release/scripts/vps
sudo chmod 0555 /opt/hbcb/release/scripts/operator-smoke
```

Do not copy a worktree with uncommitted changes. Do not clone a branch that
can change on the VPS. Do not copy new source over an existing release
directory. For upgrades, stage the specified release in a separate directory and use the
forward-only handoff procedure.

Install the non-secret configuration template from the installed release.
Install the publisher-supplied lock for the same release. Use regular files,
not symlinks:

```sh
cd /opt/hbcb/release
sudo install -o root -g root -m 0644 deploy/vps/vps.env.example \
  /etc/hbcb/vps.env
sudo install -o root -g root -m 0644 \
  /absolute/path/to/publisher-supplied/release.lock.env \
  /etc/hbcb/release.lock.env
```

Change `/etc/hbcb/vps.env` for the approved host. Do not install
`deploy/vps/release.lock.env.example`. Its zero digests are invalid, and
preflight rejects them. Complete the access-controlled role files as specified
in [VPS secret files](../deploy/vps/SECRETS.md).

When the wrapper operates as root, it does checks of numeric ownership for
these paths:

- The release tree
- The VPS configuration and release lock
- The secrets directory and files
- The state parent
- The backup root and bundles.

It rejects ownership that does not agree with the contract. It also rejects
symlinks and group/world-writable components in the root trust path.
Secret directories must be `0700`. Secret files must be `0600`.
Caddy state directories must be `0700` and owned by UID 1000.

Use plain `NAME=value` syntax for configuration values. Do not use quotes,
interpolation, backticks, surrounding whitespace, duplicate keys, or multiline values.

Refer to [VPS secret files](../deploy/vps/SECRETS.md) for role files and named
values that must agree between files. Use independently generated URL-safe random values.
64 lowercase hexadecimal characters are a safe format for database and Redis
passwords. `HBCB_API_TOKEN` and `HBCB_IDEMPOTENCY_SECRET` must each have
64 lowercase hexadecimal characters. Each must be different from all other secrets.

## External storage and network contract

Make the named network outside this Compose project. Set the Docker
`Internal` property to `true`. Then attach the independently maintained S3
gateway. For the example name, use this command:

```sh
sudo docker network create --driver bridge --internal hbcb-storage-private
sudo docker network inspect \
  --format '{{.Name}} internal={{.Internal}}' hbcb-storage-private
```

Attach only the storage gateway and HBCB services to this network.
The gateway must have a second, independently controlled route to the storage
service. Do not give that route or default/general egress to the HBCB API or worker.

Live preflight makes sure that the named network is available and reports
`Internal=true`. It cannot verify the gateway's upstream ACL, TLS policy,
or IAM. The operator must control these items.

The storage settings have different functions:

- `HBCB_STORAGE_INTERNAL_ENDPOINT` is the private TLS endpoint for bucket
  checks, uploads, reads, and verification. The reference value is `s3-gateway:443`.
- `HBCB_STORAGE_PUBLIC_ENDPOINT` is the public TLS hostname in signed download
  URLs. Clients must have access to it. The worker must not have access to it.
- The two `*_SECURE` values must be `true` on VPS.
- `HBCB_STORAGE_REGION` must be the bucket's actual region. This fixed value
  removes the public-endpoint region lookup from URL signing.
- The two endpoints must identify the same logical versioned bucket. The two must
  accept the same API signing identity. They must have different hostnames.

Endpoint values are `host` or `host:port`. They must not contain a scheme,
path, credentials, or query string. The internal gateway certificate must be
trusted by the release images and correct for the configured internal hostname.
Do not use the public endpoint as the worker's internal endpoint to pass readiness checks.

Before first startup, enable versioning. Do a separate check with the
provider's tools. Each upload that succeeds must return a nonempty version ID.
Do not configure general lifecycle expiry on the live namespace. It can
delete a version that PostgreSQL references. Provider cleanup of
incomplete multipart uploads is permitted.

The maintenance identity records object versions only under the canonical
`<namespace>/v1/builds/` prefix. To preview previous versions absent from
PostgreSQL, use the operator wrapper. Thus, the inventory uses the host mutex
and command deadline:

```sh
sudo ./scripts/vps orphan-discovery-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --limit 100 \
  --scan-limit 100000
```

The preview prints counts within the specified limits and a scope-bound token,
for example `discover-orphans:100:100000`. Examine the counts. Then, to queue
the same scope, supply the two acknowledgements:

```sh
sudo ./scripts/vps orphan-discovery-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --limit 100 \
  --scan-limit 100000 \
  --confirm \
  --confirmation-token discover-orphans:100:100000
```

A change to either limit changes the necessary token. Do a new preview.
The permitted range is 1–1,000 candidates and 1–100,000 scanned versions.

Apply records these values in PostgreSQL: bucket, key, version ID, digest,
byte size, object timestamp, and discovery origin. It does not delete storage.
Use `artifact-deletion-preview` as a separate operation. Then use `artifact-deletion-apply`
with `--confirm` to claim and delete the specified versions.

The deletion queue applies the configured grace period again from discovery
time. Thus, a new candidate usually does not show immediately in the deletion
preview. This gives a second period for inspection. The two phases have limits.
The process does not select new versions, versions referenced by `hbcb.artifacts`,
or versions owned by active builds.

Discovery stops fully, without partial queue results, if it finds any
of these conditions:

- A delete marker or unversioned object
- A noncanonical key
- A missing digest, version, or timestamp
- A listing that changes
- A duplicate or incomplete listing
- A scan ceiling that was exceeded.

Redis contains wake-ups. It does not contain authoritative build state.
After group acknowledgement, the process removes settled entries from the
main Stream. The dead-letter Stream keeps a maximum of the newest 10,000 build IDs.

Redis uses AOF with `appendfsync everysec`, automatic AOF rewrite, a 384 MiB
dataset ceiling, and `noeviction`. This limits the dataset and removes previous,
settled AOF history without automatic eviction of coordination state.
Capacity alerts must include the Redis data volume, pending-entry count,
and AOF rewrite failures.

## DNS, TLS, and the public edge

Before `up`, do these steps:

1. Point the API hostname's `A` record to the VPS. Add `AAAA` only with a
   full IPv6 configuration.
2. Make sure that public TCP 80 and 443 have access to the VPS. UDP 443 is optional.
3. Make sure that no host mapping gives external access to ports 5432, 6379,
   8080, or the storage gateway.
4. Set `HBCB_API_DOMAIN` to the hostname only. Set a correct `HBCB_ACME_EMAIL`.
5. Make sure that the artifact hostname in `HBCB_STORAGE_PUBLIC_ENDPOINT`
   resolves to the storage service.

Caddy gets and renews certificates. It stores ACME state in the two UID-1000
state directories. Its admin API and dynamic-config persistence are disabled.
The public edge accepts `/healthz` and `/v1/*`. All other paths, including
`/readyz`, return `404`. Readiness stays inside Compose and the service because
it shows dependency state.

Build and artifact routes use the API bearer token. TLS does not replace
API authentication. Do not put tokens in URLs.

## Release lock

`release.lock.env` is an immutable bill of materials for one release.
Get it with the related source release after inspection. Do not make a lock
with images from different release tags.

The lock specifies these identities:

- The project-derived PostgreSQL image by OCI digest
- API and worker images by OCI digest
- Caddy by OCI digest
- The builder provenance reference and image configuration ID
- The frozen G4 source revision
- The migration-catalog SHA-256
- A semantic release version.

The wrapper rejects all-zero digests, mutable tags, extra keys, and missing
keys. It also rejects source-revision or migration-digest disagreement with
the installed source. The builder image and worker supervisor must come from
the same examined release lineage. Keep each deployed lock with backups and
upgrade records. The lock is necessary for recovery and rollback to the
specified state.

## Safe lifecycle commands

Use the wrapper from the installed release tree. Give absolute configuration
paths. It validates keys, file format, permissions, digest pins, the migration
catalog, and the merged Compose model. Unless offline, it also validates the
private storage network. Errors do not print secret values.

First, validate without an inspection of live infrastructure:

```sh
cd /opt/hbcb/release
sudo ./scripts/vps preflight \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --offline
```

After the internal storage network and gateway are available, do live preflight:

```sh
sudo ./scripts/vps preflight \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

If the wrapper reports `private storage network is unavailable`, make the configured
Docker-internal network and attach the private S3 gateway. Use the
[External storage and network contract](#external-storage-and-network-contract).
Then do live preflight again. This error does not include the configured network
name or captured Docker output.

`config` does the same safe, quiet validation. It prints only a pass/fail
marker. Do not use raw `docker compose config`. Resolved service configuration
can contain credentials from role env files.

During root execution, the wrapper does not trust the caller's Docker or
Compose control environment. It rejects inherited `DOCKER_*`, `COMPOSE_*`,
`BUILDX_*`, and `BUILDKIT_*` variables. It uses a `PATH` with specified system directories and
a fixed Compose project name. By default, it accepts Docker only at an
examined root-owned system path.

If Docker Compose is installed elsewhere, set `HBCB_COMPOSE_BIN` to its
absolute executable path. Each path component and the executable must be
root-owned and not group/world writable. Put private-registry authentication
in the access-controlled root Docker configuration. Do not put it in an
operator shell variable or repository file.

Start the examined images:

```sh
sudo ./scripts/vps up \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

`up` pulls images by digest, starts PostgreSQL and Redis, and operates the
one-shot database initializer. Before API, worker, or Caddy startup, the
wrapper examines namespace-bearing database metadata. That metadata must be
empty or contain only `HBCB_DEPLOYMENT_NAMESPACE`. A second or foreign
namespace stops startup.

The wrapper then starts one API, one worker, and Caddy. It waits for health
checks. Incomplete startup gives a nonzero exit code.

Stop the services but keep named volumes, Caddy state, backups, and external artifacts:

```sh
sudo ./scripts/vps down \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

Do not add `--volumes`, use `docker volume prune`, or delete state/backup
directories to correct a fault. A usual `down` is not a backup.
`down` does not examine the live storage network. Thus, the operator can stop
the system during a gateway outage. Only this mutating action accepts `--offline`.
Other mutating wrapper actions reject the flag.

Each action other than `preflight` and `config` must operate as root.
It holds the same nonblocking host mutex at `/var/lib/hbcb/operator.lock`.
The mutex stays held from before the first operational command until the end.
If a different wrapper action is active, the new action stops immediately.

The lock file is a persistent root-owned inode with mode `0600` inside the
validated state parent. Do not delete, replace, manually lock, or change the
permissions of this file. Scheduled retention, artifact deletion, queue
reconstruction, backups, upgrades, and lifecycle commands must use this wrapper.
Thus, all actions use the same mutual exclusion.

Each Docker/Compose child command has a wall-clock deadline. The default is
900 seconds for lifecycle and health commands. For image pulls, database
dumps/restores, and object transfers, the default is 14,400 seconds.
An approved operator can select 30 through 86,400 seconds with
`--command-timeout-seconds SECONDS` or `--transfer-timeout-seconds SECONDS`.

The wrapper sends large backup/restore payloads directly to the access-controlled
file or container input. It limits all captured stdout/stderr. Error messages
do not include captured command output.

At a deadline or output-limit failure, the wrapper terminates the command's
process group. After a short grace period, it kills remaining processes before
cleanup. The host mutex stays held during process termination and recovery.
`Ctrl-C`/`SIGINT`, `SIGTERM`, and `SIGHUP` use the same child-tree termination
before the wrapper releases the mutex. A terminated operation stops safely,
but can make documented recovery or retry necessary.

## Logs and observability

All production containers use the Docker `json-file` driver with
`max-size=10m` and `max-file=5`. This limits stored container logs to
approximately 50 MiB per service. The API disables Uvicorn access logging.
Caddy has no access log directive. Usual logs contain size-limited lifecycle
metadata, not HTTP request records.

Before you enable access or debug logging on a public deployment, get a
separate privacy and redaction inspection. Do not record authorization
headers, request bodies, prompts, object credentials, signed URLs, or artifact
bytes in logs. During diagnosis, examine only a specified maximum number of last log
lines. Before issue publication, examine raw logs for private data.

## Retention

Retention uses database state. Its default operation is a preview.
The reference policy is:

| Build status | Default age | Eligibility |
|---|---:|---|
| `succeeded` | 30 days | Terminal builds only, from the end |
| `failed` | 7 days | Terminal builds only, from the end |
| `canceled` | 7 days | Terminal builds only, from the end |
| `needs_review` | 7 days | Terminal builds only, from the end |
| Any nonterminal status | No age-based deletion | A terminal state must occur first |
| Queued exact artifact version | 7-day grace | From durable deletion-queue insertion |

Use the deployed release for the preview. Examine counts before deletion:

```sh
sudo ./scripts/vps retention-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

Before apply, examine the preview. Make sure that no backup, restore, or
upgrade is active:

```sh
sudo ./scripts/vps retention-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

Retention apply first copies each affected artifact's bucket, key, version ID,
SHA-256, and byte count into the durable deletion queue. Then it removes the
terminal build row in a transaction. It does not immediately remove bucket bytes.

After the orphan grace period, the separate artifact-deletion operation
previews or processes that queue. It deletes only each recorded version,
not an unversioned key. Failed exact-version deletion stays in durable
state. You can safely do that deletion again.

After the configured grace period, preview the second stage:

```sh
sudo ./scripts/vps artifact-deletion-preview \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env
```

Examine the preview before apply:

```sh
sudo ./scripts/vps artifact-deletion-apply \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

Before you schedule either apply stage, examine a minimum of one manual
preview and apply cycle. Do not use a provider-wide bucket lifecycle rule as
an alternative to this process.

## Quiesced backup

A full application backup with coordinated state has four parts:

1. A transaction-consistent PostgreSQL dump.
2. A catalog and access-controlled copy of each S3 object version referenced
   by the dump. These include the object key, source version ID, SHA-256,
   and byte count.
3. The release lock, non-secret VPS configuration, backup metadata, and
   checksums. Keep the related examined source release in a separate location. The bundle
   does not contain the source release.
4. A separate encrypted backup of role secrets. Do not put secrets in the
   application-data bundle.

Redis is not authoritative. Recovery does not restore its AOF.
You can copy Caddy state as a separate operation while Caddy is stopped. Loss of Caddy
state does not cause build loss. But new ACME certificates can be necessary,
and provider rate limits can apply.

Use the release backup action only on an approved live target.
A root operator and explicit acknowledgement are necessary because the action
stops ingress:

```sh
sudo ./scripts/vps backup \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

The default worker drain timeout is 3,600 seconds. To select a different
value, add `--drain-timeout-seconds SECONDS`. The permitted range is
30–86,400 seconds. This is a total drain deadline, not a per-poll timeout.
Each quiescence probe gets only the remaining time.

An ordinary backup timeout removes the unpublished partial bundle. The
wrapper then tries to restore the initial live service set. After an upgrade
handoff starts, a timeout keeps ingress stopped and the database read-only.
The durable handoff stays for an exact-target retry or documented
empty-target rollback.

The wrapper does this sequence:

1. Complete live preflight and do a check of the installed release lock.
2. Stop Caddy and the API to prevent new submissions. Keep the single worker
   in operation until existing work finishes.
3. Poll the backup inventory until no build has these states: `validating`,
   `queued`, `running`, `geometry_qa`, or `rendering`. Then stop the worker
   and do the quiescence check again.
4. Immediately before and after the dump, examine namespaces in `builds`,
   `idempotency_keys`, `artifact_deletion_queue`, and `artifact_restore_remaps`.
   The set must contain only the configured namespace, or be empty.
   Make a custom-format, data-only dump of the `hbcb` schema.
   Namespace-owned parent rows limit dependent build-attempt, event, artifact,
   and outbox rows.

   Do not include schema migrations or artifact deletion queue/attempt data.
   The related release makes the schema again. Recovery must not replay stale
   exact-version deletion work on the restored namespace.
5. Export each S3 version referenced by the same quiesced database state.
   Do checks of SHA-256 and byte count. Write `objects/inventory.json`.
6. Copy `release.lock.env` and `vps.env`. Record hashes, counts, release,
   migration catalog, namespace, bucket, and creation time in `backup-manifest.json`.
   Atomically publish a direct-child bundle below `HBCB_BACKUP_ROOT`.
7. For an ordinary backup, restart the unchanged PostgreSQL, Redis,
   initializer, API, worker, and Caddy. Do this after backup success or failure.
   A restart failure is fatal.

On success, stdout ends with `VPS_BACKUP: PASS bundle=/absolute/path`.
Record that path. A correct bundle contains only `backup-manifest.json`,
`database.dump`, `objects/`, `release.lock.env`, and `vps.env`.
Directories have mode `0700`. Files have mode `0600`.

UID 0 owns the bundle directory and its four top-level files.
Numeric UID 65532 owns `objects/` and all directories and files below it.
Thus, the unprivileged maintenance container can read a direct, read-only
bind mount without access through the root-only bundle parent.
The bundle contains no source tree, secret files, Redis AOF, or Caddy state.

Copy the bundle and independently encrypted role-secret backup off the VPS.
Use a root-operated archive or transfer that keeps numeric owners and modes.
For example, use an archive or `rsync` procedure configured for numeric IDs.
Do restore tests at regular intervals.

Do not use a recursive copy that changes each owner to root or the recipient
account. Recovery rejects such a bundle. Before `preflight` or `restore`,
put the bundle under `HBCB_BACKUP_ROOT` with its recorded numeric ownership
and modes. Do not make the root-only bundle directory traversable to bypass
these controls.

For a pre-upgrade handoff, add `--leave-ingress-down` to the backup command.
On success, the wrapper keeps Caddy, API, and worker stopped. It sets the
database to default read-only. It binds the system identifier and database
OID to the specified bundle and source-lock hash. Then it atomically writes
`/var/lib/hbcb/upgrade-handoff.json`.

Success reports `handoff=ready ingress=stopped`. While this marker file is at its specified path,
unrelated lifecycle and maintenance actions stop. Use the upgrade or
handoff-abort procedure in the next sections. Do not change or delete the marker.

Object-store versioning alone is not a backup. Provider failure, credential
compromise, or account deletion can remove all versions. Copy the referenced
bytes to a separate failure domain. Do not use retention while the backup
process is active.

## Empty-target restore

Restore stops ingress and rejects dangerous states. This mutating action does
not accept `--offline`. Do not restore over a deployment in operation.
The target must have a new PostgreSQL database, empty Redis database, and no
object versions under the configured deployment namespace. Use the namespace,
bucket, and canonical object keys recorded in the backup.

First, install the examined source release from the separate source backup. Install the bundle's archived `release.lock.env` as the active lock.
The active lock's file hash must equal the archived lock's hash.
Restore role secrets from the separate encrypted backup.

Keep `HBCB_IDEMPOTENCY_SECRET` unchanged, so existing idempotency keys keep
their meaning. Change the public API token only as a planned client migration.

The absolute backup path must identify one direct child of
`HBCB_BACKUP_ROOT`. Keep DNS away from the target. Then use the two
acknowledgements as root:

```sh
sudo ./scripts/vps restore \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --backup /var/backups/hbcb/EXACT-BUNDLE-DIRECTORY \
  --confirm \
  --confirm-empty-target
```

The wrapper validates all bundle hashes and metadata. It stops Caddy, API,
and worker. It starts only PostgreSQL, Redis, and the initializer.
It makes sure that each application table, Redis database 0, and the target
S3 namespace are empty.

The wrapper directly bind-mounts the validated, UID-65532-owned `objects/`
directory at `/backup`, read-only. It does not give the maintenance container
access to the root-owned bundle directory. It then restores the data-only
PostgreSQL dump.

For each artifact, the wrapper does these operations:

1. Upload the verified bytes to the canonical key.
2. Record the returned version ID.
3. Do checks of SHA-256 and byte count through that version.
4. Update the artifact row.
5. Add the source-to-restored version mapping to `artifact_restore_remaps`.

A missing object, hash/size disagreement, unexpected target data, or incomplete
remap stops the operation.

If restore fails after an object upload, the target is contaminated.
Keep ingress stopped. Keep the wrapper's size-limited error and sanitized
evidence. Discard and make new target stores: the PostgreSQL database,
Redis database 0, and full configured object namespace.

Do not continue from an object index. Do not manually change a version mapping.
Do not guess which uploaded versions are safe to delete. An interrupted
request can commit remotely without a returned version ID.

Make sure that the replacement target is empty. Do the full restore again
from the same verified bundle. If you cannot prove that the target is empty,
make a new empty target as an alternative.

The Redis reconstruction uses only build IDs whose authoritative PostgreSQL
status is `queued`. It does not copy a source AOF. At-least-once delivery
makes duplicate wake-ups safe. The wrapper starts PostgreSQL, Redis,
initializer, API, and the single worker. It keeps Caddy stopped and reports
`VPS_RESTORE: PASS ingress=stopped`.

Before `up` or a DNS change, do checks of migrations and internal readiness.
Do checks of an exact-version artifact download and a known manifest hash.
Then do the conditional operator smoke test.

Keep the previous target and backup read-only until the restored service passes
verification. A restore test passes only when exact-version downloads,
manifest hashes, database state, and Redis reconstruction all pass.

## Upgrade and rollback

Migrations use checksum verification and operate only in the forward direction.
Each upgrade changes state. It is not only an image-tag change.

Use this upgrade procedure:

1. Read the release notes. Get the full new source release and lock in a
   separate versioned directory. Keep the previous release as the live installation.
   Do the new release's offline preflight on the staged source/lock pair.
   Do not start its initializer at this time.
2. Use the installed previous release and previous lock to make the quiesced handoff backup.
   Record the printed absolute bundle path:

   ```sh
   sudo ./scripts/vps backup \
     --config /etc/hbcb/vps.env \
     --release-lock /etc/hbcb/release.lock.env \
     --confirm \
     --leave-ingress-down
   ```

   Continue only after `handoff=ready ingress=stopped`. Keep the bundle, previous
   source tree, previous lock, and independently encrypted secret backup. The database
   is read-only at this time. The durable handoff stops other operator actions.
3. Within four hours, install or select the staged new source and lock as
   one controlled release change. Then use this command:

   ```sh
   sudo ./scripts/vps upgrade \
     --config /etc/hbcb/vps.env \
     --release-lock /etc/hbcb/release.lock.env \
     --backup /var/backups/hbcb/EXACT-PRE-UPGRADE-BUNDLE \
     --confirm
   ```

   The absolute bundle path must identify a direct child of the configured
   backup root. It must equal the bundle path recorded in the handoff.
   The command does checks of the source-lock hash, manifest hash, database
   system identifier/OID, namespace, read-only state, and quiescence.

   It atomically changes the marker to `upgrading`. It records the specified
   target-lock hash before it makes the database writable. It pulls images
   while the database stays read-only. Only then can the initializer apply
   migrations.

   The wrapper starts and does checks of the private application. It starts
   Caddy. It consumes the handoff only after full startup success.
4. Before you declare upgrade success, do checks of internal readiness and public `/healthz`.
   Make sure that public `/readyz` gives `404` and token-free authentication fails.
   Do the conditional operator smoke test.

If the handoff stays `preparing` or `ready`, you can abort before the first
migration attempt. Install again or select the same previous source and lock.
Then explicitly abort:

```sh
sudo ./scripts/vps handoff-abort \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --confirm
```

The previous lock hash must equal the source-lock hash in the marker.
After the marker becomes `upgrading`, abort is permanently prohibited.
The database could contain a committed migration.

After a failed or interrupted attempt, the database is read-only again.
The target binding stays. Retry `upgrade` only with the same target
source/lock and bound bundle. As an alternative, use the empty-target `rollback`
in the next paragraph with the bound pre-upgrade bundle and same previous source/lock.
Do not delete or change the marker to force an in-place downgrade.

Rollback uses the same empty-target recovery contract. It is not only an
image reversal. Prepare a target that you can prove is empty.
Use the previous source from separate storage. Use the previous lock from the pre-upgrade bundle.
Then use this command:

```sh
sudo ./scripts/vps rollback \
  --config /etc/hbcb/vps.env \
  --release-lock /etc/hbcb/release.lock.env \
  --backup /var/backups/hbcb/EXACT-PRE-UPGRADE-BUNDLE \
  --confirm \
  --confirm-empty-target
```

As with `restore`, success reports `ingress=stopped`. Do private verification
before an explicit `up`. A migration or newer writer can change state.
After that change, replacement with previous image digests alone is dangerous.
The wrapper does not give this option. Do not manually change migration
records or database rows to force an older image to start.

## Failure recovery

| Symptom | Safe response |
|---|---|
| Preflight rejects a file, digest, or permission | Correct the named input. Do not bypass the wrapper or decrease permission restrictions. |
| `private storage network is unavailable` | Make or repair the configured external `Internal=true` network. Attach the private S3 gateway. Do live preflight again. Do not attach API or worker to a default-egress network. |
| API is healthy but not ready internally | Do checks of PostgreSQL, Redis, the migration catalog, bucket versioning, private TLS/DNS, and scoped storage IAM. Keep `/readyz` private. |
| Caddy cannot get a certificate | Do checks of DNS, host time, TCP 80/443, ACME email, and UID-1000 Caddy state ownership. Keep the API private. |
| Worker exits during a build | Keep PostgreSQL and Redis. Restart the single worker. Lease expiry and at-least-once delivery make recovery possible. Do not manually publish temporary output. |
| Redis is lost | Start empty Redis. Use `queue-rebuild-preview`, then `queue-rebuild-apply --confirm`. These use only PostgreSQL rows with status `queued`. Do not use Redis as authoritative state or restore an AOF. |
| PostgreSQL or artifact storage is lost | Keep ingress stopped. Do the empty-target restore. Database metadata and the specified artifact bytes are the two necessary. |
| A specified artifact version is missing | Record a recovery failure. Restore that verified version from backup. Do not sign the latest key version as an alternative. |
| Restore fails during object upload | Keep ingress stopped. Keep sanitized evidence. Discard and make three new empty target stores. Prove that they are empty. Use the full verified bundle again. Do not continue a partial restore or manually change version remaps. |
| Handoff is `preparing`, `ready`, or stale before upgrade starts | Keep ingress stopped. Select the same source release/lock. Use `handoff-abort --confirm`. Do not delete the marker. |
| Upgrade startup fails or is interrupted after `upgrading` | Keep ingress stopped and keep the marker. Retry only the same target lock and bound bundle. Source abort/in-place downgrade is prohibited. The migration commit state cannot be safely known. |
| Upgrade cannot recover with the same target | Prove that a new target is empty. Use `rollback` with the previous source/lock and marker-bound pre-upgrade bundle. Do not use the existing database with an older version. |
| Host disk is full | Keep ingress stopped. Keep named volumes. Independently verify which data you can discard before you remove it. Do not prune volumes or active backup files. |

If damage to the release tree or storage network stops the wrapper, first
copy the state, lock, configuration, and logs. Keep the copies access-controlled.
Manual Compose recovery is an incident action. It must keep volumes.
Do not make destructive commands from assumptions about this procedure.

Use this sequence after Redis loss:

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

The external operator smoke test makes a build through the live service and contacts an approved
public deployment. Thus, the test is conditional. Use it only when an
operator supplies the VPS/domain, correct bearer credential, and explicit authorization.
It is not part of offline package validation. Do not start it automatically
from a fork or untrusted CI job.

Without a target, the script records a conditional skip with a success status.
It makes no network request:

```sh
./scripts/operator-smoke
```

For an approved live target, put only the raw bearer token in a dedicated
regular, non-symlink file with mode `0600`. Do not give the token on the
command line. Do not give `api.env`, which contains assignments. It does not contain only one raw token. Explicitly allowlist each cross-origin artifact authority:

```sh
sudo ./scripts/operator-smoke \
  --target https://builder.example.com \
  --token-file /etc/hbcb/operator-smoke.token \
  --allow-artifact-host artifacts.example.com:443 \
  --evidence /var/backups/hbcb/operator-smoke.json
```

The script sanitizes the evidence file, writes it atomically, and sets mode
`0600`. A non-loopback target must use HTTPS with usual certificate
verification. The loopback-only HTTP switch is for automated tests.
It is not a VPS option.

The smoke test must do these operations:

- Use `https://` and usual certificate verification.
- Make sure that `/healthz` succeeds and public `/readyz` returns `404`.
- Make sure that the API rejects an unauthenticated build request.
- Send the included request with an idempotency key and receive `202`.
- Replay the same key/request. Reject a same-key/different-request conflict.
- Poll by build ID until a terminal state. Do not keep the submission request open.
- Download each specified artifact version through the public signed endpoint.
- Do checks of the manifest, artifact hashes, and expected artifact set.
- Redact the bearer token and signed URLs from stdout, stderr, and logs.

A smoke-created build stays as usual retained data. Record its build ID.
Let the configured retention policy remove it. Do not manually delete
unversioned object keys.

## Locally verifiable deployment package

These checks validate the package without contact with a cloud provider or live VPS:

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

The static gate renders the merged Compose model with temporary fixture
values. It does checks of digest pins, service sets, private networks, one
worker, security controls, log limits, and local-fixture isolation.
`make g8-gate` also does a test of the specified Caddy image and an isolated,
disposable recovery procedure. If the public image is not in the local
cache, the test can pull it by digest.

None of these commands deploys to a VPS. They do not establish these properties:

- Live DNS, ACME, or firewall operation
- Gateway egress ACLs or provider IAM
- Storage compatibility
- Off-host backup durability
- A public smoke build.

Those checks stay conditional on operator infrastructure and explicit authorization.
