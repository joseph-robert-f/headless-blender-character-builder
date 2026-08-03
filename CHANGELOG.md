# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added

First working implementation. The repository previously contained planning
documents only.

- **Deterministic builder.** `geometric-character@1.0.0` composes a character
  from Blender primitives and boolean-unions it into a single watertight
  manifold shell.
- **Printer-aware generation.** A `print_profile` on the request drives both
  the geometry and the checks: limbs, antennae, horns, and tails are thickened
  at construction time to meet the profile's minimum feature size, and every
  adjustment is reported. Four presets ship (`fdm-0.2-fine`,
  `fdm-0.4-standard`, `fdm-0.6-draft`, `resin-standard`) plus `custom`.
  Contradictory profiles are rejected before Blender starts.
- **Print QA.** Watertightness, manifoldness, shell count, normal orientation,
  solid thickness by inward raycast, unsupported overhang area, bed contact
  area, volume, and a solid-infill mass estimate. Written to `qa.json` against
  a versioned schema.
- **Artifacts.** `model.stl` (true millimetres), `model.blend`, `model.glb`,
  a preview render, three orthographic diagnostic views, `qa.json`, and
  `manifest.json` with provenance and per-artifact hashes.
- **Independent verification.** `hbcb verify` re-hashes every artifact, reopens
  the `.blend`, and re-imports the STL and GLB in a fresh Blender process.
- **CLI.** `hbcb build | verify | validate | presets | preset | profiles |
  doctor | selftest`, which locates Blender automatically and falls back to the
  `bpy` Python module. Flags for the common tweaks (`--height`, `--style`,
  `--print-profile`, `--no-renders`, `--advisory`) so basic use needs no JSON.
- **Three original presets**: `facet-bot`, `cocoa-cub`, `crystal-scout`.
- **Four JSON Schema documents** for the request, character spec, manifest, and
  QA report. Every object rejects undeclared properties.
- **Tests.** 42 unit tests with no Blender dependency, including a cross-check
  of the bundled schema validator against the reference `jsonschema` package;
  16 Blender integration tests covering topology, exact height across the full
  25–250 mm range, determinism, profile enforcement, manifest integrity, STL
  re-import, and the failing-QA path.
- **CI** running the unit matrix on Python 3.9/3.11/3.13, lint, Blender
  integration, and a container build.
- **Container image** (`docker/builder.Dockerfile`) that runs unprivileged with
  no network access.
- **Documentation**: rewritten README, `docs/REVIEW.md`, `docs/character-spec.md`,
  and `docs/architecture.md`.

### Changed

- v0.1 scope narrowed to the deterministic builder. The asynchronous service
  (FastAPI, Postgres, Redis, MinIO, Compose, VPS package) described in
  `PLAN.md` G5–G8 is deferred; its design is unchanged and it no longer blocks
  a usable release. Rationale in [docs/REVIEW.md](docs/REVIEW.md).
- The primary quickstart is now "use the Blender you already have" rather than
  a container build.

### Known limitations

- The container image, the macOS and Windows Blender-discovery paths, and the
  `blender` executable subprocess path have not been executed. All testing used
  Blender 4.5.12 as the `bpy` Python module on linux-x86_64.
- No model has been physically printed. All QA is geometric.
- No slicer runs against the output yet.

See [docs/REVIEW.md](docs/REVIEW.md#verification-status) for the full status.
