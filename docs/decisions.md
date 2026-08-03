# v0.1 Decision Ledger

Status: adopted for the local v0.1 release candidate.

The decisions below record the binding defaults from `PLAN.md` Section 17. Contract changes require corresponding documentation and tests.

| ID | Decision | Adopted value | Rationale |
|---|---|---|---|
| D-001 | Project identity | **Headless Blender Character Builder**, slug `headless-blender-character-builder` | Neutral and descriptive |
| D-002 | Source license | GPL-3.0-or-later | One clear GPL-compatible license for Blender-linked source |
| D-003 | Sample license | CC0-1.0, declared separately | Original example artwork remains distinct from source licensing |
| D-004 | Default example | Original `facet-bot` geometric desk-toy robot | Avoids third-party characters and product branding |
| D-005 | Required artifacts | `.blend`, GLB, STL, preview, front/side/back diagnostics, manifest, and QA | Editable geometry plus portable formats and evidence |
| D-006 | Print claims | Geometry diagnostics only; no physical-print warranty | Printer, material, slicing, calibration, and handling remain external |
| D-007 | AI/MCP | Post-v0.1 adapter; no OpenAI dependency in the critical path | Keeps the builder deterministic and keyless |
| D-008 | Release platform | `linux/amd64`; native macOS and Docker Desktop are contributor/evaluator paths | Matches the pinned release-container requirement |
| D-009 | Local modes | One-shot synchronous builder first; asynchronous Compose service second | Preserves a small, keyless evaluation path |
| D-010 | Service stack | FastAPI, Postgres, Redis, and MinIO behind replaceable interfaces | Provides durable local operation without coupling generator code |
| D-011 | Cloud scope | Validated VPS package in v0.1; managed-cloud templates later | Makes deployment concrete without paid infrastructure |
| D-012 | Public artifacts | Source-first repository; generated outputs ignored; no Git LFS in v0.1 | Keeps clones small and prevents local metadata leakage |
| D-013 | Governance | DCO sign-off and maintainer review; no CLA | Low-friction contribution model consistent with GPL source |
| D-014 | Windows/WSL2 | Experimental and non-release-blocking in v0.1 | No verified Windows environment is available for the release gate |
| D-015 | Contract identifiers | `build/v1`, `character/v1`, `qa/v1`, `manifest/v1`, and `geometric-character@1.0.0` | Keeps request, evidence, and generator evolution explicit |
| D-016 | Canonical hashing | Strict UTF-8 JSON, bounded decimal parsing, sorted object keys, normalized numeric forms, expanded defaults, and SHA-256 | Makes semantically equivalent requests share stable request/spec hashes |
| D-017 | QA status authority | JSON Schema enforces structure and directly expressible pass constraints; the pure-Python model is normative for cross-field arithmetic and status derivation | JSON Schema cannot express the required per-axis tolerance arithmetic without custom extensions |
| D-018 | Unknown mandatory QA | `needs_review`, application exit `11`, and no success manifest | Unmeasurable evidence must never be treated as a successful build |
| D-019 | Unit and tolerance contract | Published dimensions use millimeters; height and GLB/STL bounds use `max(0.2 mm, 0.5%)` per applicable axis | Aligns all modes and round-trip verification with `PLAN.md` Section 8 |
| D-020 | Python and schema validation | Project Python is 3.11+; production contract models remain standard-library-only; `jsonschema==4.26.0` is a test extra | Blender 4.5 bundles Python 3.11 while a real Draft 2020-12 engine remains part of the gate |
| D-021 | Blender version provenance | Record the exact bounded `bpy.app.version_string`, currently `4.5.12 LTS` | Avoids silently dropping the LTS designation from native and container manifests |
| D-022 | Generated scene representation | Preserve separate display meshes in `CHARACTER` and derive exactly one hidden printable shell in `PRINT`; total requested height includes the exact display base | Keeps editable evidence distinct from the watertight manufacturing-oriented union |
| D-023 | Generator determinism evidence | Compare canonical structural reports across two fresh processes per fixture and require a palette-independent geometry signature plus topology differences across fixtures | Proves repeatability and schema-driven geometry without promising byte-identical Blender files |
| D-024 | Semantic geometry rejection | Reject schema-valid but impossible height/base layouts before factory reset or any scene mutation | Keeps request/policy failures separate from Blender generation side effects |
| D-025 | Tail component compatibility | `stub-tail` and `swept-tail` are mutually exclusive in both JSON Schema and runtime validation, with a generator preflight guard | Prevents ambiguous double-tail composition and any partial-scene name collision |

## Recorded execution conditions

- The repository already has an explicitly authorized public `origin`; this supersedes the initial-plan preference for no remote during M0. The build goal does not authorize further remote pushes, image publication, releases, DNS changes, paid services, or live deployment.
- Native Blender is resolved from the macOS application bundle because `blender` is not on `PATH`. Container and CI contracts continue to use the standard `blender` executable path inside the image.
- Live VPS HTTPS and physical-print trials remain conditional. Local configuration validation and a recovery drill remain release-blocking.
