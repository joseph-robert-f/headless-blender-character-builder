# HTTP API v1

The source checkout includes a loopback-only asynchronous service used for
integration testing and self-hosting experiments. It is not a hosted public
API and no production images are currently published.

The API is a small asynchronous control surface over the repository's pinned,
containerized builder contract. It accepts only `BuildRequest v1` JSON, never
arbitrary Python, Blender arguments, paths, URLs, uploads, or provider keys.

## Run locally

The first-evaluation path is:

```sh
./scripts/doctor --service
make init-env
make service-config
make service-up
make service-ps
```

Follow the client journey below. When finished, run `make service-down` in a
separate command; it stops this checkout's stack while preserving its data.

`make init-env` creates a private local bearer token, a checkout-specific Compose
project identity, and other scoped credentials in ignored `.env`; it prints no
secret and refuses to overwrite an existing file. The API binds to loopback,
using host port `8080` by default. The repository does not yet include a
lightweight custom-request service client, so the copy-paste journey below is
the supported first evaluation. `make service-smoke` is a separate, slower
maintainer/integration confidence gate that builds directly and through the
service, restarts the API, tests cancellation and IAM, downloads all artifacts,
and independently verifies them. The local stack is for loopback evaluation
only; do not publish its ports or treat it as the G8 production deployment.

## Copy-paste local client journey

Run the block below from the repository root after `make service-up`. Paste the
whole block at once. It runs in a subshell, so a failure stops only this client
run—not your interactive shell. It removes private scratch data on every exit
and publishes nothing until the complete nine-file artifact set has passed its
declared byte counts and SHA-256 hashes.

Set `HBCB_REQUEST` to a schema-valid custom JSON file first if desired; the
default is Facet Bot. For example, this selects the checked-in request by its
exact absolute path (replace that path with your own schema-valid JSON):

```sh
export HBCB_REQUEST="$PWD/examples/requests/facet-bot.json"
```

If `python3` is older than 3.11, run
`export PYTHON=python3.11` once for this terminal session. The shared settings
helper reads only allowlisted, validated nonsecret selectors from `.env`; it
does not source credentials. Omitting `Idempotency-Key` intentionally creates a
new build each time, which is friendlier while iterating.

