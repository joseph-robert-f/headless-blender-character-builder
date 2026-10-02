# Troubleshooting

First, do read-only preflight from the repository root:

```sh
./scripts/doctor
```

For the local API stack, use `./scripts/doctor --service`.
For the native Blender procedure, use `./scripts/doctor --native`.
Native mode has no compatibility guarantee.

The doctor does not install or download packages, pull images, start
containers, or change Docker state. It queries only the configured clients
and Docker daemon. The one-shot doctor can examine a remote daemon.

But `--service` rejects a remote SSH, TCP, or HTTP Docker context.
The local API procedure uses host loopback on this computer.
Correct each `FAIL` before you use the longer command again.

<a id="what-success-looks-like"></a>
## Success criteria

A request-only check ends with this output:

```text
BUILDER_VALIDATE: PASS
```

A full one-shot build and separate reopen end with this output:

```text
BUILDER_BUILD: PASS
BUILDER_VERIFY: PASS
```

The exit status must also be `0`. `qa.json` must contain `"status":"passed"`.
EGL, OpenGL, emulation, or audio warnings can show at headless Blender
startup. Warnings alone do not show success or failure.

Any of these conditions shows a publication failure:

- A nonzero exit
- A `BUILDER: FAIL[n]` line
- A missing `manifest.json`
- QA without a pass.

The builder uses a private staging area. It rejects existing output paths.
If generation or QA fails, it removes its staging area. It must not keep
a partial named result.

<a id="quick-diagnosis"></a>
## Fault diagnosis

