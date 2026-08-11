# Configuration

The project separates a small character request from trusted runtime
configuration. A request can choose only reviewed model controls; it cannot
choose commands, paths inside the worker, URLs, credentials, Blender add-ons,
renderer flags, or arbitrary Python.

## One-shot Make variables

Pass overrides on the command line so each invocation is reviewable:

```sh
make build \
  REQUEST="$PWD/examples/requests/facet-bot.json" \
  OUTPUT_NAME=facet-bot
```

| Variable | Default | Purpose |
|---|---|---|
| `REQUEST` | Bundled Facet Bot request | Absolute or repository-relative input JSON path |
| `OUTPUT_NAME` | `demo` | Safe, lowercase child directory under `build/` |
| `BUILDER_IMAGE` | `headless-blender-character-builder:dev` | Local image tag used by the wrapper |
| `DOCKER` | `docker` | Docker CLI command for controlled/test environments |
| `PLATFORM` | `linux/amd64` | Release platform; other values are not release-supported |
| `PYTHON` | `python3` | Host Python command used by non-container orchestration |
| `BLENDER` | `blender` | Exact Blender 4.5.12 executable for best-effort native use |

`OUTPUT_NAME` must be at most 48 characters and match lowercase words joined by
single hyphens. It is not a path. Existing output is never overwritten.

The request fixes `generator`, `output_profile`, `render_profile`, and
`quality_profile` to versioned allowlisted values. See the
[character guide](character-spec.md) for the complete JSON contract.

## Local service `.env`

Create local credentials once:

```sh
make init-env
make service-config
```

`make init-env` uses the operating system random source, writes an ignored
mode-`0600` `.env`, prints no secret, and refuses overwrite. It creates separate
credentials for API authentication, idempotency, database roles, Redis, and
artifact-storage roles. These are local infrastructure credentials—not OpenAI,
cloud, or Blender license keys.

Treat `.env` and the named Compose volumes as a matched set. `make service-down`
preserves both data and volume-side credentials. Do not replace `.env` while
those volumes remain; restore the original file or deliberately dispose of the
local data first. See [Troubleshooting](troubleshooting.md#local-asynchronous-service).

The local service binds only to loopback. `make service-config` validates the
resolved Compose configuration without starting the application, although it
may first ensure the trusted builder image exists.

## VPS configuration

The VPS reference uses publisher-supplied digest-pinned image metadata, a
release lock, and role-scoped secret files—not the development `.env`. The
checked-in release lock is a rejected placeholder because no deployable release
is currently published. Follow the status banner and named-secret mapping in
the [deployment guide](deployment.md); never improvise production values from
the local Compose setup.

## Release variables

Maintainers can select a candidate identifier and unique evidence directory:

```sh
make release-static RELEASE_VERSION=0.1.0-rc.1
HBCB_RELEASE_RUN_ID=public-check-2 make release-check \
  RELEASE_VERSION=0.1.0-rc.1
```

Evidence directories are no-clobber. Release and dependency pins must be
updated through the coordinated process in
[Dependency maintenance](dependency-maintenance.md), not through ad hoc
environment overrides.
