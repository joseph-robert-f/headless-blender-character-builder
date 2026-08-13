# Open-Source Headless Blender Character Builder

Status: **Executed v0.1 build plan and authoritative scope record**

Last updated: **August 12, 2026**

This document is the authoritative scope record for the first public
implementation. The release-blocking milestones **M0 through M5** and work
packages **G0 through G9** were executed in order using the defaults in Section
17, leaving a locally verified v0.1 release candidate. Section 20 preserves the
completed `/goal` contract for reproducibility. Post-v0.1 work is context, not
part of that completion target.

## 1. Proposed project

Build a public, self-hostable repository that turns a bounded `BuildRequest` JSON document—containing a nested `CharacterSpec`—into real Blender geometry and a verified set of artifacts through a headless worker.

The v0.1 source candidate implements three evaluation modes and one
deployment reference. Two more capable integrations are explicitly planned,
not present:

1. **Keyless single-container quickstart:** run `make demo` with Git and Docker only; build a bundled JSON request into real artifacts in `build/demo/` without Compose, an account, or an API key.
2. **Deterministic native CLI:** invoke the same runner with Blender installed locally for generator development and debugging.
3. **Docker Compose service:** submit asynchronous builds through HTTP and run them on local worker containers with durable state and artifact storage.
4. **VPS deployment reference (implemented source, not a published service):** review the same pinned builder lineage and artifact contract for one Linux VPS. The repository has not published the release package or immutable registry images needed for a live copy-paste deployment.

Post-v0.1 proposals, not implemented capabilities:

- **Optional prompt planner and MCP adapter:** a future bring-your-own-key planner could translate a brief into `CharacterSpec`, and a thin MCP adapter could call the deterministic build API.
- **Managed cloud deployment:** a future job-platform integration could run the same contract with separately designed cloud IAM and scaling.

The public promise should be deliberately narrow:

> Generate original geometric, chibi, or low-poly characters from native Blender primitives; export editable and portable formats; and report objective geometry and print-readiness checks.

It should **not** promise unrestricted text-to-3D, organic sculpting, exact likenesses, or guaranteed physical prints.

## 2. Product principles

- **No API key required for the core demo.** The deterministic worker is the product foundation; AI planning is only a post-v0.1 adapter proposal.
- **One container before one stack.** The README's primary path must prove useful geometry with one disposable worker container. Compose is the service path, not a prerequisite for evaluating the project.
- **One build contract everywhere.** Native CLI, the one-shot container, the asynchronous worker, and future cloud jobs must call the same validated runner rather than reimplementing Blender behavior.
- **Specifications over arbitrary code.** Callers submit a strict schema. The public service does not accept Python, shell arguments, add-ons, node graphs, filesystem paths, or container settings.
- **Synchronous locally, asynchronous as a service.** Direct CLI and one-shot-container builds run to completion for simple automation; HTTP requests return a build ID rather than holding a connection open while Blender runs.
- **One job, one fresh Blender process.** A build cannot inherit user preferences, cached scene state, or another customer's data.
- **Reproducible outputs.** Every result records canonical request/spec hashes, generator and Blender versions, source revision, mode-appropriate worker provenance, input hashes, and artifact hashes.
- **Evidence accompanies the model.** A successful build includes diagnostic renders and machine-readable QA, not only an STL or `.blend` file.
- **CPU first.** Geometry generation and validation should not require a GPU. GPU rendering remains an optional deployment optimization.
- **Original and rights-cleared inputs.** The project should not ship franchise character packs or imply that transforming an uploaded reference clears copyright or trademark rights.

## 3. Intended users

### Local evaluator

Wants one command that builds a known character and proves that it is genuine editable geometry.

### Application developer

Wants a stable HTTP contract that can be called from a web app, workflow, agent, or MCP server.

### Self-hosting operator

Wants a documented Docker/VPS deployment with authentication, resource limits, persistent job state, object storage, logs, backups, and upgrade guidance.

### Generator contributor

Wants to add a new bounded generator, component, material, export format, or QA check without rewriting the API and worker lifecycle.

## 4. What users need to bring

| Use case | Required | Optional |
|---|---|---|
| Primary quickstart | Git, Docker Engine/Desktop, and `make`; no Compose, account, or API key | A custom `BuildRequest` after the bundled demo succeeds |
| Native generator development | Exact Blender 4.5.12 LTS and Python 3.11+ development tools | Docker for release-parity checks |
| Full local service | Primary prerequisites plus Docker Compose 2.24.4+, Python 3.11+, and `curl` for the supported client journey | Another deliberately configured HTTP client; locally generated service credentials |
| Prompt-to-spec demo *(post-v0.1; not implemented)* | Local prerequisites plus an `OPENAI_API_KEY`, OpenAI API billing, and explicit planner enablement | Reference images the user owns or is licensed to use |
| Codex/MCP caller *(post-v0.1; not implemented)* | Running build service URL and service token | OpenAI API key only if this service performs prompt planning itself |
| VPS deployment reference *(source only; publication blocked)* | Linux VPS, Python 3.11+, Docker/Compose 2.24.4+, domain/TLS, API authentication secret, backups | Managed Postgres, Redis, and S3-compatible storage |
| Managed cloud deployment *(post-v0.1; not implemented)* | Cloud account, container registry, object-storage bucket, job-state database, queue, IAM/service identities, secret manager | GPU job capacity for faster previews |
| 3D printing workflow | Exact printer technology, material, nozzle/resin profile, minimum feature size, and slicer profile | A physical calibration/test-print process |

Suggested development capacity, not a hard minimum:

- 4 CPU cores and 8–16 GB RAM for the deterministic demo;
- 10 GB of free disk for the image, scratch space, and artifacts;
- 8 vCPU and 32 GB RAM for the initial VPS's one fixed worker. Horizontal
  concurrency is a later, separately reviewed scaling milestone.

