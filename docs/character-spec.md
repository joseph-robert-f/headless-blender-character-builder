# Character request guide and v0.1 contracts

Use a bounded JSON recipe to choose a reviewed geometric character generator,
its proportions and accessories, and fixed output/quality profiles. This is a
declarative character format—not a way to submit Python, Blender operations,
paths, URLs, add-ons, environment variables, or renderer flags.

The one-shot builder and later HTTP service accept the same complete `BuildRequest`. Callers choose a reviewed generator and bounded profiles; they do not submit Python, Blender operations, paths, URLs, add-ons, environment variables, or renderer flags.

## Validate a request

The fastest supported check uses the pinned builder image and does not start
Blender:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot.json"
```

`BUILDER_VALIDATE: PASS` means the request satisfies the structural and runtime
input contract. It does **not** mean the generated geometry will pass
publication QA. Only a successful `make build` followed by `make verify` proves
that for a particular request and source revision.

Contributors who are changing the contract can run its focused host tests with
Python 3.11 or newer:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest \
  tests.unit.test_request_contract \
  tests.contract.test_json_schemas -v
```

The full Docker-backed suite, including the separately packaged service, is
`make test-unit`. See [Contributing](../CONTRIBUTING.md) for the test matrix.

## Request envelope

See [Facet Bot](../examples/requests/facet-bot.json) for the passing canonical
starter and [Moss Hopper](../examples/requests/moss-hopper.json) for a
materially different, intentionally `needs_review` request. The
[examples guide](../examples/README.md) gives exact commands and expected
outcomes.

```json
{
  "request_version": "build/v1",
  "generator": "geometric-character@1.0.0",
  "spec": {
    "spec_version": "character/v1",
    "name": "Facet Bot",
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

The complete UTF-8 request is limited to 64 KiB. Every object rejects extra properties. Names, slugs, numbers, lists, colors, and enums are bounded; missing optional fields expand to deterministic defaults before hashing.

## Supported character controls

| Field | Required? | Values and limits | Default |
|---|---:|---|---|
| `spec_version` | yes | Exactly `character/v1` | — |
| `name` | yes | 1–64 ASCII letters, digits, spaces, apostrophes, or hyphens; must begin and end with a letter or digit | — |
| `slug` | no | 1–48 lowercase letters/digits separated by single hyphens | Safely derived from `name` |
| `style` | yes | `geometric`, `low_poly`, or `chibi` | — |
| `height_mm` | yes | 25–250 mm; includes the base | — |
| `pose` | yes | `standing`, `wave`, or `heroic` | — |
| `palette` | yes | 1–8 unique uppercase `#RRGGBB` colors | — |
| `proportions.head_scale` | yes | 0.7–1.6 | — |
| `proportions.body_scale` | no | 0.7–1.4 | `1` |
| `proportions.limb_scale` | yes | 0.7–1.3 | — |
| `material_preset` | no | `matte`, `satin`, or `glossy` | `matte` |
| `eye_preset` | no | `round`, `visor`, or `sleepy` | `round` |
| `components` | no | Unique reviewed component names; at most 16 | `[]` |
| `base` | no | Complete base object described below | Round, 48 × 48 × 5 mm |

The component allowlist is:

```text
antenna-pair  backpack     chest-badge   long-horns    pointed-ears
round-ears    short-horns  stub-tail     swept-tail
```

`stub-tail` and `swept-tail` are mutually exclusive. Component order is
normalized before hashing.

A base object always supplies `preset`, `width_mm`, `depth_mm`, and
`height_mm`. For `round`, `square`, or `hexagonal`, width and depth are 20–160
mm and height is 2–25 mm. For `none`, all three dimensions must be `0`.
The generator preflight also requires `height_mm - base.height_mm >= 18`; some
extreme but structurally valid proportion/base combinations can still be
rejected because the reviewed body layout does not fit.

The schemas in [`schemas/`](../schemas/) are the portable structural contracts. The immutable models in [`shared/`](../shared/) add strict decoding and semantic rules.

## Implemented generator behavior

`geometric-character@1.0.0` is a closed registry entry, not a general Blender scripting endpoint. It accepts only an already validated `BuildRequest`, rejects impossible height/base combinations before replacing the active scene, and then starts from Blender factory state. The generated scene has exactly these top-level collections:

```text
CAMERAS
CHARACTER
LIGHTS
PRINT
SET
```

`CHARACTER` contains separately named procedural display meshes with bounded native materials and semantic component metadata. `PRINT` contains exactly one derived `PrintableShell`; the source display meshes remain independently inspectable. Total requested height includes the base, and the base display mesh uses the requested width, depth, and height exactly.

