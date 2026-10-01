# Character request guide and v0.1 contracts

The one-shot builder and local HTTP service accept the same complete `BuildRequest`.
This JSON document selects a reviewed geometric generator, proportions,
accessories, and fixed output and quality profiles.

The request format does not accept Python, Blender operations, paths, URLs,
add-ons, environment variables, or renderer flags.

## Validate a request

Use the pinned builder image to validate the request without a Blender process:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot.json"
```

`make validate` rebuilds the builder from the current checkout.
It usually uses Docker's cache. Thus, a source update cannot leave validation
with an previous schema.

`BUILDER_VALIDATE: PASS` means that the request agrees with the checkout's structural
and runtime input contract. This result does not show that the geometry will pass publication QA.
For that evidence, `make build` and then `make verify` must succeed
for the specified request and source revision.

Contributors can use Python 3.11 or newer for these contract tests on the host:

```sh
export PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest \
  tests.unit.test_request_contract \
  tests.contract.test_json_schemas -v
```

The full Docker-backed suite, including the independently packaged service, is
`make test-unit`. See [Contributing](../CONTRIBUTING.md) for the test matrix.

## Request envelope

Use [Facet Bot](../examples/requests/facet-bot.json) as the first example that passes QA.
[Facet Bot Tidepool](../examples/requests/facet-bot-tidepool.json) changes only the palette and also passes.
[Moss Hopper](../examples/requests/moss-hopper.json) has different geometry and an intentional `needs_review` result.
The [examples guide](../examples/README.md) gives the commands and expected results.

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

The complete UTF-8 request must not be more than 64 KiB.
Each object rejects properties not in the schema.
Names, slugs, numbers, lists, colors, and enums have limits.
Before hash calculation, the runtime sets missing optional fields to deterministic defaults.

## Supported character controls

| Field | Required? | Values and limits | Default |
|---|---:|---|---|
| `spec_version` | yes | Exactly `character/v1` | — |
| `name` | yes | 1–64 ASCII letters, digits, spaces, apostrophes, or hyphens. Must begin and end with a letter or digit | — |
| `slug` | no | 1–48 lowercase letters/digits differentd by single hyphens | Safely derived from `name` |
| `style` | yes | `geometric`, `low_poly`, or `chibi` | — |
| `height_mm` | yes | 25–250 mm. Includes the base | — |
| `pose` | yes | `standing`, `wave`, or `heroic` | — |
| `palette` | yes | 1–8 unique uppercase `#RRGGBB` colors | — |
| `proportions.head_scale` | yes | 0.7–1.6 | — |
| `proportions.body_scale` | no | 0.7–1.4 | `1` |
| `proportions.limb_scale` | yes | 0.7–1.3 | — |
| `material_preset` | no | `matte`, `satin`, or `glossy` | `matte` |
| `eye_preset` | no | `round`, `visor`, or `sleepy` | `round` |
| `components` | no | Unique reviewed component names. a maximum of 16 | `[]` |
| `base` | no | Complete base object described below | Round, 48 × 48 × 5 mm |

The component allowlist is:

```text
antenna-pair  backpack     chest-badge   long-horns    pointed-ears
round-ears    short-horns  stub-tail     swept-tail
```

Select no more than one of `stub-tail` and `swept-tail`.
The runtime normalizes component order before hash calculation.

### What the visible choices change

| Control | Visible effect |
|---|---|
| `style` | `geometric` uses a rounded-box head and rounded body. `low_poly` uses faceted icosphere-derived head/body volumes. `chibi` uses smoother volumes with the largest head-to-body ratio |
| `pose` | `standing` keeps the two arms lowered. `wave` raises and bends the character's right arm. `heroic` bends the two arms to the hips |
| `eye_preset` | `round` makes two rounded eyes, `visor` makes one wide bar, and `sleepy` makes two narrow tilted eyes. All use fixed charcoal rather than a palette swatch |
| `material_preset` | Changes surface roughness only: `matte` is least reflective, `satin` is intermediate, and `glossy` is most reflective |
| `proportions` | `head_scale`, `body_scale`, and `limb_scale` independently change those reviewed regions in the specified bounds. Extreme valid values can fail layout or geometry QA |
| `base.preset` | Selects no display base or a round, square, or hexagonal base with the requested dimensions |
| `components` | Adds only the named reviewed accessory geometry. Paired names add symmetric features, while tail choices are exclusive |

Palette order changes the result.
The first swatch gives the body, base, and limbs their color.
The second gives the head, feet, hands, badge, and accent tips their color.
The third gives the optional backpack its color.
If you supply fewer colors, the generator uses the available swatches again in sequence.

The `.blend` file keeps all 1–8 supplied swatches as native materials for provenance.
The current composition does not always use swatches four through eight on visible geometry.

A base object must contain `preset`, `width_mm`, `depth_mm`, and `height_mm`.
For `round`, `square`, or `hexagonal`, width and depth must be 20–160 mm.
Height must be 2–25 mm. For `none`, set all three dimensions to `0`.

Generator preflight enforces `height_mm - base.height_mm >= 18`.
Some proportion and base combinations pass structural validation but do not fit
the reviewed body layout. The generator rejects these combinations.

The schemas in [`schemas/`](../schemas/) are the portable structural contracts. The immutable models in [`shared/`](../shared/) add strict decoding and semantic rules.

## Implemented generator behavior