```sh
(
set -eu
umask 077

HBCB_API_TMP=
HBCB_STAGE=
HBCB_RESERVED_RESULT=
HBCB_BUILD_ID=
HBCB_CANCEL_ON_EXIT=0
safe_api_error_code() {
  "$HBCB_PYTHON" - "$1" <<'PY'
import json
from pathlib import Path
import re
import stat
import sys

path = Path(sys.argv[1])
try:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1024 * 1024:
        raise ValueError
    document = json.loads(path.read_text(encoding="utf-8"))
    code = document["error"]["code"]
except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
    raise SystemExit(1)
if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
    raise SystemExit(1)
print(code)
PY
}
api_request() {
  HBCB_API_LABEL=$1
  HBCB_API_OUTPUT=$2
  HBCB_API_MAX_TIME=$3
  shift 3
  : > "$HBCB_API_OUTPUT"
  if curl --fail-with-body --silent --show-error \
    --connect-timeout 5 --max-time "$HBCB_API_MAX_TIME" \
    --noproxy '*' \
    --max-filesize 1048576 \
    --output "$HBCB_API_OUTPUT" "$@"; then
    return 0
  fi
  HBCB_API_ERROR=$(safe_api_error_code "$HBCB_API_OUTPUT" 2>/dev/null || \
    printf '%s\n' http_request_failed)
  printf '%s (%s)\n' "$HBCB_API_LABEL" "$HBCB_API_ERROR" >&2
  return 1
}
cleanup_service_client() {
  HBCB_CLIENT_STATUS=$?
  trap - EXIT HUP INT TERM
  if test "$HBCB_CANCEL_ON_EXIT" = 1 && test -n "$HBCB_BUILD_ID" && \
    test -n "${HBCB_API_BASE:-}" && test -n "$HBCB_API_TMP" && \
    test -s "$HBCB_API_TMP/auth.header"; then
    HBCB_CANCEL_ON_EXIT=0
    curl --fail-with-body --silent --show-error \
      --connect-timeout 5 --max-time 15 \
      --noproxy '*' \
      --max-filesize 1048576 \
      --request POST \
      --header @"$HBCB_API_TMP/auth.header" \
      --header 'Content-Length: 0' \
      --output "$HBCB_API_TMP/cancel.json" \
      "$HBCB_API_BASE/v1/builds/$HBCB_BUILD_ID/cancel" >/dev/null 2>&1 || true
  fi
  if test -n "$HBCB_API_TMP" && test -d "$HBCB_API_TMP"; then
    rm -r -- "$HBCB_API_TMP" || true
  fi
  if test -n "$HBCB_STAGE" && test -d "$HBCB_STAGE"; then
    rm -r -- "$HBCB_STAGE" || true
  fi
  if test -n "$HBCB_RESERVED_RESULT" && \
    test -d "$HBCB_RESERVED_RESULT" && test ! -L "$HBCB_RESERVED_RESULT"; then
    rm -r -- "$HBCB_RESERVED_RESULT" || true
  fi
  exit "$HBCB_CLIENT_STATUS"
}
interrupt_service_client() {
  exit 130
}
trap cleanup_service_client EXIT
trap interrupt_service_client HUP INT TERM

HBCB_PYTHON=${PYTHON:-python3}
command -v "$HBCB_PYTHON" >/dev/null
command -v curl >/dev/null
. ./scripts/service-common
hbcb_service_settings
if ! hbcb_service_env_private; then
  printf '%s\n' \
    'client requires an owned mode-0600 regular .env; run make init-env if it is missing' >&2
  exit 1
fi
HBCB_API_BASE=http://127.0.0.1:$HBCB_API_HOST_PORT
HBCB_REQUEST=${HBCB_REQUEST:-examples/requests/facet-bot.json}
test -f "$HBCB_REQUEST"

HBCB_API_TMP=$(mktemp -d "${TMPDIR:-/tmp}/hbcb-api.XXXXXX")
chmod 700 "$HBCB_API_TMP"
awk -F= '$1 == "HBCB_API_TOKEN" { print "Authorization: Bearer " $2 }' \
  .env > "$HBCB_API_TMP/auth.header"
chmod 600 "$HBCB_API_TMP/auth.header"
test "$(wc -l < "$HBCB_API_TMP/auth.header" | tr -d ' ')" = 1

api_request 'build submission failed' "$HBCB_API_TMP/build.json" 30 \
  --header @"$HBCB_API_TMP/auth.header" \
  --header 'Content-Type: application/json' \
  --data-binary @"$HBCB_REQUEST" \
  "$HBCB_API_BASE/v1/builds"

HBCB_BUILD_ID=$("$HBCB_PYTHON" -c \
  'import json,sys; from uuid import UUID; print(UUID(json.load(open(sys.argv[1], encoding="utf-8"))["build_id"]))' \
  "$HBCB_API_TMP/build.json")
HBCB_CANCEL_ON_EXIT=1
printf 'queued build %s\n' "$HBCB_BUILD_ID"

HBCB_BUILD_STATUS=unknown
HBCB_TERMINAL_CODE=-
HBCB_POLL_ATTEMPT=0
HBCB_POLL_DEADLINE=$(( $(date +%s) + 1200 ))
while test "$HBCB_POLL_ATTEMPT" -lt 600 && \
  test "$(date +%s)" -lt "$HBCB_POLL_DEADLINE"; do
  api_request 'build status request failed' "$HBCB_API_TMP/status.json" 15 \
    --header @"$HBCB_API_TMP/auth.header" \
    "$HBCB_API_BASE/v1/builds/$HBCB_BUILD_ID"
  HBCB_STATUS_LINE=$("$HBCB_PYTHON" - "$HBCB_API_TMP/status.json" \
    "$HBCB_BUILD_ID" <<'PY'
import json
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
if path.stat().st_size > 1024 * 1024:
    raise SystemExit("build status response is unexpectedly large")
document = json.loads(path.read_text(encoding="utf-8"))
status = document.get("status")
code = document.get("terminal_code")
nonterminal = {"validating", "queued", "running", "geometry_qa", "rendering"}
terminal = {"succeeded", "failed", "canceled", "needs_review"}
if document.get("build_id") != sys.argv[2] or status not in nonterminal | terminal:
    raise SystemExit("build status response is invalid")
if status in {"failed", "canceled", "needs_review"}:
    if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) is None:
        raise SystemExit("build terminal code is invalid")
elif code is not None:
    raise SystemExit("build terminal code is invalid")
print(status + ":" + (code or "-"))
PY
  )
  HBCB_BUILD_STATUS=${HBCB_STATUS_LINE%%:*}
  HBCB_TERMINAL_CODE=${HBCB_STATUS_LINE#*:}
  printf 'status: %s\n' "$HBCB_BUILD_STATUS"
  case "$HBCB_BUILD_STATUS" in
    succeeded|failed|canceled|needs_review)
      HBCB_CANCEL_ON_EXIT=0
      break
      ;;
  esac
  HBCB_POLL_ATTEMPT=$((HBCB_POLL_ATTEMPT + 1))
  sleep 2
done
if test "$HBCB_BUILD_STATUS" != succeeded; then
  if test "$HBCB_TERMINAL_CODE" = -; then
    printf 'build stopped at status %s; run make service-logs\n' \
      "$HBCB_BUILD_STATUS" >&2
  else
    printf 'build stopped at status %s (terminal code: %s); run make service-logs\n' \
      "$HBCB_BUILD_STATUS" "$HBCB_TERMINAL_CODE" >&2
  fi
  if test "$HBCB_BUILD_STATUS" = needs_review; then
    printf '%s\n' \
      'run the same request with one-shot make build to see bounded safe diagnostics' >&2
  fi
  exit 1
fi

api_request 'artifact listing request failed' "$HBCB_API_TMP/artifacts.json" 30 \
  --header @"$HBCB_API_TMP/auth.header" \
  "$HBCB_API_BASE/v1/builds/$HBCB_BUILD_ID/artifacts"

test ! -L build
mkdir -p build
test ! -L build/service-client
mkdir -p build/service-client
HBCB_RESULT_CANDIDATE=$PWD/build/service-client/$HBCB_BUILD_ID
"$HBCB_PYTHON" - "$HBCB_RESULT_CANDIDATE" <<'PY'
import os
from pathlib import Path
import stat
import sys

reservation = Path(sys.argv[1])
try:
    os.mkdir(reservation, 0o700)
except FileExistsError:
    raise SystemExit("verified result already exists; refusing to overwrite it") from None
except OSError:
    raise SystemExit("verified result could not be reserved safely") from None
metadata = reservation.lstat()
if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
    raise SystemExit("verified result reservation is unsafe")
PY
HBCB_RESERVED_RESULT=$HBCB_RESULT_CANDIDATE
HBCB_RESULT=$HBCB_RESERVED_RESULT/artifacts
HBCB_STAGE=$(mktemp -d "$HBCB_RESERVED_RESULT/.stage.XXXXXX")

"$HBCB_PYTHON" - "$HBCB_API_TMP/artifacts.json" "$HBCB_STAGE" \
  "$HBCB_STORAGE_HOST_PORT" <<'PY'
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

required = (
    "model.blend", "model.glb", "model.stl", "preview.png",
    "diagnostics/front.png", "diagnostics/side.png", "diagnostics/back.png",
    "qa.json", "manifest.json",
)
listing = Path(sys.argv[1])
stage = Path(sys.argv[2])
storage_port = int(sys.argv[3])
if listing.stat().st_size > 1024 * 1024:
    raise SystemExit("artifact listing is unexpectedly large")
document = json.loads(listing.read_text(encoding="utf-8"))
entries = document.get("artifacts")
if (
    not isinstance(entries, list)
    or any(not isinstance(item, dict) for item in entries)
    or tuple(item.get("path") for item in entries) != required
):
    raise SystemExit("artifact listing is incomplete or out of order")

def checked_url(raw):
    if (
        not isinstance(raw, str)
        or len(raw) > 8192
        or any(ord(character) < 33 or ord(character) > 126 for character in raw)
    ):
        raise SystemExit("artifact URL is outside the selected local service")
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
        query = urllib.parse.parse_qs(parsed.query)
    except ValueError:
        raise SystemExit("artifact URL is outside the selected local service") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("localhost", "127.0.0.1")
        or port != storage_port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or len(query.get("versionId", ())) != 1
    ):
        raise SystemExit("artifact URL is outside the selected local service")
    return raw

class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    RejectRedirects(),
)
budget = 2 * 1024 * 1024 * 1024
declared_total = 0
for entry in entries:
    expected_bytes = entry.get("bytes")
    expected_hash = entry.get("sha256")
    if (
        type(expected_bytes) is not int
        or expected_bytes < 0
        or expected_bytes > budget
        or not isinstance(expected_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
    ):
        raise SystemExit("artifact evidence is invalid")
    checked_url(entry.get("download_url"))
    declared_total += expected_bytes
    if declared_total > budget:
        raise SystemExit("artifact set exceeds the v0.1 size budget")

total = 0
for entry in entries:
    relative = entry["path"]
    expected_bytes = entry["bytes"]
    expected_hash = entry["sha256"]
    download_url = entry["download_url"]
    destination = stage / relative
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    consumed = 0
    digest = hashlib.sha256()
    try:
        response = opener.open(download_url, timeout=30)
    except urllib.error.HTTPError as error:
        error.close()
        if 300 <= error.code < 400:
            raise SystemExit("artifact redirect was rejected") from None
        raise SystemExit("artifact download returned an HTTP error") from None
    except (urllib.error.URLError, HTTPException, OSError, TimeoutError):
        raise SystemExit("artifact download failed") from None
    try:
        with response:
            final_url = checked_url(response.geturl())
            if final_url != download_url or getattr(response, "status", None) != 200:
                raise SystemExit("artifact response changed URL or status unexpectedly")
            with destination.open("xb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if consumed > expected_bytes:
                        raise SystemExit("artifact exceeded its declared size")
                    digest.update(chunk)
                    stream.write(chunk)
    except (urllib.error.URLError, HTTPException, OSError, TimeoutError):
        raise SystemExit("artifact download failed") from None
    if consumed != expected_bytes or digest.hexdigest() != expected_hash:
        raise SystemExit("artifact evidence did not match its downloaded bytes")
    os.chmod(destination, 0o600)
    total += consumed
    if total > budget:
        raise SystemExit("artifact set exceeds the v0.1 size budget")
PY

cp "$HBCB_API_TMP/status.json" "$HBCB_STAGE/build.json"
chmod 600 "$HBCB_STAGE/build.json"
"$HBCB_PYTHON" - "$HBCB_STAGE" "$HBCB_RESULT" <<'PY'
import os
from pathlib import Path
import stat
import sys

stage = Path(sys.argv[1])
result = Path(sys.argv[2])
try:
    parent = result.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700:
        raise OSError
    try:
        result.lstat()
    except FileNotFoundError:
        pass
    else:
        raise OSError
    # The destination is absent inside the private directory atomically
    # reserved by this process, so the verified payload appears in one rename.
    os.rename(stage, result)
except OSError:
    raise SystemExit("verified result could not be published atomically") from None
PY
HBCB_STAGE=
HBCB_RESERVED_RESULT=
printf 'verified model and evidence saved in %s\n' "$HBCB_RESULT"
)
```

