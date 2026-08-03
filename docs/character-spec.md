# CharacterSpec v1 reference

The authoritative definition is
[`schemas/character-spec-v1.schema.json`](../schemas/character-spec-v1.schema.json).
This page explains what the fields mean and how they interact.

Every object in the contract rejects properties it does not declare. A typo in
a field name is an error, not a silently ignored value.

## The request wrapper

```json
{
  "request_version": "build/v1",
  "generator": "geometric-character@1.0.0",
  "print_profile": { "preset": "fdm-0.4-standard" },
  "spec": { "...": "the CharacterSpec, below" },
  "output_profile": "complete-v1",
  "render_profile": "diagnostic-v1",
  "quality_profile": "geometry-v1"
}
```

| Field | Values | Default |
|---|---|---|
| `request_version` | `build/v1` | required |
| `generator` | `geometric-character@1.0.0` | required |
| `spec` | a CharacterSpec | required |
| `print_profile` | see [Print profiles](#print-profiles) | `fdm-0.4-standard` |
| `output_profile` | `complete-v1`, `print-only-v1` | `complete-v1` |
| `render_profile` | `diagnostic-v1`, `none` | `diagnostic-v1` |
| `quality_profile` | `geometry-v1`, `advisory-v1` | `geometry-v1` |

`print-only-v1` publishes just the STL, `.blend`, QA, and manifest. Rendering
is by far the slowest stage, so this is what you want for batches.

`advisory-v1` records the same measurements but publishes the model even when a
required check fails, marking the manifest `needs_review`.

## CharacterSpec fields

### Required

| Field | Type | Range |
|---|---|---|
| `spec_version` | string | `character/v1` |
| `name` | string | 1–64 chars, must start alphanumeric |
| `style` | enum | `geometric`, `low_poly`, `chibi` |
| `height_mm` | number | 25–250 |

`height_mm` is the **total** finished height including the base and anything
that sticks up, and the exported model matches it to within 0.05 mm. Adding an
antenna does not make the model taller — the generator reserves headroom and
shortens the body to compensate.

`name` is a display name. The filesystem slug is derived from it and is
restricted to lowercase alphanumerics and hyphens, so a name cannot influence
where files are written.

### Style

Style is not a paint job; it changes the silhouette, the primitives, and the
default proportions.

| Style | Head share | Head shape | Mesh | Edges |
|---|---:|---|---|---|
| `geometric` | 0.30 | bevelled box | 32-segment | crisp bevels |
| `low_poly` | 0.26 | icosphere | 8-segment | faceted, no bevel |
| `chibi` | 0.42 | sphere | 32-segment | heavily rounded |

Head, torso, and leg shares are normalised to sum to 1 after your
`proportions` multipliers are applied, which is what keeps total height exact
regardless of how you tune them.

### Optional

| Field | Type | Range | Default |
|---|---|---|---|
| `pose` | enum | `standing`, `t_pose`, `wide_stance` | `standing` |
| `palette` | array of `#RRGGBB` | 1–8 entries | orange/cream/charcoal |
| `proportions.head_scale` | number | 0.5–2.2 | 1.0 |
| `proportions.torso_width` | number | 0.6–1.8 | 1.0 |
| `proportions.limb_scale` | number | 0.6–1.6 | 1.0 |
| `proportions.leg_length` | number | 0.5–1.6 | 1.0 |
| `features.eyes` | enum | `dot`, `visor`, `none` | `dot` |
| `features.ears` | enum | `none`, `round`, `antenna` | `none` |
| `features.horns` | enum | `none`, `short`, `curved` | `none` |
| `features.tail` | enum | `none`, `stub`, `long` | `none` |
| `features.backpack` | boolean | — | `false` |
| `base.enabled` | boolean | — | `true` |
| `base.shape` | enum | `round`, `square` | `round` |
| `base.height_mm` | number | 1–20 | 4 |
| `base.margin_mm` | number | 0–20 | 3 |

Palette slot 0 is the body, 1 the accent (limbs, base), and 2 the detail (eyes,
antenna tip). A shorter palette repeats its last colour, so a one-colour
palette gives a monochrome model.

The base is capped at a quarter of the total height; a taller request is
reduced and the change is reported. Disabling the base is fine — the feet then
form the flat bottom, still resting exactly on Z=0.

## Print profiles

```json
"print_profile": { "preset": "fdm-0.6-draft" }
```

| Preset | Technology | Nozzle | Layer | Min wall | Min feature | Max overhang |
|---|---|---:|---:|---:|---:|---:|
| `fdm-0.2-fine` | FDM | 0.2 mm | 0.10 mm | 0.80 mm | 1.20 mm | 50° |
| `fdm-0.4-standard` | FDM | 0.4 mm | 0.20 mm | 1.20 mm | 2.00 mm | 45° |
| `fdm-0.6-draft` | FDM | 0.6 mm | 0.30 mm | 1.80 mm | 3.00 mm | 45° |
| `resin-standard` | resin | — | 0.05 mm | 0.80 mm | 1.00 mm | 60° |

Override individual fields, alone or on top of a preset:

```json
"print_profile": {
  "preset": "custom",
  "technology": "fdm",
  "nozzle_mm": 0.4,
  "layer_height_mm": 0.15,
  "min_wall_mm": 1.6,
  "min_feature_mm": 2.5,
  "max_overhang_deg": 50,
  "material_density_g_cm3": 1.24
}
```

Contradictory combinations are rejected before Blender starts, with the reason:

- a minimum feature thinner than the minimum wall;
- an FDM minimum wall under two extrusion widths for the stated nozzle;
- a layer height over 80% of the nozzle diameter.

### The profile changes the model

This is the part worth internalising. The generator enforces
`min_feature_mm` while building — every limb, antenna, horn, and tail radius is
raised to meet it — so the same character built for different printers is
genuinely different geometry, and small models get chunkier rather than
failing.

## Limits

| Limit | Value |
|---|---:|
| Request document | 64 KiB |
| Name / slug | 64 / 48 characters |
| Height | 25–250 mm |
| Palette entries | 1–8 |

## What is not accepted

By design, and enforced by the schema rather than by convention: arbitrary
Python or Blender API calls, geometry-node graphs, shaders, add-ons, file
paths, output paths, remote URLs, uploaded `.blend` files, Blender command-line
flags, environment variables, container settings, renderer settings, camera
transforms, and polygon or sample counts.

If a request contains a property the schema does not declare, the build fails
with exit code 3 and names the offending property.
