# Headless Blender Character Builder

Turn a small JSON document into a printable 3D character: real Blender
geometry, a watertight STL, an editable `.blend`, preview renders, and a
machine-readable print-readiness report.

```sh
git clone https://github.com/joseph-robert-f/headless-blender-character-builder.git
cd headless-blender-character-builder
./hbcb-cli build --preset facet-bot -o build/facet-bot
```

No account, no API key, no config file, no `.env`. If you already have Blender
installed, that is the whole setup.

```
build/facet-bot/
├── model.stl          <- drop this into your slicer
├── model.blend        <- open and keep editing
├── model.glb          <- preview in a browser or engine
├── preview.png
├── diagnostics/       <- front, side, back orthographic views
├── qa.json            <- every print measurement
└── manifest.json      <- hashes, provenance, what was built
```

> **Status: v0.1, early.** The geometry, exports, QA, and CLI are implemented
> and tested. The HTTP service described in [PLAN.md](PLAN.md) is not built.
> Read [docs/REVIEW.md](docs/REVIEW.md) for what is verified and what is not —
> notably, nothing here has been physically printed yet.

## What it does and does not do

**Does:** compose original geometric, low-poly, and chibi characters from
Blender primitives; boolean-union them into one watertight manifold shell;
export STL/GLB/`.blend` in true millimetres; measure wall thickness, overhangs,
shells, and volume against *your printer's* limits; and re-verify every
artifact in a second, independent Blender process.