The result contains `model.blend`, `model.glb`, `model.stl`, the preview and
three diagnostic renders, `qa.json`, `manifest.json`, and one final
`build.json` API record. It deliberately does not retain the artifact-listing
response or its short-lived signed URLs. The build-ID directory is reserved
atomically, and the verified payload appears inside it with one atomic rename;
an existing file, directory, or symlink with that build ID is never
overwritten. Artifact redirects are rejected without being followed, and every
initial and final download URL must use the exact selected loopback storage
port.

Use Finder, File Explorer, or your Linux file manager to open the exact result
directory printed after `verified model and evidence saved in`. Open its
`preview.png` to inspect the render and `model.blend` to inspect the Blender
source. STL carries geometry but no color or materials, while GLB is the
convenient colored viewer/export format. Pressing Control-C while the client block is
polling—or a polling request or response failure—sends one bounded cancellation
request for a nonterminal build before removing scratch data. Terminal failures
print only the API's bounded safe `terminal_code`; response bodies and signed
URLs remain in private scratch and are removed. The cancellation endpoint
contract is documented below.

When finished, stop the stack. The client block already removed its private
scratch directory and retained only the verified result:

```sh
make service-down
```

`make service-down` preserves the named local data volumes and their matching
credentials. The [troubleshooting guide](troubleshooting.md) explains the safe
choices if `.env` is missing or those volumes are no longer wanted.

