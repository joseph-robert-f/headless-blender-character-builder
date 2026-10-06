<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Anime cat accessory revision fixture

This original, low-poly cat tests three recorded instructions through the existing
experimental modeling controller. It is a reviewed deterministic source fixture.
It is not a live text-to-3D model request. No provider, API key, or external asset
is required. The source reads the supplied parameters and writes the supplied
Blender scene. The controller owns inspection, exports, acceptance, and history.

## Recorded instructions

| Revision | Instruction | Permitted change |
| --- | --- | --- |
| `r0` | Create a cute, anime-styled 3D cat. | Initial cat |
| `r1` | Add a hat to the same cat. | Add `accessory` |
| `r2` | Remove the hat and add sunglasses to the same cat. | Replace `accessory` geometry |
| `bad-base` | Deliberately move the protected cat by 0.15 m. | Accessory only. Reject. |

These are test instructions, not evidence of automatic prompt interpretation.
The positive parameter states keep `cat_shift` at zero. The negative state uses
0.15 while its policy still permits only an accessory change.

## Protected cat and accessory replacement

The `cat` semantic mesh contains the body, face, ears, paws, and tail. It has
1,586 vertices and 1,680 faces. Its coordinates, topology, normals, materials,
and transform must remain identical across the three revisions.

The current contract rejects semantic-part removal. The `accessory` part is
absent in r0, holds the hat in r1, and holds new sunglasses geometry in r2.
The hat geometry is replaced, not hidden. All hat vertices are above Z 2.595.
All final accessory vertices are below Z 2.292. Exact part sets and protected
cat hashes prevent a leftover hat from moving into another semantic part.

The sunglasses include two lenses, two rims, two temples, two glints, and a bridge.
The independent verifier checks their geometry and material assignments.

The source uses schema-v2 policies to preserve per-face material colors.
The legacy schema-v1 observer does not preserve these assignments.
Fixed tessellation keeps observations within the existing JSON size bound.
Stable face ordering prevents construction-order changes between rebuilds.
No controller limit or acceptance implementation changes are needed.

## Run and inspect

Use the repository-pinned Blender 4.5.12 runtime and a fresh store.
Review the source before native execution.

```sh
python3 tests/experimental_modeling/run_anime_cat.py \
  --store /tmp/anime-cat-review \
  --trusted-reviewed-source \
  --blender /absolute/path/to/blender
```

Native execution is **NOT SANDBOXED**. A subprocess and disabled automatic scripts
do not isolate malicious Python or scene files. Untrusted source requires the
existing verified Docker boundary. There is no native fallback from Docker mode.

```sh
python3 tests/experimental_modeling/run_anime_cat.py \
  --store /tmp/anime-cat-review \
  --sandbox-image sha256:YOUR_VERIFIED_LOCAL_IMAGE_ID
```

The existing offline Linux workflow runs the Docker command. It does not dispatch
the guarded live proposal job. A local native pass does not establish a CI pass
or validate the Docker boundary. Use the current commit's workflow result.

The runner checks all three accepted revisions, four views per revision, saved
Blender reopening, GLB roundtrip, independent geometry checks, and a clean rebuild.
It also requires rejection of the invalid cat move and byte-identical last-good
history. The output summary records source, policy, runtime, controller, and
artifact provenance. Machine acceptance does not imply human visual acceptance.

## Limits

This is a decorative scene fixture. Its converted curves contain separate cap seams:
the cat and sunglasses each have 168 boundary edges. The independent verifier
checks this exact reviewed topology instead of claiming watertight meshes.
Some solids intersect, and some components are disconnected. The scene has no
rigging, animation, mechanical-strength, manufacturing, or print-readiness claim.

One passing fixture does not establish general text-to-3D or editing quality.
Numeric coordinates use the controller's meter convention, not a practical scale.

The reconciled fixture was executed on source tree
`8daa587d4ac6600e402a0fc8a41bfff4345a690d`, corresponding to main
`5025be4d444018eb7c5371048990e513e8a459c4`, with Blender 4.5.12.
Independent saved-scene checks confirmed the cat's exact hashes and colors.
The repository runner must pass again on each proposed revision.
