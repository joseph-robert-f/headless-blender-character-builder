# VPS secret files

The VPS overlay reads five role-scoped environment files from the absolute
directory named by `HBCB_VPS_SECRETS_DIR`. Create that directory as root with
mode `0700`; create every file below as a regular, non-symlink file owned by
root with mode `0600`.

Never commit these files, copy them into an image, print resolved Compose
configuration, or place them in the application backup bundle. Keep a separate
encrypted, access-controlled secret backup in another failure domain.

## Placeholder rules

Every angle-bracketed value below is a **named placeholder**, not text to copy
literally:

- the same placeholder name must be replaced by the same value everywhere it
  appears;
- different placeholder names must receive independent values; and
- no value may contain a newline, shell syntax, surrounding quotes, or an
  inline comment.

The wrapper requires direct secrets to be 32–128 printable ASCII characters
and pairwise distinct. Use a cryptographically secure secret manager or
generator. Sixty-four lowercase hexadecimal characters represent 32 random
bytes and avoid URL-encoding ambiguity for database and Redis passwords.
`HBCB_API_TOKEN` and `HBCB_IDEMPOTENCY_SECRET` specifically require exactly 64
lowercase hexadecimal characters.

| Placeholder | Where it repeats |
|---|---|
| `<DB_ADMIN_PASSWORD_64_HEX>` | `postgres.env` and the admin URL in `database-init.env` |
| `<DB_MIGRATOR_PASSWORD_64_HEX>` | migrator URL and direct migrator password in `database-init.env` |
| `<DB_API_PASSWORD_64_HEX>` | API direct password in `database-init.env` and API database URL |
| `<DB_WORKER_PASSWORD_64_HEX>` | worker direct password in `database-init.env` and worker database URL |
| `<DB_MAINTENANCE_PASSWORD_64_HEX>` | maintenance direct password in `database-init.env` and maintenance database URL |
| `<REDIS_PASSWORD_64_HEX>` | `redis.env` and the API, worker, and maintenance Redis URLs |

All other named placeholders occur once and must remain distinct from every
password, token, and secret key above.

The URL placeholders below are assembly instructions, not additional secrets.
Construct each URL from the exact components in this table after replacing the
named password placeholder. Do not add quotes or whitespace:

| URL placeholder | Scheme | Username | Password | Host, port, and database |
|---|---|---|---|---|
| `<DB_ADMIN_URL_FROM_TABLE>` | `postgresql` | `hbcb_admin` | `<DB_ADMIN_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_MIGRATOR_URL_FROM_TABLE>` | `postgresql` | `hbcb_migrator` | `<DB_MIGRATOR_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_API_URL_FROM_TABLE>` | `postgresql` | `hbcb_api` | `<DB_API_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_WORKER_URL_FROM_TABLE>` | `postgresql` | `hbcb_worker` | `<DB_WORKER_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_MAINTENANCE_URL_FROM_TABLE>` | `postgresql` | `hbcb_maintenance` | `<DB_MAINTENANCE_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<REDIS_URL_FROM_TABLE>` | `redis` | empty | `<REDIS_PASSWORD_64_HEX>` | `redis`, `6379`, database `0` |

Use the standard URI form for the named scheme: scheme separator, optional
username, colon, password, `@`, host, port, and database path. Hexadecimal
passwords need no percent-encoding. Keeping credential-bearing URLs out of this
tracked guide is intentional; the release audit rejects them even when they
contain documentation placeholders.

## Required files

### `postgres.env`

```text
POSTGRES_DB=hbcb
POSTGRES_USER=hbcb_admin
POSTGRES_PASSWORD=<DB_ADMIN_PASSWORD_64_HEX>
```

### `redis.env`

```text
REDIS_PASSWORD=<REDIS_PASSWORD_64_HEX>
```

### `database-init.env`

This role receives administrative bootstrap authority and is never attached
to the API or worker:

