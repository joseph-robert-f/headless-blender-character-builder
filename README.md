# Headless Blender Character Builder

For the unsigned developer package, read [HBCB REVIEW PREVIEW](docs/review-preview.md).
This read-only program opens evidence from existing projects.
Python and Node installation is not necessary.
The program cannot make models.
It does not add native model generation on Windows or Mac.

This system uses Blender to make a small geometric character from a JSON request.
It gives you a preview image, a Blender scene, a GLB file, and an STL file.
GLB is a portable 3D-model format.
STL is a format for 3D printing.

The primary workflow uses Docker without a graphical Blender interface.
A host Blender installation, an AI key, and a provider account are not necessary.

![Facet Bot model from the headless Blender pipeline](docs/assets/facet-bot-preview.png)

This image is an optimized copy of `preview.png` from a Blender build that passed its checks in a container.
The same build made a `.blend` file that Blender can open again, a GLB file, and a single-shell STL file.
It also made three diagnostic views, geometry QA results, and a hash manifest.
The [asset manifest](docs/assets/manifest.json) records the source information and the CC0 license.

> **v0.1 support boundary:** Use the builder locally as one trusted person.
> Use only requests that you made or examined.
> The optional Compose service is experimental and local-only.
> The project has no hosted service, published container images, or package on PyPI.
> Do not install a package with almost the same name.
> Read [Installation](docs/installation.md) for the full support boundary.

## Build your first model

Before you start, make sure that these tools and resources are available:

- Git: `git --version`
- Docker Engine or Docker Desktop: `docker info`
- GNU Make: `make --version`
- Approximately 4 CPU cores, 8 GB RAM, and 10 GB of free disk space.

