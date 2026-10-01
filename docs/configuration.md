# Configuration

The project differents character requests from trusted runtime configuration.
A request can select only reviewed model controls.
It cannot select commands, worker paths, URLs, credentials, Blender add-ons,
renderer flags, or Python code.

## One-shot Make variables

To change a setting, give its value on the command line:

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
| `PLATFORM` | `linux/amd64` | Release platform. Other values are not release-supported |
| `PYTHON` | `python3` | Host Python command used by non-container orchestration |
| `BLENDER` | `blender` | Specified Blender 4.5.12 executable for best-effort native use |

`OUTPUT_NAME` must contain no more than 48 characters.
Use lowercase words with one hyphen between words. This value is not a path.
The builder does not overwrite existing output.

The request fixes `generator`, `output_profile`, `render_profile`, and
`quality_profile` to versioned allowlisted values. See the
[character guide](character-spec.md) for the complete JSON contract.

## Local service `.env`

Create the local credentials:

```sh
make init-env
make service-config
```

`make init-env` uses the operating system random source.
It writes an ignored mode-`0600` `.env` file and prints no secret.
It does not overwrite an existing file.
It creates different credentials for API authentication, idempotency,
database roles, Redis, and artifact-storage roles.
These credentials are for local infrastructure. They are not OpenAI, cloud,
or Blender license keys.

New `.env` files contain `HBCB_COMPOSE_PROJECT_NAME`.
This generated identity selects the checkout's containers, networks, and named volumes.
Move the checkout and its `.env` file together to keep the identity.
Existing `.env` files without this key keep the previous project name `hbcb-local`.
Thus, an upgrade does not disconnect existing volumes.

For automation, `COMPOSE_PROJECT_NAME` can replace the stored identity.
Use a supported safe value. Supply the same value to each command for that stack.
A different identity selects different resources. It does not rename or migrate existing volumes.

Service commands accept `PYTHON` when the default `python3` is older than 3.11:

```sh
PYTHON=python3.11 make service-config
PYTHON=python3.11 make service-up
```

The commands also accept `DOCKER` as one executable path for controlled environments.
Use the Make targets. They restore the checkout identity, image provenance,
and selected ports for each command.

The local API and storage endpoints bind only to loopback.
Select their host ports before startup. Use different canonical decimal port values
from 1 through 65535:

```sh
export HBCB_API_HOST_PORT=18080 HBCB_STORAGE_HOST_PORT=19000
make service-up
```

The defaults are `8080` and `9000`.
The `export` sets the ports for `service-config`, `service-up`, `service-ps`,
`service-logs`, the API client, and `service-down` in that terminal session.
As an alternative, change only the two nonsecret port-selector lines in the
private `.env` file before startup.

Keep `.env` with its related named Compose volumes.
`make service-down` keeps the data and volume-side credentials.
Do not replace `.env` while those volumes exist.
Restore the initial file, or delete the local data first. See [Troubleshooting](troubleshooting.md#local-asynchronous-service).

A PostgreSQL base-image change can make an existing `postgres-data` volume unsafe to use.
The Debian-to-Alpine, UID-999-to-70 change is one example.
`make service-up` detects this condition and does not start. See [PostgreSQL image upgrade and existing
volumes](troubleshooting.md#postgresql-image-upgrade-and-existing-volumes) for
the supported dump/restore path.

The local service binds only to loopback.
`make service-config` validates the resolved Compose configuration.
It does not start the application or build an image.
`make service-up` builds trusted builder and service images from the current checkout.
Then it starts the stack.

`make service-ps` shows this checkout's containers.
`make service-logs` prints only the last 100 API and worker lines.
`make service-down` stops containers and keeps named volumes.

## VPS configuration

The VPS design uses publisher-supplied image metadata with fixed digests,
a release lock, and different secret files for each role.
It does not use the development `.env` file.
The release lock in the repository is a placeholder that validation rejects.
No release for deployment is published.
Use the status banner and named-secret map in the [deployment guide](deployment.md).
Do not use local Compose values as production configuration.

## Release variables

Maintainers can select a candidate identifier and unique evidence directory:

```sh
make release-static RELEASE_VERSION=0.1.0-rc.1
HBCB_RELEASE_RUN_ID=public-check-2 make release-check \
  RELEASE_VERSION=0.1.0-rc.1
```

Commands do not overwrite evidence directories.
Use the procedure in [Dependency maintenance](dependency-maintenance.md)
to change release and dependency pins.
Do not change these pins through environment overrides.
