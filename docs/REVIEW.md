# Repository review and proposed direction

Reviewed at commit `6619b8b`, before the changes described in "What this change
does" below.

## Summary

The repository was 120 KB of planning documents and zero lines of code. The
planning was unusually thorough — the original plan (now archived at
[`plan-archive-2026-07.md`](plan-archive-2026-07.md)) had already settled the artifact
contract, exit codes, unit conventions, and security boundary, and most of that
thinking survives intact in the implementation. The problem was not the quality
of the plan. It was that the plan's v0.1 was too large to finish, and that
nothing in it could be run.

Three findings drove the changes.

### 1. Nothing was executable, and the plan's v0.1 was too big to change that

The original plan's §18 made **both** of these release-blocking for v0.1:

- the deterministic Blender builder, and
- an asynchronous self-hosted service with FastAPI, Postgres, Redis, MinIO,
  Compose orchestration, bearer auth, a VPS deployment package, backup/restore
  runbooks, and a recovery drill.

The nine gates G0–G9 had to be completed in order, and the service work (G5–G8)
was four of them. So the first runnable geometry sat behind roughly half a
release of infrastructure that produces no geometry at all.

For a project whose value is "JSON in, printable STL out", that ordering is
backwards. The builder is the product; the service is a deployment topology for
it. **Proposed: cut the service out of v0.1 entirely** and ship the builder
alone. Everything in G5–G8 remains a coherent future milestone, and the
interfaces it needs are unchanged — a queue consumer calls the same
`blender/build.py:run` the CLI does.

### 2. The plug-and-play story required Docker, which is the wrong default

The original plan's §5 made `make demo` — clone, then `docker build` a Blender image —
the primary path. That is a reproducibility path, not an accessibility path. It
asks a user who already has Blender installed to download it again inside a
container, and it puts a multi-gigabyte image build between them and their
first STL.

**Proposed: make "use the Blender you already have" the primary path**, keep
the container for reproducibility and CI, and add a third path for people who
have neither. All three now run the identical runner:

| Path | Command | Needs |
|---|---|---|
| Existing Blender | `./hbcb-cli build --preset facet-bot -o out` | Blender 4.2+ |
| No Blender at all | `pip install -e ".[bundled-blender]"` then `hbcb build …` | pip |
| Reproducible | `make docker-demo` | Docker |

### 3. Nothing tied the model to an actual printer

This is the substantive gap, and the one most worth fixing. The plan specified
fixed geometry thresholds — 1.2 mm walls, 2.0 mm features (§8) — as global
constants. But those numbers are properties of *a printer*, not of a model. A
0.6 mm draft nozzle cannot do a 1.2 mm wall well; a resin printer does 0.8 mm
comfortably. A single hardcoded pair is either too strict for one user or
unsafe for another.

Worse, the thresholds were only ever going to be *checked*. A model whose
antenna came out at 1.6 mm would fail QA and the user would be told to go edit
their request.

**Proposed, and implemented:** make the printer a first-class input.

```json
"print_profile": { "preset": "fdm-0.4-standard" }
```

The resolved profile then drives **both** halves of the pipeline. The generator
thickens any limb, antenna, horn, or tail below `min_feature_mm` *at
construction time* and reports what it changed; QA judges the result against
the same numbers. Building the same character for a 0.6 mm nozzle produces
visibly chunkier geometry, not a failure:

```
$ hbcb build --preset facet-bot --height 60 --print-profile fdm-0.6-draft -o out
  adjusted: antenna diameter raised from 1.66 mm to 3.00 mm to meet the
            profile's 3.00 mm minimum feature size
```

Four profiles ship (`fdm-0.4-standard`, `fdm-0.6-draft`, `fdm-0.2-fine`,
`resin-standard`), and `custom` accepts explicit values. Contradictory profiles
are rejected up front with the reason — asking for a 0.5 mm wall from a 0.8 mm
nozzle fails in milliseconds rather than after a five-hour print.

Two print metrics the plan did not have were also added, because they are what
users actually get wrong: **unsupported overhang area** (downward-facing
surface steeper than the profile allows, excluding faces resting on the bed)
and **bed contact area**. Both are reported as warnings rather than failures —
they are printable with supports, so they are facts about print setup, not
defects in the geometry.

## What this change does

Implements the deterministic builder end to end. Concretely:

- `hbcb/` — stdlib-only shared core: canonical JSON and hashing, a JSON Schema
  subset validator, request resolution, print profiles, presets, manifest,
  Blender discovery, and the CLI.
- `blender/` — scene, primitives, materials, the `geometric-character@1.0.0`
  generator, exporters, Cycles rendering, print QA, and an independent verifier.
- `schemas/` — four versioned JSON Schema documents covering the request, the
  character spec, the manifest, and the QA report.
