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

## Recorded execution conditions

- The repository already has an explicitly authorized public `origin`; this supersedes the initial-plan preference for no remote during M0. The build goal does not authorize further remote pushes, image publication, releases, DNS changes, paid services, or live deployment.
- Native Blender is resolved from the macOS application bundle because `blender` is not on `PATH`. Container and CI contracts continue to use the standard `blender` executable path inside the image.
- Live VPS HTTPS and physical-print trials remain conditional. Local configuration validation and a recovery drill remain release-blocking.