For macOS, read [macOS without Homebrew](docs/installation.md#macos-without-homebrew).
That procedure uses Docker Desktop.
For Linux, read the Docker Engine installation commands in [Linux](docs/installation.md#linux).
For Windows, use the experimental [Windows with WSL2](docs/installation.md#windows-with-wsl2-experimental) procedure.

Start Docker.
Enter these commands:

```sh
git clone https://github.com/joseph-robert-f/headless-blender-character-builder.git
cd headless-blender-character-builder
./scripts/doctor
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
```

If a step does not complete, enter `./scripts/doctor` again.
This command examines Git, Docker, and Make.
It gives instructions to correct problems.
The success marker is `HBCB_DOCTOR: PASS`.
Read the [troubleshooting guide](docs/troubleshooting.md) if the problem continues.

The first build downloads some gigabytes, which include the pinned base image and Blender 4.5.12 LTS.
Network access is necessary for this download.
The download and build time change with your connection and hardware.
Generation and verification then use new containers without network access.
Subsequent builds use the Docker cache again and usually take less time.

When the build and verification pass, they show these markers:

```text
BUILDER_BUILD: PASS
BUILDER_VERIFY: PASS
```

Your model is in `build/facet-bot/`.
Open `preview.png` first.
Then select the applicable artifact:

| Artifact | Instruction |
|---|---|
| `model.blend` | Open the scene in Blender 4.5.12 LTS. The display meshes do not connect to each other. The printable shell is `PRINT/PrintableShell`. |
| `model.glb` | Open the display model in a GLB viewer. You can also import it into a compatible 3D tool or engine. |
| `model.stl` | Open the single-shell export in a slicer. Select **millimeters**. STL files do not store units. |
| `preview.png` | Examine the presentation image without a 3D application. |
| `diagnostics/*.png` | Compare the front, side, and back geometry views. |
| `qa.json` | Read the geometry measurements and QA result. |
| `manifest.json` | Examine the source information for the other eight artifacts. It includes request, generator, Blender, execution, size, and SHA-256 data. |

Enter `make inspect OUTPUT_NAME=facet-bot` to see a summary with fixed limits of the manifest and QA results.
This read-only summary contains no paths.
Use `make verify` to verify the artifacts independently.

The builder does not overwrite an existing output.
To keep a result, move it to a different location.
As an alternative, select a new output name.
These commands move the result and make a new model:

```sh
mv build/facet-bot build/facet-bot.previous
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot
```

The [installation guide](docs/installation.md) gives more procedures.
It includes platform installation, direct Docker commands, native Blender, updates, and cleanup.

## Make it yours

A request is JSON with fixed limits.
The generator does not accept code, paths, URLs, add-ons, or Blender flags in a request.
The example below shows part of its interface:

```json
{
  "request_version": "build/v1",
  "generator": "geometric-character@1.0.0",
  "spec": {
    "name": "Facet Bot",
    "style": "geometric",
    "height_mm": 95,
    "palette": ["#E87532", "#FFF3D6"],
    "proportions": { "head_scale": 1.2, "body_scale": 0.95, "limb_scale": 0.95 }
  }
}
```

This example is part of [`examples/requests/facet-bot.json`](examples/requests/facet-bot.json).
The full request also sets `spec_version`, `slug`, `pose`, `material_preset`, `eye_preset`, `components`, and `base`.
It sets the output, render, and quality profiles.
Read the [character contract](docs/character-spec.md) for these fields.

Copy the example to the ignored build directory.
Change the documented fields.
Give each build a different lowercase output name with hyphens:

```sh
mkdir -p build/requests
cp examples/requests/facet-bot.json build/requests/my-character.json
# Edit build/requests/my-character.json using docs/character-spec.md.
make validate REQUEST="$PWD/build/requests/my-character.json"
make build REQUEST="$PWD/build/requests/my-character.json" OUTPUT_NAME=my-character
make verify REQUEST="$PWD/build/requests/my-character.json" OUTPUT_NAME=my-character
```

Read [Examples and project ideas](examples/README.md) first.
Use the [configuration reference](docs/configuration.md) and [character contract](docs/character-spec.md) for the permitted fields.
The supplied `moss-hopper` request demonstrates a QA rejection.
Its wall evidence is not conclusive.
Thus, the builder returns `needs_review` and does not publish an artifact tree with a PASS result.

You can use this v0.1 generator for:

- Original desk mascots and geometric creatures
- Repeatable GLB test fixtures for viewers, engines, and asset pipelines
- Print-oriented prototypes for slicer examination before a test print
- Classes or workshops that use procedural geometry
- CI demonstrations for which a PNG file is not sufficient evidence.

The generator does not give unrestricted text-to-3D generation, organic sculpture, protected-character copies, or arbitrary Blender automation.
It does not guarantee that a physical print will be correct.

## How the model is proved

Verification includes more than file-existence checks:

- A new Blender process opens `model.blend` with factory startup settings.
- It identifies mesh objects, vertices, faces, materials, finite transforms, and 3D bounds.
- It imports GLB and STL into empty scenes.
- It compares imported dimensions with recorded dimensions with the specified tolerances.
- The STL must have one face-connected, watertight shell with outward orientation and positive volume.
- The STL must have no non-manifold edges or zero-area faces.
- The verifier calculates each artifact byte count and SHA-256 again before it accepts the manifest.

During a build, the verifier also compares the saved scene with its structural fingerprint.
These checks do not compare each surface across the model formats.
They show that the model contains geometry and that the examined internal data agree.
They do not replace slicer settings, material selection, printer calibration, supports, or physical tests.

## Choose a workflow

| Goal | Procedure | Prerequisites |
|---|---|---|
| Make one model locally | [Container quickstart](docs/installation.md#container-path-recommended) | Git, Docker, GNU Make |
| Make a model without Make | [Direct Docker commands](docs/installation.md#docker-without-make) | Git and Docker |
| Develop with host Blender | [Native path](docs/installation.md#native-blender-best-effort) | Python 3.11+ and Blender 4.5.12 LTS only |
| Evaluate the experimental local HTTP API | [Asynchronous service](#optional-asynchronous-service) | One trusted operator, Docker Compose 2.24.4+, Python 3.11+, 8 GiB Docker memory, and 20 GB free disk space |
| Examine the VPS design not in v0.1 support | [VPS runbook](docs/deployment.md) | Operations and security knowledge |
| Contribute | [Contribution guide](CONTRIBUTING.md) | A change with a small scope, an issue where necessary, applicable tests, and DCO sign-off |

The release reference is `linux/amd64`.
Docker Desktop on Apple Silicon uses emulation and can operate for evaluation.
Linux `arm64` has best-effort support.
WSL2 is experimental.
Read [Compatibility](docs/compatibility.md).

## Optional asynchronous service

> **Experimental and local-only:** Use this service on loopback as one trusted operator.
> Use only requests that you made or examined.
> Internet-facing operation, multiple users, and hostile input are not in v0.1 support for this service.

The service includes an authenticated API, PostgreSQL, Redis, versioned S3-compatible local storage, and one Blender worker.
It uses the same builder contract.
An AI-provider key is not necessary.

If `python3 --version` is earlier than 3.11, enter `export PYTHON=python3.11` first.
You can select a different installed Python 3.11+ executable.
This setting applies to the current terminal session.

```sh
./scripts/doctor --service
make init-env
make service-config
make service-up
make service-ps
```

The `service-ps` output must show `api`, `worker`, PostgreSQL, Redis, and MinIO in operation.
The one-shot `database-init` and `minio-init` rows must show `Exited (0)`.
Submit the supplied request to save one verified result:

```sh
make service-client REQUEST="$PWD/examples/requests/facet-bot.json"
```

After use, stop the service for this checkout with `make service-down`.

`make init-env` makes an ignored `.env` file with mode `0600` one time.
It does not overwrite the file or show secrets.
Read [Configuration](docs/configuration.md#local-service-env) for checkout identity and legacy volumes.

The API and artifact downloads bind to host loopback.
PostgreSQL and Redis have no published ports.
The worker container connects only to its necessary internal service networks.
Its new Blender child gets an environment without API, database, queue, storage, provider, or Docker credentials.
The child shares the supervisor container's network namespace.
It does not have its own network isolation.

The local MinIO image is a pinned compatibility fixture.
It is not a recommendation for production object storage.
Do not expose this service publicly.
Before integration or operation, read these documents:

- [Lightweight HTTP API client](docs/api.md#lightweight-local-client)
- [Troubleshooting](docs/troubleshooting.md)
- [Architecture](docs/architecture.md)
- [VPS availability](docs/deployment.md#availability).

Use `make service-client` for the first evaluation and custom requests.
The slower `make service-smoke` command is an integration test for maintainers.
It does direct builds and service builds, restarts the API, tests cancellation and IAM, and keeps evidence.
It can add a 4 GiB builder workload.
Before this test, give Docker a minimum of 12 GiB of memory.

## Security, rights, and print limits

- The stable builder accepts only declarative JSON that passes schema validation.
- Uploaded `.blend` files, request-authored Python or shell code, archives, remote URLs, host paths, and add-ons are invalid or not in scope.
- One-shot build and verification containers use a non-root account, no network, a read-only root filesystem, no capabilities, and resources with fixed limits.
- Blender is trusted generator code. It is not a sandbox for hostile scripts or files.
- STL numeric coordinates are millimeters. STL has no unit metadata.
- Automated QA cannot certify physical safety, durability, food safety, child safety, medical use, electrical use, or load-bearing capacity.
- You are responsible for rights to designs, names, references, logos, likenesses, and outputs.
- This project grants no rights to Pokémon or other third-party characters or brands.
- v0.1 support includes the trusted local one-shot builder. The optional local service is experimental.
- Public, multi-tenant, and VPS operation are not in scope.
- The project has no billing system, SLA, automatic IP clearance, or print-success warranty.

Read [OUTPUT_POLICY.md](OUTPUT_POLICY.md), [SECURITY.md](SECURITY.md), and [SUPPORT.md](SUPPORT.md).
Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/joseph-robert-f/headless-blender-character-builder/security/advisories/new).
Do not put vulnerability details in a public issue.

## Develop and verify the project

Use these maintainer commands as applicable:

```sh
make test-unit          # contracts, policies, service units, and security tests
make test-blender       # real headless Blender integration gates
make check              # lint/static, unit/security, and Blender checks
make dependency-check   # verify synchronized dependency pins offline
make dependency-audit   # report upstream version/image status without mutation
make dependency-scan    # vulnerability-scan locks and release images
make release-static     # audit tracked source, policies, licenses, docs, and CI
HBCB_RELEASE_RUN_ID=review-1 make release-check  # complete clean-index gate
```

The release run ID is mandatory.
Use a different ID for each checkout on the same Docker daemon.
`make release-check` makes local evidence and versioned image tags from a clean export of the Git index.
It does not push images, make a Git tag or Release, deploy infrastructure, or read registry credentials.
Read the [release process](docs/release-process.md) and [dependency maintenance guide](docs/dependency-maintenance.md).

## Documentation

### User-facing docs

- [Installation](docs/installation.md): installation, first build, artifacts, cleanup, updates, direct Docker, and native use
- [Examples and ideas](examples/README.md): initial requests and uses
- [Configuration](docs/configuration.md): Make variables and service configuration
- [Character and request contract](docs/character-spec.md): permitted JSON fields
- [Documentation index](docs/README.md): documents for users, integrators, contributors, and operators
- [Troubleshooting](docs/troubleshooting.md): success markers and usual failures.

### Project and contributor material

- [Architecture](docs/architecture.md) and [threat model](docs/threat-model.md)
- [PLAN.md](PLAN.md), [TEST_PLAN.md](TEST_PLAN.md), and [progress evidence](docs/progress.md)
- [Backlog](docs/backlog.md): work after v0.1, which includes prompt planning and MCP
- [Contributing](CONTRIBUTING.md): change scope, tests, and DCO sign-off.

OpenAI, Codex, and MCP are not v0.1 dependencies.
A future prompt planner or MCP adapter can use the JSON or API contract with its fixed limits.
These components do not give a different code-execution interface at this time.

## License

Project source is GPL-3.0-or-later.
The original tracked preview has its own CC0-1.0 dedication.
Read [ASSET_LICENSE.md](ASSET_LICENSE.md).
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) records dependencies and redistribution notices.
Generated outputs are subject to their inputs, templates, applicable law, and [OUTPUT_POLICY.md](OUTPUT_POLICY.md).
