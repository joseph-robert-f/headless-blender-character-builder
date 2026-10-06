<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Anime cat accessory revision fixture

An original, deterministic chibi cat for a **local, reviewed-source test** of
three user instructions. This is a handwritten fixture, not a live text-to-3D
generation result. It uses only local polygon meshes constructed by the three
reviewable Python files in `source/`; there are no external assets or model
services. Source code is the construction input, and `.blend`/GLB files and
renders are derived test evidence. The scene uses the experiment's meter unit.

## Exact instruction sequence

| Revision | Instruction | Parameters | Permitted semantic change |
| --- | --- | --- | --- |
| `r0` | “Create a cute, anime-styled 3D cat.” | `params/r0.json` | Initial cat |
| `r1` | “Add a hat to the same cat.” | `params/r1.json` | Add `accessory` hat |
| `r2` | “Remove the hat and add sunglasses to the same cat.” | `params/r2.json` | Change `accessory` to glasses |
| `bad` | Deliberately move the cat's body 0.08 m while retaining the sunglasses. | `params/bad.json` | **No body change permitted; reject** |

The controller's policy contract rejects *removing a semantic part* from a
revision. The hat and sunglasses therefore occupy one persistent `accessory`
semantic part. `r0` has no accessory object. `r1` adds the part with brim and
crown geometry entirely above 2.40 m. `r2` replaces **all** of that geometry
with five disconnected mesh components: two filled oval lenses, one bridge,
and two temples, entirely below 2.15 m and in front of the face. No hat mesh
component remains. This is a geometric replacement, not an invisible hat.

The cat's 19 base semantic parts are identical across `r0`, `r1`, and `r2`:
`body`, `belly`, `head`, `ears`, `inner_ears`, `paws`, `tail`, `tail_tip`, `eyes`,
`irises`, `pupils`, `highlights`, `muzzle`, `nose`, `mouth`, `whiskers`, `cheeks`,
`collar`, and `bell`. The body, face, and pose have no dependence on the
accessory parameter. Controller-owned `policies/` records this edit scope.
The `body_shift_x` parameter is 0 for all positive revisions and 0.08 only in
the deliberate bad candidate; its policy still permits only `accessory`.

## Provenance and controls

This fixture was authored for repository main
`5025be4d444018eb7c5371048990e513e8a459c4`, after reviewing
`docs/experimental-source-modeling.md`, the desk-creature and robot source
fixtures, the acceptance policy contract, and the saved-scene observer. There
were no `AGENTS.md` or `.agents/skills` files on that commit. The source reads
only the passed parameter JSON and writes only the passed output `.blend`.

Run with the repository-pinned Blender runtime and an empty store. The
repository's `tests/experimental_modeling/run_anime_cat.py` runner, where
present, is responsible for full controller promotion, saved-artifact
inspection, independent geometric assertions, a rejected bad edit,
last-good checks, and rendered comparisons. The fixture source alone does not
declare success; report actual results separately after executing that runner.
Native `--trusted-reviewed-source` executes this reviewed code with host
authority and is not a sandbox. For untrusted source, use the repository's
verified isolation boundary instead.

Policy v1 checks manifold edge incidence and accessory width/height ranges.
Independent saved-geometry checks must additionally establish base hashes,
hat-only geometry in `r1`, sunglasses-only geometry in `r2`, and rejected
last-good behavior for `bad`. Visual review should check that the cat reads
as a cute anime cat and that the requested edits are apparent in the renders.
These checks do not certify print readiness or general text-to-3D capability.
