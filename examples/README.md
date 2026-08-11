# Examples and ideas

The bundled requests show two different outcomes on purpose. A request can be
schema-valid JSON and still fail the geometry publication gate. That distinction is a
feature: the builder publishes a success manifest only after the generated
Blender scene, GLB, and STL pass the complete checks.

## Bundled requests

| Request | What it demonstrates | Expected result |
|---|---|---|
| [`facet-bot.json`](requests/facet-bot.json) | The canonical geometric mascot and release fixture | **Passes** the complete build and fresh-process verification gates |
| [`moss-hopper.json`](requests/moss-hopper.json) | A materially different chibi character and the fail-closed review path | **`needs_review`**; exit `11`, no output directory, and no success manifest |

Build and independently reopen the passing example without overwriting the
quickstart's `build/facet-bot` output:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot.json"
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-example
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-example
```

The expected final markers are `BUILDER_VALIDATE: PASS`,
`BUILDER_BUILD: PASS`, and `BUILDER_VERIFY: PASS`. The result is in
`build/facet-bot-example/`.

To exercise the safe review outcome:

```sh
make validate REQUEST="$PWD/examples/requests/moss-hopper.json"
make build REQUEST="$PWD/examples/requests/moss-hopper.json" OUTPUT_NAME=moss-hopper
```

Validation passes, but the build exits `11`. `build/moss-hopper/` must not
exist afterward. The generator found unresolved short-wall candidates, so it
refuses to claim the STL passed.

## Make a character your own

Copy `facet-bot.json`, give the copy an original name and slug, then change one
small group of controls at a time. The supported palette, style, pose,
proportion, eye, material, component, and base values are listed in the
[character guide](../docs/character-spec.md). Validate first, then choose a new
`OUTPUT_NAME` for every experiment.

These are useful themes, not pre-verified geometry fixtures:

- **Colorway Parade** — a family of original mascots with shared geometry and
  different palettes or material finishes.
- **Dungeon Department** — original tabletop-token prototypes with bases,
  badges, horns, ears, or backpacks. Treat every STL as a prototype, not a
  print guarantee.
- **GLB Petting Zoo** — small web-viewable characters for layout and game-engine
  placeholders.
- **QA Gremlin** — deliberately difficult requests used to teach the
  difference between valid input and publishable geometry.
- **Classroom Geometry Lab** — inspect units, manifold meshes, connected shells,
  hashes, and provenance in a concrete Blender project.
- **Desk-Sized Diplomats** — original team or project mascots intended for
  review in Blender before optional slicing and test printing.

Do not describe a new request as passing until it completes both `make build`
and `make verify`. JSON validation alone does not evaluate wall thickness,
feature size, mesh connectivity, STL orientation, or physical manufacturability.

## Rights and safety

Use original or rights-cleared character designs. Do not upload third-party
models or imply that a procedural resemblance grants permission to use a
protected character. Geometry QA is evidence about the files, not legal
clearance, slicer validation, printer calibration, material advice, or a safety
certification. See the [output policy](../OUTPUT_POLICY.md).