## Authentication and response policy

`GET /healthz` is public. `GET /readyz` and every `/v1/*` route require exactly one header:

```text
Authorization: Bearer <HBCB_API_TOKEN>
```

The token is generated by `make init-env`. Missing, duplicated, malformed, or incorrect authorization returns `401` with `WWW-Authenticate: Bearer`. Authentication runs before route parsing and request-body processing.

An idempotency key is useful for an automated retry, but do not reuse one after
editing the request: the same key and same canonical request replay the original
build, while the same key with different content returns `409`.

Every response includes:

```text
Cache-Control: no-store
X-Request-ID: <server-generated UUID>
```

The service disables interactive API documentation, OpenAPI publication, CORS, proxy-header trust, server-version headers, and access logs by default.

## Submit a build

```http
POST /v1/builds
Content-Type: application/json
Authorization: Bearer <token>
Idempotency-Key: my-character-0001

<BuildRequest v1 JSON>
```

`Content-Type` must be exactly `application/json` with an optional single `charset=utf-8` parameter. `Content-Encoding` may be absent or `identity`. The raw body is capped at 65,536 bytes while streaming, before JSON parsing. Duplicate headers, duplicate JSON keys, malformed UTF-8, non-finite/pathological numbers, extra fields, and every other contract violation fail closed.