- Three original presets that are materially different, not one renamed scene.
- 42 unit tests (no Blender needed) and 16 Blender integration tests.
- CI running the unit matrix, lint, Blender integration, and a container build.

### Why the core has no dependencies

`hbcb/` imports nothing outside the standard library, including the schema
validator. This is not minimalism for its own sake: the same modules must run
inside Blender's bundled Python, which cannot install packages and which users
must not be asked to modify. Publishing real JSON Schema files while validating
with a hand-written subset is a genuine risk of divergence, so
`tests/unit/test_schema_conformance.py` holds the bundled validator against the
reference `jsonschema` package whenever that package is installed, and asserts
that anything the reference rejects the bundled one rejects too.

### Three geometry findings worth recording

These were found by the verifier and are the kind of thing that silently ships
otherwise.

**Coplanar surfaces produce holes in the STL.** The `capsule` primitive
originally ended its cylinder exactly at the cap sphere's equator, and used the
same radius for both. Two tangent surfaces union into a ring of zero-area
faces; Blender's own STL importer then strips those faces, leaving open
boundary edges — a mesh that looked watertight in Blender but was not watertight
as a file. Extending the shaft past the equator and shrinking the cap by 1.5%
makes the intersection transversal and drops degenerate faces on `facet-bot`
from 42 to 0.

**Cleaning the boolean result made it worse.** The obvious fix for those
degenerate faces — merge-by-distance — was measured across thresholds from 1e-5
to 5e-4 mm, with and without a degenerate-edge dissolve. Every variant turned a
watertight manifold mesh into one with open boundary edges, because at a
boolean seam the "duplicate" vertices are distinct corners of the surface. The
union's topology is now left exactly as the solver produced it.

**Renders were nearly black.** Cycles computes lamp falloff treating one
Blender unit as one metre, but this project's unit is the millimetre, so a lamp
200 units away is treated as 200 m away. The rig now uses sun lamps, whose
strength is distance-independent, giving identical exposure for a 25 mm figure
and a 250 mm one.

## What is deliberately not here

- **The asynchronous service** (archived plan G5–G8): FastAPI, Postgres, Redis,
  MinIO, Compose, VPS package. Cut from v0.1 per finding 1.
- **The OpenAI planner and MCP adapter**: already post-v0.1 in the plan.
- **A real slicer in the loop.** The QA here is geometric. Running
  PrusaSlicer's CLI on the STL and reporting its diagnostics would turn
  "probably printable" into "this slices", and is the single highest-value next
  addition.
- **Verified container and Windows/macOS paths.** See "Verification status".

## Verification status

Everything below was run against Blender 4.5.12 LTS on linux-x86_64.

| Check | Result |
|---|---|
| Unit tests (42) | pass |
| Blender integration tests (16) | pass |
| `ruff check` / `ruff format --check` | clean |
| Build + verify, all three presets, full artifact set | pass |
| STL re-import: watertight, manifold, single shell, exact dimensions | pass |
| Heights 25/60/137.5/250 mm exact to 0.05 mm | pass |
| Determinism: identical request, identical structure | pass |
| Failing-QA path publishes evidence and marks `needs_review` | pass |

**Not verified in this environment**, and flagged rather than assumed:

- **The container image was never built.** The sandbox proxy blocks
  `download.blender.org` and Docker's registry, so `docker/builder.Dockerfile`
  and the `container` CI job are written but unexercised. The Dockerfile
  installs Blender from the same pinned `bpy` wheel that every passing test
  used, so the risk is in the packaging, not the Blender version — but it needs
  one real run before anyone relies on it.
- **macOS and Windows.** `hbcb/blender_finder.py` has candidate paths for both;
  only the Linux path has been executed.
- **The `blender` executable path.** All testing used Blender as the `bpy`
  Python module, because no Blender binary could be downloaded here. The
  subprocess path in `hbcb/cli.py` — the `blender --background --python` flags,
  output filtering, and the exit-code sentinel — is therefore untested. The
  sentinel exists precisely because Blender's handling of a script's
  `sys.exit` is inconsistent across versions; it should be confirmed on a real
  install.
- **No physical print.** Every QA number is geometric. Nothing here has been
  put on a printer.

## Suggested order for what comes next

1. Run `make docker-demo` and `hbcb doctor` on a machine with a real Blender
   install. Closes the three unverified paths above.
2. Add slicer-backed QA (PrusaSlicer or CuraEngine CLI in the builder image),
   reporting real layer counts, support volume, and print time.
3. Print one `facet-bot` and record the measured dimensions against
   `manifest.json`. That is the only thing that turns the QA claims from
   plausible into evidenced.
4. Add generators. The registry seam is `blender/generator.py`; a second
   generator is what proves the schema is a contract rather than one scene.
5. Then, if demand exists, the service from the archived plan G5–G8 — unchanged in
   design, just no longer blocking a usable release.