**Does not:** text-to-3D, organic sculpting, likenesses of real people,
copyrighted characters, rigging, or animation. It also does not guarantee a
successful print — the QA is geometric evidence, not a slicer result. See
[Print readiness](#print-readiness).

## Install

Pick whichever line describes you.

**You already have Blender 4.2 or newer.** Nothing to install.

```sh
./hbcb-cli doctor        # confirms it can find Blender
./hbcb-cli build --preset facet-bot -o build/facet-bot
```

If Blender is installed somewhere unusual, point at it:

```sh
export HBCB_BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
```

**You do not have Blender, and would rather not install the app.** Blender
publishes itself as a Python wheel:

```sh
pip install -e ".[bundled-blender]"    # pulls in bpy; ~400 MB, Python 3.11
hbcb build --preset facet-bot -o build/facet-bot
```

**You want a reproducible, locked-down build.** The container runs with no
network access at all:

```sh
make docker-demo
```

> The container path is written but has not been executed yet — see
> [docs/REVIEW.md](docs/REVIEW.md#verification-status).

## Using it

```sh
hbcb presets                       # what is bundled
hbcb profiles                      # what printers are known
hbcb build --preset cocoa-cub -o out/cub
hbcb verify out/cub                # re-check in a fresh Blender process
```

Common tweaks need no JSON at all:

```sh
hbcb build --preset facet-bot --height 120 -o out/tall
hbcb build --preset facet-bot --print-profile resin-standard -o out/resin
hbcb build --preset facet-bot --no-renders -o out/fast     # seconds, not a minute
```

When you want more control, start from a preset and edit it:

```sh
hbcb preset facet-bot > my-character.json
$EDITOR my-character.json
hbcb validate my-character.json
hbcb build --request my-character.json -o out/mine
```

A complete request is small:

```json
{
  "request_version": "build/v1",
  "generator": "geometric-character@1.0.0",
  "print_profile": { "preset": "fdm-0.4-standard" },
  "spec": {
    "spec_version": "character/v1",
    "name": "facet-bot",
    "style": "geometric",
    "height_mm": 95,
    "palette": ["#E87532", "#FFF3D6", "#2E3138"],
    "proportions": { "head_scale": 1.2, "limb_scale": 0.95 },
    "features": { "eyes": "dot", "ears": "antenna" },
    "base": { "enabled": true, "shape": "round", "height_mm": 4 }
  }
}
```

Every field, with its range, is in
[docs/character-spec.md](docs/character-spec.md). The schemas in `schemas/` are
ordinary JSON Schema 2020-12, so most editors will autocomplete and validate
them for you.

### Calling Blender directly

The CLI is a convenience wrapper. The underlying contract is a plain Blender
invocation, and nothing is hidden from you:

```sh
blender --background --factory-startup --offline-mode --disable-autoexec \
  --python blender/runner.py -- \
  build --request examples/requests/facet-bot.json --output build/demo
```

## Print readiness

The printer is an input, not a hardcoded assumption. A print profile sets the
minimum wall, minimum feature size, and overhang limit — and it drives *both*
the geometry and the checks.

| Profile | Layer | Min wall | Min feature |
|---|---:|---:|---:|
| `fdm-0.2-fine` | 0.10 mm | 0.80 mm | 1.20 mm |
| `fdm-0.4-standard` (default) | 0.20 mm | 1.20 mm | 2.00 mm |
| `fdm-0.6-draft` | 0.30 mm | 1.80 mm | 3.00 mm |
| `resin-standard` | 0.05 mm | 0.80 mm | 1.00 mm |

Because the profile drives generation, a model too small for its printer gets
*thicker*, rather than failing:

```
$ hbcb build --preset facet-bot --height 60 --print-profile fdm-0.6-draft -o out
  adjusted: antenna diameter raised from 1.66 mm to 3.00 mm to meet the
            profile's 3.00 mm minimum feature size
```

Every adjustment is reported and recorded in `manifest.json`. Nothing is
changed silently.

`qa.json` then records:

| Check | Fails the build? |
|---|---|
| Watertight — no open boundary edges | yes |
| Manifold — no non-manifold edges or vertices | yes |
| Single connected shell | yes |
| Positive volume, normals outward | yes |
| Minimum solid thickness vs. `min_wall_mm` | yes |
| Unsupported overhang area | warning |
| Bed contact area | warning |
| Zero-area faces | warning |

Plus solid volume, an estimated mass at 100% infill, surface area, and exact
bounding dimensions.

Two honest caveats. The thickness check uses the 1st percentile of a
per-face inward raycast rather than the raw minimum, so a single sliver face on
a bevel seam cannot condemn a sound model — the absolute minimum is reported
alongside it. And overhangs are a warning because they are printable with
supports; whether you want to print them is your call, not the tool's.

Use `--advisory` to publish a model whose required checks failed, so you can
look at it rather than guess.

## Verifying a build

`hbcb verify` runs in a **fresh Blender process** that did not build the model.
It re-hashes every artifact against the manifest, reopens the `.blend`, and
re-imports the STL and GLB to confirm they load at the right size with the
right topology. That last part matters: a mesh can be watertight in memory and
not watertight as a file.

```sh
$ hbcb verify build/facet-bot
checking artifact hashes
reopening model.blend in this fresh process
re-importing model.stl
  model.stl: 5054 triangles, watertight
re-importing model.glb
verified: 8 artifacts, hashes match, .blend and exports re-open cleanly
```

## Exit codes

Stable, for scripting.

| Code | Meaning |
|---:|---|
| 0 | success |
| 2 | bad command line |
| 3 | invalid or rejected request |
| 4 | filesystem failure |
| 10 | Blender generation, render, or export failure |
| 11 | verification or a required print check failed |
| 12 | unexpected internal failure |
| 124 | timeout |

## Development

```sh
make help
make test-unit      # 42 tests, no Blender needed, <1s
make test-blender   # 16 geometry and artifact tests, needs Blender
make lint
make check          # everything CI runs
```

The `hbcb` package is standard-library only, deliberately: the same modules run
inside Blender's bundled Python, which cannot install packages. Please keep it
that way — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Safety and rights

- Requests are strict, closed JSON. Arbitrary Python, Blender flags, add-ons,
  file paths, and URLs are not accepted from callers, by design.
- The container runs unprivileged, with `--network none` and all capabilities
  dropped.
- Geometry checks are diagnostic evidence, not a warranty that a model prints.
- You are responsible for the rights to anything you generate. The project
  ships no franchise characters and grants no rights to third-party designs.

## License

Source is GPL-3.0-or-later. Original sample assets use the separate policy in
[ASSET_LICENSE.md](ASSET_LICENSE.md).

## Where to read next

- [docs/REVIEW.md](docs/REVIEW.md) — what changed, what is verified, what is next
- [docs/character-spec.md](docs/character-spec.md) — every field and its range
- [docs/architecture.md](docs/architecture.md) — how a build actually runs
- [PLAN.md](PLAN.md) — the original long-range plan, including the unbuilt service
