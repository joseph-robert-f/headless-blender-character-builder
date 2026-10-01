# VPS secret files

The VPS overlay reads six role-scoped environment files.
`HBCB_VPS_SECRETS_DIR` identifies their absolute directory.
As root, make that directory with mode `0700`.
Make each specified role file a regular, non-symlink file owned by root, with mode `0600`.

Do not commit these files or copy them into an image.
Do not print resolved Compose configuration. Do not put these files in the
application backup bundle. Keep a separate encrypted, access-controlled
secret backup in a different failure domain.

## Placeholder rules

Each angle-bracketed value in this guide is a **named placeholder**.
Do not copy the placeholder as a secret value. Obey these rules:

- Replace the same placeholder name with the same value at each location.
- Give different placeholder names independently generated values.
- Do not include a newline, shell syntax, surrounding quotes, or an inline
  comment in a value.

Each direct secret must have 32–128 printable ASCII characters.
Each secret must be different from all other secrets. Use a cryptographically
secure secret manager or generator. 64 lowercase hexadecimal characters
represent 32 random bytes. This format prevents URL-encoding ambiguity for
database and Redis passwords.

`HBCB_API_TOKEN` and `HBCB_IDEMPOTENCY_SECRET` must each have 64 lowercase
hexadecimal characters.

| Placeholder | Locations with the same value |
|---|---|
| `<DB_ADMIN_PASSWORD_64_HEX>` | `postgres.env` and the admin URL in `database-init.env` |
| `<DB_MIGRATOR_PASSWORD_64_HEX>` | Migrator URL and direct migrator password in `database-init.env` |
| `<DB_API_PASSWORD_64_HEX>` | API direct password in `database-init.env` and API database URL |
| `<DB_WORKER_PASSWORD_64_HEX>` | Worker direct password in `database-init.env` and worker database URL |
| `<DB_MAINTENANCE_PASSWORD_64_HEX>` | Maintenance direct password in `database-init.env` and maintenance database URL |
| `<REDIS_PASSWORD_64_HEX>` | `redis.env` and the API, worker, and maintenance Redis URLs |

All other named placeholders occur one time. Their values must be different from
each password, token, and secret key in the table.

The URL placeholders in the next table give assembly instructions. They are not
more secrets. Replace the named password placeholder first.
Then make each URL from the specified table components.
Do not add quotes or whitespace:

| URL placeholder | Scheme | Username | Password | Host, port, and database |
|---|---|---|---|---|
| `<DB_ADMIN_URL_FROM_TABLE>` | `postgresql` | `hbcb_admin` | `<DB_ADMIN_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_MIGRATOR_URL_FROM_TABLE>` | `postgresql` | `hbcb_migrator` | `<DB_MIGRATOR_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_API_URL_FROM_TABLE>` | `postgresql` | `hbcb_api` | `<DB_API_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_WORKER_URL_FROM_TABLE>` | `postgresql` | `hbcb_worker` | `<DB_WORKER_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<DB_MAINTENANCE_URL_FROM_TABLE>` | `postgresql` | `hbcb_maintenance` | `<DB_MAINTENANCE_PASSWORD_64_HEX>` | `postgres`, `5432`, `hbcb` |
| `<REDIS_URL_FROM_TABLE>` | `redis` | empty | `<REDIS_PASSWORD_64_HEX>` | `redis`, `6379`, database `0` |

Use the standard URI format for the named scheme. Its components are the
scheme separator, optional username, colon, password, `@`, host, port, and
database path. Hexadecimal passwords do not use percent-encoding.
This tracked guide contains no credential-bearing URLs. The release audit
rejects such URLs, including URLs with documentation placeholders.

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

This role has administrative bootstrap authority. Do not attach it to the API
or worker:

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

During restore, keep `<IDEMPOTENCY_SECRET_64_HEX>` unchanged.
Thus, existing idempotency keys keep their meaning.
Change `<API_TOKEN_64_HEX>` only as a planned client migration.

### `worker.env`

The worker S3 policy can read and make versions under the configured
namespace. It must not delete versions or give bucket administration permissions:

```text
HBCB_DATABASE_URL=<DB_WORKER_URL_FROM_TABLE>
HBCB_REDIS_URL=<REDIS_URL_FROM_TABLE>
HBCB_STORAGE_ACCESS_KEY=<WORKER_STORAGE_ACCESS_KEY>
HBCB_STORAGE_SECRET_KEY=<WORKER_STORAGE_SECRET_64_HEX>
```

### `maintenance.env`

Only explicit backup, restore, retention, exact-version deletion, and Redis
reconstruction operations use this file:

```text
HBCB_DATABASE_URL=<DB_MAINTENANCE_URL_FROM_TABLE>
HBCB_REDIS_URL=<REDIS_URL_FROM_TABLE>
HBCB_STORAGE_ACCESS_KEY=<MAINTENANCE_STORAGE_ACCESS_KEY>
HBCB_STORAGE_SECRET_KEY=<MAINTENANCE_STORAGE_SECRET_64_HEX>
```

## Storage permissions

The storage access keys must identify three different identities:

- API: Bucket/versioning inspection, exact-version read, and presigning
- Worker: Bucket/versioning inspection, exact-version read, and create-version,
  without delete authority
- Maintenance: Version listing, exact-version read, create/copy, and
  exact-version delete only under the deployment namespace.

The maintenance S3 policy must include `s3:ListBucketVersions`,
`s3:GetObjectVersion`, `s3:PutObject`, and `s3:DeleteObjectVersion`.
Limit these permissions to the configured bucket and namespace.
Do not give unversioned `s3:DeleteObject` permission.

None of the identities can change bucket versioning. None can administer
accounts, users, policies, or unrelated prefixes.

Enable object versioning before deployment. Do not configure general
lifecycle expiration on the live namespace. It can remove a version that
PostgreSQL references. Incomplete-multipart cleanup is permitted.
The HBCB database-aware retention default is dry-run.

## Backup and rotation

`scripts/vps backup` bundles do not contain secrets.
Keep the separate encrypted secret backup and a record that identifies its
related application bundle. Do not store the application backup or secret backup inside the source tree.

Secret rotation is a coordinated maintenance event. Use this sequence:

1. Quiesce ingress and the worker.
2. Update the authoritative database, Redis, or storage credential first.
3. Atomically replace each affected `0600` role file.
4. Do preflight.
5. Restart with the same release lock.

Database and Redis passwords occur in more than one named file in this guide.
Incomplete rotation stops operation. Do not change `HBCB_IDEMPOTENCY_SECRET`
during an ordinary restore or upgrade.
