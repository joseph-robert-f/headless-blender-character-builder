#!/bin/sh
set -eu

umask 077

required='MINIO_ROOT_USER MINIO_ROOT_PASSWORD HBCB_STORAGE_API_ACCESS_KEY HBCB_STORAGE_API_SECRET_KEY HBCB_STORAGE_WORKER_ACCESS_KEY HBCB_STORAGE_WORKER_SECRET_KEY HBCB_STORAGE_MAINTENANCE_ACCESS_KEY HBCB_STORAGE_MAINTENANCE_SECRET_KEY HBCB_STORAGE_BUCKET HBCB_DEPLOYMENT_NAMESPACE'
for name in $required; do
  eval "value=\${$name-}"
  if [ -z "$value" ]; then
    printf '%s\n' 'MINIO_INIT: required configuration is missing' >&2
    exit 2
  fi
done

if [ "$HBCB_STORAGE_BUCKET" != 'hbcb-artifacts' ] || [ "$HBCB_DEPLOYMENT_NAMESPACE" != 'local' ]; then
  printf '%s\n' 'MINIO_INIT: local policy and namespace do not match' >&2
  exit 3
fi
case "$HBCB_STORAGE_API_ACCESS_KEY" in
  hbcb_api) ;;
  hbcb_api_?*)
    api_suffix=${HBCB_STORAGE_API_ACCESS_KEY#hbcb_api_}
    case "$api_suffix" in
      *[!A-Za-z0-9_-]*)
        printf '%s\n' 'MINIO_INIT: API storage identity is outside its reserved prefix' >&2
        exit 4
        ;;
    esac
    ;;
  *)
    printf '%s\n' 'MINIO_INIT: API storage identity is outside its reserved prefix' >&2
    exit 4
    ;;
esac
case "$HBCB_STORAGE_WORKER_ACCESS_KEY" in
  hbcb_worker) ;;
  hbcb_worker_?*)
    worker_suffix=${HBCB_STORAGE_WORKER_ACCESS_KEY#hbcb_worker_}
    case "$worker_suffix" in
      *[!A-Za-z0-9_-]*)
        printf '%s\n' 'MINIO_INIT: worker storage identity is outside its reserved prefix' >&2
        exit 4
        ;;
    esac
    ;;
  *)
    printf '%s\n' 'MINIO_INIT: worker storage identity is outside its reserved prefix' >&2
    exit 4
    ;;
esac
case "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" in
  hbcb_maintenance) ;;
  hbcb_maintenance_?*)
    maintenance_suffix=${HBCB_STORAGE_MAINTENANCE_ACCESS_KEY#hbcb_maintenance_}
    case "$maintenance_suffix" in
      *[!A-Za-z0-9_-]*)
        printf '%s\n' 'MINIO_INIT: maintenance storage identity is outside its reserved prefix' >&2
        exit 4
        ;;
    esac
    ;;
  *)
    printf '%s\n' 'MINIO_INIT: maintenance storage identity is outside its reserved prefix' >&2
    exit 4
    ;;
esac
if [ "$HBCB_STORAGE_API_ACCESS_KEY" = "$HBCB_STORAGE_WORKER_ACCESS_KEY" ] || \
   [ "$HBCB_STORAGE_API_ACCESS_KEY" = "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" ] || \
   [ "$HBCB_STORAGE_WORKER_ACCESS_KEY" = "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" ] || \
   [ "$HBCB_STORAGE_API_ACCESS_KEY" = "$MINIO_ROOT_USER" ] || \
   [ "$HBCB_STORAGE_WORKER_ACCESS_KEY" = "$MINIO_ROOT_USER" ] || \
   [ "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" = "$MINIO_ROOT_USER" ]; then
  printf '%s\n' 'MINIO_INIT: storage identities must be distinct' >&2
  exit 4