| Symptom | Possible cause | Safe next action |
|---|---|---|
| `Docker is unavailable` | Docker CLI is not installed or is not on `PATH` | Install and open Docker Desktop/Engine. Use `./scripts/doctor` again. |
| `Docker daemon is not reachable` or socket permission error | Docker is stopped, the user has no daemon access, or the selected context is not available | Make sure that `docker info` succeeds as your user. On Linux, obey [Docker's non-root guidance](https://docs.docker.com/engine/install/linux-postinstall/) and its root-equivalent group warning. Do not use general `sudo` commands to bypass permissions. |
| `local service requires a local Docker daemon/context` | SSH, TCP, or HTTP selects a remote endpoint. Its loopback ports are on a different host. | Select a local context in Docker Desktop or with `docker context use <local-context>`. Clear `DOCKER_HOST` or `DOCKER_CONTEXT` if it selects the remote daemon. Use `./scripts/doctor --service` again. |
| Failure during Blender/Debian input download | The image build uses outbound HTTPS/DNS access to specified sources | Do checks of proxy, DNS, and firewall settings. Retry `make image`. Keep checksum and digest verification unchanged. |
| BuildKit/frontend error | Docker is too previous, or BuildKit/Buildx is not available | Upgrade Docker. `docker build` must accept `--platform` and the specified Dockerfile frontend. |
| `linux/amd64` platform or emulation error | The release image is amd64, but emulation is not available | Enable Docker Desktop amd64 emulation or use an amd64 Linux host. |
| `linux/amd64` error on Linux `arm64` | The host has no amd64 emulation that operates. v0.1 has no permitted checksum-pinned native arm64 Blender archive. | Configure the host's maintained Docker/binfmt emulation. Make sure that a simple `linux/amd64` container operates. As an alternative, use an amd64 Linux host. The emulation procedure has no release-support guarantee. |
| Very slow first build on Apple Silicon | Blender and its base image use amd64 emulation | Wait longer. Subsequent builds use verified local layers again. |
| Builder code / Make `Error 137`, or daemon reports OOM | Docker killed Blender because memory was not sufficient | Close large workloads. Give Docker a minimum of 4 GiB for the one-shot procedure. Retry with a new output name. |
| `no space left on device` | Image layers, cache, or outputs filled Docker/host storage | Examine `docker system df` and host free space. Independently identify disposable data before removal. Do not prune service volumes without inspection. |
| Bind mount/file-sharing error on macOS | The checkout is outside Docker Desktop shared paths | Move the repository to a shared path, or share its path in Docker Desktop. Use the doctor again. |
| `docker: command not found` inside WSL2, or Docker access fails from WSL | Distribution integration is disabled, Docker Desktop is stopped, or Engine is installed only on Windows | Enable Docker Desktop WSL integration for this distribution, or install Engine inside it. Make sure that `docker info` succeeds from the same WSL shell. Then use the doctor again. WSL2 stays experimental. |
| WSL2 bind mounts are slow or give unexpected Windows permissions | The checkout is below `/mnt/c/...`. It is not in the WSL filesystem | Move the checkout below the WSL home directory, for example `~/headless-blender-character-builder`. Use that WSL shell for each project command. |
| Native Windows shell or path errors | Native Windows without WSL2 has no validation for the POSIX build shell, path, and permission contracts | Use the documented experimental WSL2 procedure or an amd64 Linux host. Do not translate build commands without validation of equivalent release behavior. |
| Output files are not accessible | A previous root operation or unusual Docker mapping owns them | Do not do the build again as root. Examine ownership. Move the previous result before a new named build. |
| `HBCB_MAKE: FAIL[request_missing]` | `REQUEST` does not identify an existing regular file | Set `REQUEST=/absolute/path/to/request.json`. Make does this check before an image build or inspection. |
| `HBCB_MAKE: FAIL[output_exists]` | There is output at the selected path. Publication does not overwrite it. | Select a new safe `OUTPUT_NAME`, or move the full previous output. |
| `HBCB_MAKE: FAIL[output_missing]` | `make verify` cannot find a regular, non-symlink output directory | First use `make build` with the same `REQUEST` and `OUTPUT_NAME`, or correct the name. Verification rejects output-directory symlinks. |
| `HBCB_MAKE: FAIL[manifest_missing]` | `make inspect` cannot find a regular, non-symlink `manifest.json` | Make sure that `OUTPUT_NAME` is correct. Complete `make build` and `make verify`. Do not use a different output's manifest. |
| `output must not already exist` / `BUILDER: FAIL[4]` | A direct builder command found an existing output | Select a new output path, or move the full previous output. |
| `manifest request provenance mismatch` / `BUILDER: FAIL[11]` | The verification request is different from the build request | Use the same request that made the manifest for verification. Compare its recorded request hash. |
| `manifest baked provenance mismatch`, `manifest image provenance mismatch`, or `manifest source provenance mismatch` / `BUILDER: FAIL[11]` | The verifier uses different project source or a different container image | Keep the previous output unchanged for inspection. Use the source checkout for a new output build and verification. Advanced operators can use this alternative: keep and use the same previous image recorded in the manifest. |
| `manifest Blender binary provenance mismatch` / `BUILDER: FAIL[11]` | The Blender binary is different from the build record | Use the same Blender binary for verification. As an alternative, make and verify a new output with the selected Blender 4.5.12 binary. |
| `BuildRequest was rejected` / `BUILDER: FAIL[3]` | JSON, field, enum, size, or runtime contract violation | Use `make validate REQUEST=/absolute/path/request.json`. Compare the request with the [character guide](character-spec.md). |
| `needs_review` / `BUILDER: FAIL[11]` without output | Mandatory geometry evidence was unknown or below policy limits | Read the reason after `safe diagnostics:` in the preceding `BLENDER_BUILDER: FAIL[11]` line. Change the recipe and use a new output name. Do not make an incorrect success manifest. |
| Native Blender exits during Metal initialization | Host Blender/backend incompatibility occurred before project code | Use the Docker procedure. Native macOS has no compatibility guarantee, even with Blender 4.5.12. |

## Named builds and reruns

The README first-build procedure uses `build/facet-bot`.
The previous `make demo` alias uses `build/demo`. For different work, use a
separate output name to keep the two results:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot.json"
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-2
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-2
```

`OUTPUT_NAME` is one lowercase directory name with hyphens between words.
Its maximum length is 48 characters. The builder rejects paths, slashes,
`.`/`..`, spaces, shell syntax, and uppercase names. Published output is
immutable. The builder has no overwrite switch.

To read a size-limited provenance and QA summary, examine the selected success
manifest. This command prints no artifact paths, image references, or signed URLs:

```sh
make inspect OUTPUT_NAME=facet-bot
```

This command is read-only. It does not reopen Blender, GLB, or STL artifacts.
`make verify` stays the separate artifact check.

## Builder codes versus Make's exit status

These codes belong to the `builder` process. Direct `builder` or `docker run`
execution returns the code to its caller. If a Make recipe fails, GNU Make
usually exits `2`. It does not return the recipe's code.

Read the preceding `BUILDER: FAIL[n]` marker or GNU Make `Error n` diagnostic
for the builder status. For example, a geometry inspection failure usually
gives this output:

```text
BLENDER_BUILDER: FAIL[11]: mandatory geometry QA status is needs_review; safe diagnostics: minimum wall measurement unavailable
BUILDER: FAIL[11]: Blender build failed
make: *** [build] Error 11
```

The shell status after that `make build` command is usually `2`.
The builder status stays `11`. Named `HBCB_MAKE: FAIL[...]` markers identify
Make precondition failures. They stop before Docker work and use recipe status `2`.

| Builder code | Meaning |
|---:|---|
| `0` | Requested operation passed |
| `2` | Invalid CLI use or unsupported option |
| `3` | Request rejected |
| `4` | Input/output filesystem or no-clobber failure |
| `10` | Blender executable/startup failure |
| `11` | Geometry/artifact verification failure or necessary inspection |
| `12` | Internal trusted-launcher failure |
| `124` | Controlled timeout |
| `128`–`255` | Signal termination of a child process or equivalent platform status |

At the public CLI boundary, unexpected failures do not show tracebacks,
host paths, environment values, or exception details.

## Local asynchronous service

First, do these prerequisite checks:

```sh
./scripts/doctor --service
make init-env
make service-config
```

The local stack has these requirements:

- Python 3.11+
- Docker Compose 2.24.4+
- A minimum of 8 GiB for Docker
- 20 GB of free disk space
- Two free loopback ports.

The default ports are `8080` for the API and `9000` for the artifact fixture.
If `python3` is older, use the same explicit selection for each command.
Start with this command:

```sh
PYTHON=python3.11 ./scripts/doctor --service
PYTHON=python3.11 make service-config
PYTHON=python3.11 make service-up
```

Use the project wrappers for read-only status and size-limited logs:

```sh
make service-ps
make service-logs
```

`service-ps` includes stopped containers for this checkout. `service-logs`
prints only the last 100 lines from `api` and `worker`.
Do not use raw Compose commands as alternatives. The wrapper restores the
checkout identity, selected ports, and necessary image-provenance interpolation.

Sanitize these logs before you share them. Do not put these data in a public issue:

- `.env` or bearer tokens
- Database or Redis URLs
- Storage credentials
- Private references or signed artifact URLs
- Unredacted request/model content.

Common service conditions follow:

- **Missing `.env` on a new checkout:** Use `make init-env` one time.
  It makes an ignored file with mode `0600`. It records a checkout-specific
  Compose project identity. It does not overwrite existing files.
- **Existing `.env`:** Keep it. `make service-down` keeps PostgreSQL, Redis,
  and MinIO volumes. Their credentials are related to that file.
- **Older `.env` without `HBCB_COMPOSE_PROJECT_NAME`:** The stack uses the
  previous `hbcb-local` identity. Existing containers and volumes stay
  accessible. Do not add or change the identity only to remove a warning.
- **Moved checkout:** Keep `.env`. Its stored identity selects the same Docker
  resources. If you use `COMPOSE_PROJECT_NAME`, give the same safe value
  to each command. A different value selects a different stack. It does not migrate data.
- **Missing `.env` with previous named volumes:** Restore the initial `.env`
  from an access-controlled local backup. New generated credentials do not
  change credentials inside existing volumes.
- **Disposable previous data:** Stop the stack. Make sure that no necessary local
  data or backup stays. Use the active Docker context's project view,
  for example Docker Desktop on macOS/Windows. Select only this project's
  named volumes. Use the project name from `make service-ps`.

  Do not select names that only look the same or use global prune. This deletion is irreversible.
  Only after volume removal, move the previous `.env` and use `make init-env` again.
  The project has no one-command reset that could accidentally erase volumes.
- **Port conflict:** Find and stop the program on `127.0.0.1:8080` or
  `127.0.0.1:9000`. As an alternative, select different loopback host ports for
  all commands. For example, use
  `export HBCB_API_HOST_PORT=18080 HBCB_STORAGE_HOST_PORT=19000`, then
  `make service-up` in the same terminal.

  Ports must be different canonical decimal values from 1 through 65535.
  Do not change the bind address to a public interface.
- **Changed trusted builder source:** Use `make service-up` again.
  Its wrapper makes the builder image from the source before service startup.
- **Unhealthy dependency:** Examine `ps` output and a specified maximum number of last log lines.
  Keep `.env` and volumes. Use `make service-down`, then `make service-up`.
  Do not use volume pruning as a general repair.
- **API status `needs_review`:** The service gives the stable
  `builder_needs_review` terminal code, not private child output.
  Use the same JSON with one-shot `make build`. Read the size-limited
  `safe diagnostics:` reason before you change the character.
- **Docker OOM or unresponsive host:** Steady service limits total
  approximately 7 GiB RAM and 7.5 CPUs. Initialization can increase totals
  to approximately 7.375 GiB and 8.25 CPUs. Stop other workloads or give
  Docker more resources. The maintainer smoke adds a separate 4 GiB builder
  workload. For that test, give Docker a minimum of 12 GiB.

### PostgreSQL image upgrade and existing volumes

The local and VPS PostgreSQL runtime changed from the official Debian image
to a derived gosu-free Alpine image. The previous image was
`postgres:16.14-bookworm`. It used a root entrypoint and changed `PGDATA`
ownership to UID 999. The new image operates as UID/GID 70:70.

Alpine uses musl. It does not use glibc. This changes locale/collation behavior.
Thus, a `postgres-data` volume from before the change is dangerous for in-place use.
The new image cannot write PGDATA that it does not own. Even after an
ownership correction, collation-dependent sort order and indexes can disagree
without an error that the operator can see.

Before stack startup, `make service-up` finds this condition and stops.
Its error names the volume. It does not automatically delete or migrate data.
Use dump and restore. Do not attach the previous volume to the new image.

1. Start the **previous** specified image directly with the stored volume and make
   a dump. For this one-time step, use `docker run`. Do not use the Compose
   wrapper, because `compose.yaml` always makes the Alpine target:

   ```sh
   project=$(grep '^HBCB_COMPOSE_PROJECT_NAME=' .env | cut -d= -f2-)
   docker run --detach --name pgdata-migrate \
     -v "${project}_postgres-data:/var/lib/postgresql/data" \
     -e POSTGRES_PASSWORD=migrate-only \
     postgres:16.14-bookworm@sha256:64154d0babcb1741988719e703419af0382b19953706149f9872fbd0f438efa8
   docker exec pgdata-migrate pg_isready --quiet   # wait until this succeeds
   docker exec pgdata-migrate pg_dumpall --username postgres > pgdata-backup.sql
   docker stop pgdata-migrate && docker rm pgdata-migrate
   ```

2. Rename or keep the previous volume. Do not prune it automatically:

   ```sh
   docker volume ls   # confirm the exact name: ${project}_postgres-data
   docker container run --rm \
     -v "${project}_postgres-data:/from" \
     -v "${project}_postgres-data-pre-alpine:/to" \
     alpine sh -c 'cp -a /from/. /to/.'
   docker volume rm "${project}_postgres-data"
   ```

3. Start the new stack to initialize a new UID-70 volume. Restore directly
   through the `postgres` container in operation. Compose names it
   `<project>-postgres-1`. Make sure of the name with `make service-ps`:

   ```sh
   make service-up
   docker exec -i "${project}-postgres-1" \
     psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" < pgdata-backup.sql
   ```

For disposable local development data, the operator can select deletion
as an alternative to migration. The tools do not make this decision automatically:

```sh
make service-down
docker volume rm "${project}_postgres-data"
make service-up
```

Use the project name from `make service-ps`. Do not select resource
names that only look the same or use global volume prune.

A lightweight client operation with a pass ends with this output:

```text
verified model and evidence saved in .../build/service-client/<build-id>/artifacts
```

The directory contains nine verified builder artifacts and `build.json`.
The slower maintainer integration check ends with this output on success:

```text
SERVICE_SMOKE: PASS project=<checkout-project> evidence=.../build/service-smoke/run.XXXXXX
```

This optional gate does direct and service builds, restart, cancellation,
artifact, Redis, and IAM checks. It keeps evidence under `build/service-smoke/`.
It is not necessary to start or try the API.

For the first evaluation of this experimental procedure, use
`make service-client REQUEST=/absolute/path/to/request.json`.
The [HTTP API guide](api.md) also gives a longer manual protocol example for integrators.

For image cleanup, stop the stack. List and examine the six tags for the
selected service project. Remove only that list:

```sh
make service-down
make service-images
make service-image-cleanup
```

The last command stops if Docker cannot show whether a tag is available.
It also rejects the shared `hbcb-local` identity. For that identity, examine
the list. Stop each older checkout that could share the tags before manual
removal of specified tags.

The helper keeps named PostgreSQL, Redis, and MinIO volumes and `.env`.
It keeps shared Docker/BuildKit cache. Docker does not identify a reliable
checkout owner for each cache record. Examine space with `docker system df`.
Do not use global image, builder, volume, or system prune for repair or cleanup.

Ignored `build/service-smoke/run.*` evidence is local output.
The image helper does not remove it.

## Release and deployment checks

`make release-static` is the fast, offline publication-policy check.
`HBCB_RELEASE_RUN_ID=<unique-safe-id> make release-check` makes images,
executes Blender and service tests, does recovery tests, and packages
sanitized evidence.

The full check uses Docker, Python 3.11+, and Compose 2.24.4+.
It also makes sufficient time, disk space, and a clean intended Git index necessary.

Evidence does not overwrite existing output. A run ID is mandatory.
Select a new unique lowercase value for each operation:

```sh
HBCB_RELEASE_RUN_ID=public-check-2 make release-check
```

Only one full release check can use a Docker daemon at a time.
If there is a `hbcb-release-check-claim`, examine the volume. Make sure whether
a previous release process is active. Do not delete or take over the claim
without maintainer approval. The wrapper keeps foreign or ambiguous claims unchanged.

Do not operate the VPS reference until publisher-supplied image digests,
source metadata, and a usable release lock are available. The checked-in example
lock has placeholders. Operator tools reject it. Refer to the
[deployment guide](deployment.md) for deployment failures and recovery rules.

<a id="ask-for-help-with-safe-evidence"></a>
## Safe bug reports

For a reproducible public bug report, include this information:

```sh
./scripts/doctor                 # or --service / --native
git rev-parse HEAD
uname -a
```

Also include the command, shell status, and last status line.
The line can be `PASS`, `BUILDER: FAIL[n]`, `HBCB_MAKE: FAIL[...]`, or `Error n`.
Include only applicable sanitized manifest/QA fields.

Do not attach a full build without redistribution rights.
Use the private process in [SECURITY.md](../SECURITY.md) for suspected
vulnerabilities. Do not use a public issue.
