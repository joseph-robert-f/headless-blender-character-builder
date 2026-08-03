# Architecture

## The shape of it

```
BuildRequest JSON
      |
      v
  hbcb/spec.py ............ validate, fill defaults, resolve the print profile
      |
      v
  blender/build.py ........ orchestrate, stage, publish
      |
      +-- generator.py ..... primitives -> boolean union -> one watertight shell
      +-- qa.py ............ topology, thickness, overhangs, volume
      +-- exporters.py ..... .blend / .stl / .glb
      +-- render.py ........ preview + three orthographic views
      |
      v
  build/<name>/ ........... artifacts + qa.json + manifest.json
      |
      v
  blender/verify.py ....... fresh process: re-hash, reopen, re-import
```

## Two packages, one rule

**`hbcb/`** is standard-library only. Not for elegance — because these modules
have to run inside Blender's bundled Python, which cannot install packages and
which users must not be asked to modify. That constraint is why the JSON Schema
validator is hand-written rather than a dependency, and it is why adding a
third-party import to this package would break the native path.

**`blender/`** imports `bpy` and only runs inside Blender.

Because both halves are shared, the native CLI, the container, and any future
HTTP service resolve requests through the same code. None of them can drift
into accepting something the others reject.

## Millimetres everywhere

One Blender unit is one millimetre. Z is up. A finished model rests on Z=0.

This matches how slicers read STL files, and it removes a whole class of scale
bugs — but it has two consequences that are easy to trip over, both documented
at their call sites:

- **glTF is metres.** `exporters.export_glb` scales the object by 1/1000 for
  the export and reverts immediately.
- **Cycles lamp falloff assumes metres.** A point or area lamp 200 units away
  is treated as 200 m away, and the render comes out nearly black. The lighting
  rig uses sun lamps, whose strength is distance-independent.

## Why the boolean union

The generator builds 15–25 overlapping closed primitives and unions them into
one mesh with a single Boolean modifier over a collection.

A pile of intersecting-but-separate solids looks identical in a render and
slices into a mess of internal walls. One manifold shell is what a slicer
wants. This is also why parts are deliberately overlapped by a weld margin
rather than placed edge to edge: touching at a single face produces two shells,
not one.

Two related rules the geometry follows, both learned from measurements
recorded in [REVIEW.md](REVIEW.md):

- **Never let two surfaces be tangent or coplanar.** Tangent surfaces union
  into rings of zero-area faces, which Blender's STL importer then strips,
  leaving holes.
- **Do not "clean" the union.** Merge-by-distance on a boolean result tears the
  manifold, because at a seam the near-coincident vertices are distinct corners
  of the surface. Only normals are recalculated.

## Staging

Artifacts are written to `<output>/.hbcb-staging/` and moved into place only
after QA. `manifest.json` is written last. So the presence of a manifest in an
output directory is itself the signal that the directory is complete — an
interrupted build cannot leave something that looks finished.

The one exception is a build that fails a required print check: the evidence is
published anyway, with `status: "needs_review"`, because a failed check is
exactly when you want to look at the renders.

## Verification is a separate process

`blender/verify.py` runs in a Blender process that did not build the model. It
re-hashes artifacts against the manifest, reopens the `.blend`, and re-imports
the STL and GLB.

The re-import is the part that earns its keep. A mesh can be watertight in
memory and not watertight as a file — that exact bug was found this way, and
would not have been caught by inspecting the scene that produced it.

## Provenance

`manifest.json` records two request hashes:

- `request_sha256` — the document as submitted, which is what an audit trail or
  idempotency key cares about;
- `resolved_sha256` — after defaults are filled, which is what determines the
  geometry. Spelling a default out explicitly changes the first and not the
  second.

Plus the Blender version, platform, project revision (from
`HBCB_PROJECT_REVISION`, the image's baked-in revision, or `git rev-parse`),
and a sha256 and byte count for every artifact except the manifest itself.

There is no seed. `geometric-character@1.0.0` makes no random choices, so an
identical request produces an identical structure without one.

## Extending it

**A new generator** implements `generate(spec, print_profile) -> (object,
Report)` and gets added to the `generator` enum in the request schema.
`blender/build.py` needs no changes. Adding one is the best way to prove the
schema is a contract rather than one hardcoded scene.

**A new print check** adds a measurement in `qa.py:measure` and a check in
`qa.py:evaluate`. Mark it `required=False` unless it identifies a defect in the
geometry itself rather than a property of the print setup.

**A new export format** adds a function to `exporters.py`, an entry in
`hbcb/layout.py`, and a re-import check in `verify.py`. Do not add an export
without the re-import check.

**An HTTP service** — deferred, see [PLAN.md](../PLAN.md) §4 — would call
`blender/build.py:run` from a queue consumer. Nothing in the builder needs to
change for that; the storage and state adapters sit outside it.