fi
if [ "$HBCB_STORAGE_API_SECRET_KEY" = "$HBCB_STORAGE_WORKER_SECRET_KEY" ] || \
   [ "$HBCB_STORAGE_API_SECRET_KEY" = "$HBCB_STORAGE_MAINTENANCE_SECRET_KEY" ] || \
   [ "$HBCB_STORAGE_WORKER_SECRET_KEY" = "$HBCB_STORAGE_MAINTENANCE_SECRET_KEY" ] || \
   [ "$HBCB_STORAGE_API_SECRET_KEY" = "$MINIO_ROOT_PASSWORD" ] || \
   [ "$HBCB_STORAGE_WORKER_SECRET_KEY" = "$MINIO_ROOT_PASSWORD" ] || \
   [ "$HBCB_STORAGE_MAINTENANCE_SECRET_KEY" = "$MINIO_ROOT_PASSWORD" ]; then
  printf '%s\n' 'MINIO_INIT: storage secrets must be distinct' >&2
  exit 4
fi
case "$MINIO_ROOT_USER" in
  hbcb_api|hbcb_api_*|hbcb_worker|hbcb_worker_*|hbcb_maintenance|hbcb_maintenance_*)
    printf '%s\n' 'MINIO_INIT: root identity uses a reserved project prefix' >&2
    exit 4
    ;;
esac

mc alias set hbcb http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc ready hbcb >/dev/null
mc mb --ignore-existing "hbcb/$HBCB_STORAGE_BUCKET" >/dev/null
# Keep this separate from `mb`: it repairs an existing but unversioned bucket.
mc version enable "hbcb/$HBCB_STORAGE_BUCKET" >/dev/null

# Access-key usernames are stable in current configurations.  Remove both the
# current names and the random-suffix names emitted by pre-release G5/G7
# generators so regenerating .env cannot leave an old credential valid.  The
# hbcb_api*, hbcb_worker*, and hbcb_maintenance* prefixes are reserved to this
# project.  This never removes buckets, objects, or object versions.
user_payload=$(mc admin user list hbcb --json)
listed_users=$(printf '%s\n' "$user_payload" | sed -n 's/.*"accessKey":"\([^"]*\)".*/\1/p')
if [ -n "$user_payload" ] && [ -z "$listed_users" ]; then
  printf '%s\n' 'MINIO_INIT: user inventory could not be parsed safely' >&2
  exit 5
fi
printf '%s\n' "$listed_users" | while IFS= read -r username; do
  case "$username" in
    hbcb_api|hbcb_api_*|hbcb_worker|hbcb_worker_*|hbcb_maintenance|hbcb_maintenance_*)
      mc admin user remove hbcb "$username" >/dev/null
      ;;
  esac
done
mc admin user add hbcb "$HBCB_STORAGE_API_ACCESS_KEY" "$HBCB_STORAGE_API_SECRET_KEY" >/dev/null
mc admin user add hbcb "$HBCB_STORAGE_WORKER_ACCESS_KEY" "$HBCB_STORAGE_WORKER_SECRET_KEY" >/dev/null
mc admin user add hbcb "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" "$HBCB_STORAGE_MAINTENANCE_SECRET_KEY" >/dev/null
mc admin policy create hbcb hbcb-api-v1 /policies/minio-api-policy.json >/dev/null
mc admin policy create hbcb hbcb-worker-v1 /policies/minio-worker-policy.json >/dev/null
mc admin policy create hbcb hbcb-maintenance-v1 /policies/minio-maintenance-policy.json >/dev/null
mc admin policy attach hbcb hbcb-api-v1 --user "$HBCB_STORAGE_API_ACCESS_KEY" >/dev/null
mc admin policy attach hbcb hbcb-worker-v1 --user "$HBCB_STORAGE_WORKER_ACCESS_KEY" >/dev/null
mc admin policy attach hbcb hbcb-maintenance-v1 --user "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" >/dev/null

mc version info "hbcb/$HBCB_STORAGE_BUCKET" | grep -F 'versioning is enabled' >/dev/null
mc admin user info hbcb "$HBCB_STORAGE_API_ACCESS_KEY" >/dev/null
mc admin user info hbcb "$HBCB_STORAGE_WORKER_ACCESS_KEY" >/dev/null
mc admin user info hbcb "$HBCB_STORAGE_MAINTENANCE_ACCESS_KEY" >/dev/null

printf '%s\n' '{"bucket":"hbcb-artifacts","event":"minio_initialized","namespace":"local","versioning":"Enabled"}'