`Idempotency-Key` is optional. When supplied, it must be 8–128 ASCII bytes using letters, digits, `.`, `_`, `~`, or `-`, beginning with a letter or digit. The database stores only its HMAC-SHA-256 digest.

Responses:

- `202 Accepted` for a newly queued build;
- `200 OK` when the same idempotency key replays the same canonical request;
- `409 Conflict` when that key was already used for another request.

Both success responses include `Location: /v1/builds/{build_id}` and a build document. Submission never waits for Blender.

## Inspect a build

```http
GET /v1/builds/{build_id}
Authorization: Bearer <token>
```

The build document contains:

```json
{
  "build_id": "uuid",
  "request_sha256": "64 lowercase hex characters",
  "spec_sha256": "64 lowercase hex characters",
  "status": "queued",
  "state_version": 1,
  "max_attempts": 2,
  "cancel_requested_at": null,
  "terminal_code": null,
  "manifest_sha256": null,
  "manifest_bytes": null,
  "created_at": "2026-08-03T12:00:00.000Z",
  "updated_at": "2026-08-03T12:00:00.000Z",
  "finished_at": null,
  "published_at": null,
  "artifacts_url": null
}
```

Externally visible states are `queued`, `running`, `geometry_qa`, `rendering`, `succeeded`, `failed`, `canceled`, and `needs_review`. The G4 builder is opaque, so the supervisor may move directly from `running` to a terminal state rather than inventing intermediate progress.

## Retrieve artifacts

```http
GET /v1/builds/{build_id}/artifacts
Authorization: Bearer <token>
```

Only a durably succeeded build exposes artifacts. A nonterminal build returns `409 artifacts_not_ready`; a failed, canceled, or review-required build returns `409 artifacts_unavailable`.

Success returns exactly nine records in the fixed contract order:

```text
model.blend
model.glb
model.stl
preview.png
diagnostics/front.png
diagnostics/side.png
diagnostics/back.png
qa.json
manifest.json
```

Each record contains `path`, `content_type`, `bytes`, `sha256`, and a short-lived `download_url`. URLs are signed for the exact immutable object version and default to 300 seconds. The URL itself is never written to service logs.

## Cancel a build

```http
POST /v1/builds/{build_id}/cancel
Authorization: Bearer <token>
Content-Length: 0
```

The body must be empty. A queued build is canceled atomically and returns `200`. A running build records cancellation intent and returns `202`; the supervisor terminates the full builder/Blender process tree and cancellation wins over retry or publication. Repeating cancellation on an already canceled build returns `200`. A terminal successful, failed, or review-required build returns `409`.

## Health and readiness

- `GET /healthz` returns `200 {"status":"ok"}` without contacting dependencies.
- `GET /readyz` is authenticated and returns `200 {"status":"ready"}` only when PostgreSQL responds, the exact migration catalog matches, the Redis consumer group exists, and the versioned artifact bucket is available. Otherwise it returns `503 service_not_ready` without dependency details.

## Error envelope

Errors use one stable shape:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Caller-safe description.",
    "path": null,
    "request_id": "server-generated UUID"
  }
}
```

Expected status families are `400` for malformed requests, `401` for authorization, `404` for unknown builds/routes, `405` for methods, `409` for state/idempotency conflicts, `413` for oversized input, `415` for media/encoding policy, `422` for a well-formed request that violates the contract, `503` for unavailable dependencies, and a generic secret-free `500` for unexpected internal failures.