The G2 gate starts four fresh Blender 4.5 processes: both bundled examples twice. It checks finite nonempty source/evaluated meshes, collection placement, object/material/triangle caps, no image-backed materials, semantic component inventories, one connected manifold and consistently wound printable shell, positive signed volume, requested-height tolerance, repeat-stable structural evidence, and cross-example topology differences.

Native contributors can run the gate with an empty caller-owned evidence directory outside the repository:

```sh
python3 tests/blender_integration/g2_gate.py \
  --blender /absolute/path/to/blender \
  --evidence-dir /absolute/path/to/new-temporary-directory
```

The command emits path-free JSON evidence only in the supplied temporary directory. Blender is launched with factory startup, offline mode, automatic embedded-script execution disabled, and a nonzero Python exit code on probe failure.

## Native artifact runner

G3 adds a deliberately narrow public script interface after Blender's `--` boundary:

```sh
/absolute/path/to/blender \
  --background --factory-startup --offline-mode --disable-autoexec \
  --python-exit-code 12 --python blender/runner.py -- \
  --request examples/requests/facet-bot.json \
  --output /absolute/path/to/new-output-directory
```

The output parent must already exist and the output itself must not. The runner accepts no other public arguments. It validates and preflights before scene creation, writes into a mode-`0700` sibling staging directory, saves/exports/renders with fixed profiles, invokes a fresh child Blender process for reload/re-import verification, writes `qa.json`, writes a success-only `manifest.json` last, and atomically renames the complete tree into place. Any failure removes private staging and publishes nothing.

The explicit G3 review gate builds Facet Bot twice and exercises invalid input, `needs_review`, and corrupted-artifact paths:

```sh
python3 tests/blender_integration/g3_gate.py \
  --blender /absolute/path/to/blender \
  --work-dir /absolute/path/to/dedicated-temporary-directory
```

Facet Bot passes with conservative actual-shell lower bounds of 2.3001 mm for walls and 2.3089 mm for semantic features. Moss Hopper remains a valid generation request but produces `needs_review`: unresolved short wall candidates make the mandatory wall measurement unknown, so exit `11` leaves no output or success manifest.

## Deterministic hashes

The runtime rejects duplicate keys, non-finite values, excessive nesting, pathological decimal exponents, invalid UTF-8, and oversized requests before Blender starts. It then:

1. expands defaults and derives a safe slug when needed;
2. normalizes equivalent numeric forms such as `95`, `95.0`, and `9.5e1`;
3. sorts object keys and order-insensitive component selections;
4. serializes compact canonical UTF-8 JSON;
5. computes SHA-256 request and nested-spec hashes.

Equivalent normalized requests therefore produce the same contract hashes. Render bytes and `.blend` bytes are not promised to be identical.

## QA status contract

`qa/v1` has two validation layers:

- JSON Schema enforces shape, types, directly expressible limits, and the evidence required for a `passed` report.
- `QualityReport` is normative for cross-field arithmetic: requested-height agreement and GLB/STL per-axis bounds use the greater of 0.2 mm or 0.5%.

The terminal mapping is fixed:

| QA status | Build status | Exit | Success manifest |
|---|---|---:|---|
| `passed` | `succeeded` | `0` | allowed |
| `failed` | `failed` | `11` | forbidden |
| `needs_review` | `needs_review` | `11` | forbidden |

Any unmeasurable mandatory property produces `needs_review`; it never silently passes.

These are builder-process codes. Direct CLI or Docker callers receive the
listed code. Through `make build` or `make verify`, GNU Make usually exits `2`
for any failed recipe; use `BUILDER: FAIL[n]` or Make's `Error n` diagnostic to
recover the underlying builder code.

## Manifest contract

`manifest/v1` is success-only. It records canonical request/spec hashes, generator and Blender provenance, millimeter dimensions, passing QA summary, and SHA-256 plus byte size for exactly these eight artifacts:

```text
model.blend
model.glb
model.stl
preview.png
diagnostics/front.png
diagnostics/side.png
diagnostics/back.png
qa.json
```

`manifest.json` excludes its own hash. Aggregate published artifacts are limited to 2 GiB. G3 implements cross-artifact hash recomputation, exact Blender/source provenance, fresh Blender reload, and GLB/STL re-import evidence before success publication.

## Versioning

Treat schema IDs, profile names, artifact paths, units, hashes, and exit mappings as public contracts. Additive changes require tests and must preserve old meaning; breaking changes require a new version identifier.