```text
HBCB_DATABASE_ADMIN_URL=<DB_ADMIN_URL_FROM_TABLE>
HBCB_DATABASE_MIGRATOR_URL=<DB_MIGRATOR_URL_FROM_TABLE>
HBCB_DATABASE_API_USER=hbcb_api
HBCB_DATABASE_API_PASSWORD=<DB_API_PASSWORD_64_HEX>
HBCB_DATABASE_WORKER_USER=hbcb_worker
HBCB_DATABASE_WORKER_PASSWORD=<DB_WORKER_PASSWORD_64_HEX>
HBCB_DATABASE_MAINTENANCE_USER=hbcb_maintenance
HBCB_DATABASE_MAINTENANCE_PASSWORD=<DB_MAINTENANCE_PASSWORD_64_HEX>
HBCB_DATABASE_MIGRATOR_USER=hbcb_migrator
HBCB_DATABASE_MIGRATOR_PASSWORD=<DB_MIGRATOR_PASSWORD_64_HEX>
```

### `api.env`

This file contains only API authority:

```text
HBCB_API_TOKEN=<API_TOKEN_64_HEX>
HBCB_IDEMPOTENCY_SECRET=<IDEMPOTENCY_SECRET_64_HEX>
HBCB_DATABASE_URL=<DB_API_URL_FROM_TABLE>
HBCB_REDIS_URL=<REDIS_URL_FROM_TABLE>
HBCB_STORAGE_ACCESS_KEY=<API_STORAGE_ACCESS_KEY>
HBCB_STORAGE_SECRET_KEY=<API_STORAGE_SECRET_64_HEX>
```

Preserve `<IDEMPOTENCY_SECRET_64_HEX>` during restore so existing idempotency
keys retain their meaning. Rotate `<API_TOKEN_64_HEX>` only as an intentional
client migration.

### `worker.env`

The worker S3 policy may read and create versions under the configured
namespace, but it must not delete versions or administer the bucket:

```text
HBCB_DATABASE_URL=<DB_WORKER_URL_FROM_TABLE>
HBCB_REDIS_URL=<REDIS_URL_FROM_TABLE>
HBCB_STORAGE_ACCESS_KEY=<WORKER_STORAGE_ACCESS_KEY>
HBCB_STORAGE_SECRET_KEY=<WORKER_STORAGE_SECRET_64_HEX>
```

### `maintenance.env`

This file is used only by explicit backup, restore, retention, exact-version
deletion, and Redis reconstruction operations:

```text
HBCB_DATABASE_URL=<DB_MAINTENANCE_URL_FROM_TABLE>
HBCB_REDIS_URL=<REDIS_URL_FROM_TABLE>
HBCB_STORAGE_ACCESS_KEY=<MAINTENANCE_STORAGE_ACCESS_KEY>
HBCB_STORAGE_SECRET_KEY=<MAINTENANCE_STORAGE_SECRET_64_HEX>
```

## Storage permissions

The storage access keys must name three distinct identities:

- API: bucket/versioning inspection, exact-version read, and presigning;
- worker: bucket/versioning inspection, exact-version read, and create-version,
  with no delete authority; and
- maintenance: version listing, exact-version read, create/copy, and
  exact-version delete only under the deployment namespace.

In S3 policy terms, maintenance needs `s3:ListBucketVersions`,
`s3:GetObjectVersion`, `s3:PutObject`, and `s3:DeleteObjectVersion` scoped to
the configured bucket and namespace. Do not grant unversioned
`s3:DeleteObject`. None of the identities may change bucket versioning or
administer accounts, users, policies, or unrelated prefixes.

Enable object versioning before deployment. Do not configure generic lifecycle
expiration on the live namespace because it can remove a version still
referenced by PostgreSQL. Incomplete-multipart cleanup is acceptable. HBCB's
database-aware retention defaults to dry-run.

## Backup and rotation

Secrets are deliberately excluded from `scripts/vps backup` bundles. Preserve
the separate encrypted secret backup together with a record identifying its
matching application bundle, but never store either inside the source tree.

Secret rotation is a coordinated maintenance event. Quiesce ingress and the
worker, update the authoritative database, Redis, or storage credential first,
replace every affected `0600` role file atomically, run preflight, and restart
the same release lock. Database and Redis passwords repeat in the named files
above; an incomplete rotation fails closed. Never rotate
`HBCB_IDEMPOTENCY_SECRET` during an ordinary restore or upgrade.
