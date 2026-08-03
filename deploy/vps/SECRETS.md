# VPS secret files

The VPS overlay consumes separate role-scoped environment files from the absolute directory named by `HBCB_VPS_SECRETS_DIR`. Create that directory as root with mode `0700`; create every file below as a regular, non-symlink file with mode `0600`. Never commit these files, copy them into an image, print `docker compose config`, or include them in the application backup bundle.

Values must not contain newlines, shell syntax, or surrounding quotes. Generate independent random secrets of at least 32 bytes; every `<random>` below denotes a different value. Lowercase hexadecimal avoids URL-encoding ambiguity in PostgreSQL and Redis connection URLs. The password embedded in each URL must exactly match the corresponding direct password value. Preserve the API idempotency secret during restore so existing idempotency keys retain their meaning. Keep an encrypted, access-controlled secret backup separately from application data.

`postgres.env`:

```text
POSTGRES_DB=hbcb
POSTGRES_USER=hbcb_admin
POSTGRES_PASSWORD=<random>
```

`redis.env`:

```text
REDIS_PASSWORD=<random>
```

`database-init.env` receives administrative bootstrap authority and is never attached to API or worker:

```text
HBCB_DATABASE_ADMIN_URL=postgresql://hbcb_admin:<random>@postgres:5432/hbcb
HBCB_DATABASE_MIGRATOR_URL=postgresql://hbcb_migrator:<random>@postgres:5432/hbcb
HBCB_DATABASE_API_USER=hbcb_api
HBCB_DATABASE_API_PASSWORD=<random>
HBCB_DATABASE_WORKER_USER=hbcb_worker
HBCB_DATABASE_WORKER_PASSWORD=<random>
HBCB_DATABASE_MAINTENANCE_USER=hbcb_maintenance
HBCB_DATABASE_MAINTENANCE_PASSWORD=<random>
HBCB_DATABASE_MIGRATOR_USER=hbcb_migrator
HBCB_DATABASE_MIGRATOR_PASSWORD=<random>
```

`api.env` contains only API authority:

```text
HBCB_API_TOKEN=<64 lowercase hex>
HBCB_IDEMPOTENCY_SECRET=<64 lowercase hex>
HBCB_DATABASE_URL=postgresql://hbcb_api:<random>@postgres:5432/hbcb
HBCB_REDIS_URL=redis://:<random>@redis:6379/0
HBCB_STORAGE_ACCESS_KEY=<API read-only access key>
HBCB_STORAGE_SECRET_KEY=<random>
```

`worker.env` contains only worker authority. Its S3 policy may read and create versions under the configured namespace, but must not delete versions or administer the bucket:

```text
HBCB_DATABASE_URL=postgresql://hbcb_worker:<random>@postgres:5432/hbcb
HBCB_REDIS_URL=redis://:<random>@redis:6379/0
HBCB_STORAGE_ACCESS_KEY=<worker write-without-delete access key>
HBCB_STORAGE_SECRET_KEY=<random>
```

`maintenance.env` is used only by explicit backup, restore, retention, exact-version deletion, and Redis reconstruction operations. Give it a separate database role and a separate S3 identity allowed to read, create/copy, and delete exact versions only under the deployment namespace. It must not administer users, policies, or buckets:

```text
HBCB_DATABASE_URL=postgresql://hbcb_maintenance:<random>@postgres:5432/hbcb
HBCB_REDIS_URL=redis://:<random>@redis:6379/0
HBCB_STORAGE_ACCESS_KEY=<maintenance exact-version key>
HBCB_STORAGE_SECRET_KEY=<random>
```

The storage identities must be distinct. The API identity needs bucket/versioning inspection plus read and presign authority for exact versions. The worker identity needs bucket/versioning inspection plus read and create-version authority, but no delete authority. The maintenance identity needs version listing, exact-version read, create/copy, and exact-version delete authority. In S3 policy terms, that maintenance scope includes `s3:ListBucketVersions`, `s3:GetObjectVersion`, `s3:PutObject`, and `s3:DeleteObjectVersion` for only the configured bucket and deployment namespace; do not grant unversioned `s3:DeleteObject`. None may change bucket versioning or administer accounts, users, or policies.

The provider/operator must enable object versioning before deployment. Do not configure a generic lifecycle expiration on the live namespace: it can delete a version still referenced by PostgreSQL. Incomplete-multipart cleanup is acceptable. Retention is database-aware and defaults to dry-run.

Secrets are deliberately excluded from `scripts/vps backup` bundles. Preserve an encrypted, access-controlled copy in a different failure domain, together with a record that identifies the matching application bundle, without placing either inside the source tree.

Secret rotation is a coordinated maintenance event. Quiesce ingress and workers, update the authoritative service or storage credential first, replace the affected `0600` role files atomically, run preflight, and restart the same release lock. Database and Redis passwords appear in multiple matching files; an incomplete rotation is expected to fail closed. Never rotate `HBCB_IDEMPOTENCY_SECRET` during ordinary restore or upgrade.