`geometric-character@1.0.0` is a closed registry entry.
It is not a general Blender script endpoint.
It accepts only a validated `BuildRequest`.
Before it replaces the active scene, it rejects impossible height and base combinations.
Then it starts from Blender factory state.
The generated scene has only these top-level collections:

```text
CAMERAS
CHARACTER
LIGHTS
PRINT
SET
```

`CHARACTER` contains individually named procedural display meshes.
Native materials have limits. The meshes have semantic component metadata.
`PRINT` contains one and only one derived `PrintableShell`.
You can examine each source display mesh independently.

Total requested height includes the base.
The base display mesh uses the specified requested width, depth, and height.

The G2 gate starts four new Blender 4.5 processes.
It builds Facet Bot two times and Moss Hopper two times.
These fixtures have different geometry. The gate does these checks:

- Source and evaluated meshes are finite and not empty.
- Collections, objects, materials, and triangles agree with their placement rules and limits.
- Materials use no images.
- Semantic component inventories agree with the request.
- The printable shell is connected and manifold, with consistent winding and positive signed volume.
- Requested height is in tolerance.
- Repeated builds give the same structural evidence.
- The two examples have different topology.

The G3 gate also builds and independently verifies the Tidepool palette example.

For the native gate, use an empty evidence directory that you own outside the repository:

```sh
"$PYTHON" tests/blender_integration/g2_gate.py \
  --blender /absolute/path/to/blender \
  --evidence-dir /absolute/path/to/new-temporary-directory
```

The command writes JSON evidence without paths only in the specified temporary directory.
It starts Blender with factory startup and offline mode.
It disables automatic embedded-script execution.
A probe failure gives a nonzero Python exit code.

## Native artifact runner

G3 gives a fixed public script interface after Blender's `--` boundary:

```sh
/absolute/path/to/blender \
  --background --factory-startup --offline-mode --disable-autoexec \
  --python-exit-code 12 --python blender/runner.py -- \
  --request examples/requests/facet-bot.json \
  --output /absolute/path/to/new-output-directory
```

The output parent must exist. The output directory must not exist.
The runner accepts no other public arguments.
It validates the request and does preflight checks before scene creation.
It writes into a mode-`0700` staging directory beside the output directory.
It saves, exports, and renders with fixed profiles.

A new child Blender process does reload and re-import verification.
Then the runner writes `qa.json`.
On success, it writes `manifest.json` last and atomically renames the complete tree into place.
On failure, it removes private staging data and publishes nothing.

The G3 review gate builds Facet Bot two times.
It also does tests for invalid input, `needs_review`, and corrupted artifacts:

```sh
"$PYTHON" tests/blender_integration/g3_gate.py \
  --blender /absolute/path/to/blender \
  --work-dir /absolute/path/to/dedicated-temporary-directory
```

Facet Bot passes with conservative actual-shell lower bounds of 2.3001 mm for walls and 2.3089 mm for semantic features.
Moss Hopper is a valid generation request but gives `needs_review`.
Unresolved short wall candidates make the mandatory wall measurement unknown.
Thus, exit `11` leaves no output or success manifest.

## Deterministic hashes

Before Blender starts, the runtime rejects duplicate keys, non-finite values,
excessive nesting, pathological decimal exponents, invalid UTF-8, and requests above the size limit.
Then it does these operations:

1. expands defaults and derives a safe slug when needed.
2. normalizes equivalent numeric forms such as `95`, `95.0`, and `9.5e1`.
3. sorts object keys and order-insensitive component selections.
4. serializes compact canonical UTF-8 JSON.
5. computes SHA-256 request and nested-spec hashes.

Equivalent normalized requests give the same contract hashes.
Render bytes and `.blend` bytes can differ.

## QA status contract

`qa/v1` has two validation layers:

- JSON Schema enforces shape, types, directly expressible limits, and the evidence necessary for a `passed` report.
- `QualityReport` is normative for cross-field arithmetic: requested-height agreement and GLB/STL for each axis bounds use the greater of 0.2 mm or 0.5%.

The terminal mapping is fixed:

| QA status | Build status | Exit | Success manifest |
|---|---|---:|---|
| `passed` | `succeeded` | `0` | allowed |
| `failed` | `failed` | `11` | not permitted |
| `needs_review` | `needs_review` | `11` | not permitted |

If a mandatory property cannot be measured, the result is `needs_review`.
It cannot pass.

These codes come from the builder process. Direct CLI or Docker callers receive the specified code.
For a failed recipe, `make build` or `make verify` usually gives GNU Make exit code `2`.
Use `BUILDER: FAIL[n]` or Make's `Error n` diagnostic to find the builder code.

## Manifest contract

The builder writes `manifest/v1` only on success.
It records canonical request/spec hashes, generator and Blender provenance,
millimeter dimensions, and the QA summary that passed.
It records SHA-256 and byte size for only these eight artifacts:

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

`manifest.json` excludes its own hash. The 2 GiB publication limit includes all
nine files. This includes the canonical manifest and its last newline. The
builder, service, and download client use this same total.

G3 checks artifact hashes, Blender and source provenance, new Blender reload,
and GLB/STL re-import evidence before success publication.

## Versioning

Keep schema IDs, profile names, artifact paths, units, hashes, and exit mappings as public contracts.
Do tests for additive changes. Keep the existing meaning.
Use a new version identifier for not compatible changes.