OpenAI credentials must never be required by the Blender worker or included in images. A future planner would receive the key through an environment variable or secret manager, consistent with [OpenAI's API-key guidance](https://developers.openai.com/api/docs/guides/production-best-practices#api-keys).

Credential policy by mode:

- `make demo` and the direct one-shot container require **no secrets of any kind** and run with outbound networking disabled.
- The full local service uses only credentials generated locally by `make init-env` for service authentication and its internal development services. Users do not have to bring third-party keys.
- `.env.example` lists variable names and safe descriptions, never working production secrets. `.env` is ignored by Git.
- `OPENAI_API_KEY` would be introduced only by the unimplemented optional planner workstream and scoped to that process. It is never part of the v0.1 API worker or Blender environment, manifests, logs, or generated artifacts.
- VPS and managed-cloud operators bring their own domain/TLS, authentication, storage, and cloud secrets through a secret manager or protected deployment environment.

## 5. Target first-run experience

### Primary path: keyless single-container demo

```sh
git clone https://github.com/joseph-robert-f/headless-blender-character-builder.git
cd headless-blender-character-builder
make demo
make verify-demo
```

`make demo` must build or reuse the pinned builder image, create `build/demo/`, and run exactly one disposable container. It must not start Compose, prompt for an account, or read `.env`. Building or pulling the image can use the network on first run; the actual model build must run with `--network none`. `make verify-demo` must reopen the saved `.blend` in a second fresh Blender process, verify the exported files and hashes, and fail nonzero if the evidence is inconsistent.

The equivalent direct-container contract should remain documented for users who do not use Make:

```sh
mkdir -p build
test ! -e build/demo
host_uid="$(id -u)"
runtime_uid="$host_uid"
runtime_gid="$(id -g)"
if [ "$runtime_uid" = 0 ]; then runtime_uid=65532; fi
if [ "$runtime_gid" = 0 ]; then runtime_gid=65532; fi
if [ "$host_uid" = 0 ]; then chown "$runtime_uid:$runtime_gid" build; fi
docker build \
  --file docker/builder.Dockerfile \
  --target builder \
  --tag headless-blender-character-builder:dev \
  --platform linux/amd64 \
  .
image_id="$(docker image inspect --format '{{.Id}}' headless-blender-character-builder:dev)"
docker run --rm --init \
  --platform linux/amd64 \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 512 \
  --cpus 4 \
  --memory 4g \
  --user "$runtime_uid:$runtime_gid" \
  --tmpfs /work:rw,nosuid,nodev,noexec,size=2g,mode=1777 \
  --mount "type=bind,source=$PWD/examples/requests/facet-bot.json,target=/input/request.json,readonly" \
  --mount "type=bind,source=$PWD/build,target=/output" \
  --env HBCB_EXECUTION_MODE=container \
  --env HBCB_WORKER_IMAGE_REFERENCE=headless-blender-character-builder:dev \
  --env "HBCB_WORKER_IMAGE_ID=$image_id" \
  headless-blender-character-builder:dev \
  build \
  --request /input/request.json \
  --output /output/demo
```

A successful v0.1 demo must expose:

- `model.blend`;
- `model.glb`;
- `model.stl`;
- `preview.png` and `diagnostics/front.png`, `side.png`, and `back.png`;
- `manifest.json` with provenance and hashes;
- `qa.json` with geometry results.

```text
build/demo/
├── model.blend
├── model.glb
├── model.stl
├── preview.png
├── diagnostics/
│   ├── front.png
│   ├── side.png
│   └── back.png
├── manifest.json
└── qa.json
```

The one-shot CLI contract uses stable exit codes:

| Exit code | Meaning |
|---:|---|
| `0` | Build and all required QA succeeded |
| `2` | Invalid CLI command or unsupported option |
| `3` | Invalid or policy-rejected `BuildRequest` before Blender scene creation |
| `4` | Input, output, or staging filesystem failure |
| `10` | Blender generation, render, or export failure |
| `11` | Fresh-reload, artifact verification, or mandatory QA failure |
| `12` | Unexpected trusted-wrapper failure |
| `124` | Controlled wall-clock timeout |

Docker/runtime exit codes such as `125`, `126`, `127`, `137`, and `143` keep their conventional meanings. Partial output must remain in private staging or be clearly marked incomplete and must never contain a success manifest.

### Secondary path: full local service

After the one-shot demo passes, users who need HTTP, queues, durable state, or
the fixed one-worker service can start the Compose stack:

```sh
make init-env
make service-config
make service-up
make service-ps
```

`make init-env` creates an ignored `.env` containing random local-only service
credentials. First-time evaluators follow the copy-paste client in
`docs/api.md`; it submits a selected request, receives `202 Accepted`, polls to
a terminal state, downloads and verifies the exact artifact set, and prints the
durable result directory. `make service-smoke` remains the heavier maintainer
integration gate: it exercises direct and service builds, cancellation, IAM,
and retained evidence and can require at least 12 GiB of Docker memory.

Expected stable developer commands:

| Command | Purpose |
|---|---|
| `make demo` | Build the bundled spec in one keyless, network-disabled container |
| `make verify-demo` | Reopen and verify all required demo artifacts |
| `make lint` | Run formatting, lint, type, schema, and repository-hygiene checks |
| `make test-unit` | Run schema, manifest, policy, and service-free unit tests |
| `make test-blender` | Run the Blender integration suite in the builder image |
| `make check` | Run all release-blocking local static and test checks |
| `make init-env` | Generate ignored local-service credentials without third-party keys |
| `make service-up` | Start the full Compose service |
| `make service-smoke` | Exercise the asynchronous API end to end |
| `make service-down` | Stop the local service without deleting persistent data |
| `make security-check` | Scan tracked files, dependencies, image configuration, and Compose policy |
| `make release-check` | Run the clean-demo, service, security, documentation, and packaging gates |

### Local Blender path

```sh
blender \
  --background \
  --factory-startup \
  --offline-mode \
  --disable-autoexec \
  --python-exit-code 1 \
  --python blender/runner.py \
  -- \
  --request examples/requests/facet-bot.json \
  --output build/demo
```

Blender documents background execution, Python scripts, explicit Python failure codes, and passing script arguments after `--` in its [command-line manual](https://docs.blender.org/manual/en/4.5/advanced/command_line/arguments.html).

## 6. System architecture

```text
Lane A — primary quickstart

BuildRequest JSON ─▶ validated CLI ─▶ one-shot Blender worker ─▶ local build directory
                                          │
                                          └─ compile / export / render / QA

Lane B — durable service

brief / JSON / MCP ─▶ API ─▶ durable state + queue ─▶ same worker contract ─▶ object storage
                       │              │                         │
                       │              └─ build_id only          └─ Blender child gets no service secrets
                       └─ auth + schema + policy
```

### One-shot build path

The one-shot container is not a reduced or fake implementation. It is the deterministic builder image and invokes the same inherited runner used by queued jobs. Its only substitutions are a read-only bind mount for the request and a caller-owned local output directory instead of database, queue, and object-storage adapters. The resulting `.blend`, exports, renders, manifest, and QA schema must be identical to the derived service path for the same pinned builder lineage and request.

The quickstart must remain independent of FastAPI, Postgres, Redis, MinIO, OpenAI, MCP, and cloud services. This boundary is release-blocking: a service dependency leaking into the deterministic runner is a regression.

### Full local service components

- `api`: FastAPI service, request validation, authentication, job reads, and cancellation.
- `worker`: consumes build IDs and launches one fresh controlled Blender subprocess per attempt at concurrency one.
- `postgres`: durable job, attempt, event, and artifact metadata.
- `redis`: queue and short-lived coordination.
- `minio`: local S3-compatible artifact storage.

The interfaces for queue, database, and storage must be replaceable. A production operator should be able to substitute managed Postgres, Redis, S3, GCS, Pub/Sub, or Cloud Tasks without modifying generator code.

### Managed-cloud mapping

- HTTP API: Cloud Run Service or equivalent.
- Worker execution: pre-deployed Cloud Run Job, AWS Batch job, ECS task, Kubernetes Job, or dedicated VPS worker.
- Storage: GCS/S3-compatible object storage.
- Job state: managed Postgres.
- Queue: managed durable queue.
- Secrets and auth: cloud secret manager and least-privilege service identities.

A Cloud Run Job runs a container and exits; it does not listen for normal HTTP requests. The API service should invoke the existing job through `jobs.run` and pass only a build ID. See [Cloud Run job creation](https://cloud.google.com/run/docs/create-jobs) and [job execution](https://docs.cloud.google.com/run/docs/execute/jobs).

## 7. Public API v1

### Endpoints

- `POST /v1/builds`
- `GET /v1/builds/{build_id}`
- `GET /v1/builds/{build_id}/artifacts`
- `POST /v1/builds/{build_id}/cancel`
- `GET /healthz`
- `GET /readyz`

Controlled reference-asset uploads are post-v0.1. The first generator is completely procedural and accepts no uploaded files or remote references.

The v0.1 service is **single-operator and single-namespace**, not multi-tenant. All build and artifact endpoints require one deployment bearer token; `/healthz` may be unauthenticated and `/readyz` should be private outside local development. Per-user accounts, tenant IDs, quotas, and cross-tenant authorization are post-v0.1.

### `BuildRequest` and `CharacterSpec`

The API and one-shot CLI accept the same complete `BuildRequest v1` JSON document. `CharacterSpec v1` is the nested `spec` value that describes geometry and carries its own schema version; the outer request selects the trusted generator and versioned output, render, and quality profiles. The canonical example is `examples/requests/facet-bot.json`. This avoids separate local and HTTP input formats.

```json
{
  "request_version": "build/v1",
  "generator": "geometric-character@1.0.0",
  "spec": {
    "spec_version": "character/v1",
    "name": "facet-bot",
    "style": "geometric",
    "height_mm": 95,
    "pose": "standing",
    "palette": ["#E87532", "#FFF3D6"],
    "proportions": {
      "head_scale": 1.2,
      "limb_scale": 0.95
    }
  },
  "output_profile": "complete-v1",
  "render_profile": "diagnostic-v1",
  "quality_profile": "geometry-v1"
}
```

`complete-v1` is the only v0.1 output profile and always publishes the exact Section 5 artifact tree. Callers cannot request subsets in v0.1. `manifest.json` and `qa.json` are mandatory evidence rather than optional outputs. Future additive profiles require a new closed enum value and contract tests.

Every object schema should reject extra properties. Values must have explicit ranges and size limits. Users cannot supply shell fragments, Python, arbitrary URLs, host paths, output paths, Blender flags, environment variables, or image/container selections.

### State model

```text
validating → queued → running → geometry_qa → rendering → succeeded
     │          │         │            │             └→ failed
     └──────────┴─────────┴────────────┴──────────────→ canceled
                                      └───────────────→ needs_review
```

Attempts are separate from logical builds. An `Idempotency-Key` maps the same request to the original build; reusing the key with a different request hash returns `409 Conflict`.

### Artifact manifest

```json
{
  "request_sha256": "...",
  "spec_sha256": "...",
  "input_sha256": {},
  "generator_version": "1.0.0",
  "execution": {
    "mode": "container",
    "project_revision": "git-sha-or-source-tree-sha256",
    "blender_version": "4.5.x-pinned",
    "blender_binary_sha256": "...",
    "worker_image_reference": "headless-blender-character-builder:dev",
    "worker_image_digest": null,
    "worker_image_id": "sha256:..."
  },
  "dimensions_mm": [64, 51, 95],
  "artifacts": {
    "model.blend": {"sha256": "...", "bytes": 4812094},
    "model.glb": {"sha256": "...", "bytes": 2812094},
    "model.stl": {"sha256": "...", "bytes": 3812094},
    "preview.png": {"sha256": "...", "bytes": 412094},
    "diagnostics/front.png": {"sha256": "...", "bytes": 312094},
    "diagnostics/side.png": {"sha256": "...", "bytes": 302094},
    "diagnostics/back.png": {"sha256": "...", "bytes": 309094},
    "qa.json": {"sha256": "...", "bytes": 4096}
  },
  "qa": {
    "manifold": true,
    "non_manifold_edges": 0,
    "minimum_wall_mm": 1.34,
    "minimum_feature_mm": 2.15,
    "connected_shells": 1,
    "positive_volume": true,
    "fresh_reload": true,
    "stl_reimport": true
  }
}
```

The image build writes immutable source-tree, Blender-version, and Blender-binary provenance under `/opt/builder/` in the read-only image. The trusted launcher combines that with execution context in bounded scratch space; none of it is accepted through `BuildRequest`. Native mode records the source revision/tree hash, exact Blender version, and Blender binary hash while image fields are `null`. `make demo` may add the local image ID obtained through `docker image inspect`; the raw direct-Docker path may leave that field `null`. A published service pins the image by OCI digest in operator-controlled deployment configuration, and its supervisor injects that digest through a reserved launcher-only channel. These fields are reproducibility metadata, not a signed attestation. The manifest hashes every required artifact except `manifest.json` itself, which is excluded to avoid a self-referential hash.

## 8. `CharacterSpec v1` scope

The first schema should support one coherent geometric character family, not a generic representation of every possible Blender operation.

### Supported controls

- display name and safe slug;
- target height in millimeters;
- style enum: `geometric`, `low_poly`, and `chibi`, implemented as bounded presets in the same generator;
- bounded body and head proportions;
- one small set of poses;
- palette and material presets;
- face/eye preset;
- ear, horn, tail, or accessory presets from allowlisted components;
- base/pedestal preset and its bounded dimensions.

The outer `BuildRequest`—not `CharacterSpec`—selects `output_profile`, `render_profile`, and `quality_profile` from closed, versioned enums. Camera transforms, Blender flags, arbitrary output paths, and renderer settings remain implementation-controlled.

### Explicitly unsupported

- arbitrary Python or Blender API calls;
- arbitrary geometry-node graphs, shaders, add-ons, or expressions;
- arbitrary text/image-to-production-quality geometry;
- unrestricted remote URLs;
- unrestricted uploaded `.blend` files;
- exact human likenesses or protected-character replication;
- custom rigging, animation, or simulation;
- unbounded polygon, resolution, frame, or sampling settings.

### Normative v0.1 limits

These are adopted implementation limits, not suggestions. A change requires tests, documentation, and a versioned policy update.

| Limit | v0.1 value |
|---|---:|
| Complete `BuildRequest` payload | 64 KiB |
| Display name / safe slug | 64 / 48 characters |
| Target character height | 25–250 mm |
| Palette entries | 1–8 |
| Allowlisted optional components | 0–16 |
| Evaluated mesh triangles | 500,000 maximum |
| Scene objects / materials | 256 / 64 maximum |
| Required preview size | 1024 × 1024 maximum, up to 4 renders |
| Render samples | 64 maximum |
| One-shot wall time | 15 minutes |
| Scratch plus published output | 2 GiB maximum |
| Worker concurrency | 1 active Blender process per worker container |

All geometry and manifest dimensions are expressed in millimeters. STL and GLB re-imported bounds must match the `.blend` evaluated bounds within the greater of **0.2 mm or 0.5% per axis**.

The v0.1 `geometry-v1` quality profile is pass/fail and requires:

- one connected, watertight STL shell with zero non-manifold edges;
- positive volume, finite coordinates/transforms, consistently outward normals, and zero zero-area faces;
- minimum measured wall thickness of **1.2 mm**;
- minimum diameter/thickness of any freestanding strut, ear, horn, tail, limb, or accessory connection of **2.0 mm**;
- exported height within the Section 8 re-import tolerance of the requested height;
- fresh `.blend` reload plus GLB and STL re-import success.

The bounded generator must enforce these minima at parameter-validation and component-construction time and confirm them with mesh QA. If a required measurement cannot be established, the build becomes `needs_review` rather than `succeeded`. These conservative geometry checks are diagnostic evidence, not a slicer result or physical-print guarantee.

Determinism is structural, not a promise of byte-identical Blender files. Canonical JSON uses sorted keys and normalized numeric serialization; any random choice uses a seed derived from the canonical request hash. Repeated builds on the reference image must produce the same object inventory, topology counts, material assignments, dimensions within tolerance, and structural fingerprint. Binary output hashes are recorded but may legitimately differ after a documented Blender or encoder change.

## 9. Proposed repository structure

```text
.
├── README.md
├── PLAN.md
├── LICENSE
├── ASSET_LICENSE.md
├── OUTPUT_POLICY.md
├── THIRD_PARTY_NOTICES.md
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── SUPPORT.md
├── CHANGELOG.md
├── .env.example             # M3 service variables; never read by `make demo`
├── .gitignore
├── .dockerignore
├── compose.yaml             # M3 full service; not a quickstart dependency
├── Makefile
├── pyproject.toml
├── docker/
│   ├── builder.Dockerfile
│   ├── worker-supervisor.Dockerfile
│   ├── api.Dockerfile
│   └── blender-download.sha256
├── builder_cli/
│   ├── __main__.py
│   ├── commands.py
│   └── exit_codes.py
├── schemas/
│   ├── build-request-v1.schema.json
│   ├── character-spec-v1.schema.json
│   ├── manifest-v1.schema.json
│   └── qa-v1.schema.json
├── api/
│   ├── app.py
│   ├── routes/
│   └── schemas/
├── worker/
│   ├── consumer.py
│   ├── launcher.py
│   └── lifecycle.py
├── blender/
│   ├── runner.py
│   ├── core/
│   │   ├── primitives.py
│   │   ├── materials.py
│   │   ├── camera.py
│   │   └── scene.py
│   ├── generators/
│   │   └── geometric_character_v1/
│   ├── exporters/
│   ├── render/
│   └── qa/
├── shared/
│   ├── character_spec.py
│   ├── build_manifest.py
│   ├── config.py
│   └── storage.py
├── integrations/
│   ├── openai_planner/
│   └── mcp_server/
├── examples/
│   ├── requests/
│   └── expected/
│       └── facet-bot.structural.json
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── api/
│   ├── blender_integration/
│   ├── security/
│   └── fixtures/
├── deploy/
│   ├── vps/
│   ├── cloud-run/
│   └── terraform/          # post-v0.1 unless maintained in CI
├── docs/
│   ├── architecture.md
│   ├── character-spec.md
│   ├── api.md
│   ├── deployment.md
│   ├── printer-profiles.md
│   ├── threat-model.md
│   ├── licensing.md
│   ├── decisions.md
│   ├── progress.md
│   └── backlog.md
└── .github/
    ├── CODEOWNERS
    ├── ISSUE_TEMPLATE/
    ├── pull_request_template.md
    └── workflows/
```

## 10. Migration from the current workspace

| Current file | Public-repo role | Required change |
|---|---|---|
| `create_codex_avatar.py` | First generator fixture and source of reusable primitives/materials | Split helpers from character composition; replace global output paths and hardcoded parameters with a validated spec/context |
| `verify_codex_avatar.py` | Starting point for fresh-process integration QA | Separate generic scene/export checks from signature-character assertions |
| `prove_model_geometry.py` | Diagnostic render/geometry evidence module | Accept arbitrary build path and output directory; emit machine-readable results |
| `create_turntable_animation.py` | Optional turntable stage | Remove hardcoded source/output names and use a render profile |
| `verify_turntable_animation.py` | Animation integration test | Generalize object counts, paths, duration, resolution, and frame profile |
| `.blend`, `.glb`, PNG, and MP4 outputs | Demonstration/release artifacts | Do not treat generated files as source; publish one optimized preview in docs and attach larger artifacts to GitHub Releases; do not add Git LFS in v0.1 |
| `.blend1` files | Local backups only | Exclude from Git through `.gitignore` |
| Business report and calculation artifacts | Supporting product research | Keep under `docs/research/` only if they help public maintainers; otherwise exclude from the technical v0.1 repository |

The current sample is approximately 21 MB, with duplicate `.blend1` backups accounting for more than 5 MB. Public clones should remain source-first. A neutral original example should become the default tutorial. The current “Codex Self-Portrait” can be renamed and de-branded, retained as an optional fixture after branding review, or distributed only as a release artifact.

## 11. Build milestones and exit criteria

The v0.1 critical path is M0 through M5. Each milestone depends on the previous milestone's exit gate; `/goal` must record the commands and results for a gate before advancing. Optional AI/MCP and managed-cloud workstreams are documented separately and must not be implemented on this critical path. The sequencing is a planning estimate for one experienced engineer, not a delivery commitment.

Rough solo-engineer planning range:

| Milestone | Working estimate |
|---|---:|
| M0 — baseline and public-project foundation | 1–3 days |
| M1 — generic deterministic engine | 5–8 days |
| M2 — container and local demo | 3–5 days |
| M3 — asynchronous service | 7–10 days |
| M4 — VPS reference deployment | 3–5 days |
| M5 — release-candidate hardening and independent clean-room test | 3–5 days |
| **Likely elapsed v0.1 range with integration buffer** | **4–7 full-time weeks** |

The range assumes reuse of the current procedural scene and QA logic, one generator family, one reference platform for release blocking, and no web UI, hosted public demo, arbitrary generated code, or guaranteed print pipeline.

### M0 — Baseline and public-project foundation

Deliverables:

- inventory of the current workspace, generated artifacts, local paths, and reusable Blender scripts;
- preserved baseline run or inspection evidence for the existing model, geometry proof, exports, and turntable where the local environment permits it;
- adopted decision ledger from Section 17 in `docs/decisions.md`;
- source-first `.gitignore` and `.dockerignore` that exclude `.env`, `build/`, `.blend1`, caches, credentials, and local scratch data;
- a local Git repository when one is not already present, with no remote configured, plus an intentional source index used to export clean test trees with `git checkout-index`;
- project metadata, provisional name/slug, source and sample-asset licenses, support matrix, and one-sentence positioning;
- `docs/progress.md` milestone log with the M0–M5 checklist and a place to record commands, results, deviations, and blockers;
- neutral original default-character brief that does not depend on third-party or product branding.

Exit criteria:

- Section 17 defaults are recorded and no publication-blocking implementation choice remains unanswered;
- no third-party or branded reference material is required by the demo;
- repository can state clearly what is code, what is sample artwork, and who owns generated outputs;
- `git ls-files` contains only intended publication source/assets, ignored generated binaries remain preserved in the worktree, and `git remote -v` is empty unless the user separately authorized a remote;
- existing user files have not been deleted or overwritten, and refactoring has not begun before the baseline is recorded.

### M1 — Generic deterministic engine

Deliverables:

- `BuildRequest v1` and nested `CharacterSpec v1` JSON Schemas plus Python validation models;
- generator registry and `geometric-character@1.0.0`;
- reusable primitive, material, camera, scene, exporter, render, and QA modules;
- runner accepting only `--request` and `--output` after Blender's `--` boundary;
- deterministic example build requests;
- `.blend`, GLB, STL, PNG, manifest, and QA outputs;
- fresh-process reload verification.

Exit criteria:

- two materially different requests generate deterministic geometry from a clean Blender startup; the public `facet-bot` path publishes successfully, while `moss-hopper` intentionally proves the later fail-closed `needs_review` path rather than a second successful publication;
- the same canonical request produces the same topology/object inventory and stable manifest fields across repeated runs on the reference platform;
- malformed and out-of-range specs fail before scene creation;
- exported GLB/STL can be re-imported and checked;
- no external textures, fonts, network calls, or user startup state are required.

### M2 — Container and one-command local demo

Deliverables:

- pinned Blender 4.5 LTS builder image with recorded download checksum;
- narrow `builder validate --request ...` and
  `builder build --request ... --output ...` entrypoints with the Section 5
  exit-code contract;
- non-root runtime user plus support for an arbitrary host UID/GID;
- read-only root filesystem support, all capabilities dropped, no-new-privileges, bounded `/work`, and runtime networking disabled;
- `Makefile` targets `validate`, named `build`/`verify`, compatibility aliases
  `demo`/`verify-demo`, `test-unit`, `test-blender`, and `check`;
- local artifact storage adapter;
- documented native-Blender fallback;
- container smoke and invalid-input fixtures.

Exit criteria:

- a new user with only Git, Docker, and Make can run `make demo && make verify-demo` from a clean clone;
- the demo uses no `.env`, Compose, account, registry login for a source build, host Blender installation, database, queue, object storage, or API key;
- the model-build container runs with `--network none` and only the single read-only request plus writable output and bounded scratch paths;
- the demo leaves the exact required artifact tree under ignored `build/demo/` and publishes a success manifest only after mandatory QA;
- the documented application exit codes are tested, including invalid input and a forced QA failure;
- a repeat build has the same canonical request hash and structural fingerprint without requiring byte-identical `.blend` or PNG files;
- no credentials are required, read, or printed;
- the image and bundled dependencies have an SBOM and license inventory.

### M3 — Asynchronous build service

Deliverables:

- FastAPI endpoints from Section 7;
- `compose.yaml`, `.env.example`, `make init-env`, `make service-up`, `make service-smoke`, and `make service-down`;
- Postgres job/attempt/artifact/event schema;
- Redis queue and worker lease/heartbeat logic;
- idempotency and request fingerprinting;
- local S3-compatible artifact adapter and signed downloads;
- cancellation, timeout, retry, and dead-letter behavior;
- structured logs with build and attempt IDs.

The M2 builder image remains the immutable deterministic base. M3 adds a separately identified worker-supervisor image derived `FROM` the pinned M2 builder image; it adds queue/state/storage orchestration but must not replace the builder entrypoint, generator, exporter, QA, manifest code, or artifact contract. For local service v0.1, each supervisor container consumes jobs at concurrency one and launches one fresh Blender subprocess through that inherited builder runner per job. Managed-cloud job-per-build isolation remains post-v0.1. The API must never receive a Docker socket or permission to launch arbitrary containers.

Exit criteria:

- API returns `202` without waiting for Blender;
- two duplicate requests with the same key return the same build;
- the same key with a different request returns `409`;
- interrupted workers can be retried without exposing partial outputs as successful;
- terminal build status is committed only after an immutable artifact manifest exists;
- API container has no Docker socket and no Blender execution privilege;
- `make service-smoke` proves health, asynchronous `202`, polling, artifact download and hash verification, idempotency conflict behavior, API-restart persistence, and contract parity with the M2 output;
- the core Compose profile starts without `OPENAI_API_KEY` or any third-party credential, binds development services to localhost by default, and uses only locally generated secrets.

### Post-v0.1 A — Optional OpenAI planner and MCP adapter

Deliverables:

- opt-in prompt-to-`CharacterSpec` planner using a strict schema;
- model name configurable through settings rather than embedded in generator code;
- user-facing preview/confirmation of the spec before a paid or mutating build;
- MCP tools: `create_blender_build`, `get_blender_build`, and `cancel_blender_build`;
- approval-required default for build creation/cancellation;
- planner/MCP audit events that exclude secrets.

Exit criteria:

- deterministic mode remains fully functional without an API key;
- strict schema rejects extra fields and unbounded values;
- OpenAI key is present only in the planner process and never in Blender, output manifests, images, or logs;
- MCP is a thin wrapper over the public API rather than a second execution engine;
- tool calls return build IDs instead of blocking until Blender completes.

OpenAI documents the application-side tool-call loop and recommends strict function schemas in its [function-calling guide](https://developers.openai.com/api/docs/guides/function-calling). Remote MCP can expose trusted external actions with approval controls; see the [MCP guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).

### M4 — VPS reference deployment

Deliverables:

- documented Linux VPS deployment using Docker Compose;
- reverse proxy with TLS;
- bearer-token or OIDC authentication;
- rootless/private worker runtime;
- managed or backed-up state and storage recommendations;
- resource caps, retention, recovery, and upgrade documentation;
- an operator smoke script that can exercise the public HTTPS endpoint when an authorized target is supplied.

Exit criteria:

- Compose configuration and deployment scripts validate locally without contacting a cloud provider;
- deployment survives API restart without losing job state;
- artifacts are stored outside ephemeral worker storage;
- the worker supervisor has only minimum scoped storage/job credentials; its network is restricted to required internal services with no public-internet egress, and the Blender child receives a scrubbed environment with no secrets;
- backup and restore procedure is tested;
- an operator can upgrade and roll back the pinned builder and service images;
- a live HTTPS smoke test is required only when the user supplies a VPS, domain, and deployment authorization. Otherwise M4 completes with a validated deployment package, local recovery drill, and exact operator runbook.

### Post-v0.1 B — Managed-cloud template

Deliverables:

- one maintained cloud target, recommended initially as Cloud Run Service + Cloud Run Job + GCS + managed Postgres/queue;
- least-privilege IAM/service identities;
- per-build job invocation using a stored build ID;
- logs, metrics, budgets, and deployment smoke tests;
- infrastructure definition only if CI can keep it working.

Exit criteria:

- no cloud credential is passed to Blender itself;
- API and worker identities have separate permissions;
- worker tasks can scale independently of the API;
- documented timeout/retry settings match service limits;
- deploy and destroy instructions are verified in an isolated project.

### M5 — Public v0.1 release candidate

Deliverables:

- rewritten README with architecture, optimized static model evidence, quickstart, limitations, and security warnings;
- `LICENSE`, `ASSET_LICENSE.md`, `OUTPUT_POLICY.md`, `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `SUPPORT.md`, and changelog;
- issue and pull-request templates;
- release notes, local generated sample artifacts, checksums, and a repeatable publication script or documented commands;
- release-candidate builder, supervisor, and API images tagged locally by version, with a documented digest-pinning procedure for publication;
- `docs/backlog.md`, starter-issue templates, and proposed contributor labels ready to create after publication.

Exit criteria:

- clean-clone quickstart is tested from a temporary `git checkout-index` export containing only indexed publication files and independently reviewed; an outside human trial is recommended before publication but is not required for local release-candidate completion;
- `make release-check` runs every release-blocking test and packaging audit from documented prerequisites;
- workflow definitions are syntax-validated and every command they invoke passes locally without repository secrets; the first hosted CI run is a conditional publication check;
- no `.env`, key, local path, `.blend1`, temp output, or credential-bearing URL is tracked;
- root license text and SPDX metadata validate locally; GitHub license detection is a conditional post-push check;
- security policy names the enabled GitHub private vulnerability reporting route;
- limitations explicitly state that slicer validation is not a physical-print guarantee.

The public GitHub planning repository was created and initially published with
explicit user authorization on August 2, 2026. The source branch containing the
completed v0.1 work and public-repository organization pass was explicitly
authorized on August 4, 2026. Merging that branch, publishing a GHCR image,
creating a tag or GitHub Release, attaching release assets, and deploying to a
live VPS remain separate conditional operator actions. They require explicit
authorization and do not block a locally complete release candidate.

## 12. Testing and CI

### Unit tests

- schema acceptance and rejection;
- numeric, array, string, and payload-size limits;
- canonical JSON hashing and idempotency behavior;
- safe slugs and object-storage keys;
- artifact manifest validation;
- single-operator bearer authentication and build/artifact access control;
- rejection of paths, URLs, Python, shell fragments, add-ons, and extra properties.

### Blender integration tests

- clean background build from two specs;
- source and evaluated mesh validity;
- finite transforms and nonzero dimensions;
- expected object and material categories;
- saved-file reload in a second Blender process;
- GLB/STL export, header check, re-import, dimensions, and volume;
- diagnostic renders with expected dimensions and nonempty image statistics;
- turntable frame count, rate, and all-side framing only when the optional post-v0.1 output is enabled.

Avoid exact pixel snapshots as the primary pass/fail signal; Blender, drivers, and render hardware can create benign pixel differences. Prefer structural assertions, bounded image statistics, and optional perceptual comparisons with documented tolerances.

### Quickstart contract tests

- build or reuse the builder image, then run the bundled request with a read-only root, non-root UID, dropped capabilities, bounded resources, and runtime networking disabled;
- assert the exact required output tree exists and every file is nonempty;
- validate `manifest.json` and `qa.json` against versioned schemas and recompute every artifact hash;
- reopen `model.blend` in a second factory-startup process and re-import GLB/STL;
- verify finite dimensions, nonempty geometry, positive STL volume, manifold status, and Section 8 bounds tolerance;
- run an invalid request and assert application exit `3` with no published success artifacts;
- run a forced QA failure and assert application exit `11` with no success manifest;
- build the example twice and compare only declared stable structural fields;
- run fork-safe without repository or provider secrets.

### Service integration tests

- asynchronous `202` behavior;
- queue retry and dead-letter behavior;
- worker crash and lease expiry;
- cancellation at each stage;
- immutable manifest publication;
- signed artifact URL authorization and expiry;
- cleanup/retention jobs;
- webhook signing and replay protection if webhooks ship.

### GitHub Actions policy

- run fork-safe lint, unit, schema, and container-build checks on `pull_request` without secrets;
- do not execute untrusted fork code in a privileged `pull_request_target` workflow;
- pin actions to trusted release SHAs or controlled versions;
- use least-privilege `GITHUB_TOKEN` permissions;
- keep publishing in a protected, maintainer-triggered release workflow;
- build the builder and service images from source in CI; never require a private registry login for pull-request verification;
- keep `make demo`, contract verification, and a minimal service smoke test as release-blocking jobs on the reference platform;
- add dependency review, secret scanning, CodeQL, container scanning, and an SBOM as the project matures.

GitHub warns that privileged workflows combined with untrusted pull-request code can compromise a repository; see its [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## 13. Security model

### Preferred public mode

Codex or another planner produces declarative JSON. A reviewed, versioned generator compiles it. This is the only mode promised by the normal worker.

### Excluded high-risk mode

Executing arbitrary model- or customer-authored Python is out of scope for v0.1. If added later, it requires a separate worker pool using a materially stronger isolation boundary such as gVisor/Kata or per-job microVMs. It must never share the API host, database network, service credentials, or normal worker identity.

### Isolation by execution mode

| Mode | Process/network boundary | Credentials and cleanup |
|---|---|---|
| Native contributor CLI | Trusted local user process with Blender offline/factory flags; not a hosted isolation boundary | Uses no project service credential; caller owns cleanup |
| One-shot quickstart | One fresh container with `--network none`, read-only root, dropped capabilities, bounded scratch, and fixed mounts | No secrets; container removed after final artifact collection |
| Compose service v0.1 | One long-running worker supervisor at concurrency one; one fresh Blender child per attempt; container network can reach only required internal queue/state/storage services and has no public-internet egress | Supervisor has minimum scoped local-service credentials; child receives a scrubbed environment with no secrets; child terminates and attempt scratch is cleared after every job |
| Managed/post-v0.1 worker | One pre-deployed job container or stronger sandbox per build | Short-lived supervisor identity; Blender receives no credential; job destroyed after collection |

The Compose Blender child shares its supervisor's container network namespace; v0.1 does not claim per-process network-namespace isolation. Its protection is the trusted declarative generator, absence of customer Python/uploads, no public egress, scrubbed child environment, and internal endpoint allowlist. Any feature that introduces untrusted executable content requires the separate stronger-isolation mode above.

### Worker requirements

- pinned image digest and Blender version;
- non-root user and all unnecessary Linux capabilities dropped;
- read-only root filesystem;
- one bounded ephemeral input/output area;
- hosted/service workers receive no host mounts, Docker socket, SSH agent, devices, or inherited credentials;
- the local one-shot demo permits only its single read-only request-file mount and single writable artifact-directory mount; it must never mount the repository root, home directory, credential paths, or arbitrary caller-selected paths inside the worker;
- the one-shot runtime has no network; a Compose worker namespace has no public-internet egress and may reach only its allowlisted queue, job-state, and artifact-storage endpoints;
- CPU, memory, PID, disk, file-count, vertex-count, frame-count, resolution, render-sample, and wall-clock limits;
- controlled argument array with no shell interpolation;
- trusted wrapper stages inputs and uploads results; Blender receives no storage credentials;
- one-shot/cloud job containers are destroyed after collection; a long-running Compose supervisor terminates the Blender child and clears attempt scratch data after every job.

### Input and output requirements

- if controlled reference uploads are introduced post-v0.1, they use generated asset IDs, not caller-provided URLs;
- validate MIME type, digest, byte size, decompressed size, image dimensions, and file count;
- if webhooks are introduced post-v0.1, pre-register endpoints rather than accepting arbitrary callback URLs;
- short-lived signed artifact URLs;
- deployment-namespace-prefixed object keys and bearer-protected build/artifact access;
- configurable retention and deletion;
- logs must not contain prompts, reference images, tokens, or signed URLs.

## 14. Licensing and IP plan

This section is a decision framework, not legal advice.

### Source code

Adopted v0.1 default: **GPL-3.0-or-later** for all project code. Blender is GPL, and published Python that tightly uses Blender's API should use a GPL-compatible license. A single GPL license is the easiest choice for contributors to understand and leaves room for a separately operated hosted service because GPL is not an automatic network-use source-disclosure license. Blender's general GPL obligations and the separation between the application and produced artwork are summarized in its [license documentation](https://docs.blender.org/manual/en/3.2/getting_started/about/license.html).

A possible future alternative for maximum adoption is to place the Blender-linked generator/worker under GPL-3.0-or-later and independently separable API, schema, SDK, and MCP packages under Apache-2.0. This is not the v0.1 plan and must not be introduced by `/goal` without explicit user direction and license review.

Do not publish without a root license. GitHub notes that making a repository public does not by itself grant permission to use, modify, and redistribute its code; a recognized license is required for a genuinely open-source project. See [GitHub's licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

### Blender redistribution

If release images contain Blender, include the applicable GPL text, notices, exact Blender version, original download URL/checksum, and the corresponding-source compliance information required for that distribution method. Do not call a project-maintained image an official Blender image.

### Example assets

Use a separate **CC0-1.0** declaration for the original sample `.blend`, GLB, STL, PNG, and character concepts. State that the source-code license does not automatically license sample artwork. If MP4 examples are published later, include them in the same explicit sample-asset declaration unless their inputs require different attribution.

### User inputs and generated outputs

The project should state that:

- users retain responsibility for rights to submitted names, designs, references, and logos;
- no license to third-party IP is granted by the tool;
- generated outputs are not endorsed or legally cleared by maintainers;
- normal generated outputs are not automatically covered by Blender's GPL merely because Blender produced them;
- printer QA is diagnostic and not a warranty of successful manufacture.

### Branding

Use a neutral original example as the public default. Avoid franchise names and assets. If the current Codex-themed example is retained, rename/de-brand it or add clear non-affiliation and trademark notices after review.

## 15. Contribution and governance

- Begin with a maintainer-led model and documented review standards.
- Use a Developer Certificate of Origin sign-off unless future dual/commercial licensing requires a CLA.
- Require tests and docs for new `CharacterSpec` fields and generator components.
- Require a threat-model note for changes that expand inputs, network access, execution, add-ons, or storage permissions.
- Add `CODEOWNERS` for worker security, schemas, deployment, and release workflows.
- Label extension proposals separately from bugs: `generator`, `component`, `exporter`, `qa`, `deployment`, `security`, and `good first issue`.
- Treat schema stability as an API contract. Additive changes go into the existing version only when old specs retain the same meaning; breaking changes create a new spec version.
- Publish a support boundary: community help is best effort, and production operators own backups, availability, abuse prevention, and legal compliance.

## 16. Out of scope for v0.1

- arbitrary text/image-to-production-quality 3D;
- general organic sculpting;
- exact human likeness workflows;
- protected-character packs or unrestricted style imitation;
- arbitrary Blender Python, add-ons, drivers, nodes, or uploaded `.blend` files;
- rigging and animation output, including MP4 turntables;
- photorealistic GPU rendering orchestration;
- billing, subscriptions, marketplace, or paid multi-tenant control plane;
- every cloud provider or Kubernetes distribution;
- physical printing, painting, shipping, returns, or print guarantees;
- automatic copyright/trademark clearance;
- a public hosted demo that can be abused without quotas or authentication.

## 17. Adopted execution defaults

These defaults remove implementation blockers for `/goal`. They are binding for the local v0.1 release candidate unless the user explicitly changes one. They remain reversible before public publication; a naming or branding change must not force a redesign of package boundaries or APIs.

| Decision | Adopted v0.1 default |
|---|---|
| Working project name | **Headless Blender Character Builder**; repository and project/package slug `headless-blender-character-builder` |
| Source license | One repository under **GPL-3.0-or-later** |
| Sample-asset license | **CC0-1.0**, called out separately from source code |
| Default example | `facet-bot`: an original geometric desk-toy robot with a rounded-cube head, capsule torso, cylinder limbs, simple circular eyes, and optional pedestal |
| Required outputs | `.blend`, GLB, STL, `preview.png`, three diagnostic views, `manifest.json`, and `qa.json` |
| Print QA | Geometry-only diagnostics; no slicer-profile or physical-print guarantee |
| AI and MCP | Post-v0.1 optional adapter; no OpenAI dependency in the v0.1 critical path |
| Release platform | `linux/amd64` builder image is release-blocking; Docker Desktop emulation and native macOS/Linux development are documented; `linux/arm64` is best effort until an official checksum-pinned Blender distribution is validated |
| Local modes | Single-container synchronous quickstart first; full Compose asynchronous service second |
| Service stack | FastAPI, Postgres, Redis, and MinIO in Compose, behind replaceable state/queue/storage interfaces |
| Cloud scope | Validated VPS deployment package in v0.1; maintained managed-cloud template post-v0.1 |
| Public artifacts | Track only a small optimized documentation preview; ignore generated models/renders; publish larger examples as Release assets; no Git LFS in v0.1 |
| Governance | DCO sign-off, maintainer review, no CLA unless a future licensing strategy requires it |

If implementation evidence makes a default infeasible, `/goal` must choose the smallest safe compatible adjustment, record the reason and impact in `docs/decisions.md` and `docs/progress.md`, and continue when the adjustment does not expand permissions, cost, or public scope. It must ask the user before changing licensing, invoking paid infrastructure, weakening security boundaries, or materially expanding v0.1.

## 18. Binding v0.1 release cut

The v0.1 release candidate contains two public surfaces:

1. **Deterministic builder:** schemas, one geometric generator family, Blender source, exporters, rendering, QA, manifest, native contributor command, and the primary keyless single-container demo.
2. **Self-hosted service:** asynchronous API, worker lifecycle, Postgres, Redis, MinIO, Compose orchestration, local authentication, and a VPS deployment package around the exact same builder.

Both surfaces are part of the complete local v0.1 release candidate, but the deterministic builder must remain independently usable. A service failure or missing `.env` must never break `make demo`.

Required v0.1 content:

- neutral project identity and original `facet-bot` example;
- GPL-3.0-or-later source and separately identified CC0-1.0 samples;
- strict `BuildRequest v1` and `CharacterSpec v1` contracts;
- one bounded geometric-character generator producing at least two materially different fixtures;
- `.blend`, GLB, STL, preview/diagnostic PNGs, manifest, and geometry QA;
- fresh-process `.blend` reload plus GLB/STL re-import verification;
- source-built, non-root pinned Docker worker and `make demo && make verify-demo`;
- asynchronous API with Compose-backed Postgres, Redis, and MinIO;
- generated local credentials and bearer authentication for the service path;
- validated VPS deployment and recovery runbooks;
- unit, Blender, container, API, persistence, security, and release tests;
- README, architecture/spec/API/deployment docs, governance, licensing, contribution, support, and security files.

Explicitly hold for post-v0.1:

- OpenAI prompt planner and remote MCP server;
- reference-image uploads and remote asset ingestion;
- 3MF, MP4, and slicer-specific validation promises;
- Cloud Run/Terraform or other managed-cloud templates;
- GPU orchestration, web UI, billing, and hosted multi-tenancy.

## 19. Ordered implementation work packages

These work packages were used as the execution queue. Each package began only
after its dependencies and gate were satisfied. Work that did not alter a
stable contract—documentation, isolated unit tests, and license inventories—was
eligible for parallel review after its dependency was fixed.

| ID | Milestone | Depends on | Required result | Gate before advancing |
|---|---|---|---|---|
| G0 | M0 | None | Inventory, preserved baseline, adopted decisions, ignore rules, local Git initialization/source index with no remote, licenses, progress log, and neutral example brief | No user file overwritten; all defaults recorded; indexed publication tree excludes generated/private files |
| G1 | M1 | G0 | `BuildRequest`/`CharacterSpec`, QA, and manifest schemas; canonicalization; limits; example requests; rejection fixtures | Schema and policy unit tests pass; examples validate; extra properties and hostile fields fail |
| G2 | M1 | G1 | Generic scene/core modules, registry, `geometric-character@1.0.0`, and two materially different original characters | Both requests generate from factory startup with stable structural fingerprints; later complete QA intentionally leaves `moss-hopper` as `needs_review` without published output |
| G3 | M1 | G2 | `.blend`, GLB, STL, preview/diagnostics, manifest, QA, fresh reload, and re-import checks | Required artifact and Blender integration tests pass within Section 8 tolerances |
| G4 | M2 | G3 | Pinned deterministic builder image, trusted CLI, local filesystem adapter, hardened one-shot runtime, native fallback, and Make targets | From tracked source only, `make demo && make verify-demo` succeeds without `.env`, Compose, keys, or runtime network |
| G5 | M3 | G4 | Postgres models/migrations, Redis job contract, storage interface, MinIO adapter, and generated local config | State, idempotency, storage, migration, and authorization unit tests pass |
| G6 | M3 | G5 | FastAPI routes, worker leases/heartbeats, fresh Blender subprocess lifecycle, retries, cancellation, immutable publication, and logs | API/service tests cover success, failure, retry, cancellation, timeout, and authorization |
| G7 | M3 | G6 | Compose stack and service Make targets using a supervisor image derived from the pinned G4 builder and its unchanged build contract | `make service-smoke` proves `202`, polling, downloads/hashes, idempotency, restart persistence, contract parity, and no provider key |
| G8 | M4 | G7 | VPS Compose overlay, TLS/auth guidance, resource/retention policy, backup/restore, upgrade/rollback, and smoke script | Compose validates locally; recovery drill passes; live HTTPS check is conditional on an authorized target |
| G9 | M5 | G8 | Public README/docs, CI, governance, security policy, SBOM/notices, changelog, release notes, and publication instructions | Clean temporary checkout passes `make release-check`; tracked-file and secret audits are clean |

At the end of every package, update `docs/progress.md` with:

- status: `pending`, `in progress`, `passed`, or `blocked`;
- files and contracts changed;
- exact verification commands and exit results;
- evidence/artifact locations;
- deviations from this plan and their decision-log entry;
- remaining risks or externally conditional checks.

## 20. Historical `/goal` execution contract

The completed build used this copy-ready objective:

```text
/goal Build the complete local v0.1 release candidate described in PLAN.md from the current workspace. Treat PLAN.md as the authoritative scope and use its Section 17 defaults without stopping for reversible product choices. Execute work packages G0 through G9 in dependency order, preserve existing user files and baseline evidence, and update docs/progress.md after every gate. The primary acceptance path must remain a synchronous, keyless, single-container build; Compose is the secondary asynchronous service; OpenAI/MCP and managed cloud are post-v0.1. Implement, test, diagnose, and repair until every locally verifiable release gate passes. Do not create or push a remote repository, publish images/releases, deploy to a live VPS, purchase services, or use external credentials unless I explicitly authorize it. Finish with a milestone report, exact test results, artifact locations, decisions/deviations, conditional operator steps, and any genuine blockers.
```

Execution rules used for that goal:

1. Read this entire file, repository instructions, current status, and existing source before editing.
2. Preserve user work. Never delete or overwrite current `.blend`, export, render, research, or script files merely to make the public tree cleaner; ignore, migrate, or archive them only when the plan and verification support it.
3. Establish the M0 baseline before extracting code. Use existing procedural scripts as source material, not as an API contract.
4. Treat schemas, artifact layouts, exit codes, units, hashes, and security limits as versioned contracts. Update tests and docs in the same change as a contract.
5. Keep Blender headless and factory-started for all required gates. GUI/computer-use inspection can help diagnose a visual defect but can never be required for a successful build or verification.
6. Use the same trusted generator, validation, exporter, QA, and manifest code in native, one-shot, Compose, and future cloud paths.
7. Do not silently skip a failing gate, substitute a mocked Blender artifact for a required real one, or claim a command passed when it was not run. Record environmental checks that cannot run as unverified, continue independent work, and report the exact blocker.
8. Do not implement post-v0.1 items opportunistically. Add extension seams and backlog notes only where they are necessary to keep the v0.1 architecture replaceable.
9. Safe local implementation and testing are in scope. If the workspace is not already a Git repository, local `git init`, intentional staging/index maintenance, and logical local milestone commits are authorized for the build; do not configure a remote or rewrite unrelated history. Remote GitHub creation/push, GHCR publication, GitHub Release creation, live VPS/cloud deployment, DNS/TLS changes, and paid API calls remain conditional operator actions.
10. Use sub-agents for bounded parallel review or independent QA when useful, but keep contract decisions and the final integrated verification in the primary execution path.

## 21. Definition of local completion

The `/goal` was considered complete only when all of the following were true:

- G0–G9 are marked passed locally, with any external-only action explicitly marked conditional rather than falsely completed.
- A temporary tree exported from the final Git index with `git checkout-index` can run `make demo && make verify-demo` with Git, Docker, and Make, without `.env`, Compose, an account, third-party keys, or runtime networking.
- The demo produces the exact required artifact tree from real headless Blender geometry; a second fresh process reloads `.blend`, and GLB/STL re-import and geometry QA pass.
- Two materially different requests prove that the system is schema-driven rather than a renamed hardcoded scene.
- `make service-smoke` proves the durable asynchronous service, including `202`, idempotency, restart persistence, artifact integrity, authentication, failure handling, and reuse of the deterministic builder.
- `make release-check` runs all release-blocking lint, unit, Blender, container, service, security, documentation, licensing, SBOM, and tracked-file audits successfully.
- No tracked secret, `.env`, personal absolute path, signed URL, `.blend1`, cache, temporary output, or large generated binary remains in the publication candidate.
- README instructions distinguish the no-key quickstart, locally generated service credentials, optional future provider keys, and production operator secrets.
- Licensing, IP, print-readiness limitations, security boundary, support policy, and external publication/deployment steps are explicit.
- The final report gives exact commands and summarized results, links to generated evidence, lists decisions and deviations, and identifies only genuine external or permission-dependent follow-ups.
