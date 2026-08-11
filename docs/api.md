# HTTP API v1

The source checkout includes a loopback-only asynchronous service used for
integration testing and self-hosting experiments. It is not a hosted public
API and no production images are currently published.

The API is a small asynchronous control surface over the same immutable G4 builder contract. It accepts only `BuildRequest v1` JSON, never arbitrary Python, Blender arguments, paths, URLs, uploads, or provider keys.

## Run locally

The tested path is:

```sh
make init-env
make service-up
make service-smoke
make service-down
```

The first command creates a private local bearer token and other scoped credentials in ignored `.env`; it prints no secret and refuses to overwrite an existing file. The API binds to `http://127.0.0.1:8080`. `make service-smoke` performs the equivalent authenticated HTTP workflow below, downloads all nine artifacts into an ignored evidence directory, and independently verifies them. The local stack is for loopback evaluation only; do not publish its ports or treat it as the G8 production deployment.

## Copy-paste local client journey

Run these commands from the repository root after `make service-up`. They use a
mode-`0700` temporary directory and a private curl header file so the bearer
token is not printed or placed directly in curl's process arguments:

```sh
HBCB_API_BASE=http://127.0.0.1:8080
HBCB_API_TMP=$(mktemp -d "${TMPDIR:-/tmp}/hbcb-api.XXXXXX")
chmod 700 "$HBCB_API_TMP"
awk -F= '$1 == "HBCB_API_TOKEN" { print "Authorization: Bearer " $2 }' \
  .env > "$HBCB_API_TMP/auth.header"
chmod 600 "$HBCB_API_TMP/auth.header"
test "$(wc -l < "$HBCB_API_TMP/auth.header" | tr -d ' ')" = 1
```

Submit Facet Bot. The response is written to a private file rather than echoed
to the terminal:

```sh
curl --fail-with-body --silent --show-error \
  --header @"$HBCB_API_TMP/auth.header" \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: facet-request-0001' \
  --data-binary @examples/requests/facet-bot.json \
  --output "$HBCB_API_TMP/build.json" \
  "$HBCB_API_BASE/v1/builds"

HBCB_BUILD_ID=$(python3 -c \
  'import json,sys; from uuid import UUID; print(UUID(json.load(open(sys.argv[1], encoding="utf-8"))["build_id"]))' \
  "$HBCB_API_TMP/build.json")
export HBCB_API_BASE HBCB_API_TMP HBCB_BUILD_ID
printf 'queued build %s\n' "$HBCB_BUILD_ID"
```

Poll against a ten-minute deadline, with each HTTP request capped at 15 seconds.
The loop breaks on a terminal state, a request or response error, or the
deadline; it does not call `exit`, so it is safe to paste into an interactive
shell:

```sh
HBCB_BUILD_STATUS=unknown
HBCB_POLL_ATTEMPT=0
HBCB_POLL_DEADLINE=$(( $(date +%s) + 600 ))
while test "$HBCB_POLL_ATTEMPT" -lt 300 && \
  test "$(date +%s)" -lt "$HBCB_POLL_DEADLINE"; do
  if ! curl --fail-with-body --silent --show-error \
    --connect-timeout 5 \
    --max-time 15 \
    --header @"$HBCB_API_TMP/auth.header" \
    --output "$HBCB_API_TMP/status.json" \
    "$HBCB_API_BASE/v1/builds/$HBCB_BUILD_ID"; then
    HBCB_BUILD_STATUS=request_error
    break
  fi
  if ! HBCB_BUILD_STATUS=$(python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["status"])' \
    "$HBCB_API_TMP/status.json"); then
    HBCB_BUILD_STATUS=response_error
    break
  fi
  printf 'status: %s\n' "$HBCB_BUILD_STATUS"
  case "$HBCB_BUILD_STATUS" in
    succeeded|failed|canceled|needs_review) break ;;
  esac
  HBCB_POLL_ATTEMPT=$((HBCB_POLL_ATTEMPT + 1))
  sleep 2
done
case "$HBCB_BUILD_STATUS" in
  succeeded) printf 'build succeeded\n' ;;
  *) printf 'build did not succeed; stop before downloading artifacts (status: %s)\n' \
    "$HBCB_BUILD_STATUS" ;;
esac
```

Continue only if the final line says `build succeeded`. List the immutable
artifacts and download the preview without putting its short-lived signed URL
in the shell command line:

```sh
curl --fail-with-body --silent --show-error \
  --header @"$HBCB_API_TMP/auth.header" \
  --output "$HBCB_API_TMP/artifacts.json" \
  "$HBCB_API_BASE/v1/builds/$HBCB_BUILD_ID/artifacts"

python3 -c '
import json, pathlib, sys, urllib.request
document = json.load(open(sys.argv[1], encoding="utf-8"))
preview = next(item for item in document["artifacts"] if item["path"] == "preview.png")
with urllib.request.urlopen(preview["download_url"], timeout=30) as response:
    pathlib.Path(sys.argv[2]).write_bytes(response.read())
' "$HBCB_API_TMP/artifacts.json" "$HBCB_API_TMP/preview.png"

printf 'downloaded %s\n' "$HBCB_API_TMP/preview.png"
```

To cancel instead, run the following while a build is `queued` or `running`:

```sh
curl --fail-with-body --silent --show-error \
  --request POST \
  --header @"$HBCB_API_TMP/auth.header" \
  --header 'Content-Length: 0' \
  --output "$HBCB_API_TMP/cancel.json" \
  "$HBCB_API_BASE/v1/builds/$HBCB_BUILD_ID/cancel"
```

When finished, stop the stack and remove only this command's private scratch
directory:

```sh
make service-down
rm -r "$HBCB_API_TMP"
unset HBCB_API_BASE HBCB_API_TMP HBCB_BUILD_ID HBCB_BUILD_STATUS
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
Idempotency-Key: facet-request-0001

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
