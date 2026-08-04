# v0.1 JSON Contracts

Status: contracts passed in G1, deterministic geometry generation passed in G2, native artifact publication plus complete geometry QA passed in G3, and the pinned keyless container plus trusted `builder build|verify` wrapper passed in G4.

The one-shot builder and later HTTP service accept the same complete `BuildRequest`. Callers choose a reviewed generator and bounded profiles; they do not submit Python, Blender operations, paths, URLs, add-ons, environment variables, or renderer flags.

## Try the contracts

Python 3.11 or newer is required for the project test environment.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests -v
```

The tests execute all four schemas with a Draft 2020-12 validator, resolve the local `BuildRequest` to `CharacterSpec` reference, validate both examples, and exercise runtime-only cross-field rules.

## Request envelope

See [facet-bot.json](../examples/requests/facet-bot.json) for the canonical starter and [moss-hopper.json](../examples/requests/moss-hopper.json) for a materially different second character.

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

| Field | v0.1 contract |
|---|---|
| `name` / `slug` | Display name of ASCII letters, digits, spaces, apostrophes, and hyphens up to 64 characters; explicit or safely derived lowercase slug up to 48 |
| `style` | `geometric`, `low_poly`, or `chibi` |
| `height_mm` | 25–250 mm |
| `pose` | `standing`, `wave`, or `heroic` |
| `palette` | 1–8 unique uppercase `#RRGGBB` colors |
| `proportions` | Bounded head, body, and limb scales |
| `material_preset` | `matte`, `satin`, or `glossy` |
| `eye_preset` | `round`, `visor`, or `sleepy` |
| `components` | Up to 16 unique values from the schema allowlist; `stub-tail` and `swept-tail` are mutually exclusive |
| `base` | `none`, `round`, `square`, or `hexagonal` with bounded millimeter dimensions |

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
