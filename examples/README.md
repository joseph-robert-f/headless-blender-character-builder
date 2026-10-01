# Examples and ideas

The supplied requests show visual changes and two QA results.
A request can pass schema validation and fail geometry publication checks.
The builder publishes a success manifest only after the Blender scene, GLB, and STL pass all defined checks.

## Bundled requests

| Request | Purpose | Expected result |
|---|---|---|
| [`facet-bot.json`](requests/facet-bot.json) | The geometric mascot and release fixture | **Passes** the full build and new-process verification checks |
| [`facet-bot-tidepool.json`](requests/facet-bot-tidepool.json) | The reviewed Facet Bot geometry with a teal-and-ice palette | **Passes** the full build and new-process verification checks |
| [`moss-hopper.json`](requests/moss-hopper.json) | A different chibi character and the QA review result | **`needs_review`**. Builder code `11`, no output directory, and no success manifest |

Use these commands for the passing example.
The different output name prevents changes to the quickstart result in `build/facet-bot`:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot.json"
make build REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-example
make verify REQUEST="$PWD/examples/requests/facet-bot.json" OUTPUT_NAME=facet-bot-example
```

The expected result markers are `BUILDER_VALIDATE: PASS`, `BUILDER_BUILD: PASS`, and `BUILDER_VERIFY: PASS`.
The result is in `build/facet-bot-example/`.

For the tested color change without geometry changes, use the Tidepool palette in a different output directory:

```sh
make validate REQUEST="$PWD/examples/requests/facet-bot-tidepool.json"
make build REQUEST="$PWD/examples/requests/facet-bot-tidepool.json" OUTPUT_NAME=facet-bot-tidepool
make verify REQUEST="$PWD/examples/requests/facet-bot-tidepool.json" OUTPUT_NAME=facet-bot-tidepool
```

Facet Bot uses its first palette color for the body, base, and limbs.
It uses its second color for the head, hands, feet, badge, and antenna tips.
Tidepool changes orange and cream to teal and ice.
All geometry-related fields and the material preset stay the same.
Only the palette and request identity (name and slug) change.
Use this example to learn which visible parts each color controls.

To see the QA review result, enter these commands:

```sh
make validate REQUEST="$PWD/examples/requests/moss-hopper.json"
make build REQUEST="$PWD/examples/requests/moss-hopper.json" OUTPUT_NAME=moss-hopper
```

Validation passes, but the builder reports `BUILDER: FAIL[11]`.
GNU Make shows `Error 11`.
The `make` process usually exits `2`.
`build/moss-hopper/` must not exist after the operation.
The generator found unresolved short-wall candidates.
Thus, it does not claim an STL pass.

## Make a character your own

Copy `facet-bot.json`.
Give the copy an original name and slug.
Change one small group of controls at a time.
Read the [character guide](../docs/character-spec.md) for palette, style, pose, proportion, eye, material, component, and base values.
Validate the request first.
Then select a new `OUTPUT_NAME` for each experiment.

These ideas are not geometry fixtures with completed verification:

- **Colorway Parade:** Original mascots with shared geometry and different palettes or material finishes
- **Dungeon Department:** Original tabletop-token prototypes with bases, badges, horns, ears, or backpacks
- **GLB Petting Zoo:** Small characters for web display, layout, and game-engine placeholders
- **QA Gremlin:** Difficult requests that show the difference between valid input and geometry that passes publication checks
- **Classroom Geometry Lab:** Units, manifold meshes, connected shells, hashes, and provenance in a Blender project
- **Desk-Sized Diplomats:** Original team or project mascots for Blender review before optional slicing and test printing.

Treat each STL as a prototype.
It does not guarantee print success.
Do not call a new request passing before `make build` and `make verify` complete.
JSON validation does not evaluate wall thickness, feature size, mesh connectivity, STL orientation, or physical manufacturability.

## Rights and safety

Use original character designs or designs with permission from the rights holder.
Do not upload third-party models.
Do not imply that procedural resemblance gives permission to use a protected character.
Geometry QA gives file evidence only.
It does not give legal clearance, slicer validation, printer calibration, material advice, or safety certification.
Read the [output policy](../OUTPUT_POLICY.md).
