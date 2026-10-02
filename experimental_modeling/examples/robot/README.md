# Six-legged robot revision fixture

This handwritten model program uses Python modules.
It is an artifact inspection and revision experiment with limits.
It does **not show that an autonomous system can convert arbitrary text into correct 3D models**.
It does not add a shape to the v1 recipe catalog or change that implementation.

## Program and semantic parts

- `source/geometry.py`: reusable mesh constructors (box, tube, Bézier sampling, tray)
- `source/parts.py`: the robot's composition and independently adjustable dimensions
- `source/builder.py`: Blender author entrypoint. `--params JSON --output SCENE.BLEND`
- Nine semantic objects: body, curved asymmetric sensor mast, concave cargo tray,
  and six individually named legs

Each object has a unique `semantic_id`.
Measurements use saved mesh geometry, not numeric values in object custom properties.
The composition uses a scene profile for display.

Overlapping mounting tabs are part of the tray object.
They do not have a Boolean union with its shell.
Closed edge incidence alone does not show print readiness or exclude intersections.
This fixture does not give a print-ready result.

## Benchmark sequence

| Parameters | Intended change against accepted predecessor |
| --- | --- |
| `initial.json` | Create robot |
| `revision_1_mast.json` | Translate only mast by `(0.25, -0.10, 0)` |
| `revision_2_front_legs.json` | Increase each front-leg centerline by 20%. Keep the two endpoints fixed |
| `revision_3_tray.json` | Widen tray from 1.4 to 1.9, preserve mounts and 0.1 wall/floor thickness |
| `bad_edit.json` | Same tray edit plus body translation that is not permitted of 0.08 |
| `repair.json` | Remove only the unintended body translation |

The benchmark compares the intentional bad edit and repair with accepted revision 2.
Only the tray is in the permitted change scope.
A rejected candidate must not become an accepted parent.
Only the body differs between the bad candidate mesh and the repair.
The repair geometry is the same as revision 3.

The `.policy.json` files are predetermined benchmark acceptance inputs for the controller.
For an untrusted workflow, review these files independently.
Do not give source authors permission to change them.
The example bundle contains them for the fixture.
Their location does not give authored source permission to select its acceptance policy.

## Independent measurements

- Each leg has three 12-vertex rings, in consecutive index groups `0..11`,
  `12..23`, and `24..35`. The centers are computed from actual world vertices.
  Summing the two center-to-center distances measures this fixture's centerline.
- Leg vertices 36 and 37 are face-connected endpoint cap centers, not unattached
  metadata markers. Trusted anchor coordinates are fixed by the benchmark.
- Tray shell indices `0..3` form the outer bottom, `4..7` the outer top,
  `8..11` the inner top, and `12..15` the inner floor. Each top-rim outer/inner
  midpoint pair measures one wall thickness. Bottom/floor centroid distance
  measures floor thickness.
- Two fixed mounting tabs occupy vertices `16..23` and `24..31`. Their anchor
  corners stay `(-0.56,-1.16,1.35)` and `(0.44,-1.16,1.35)`.
- Policies constrain tray X extent and all six leg lengths and endpoint pairs.
  Unchanged semantic-object mesh hashes constrain the unrelated geometry.

The index groups connect this benchmark to a fixed authored mesh topology.
They do not give general part thickness or a skeleton.
They cannot prevent all incorrect measurements from malicious geometry.
They do not show that all manufacturing requirements are satisfied.

## Native development tests

From the repository root:

```
python -m unittest discover -s tests/experimental_modeling -p test_robot_blender.py -v
RUN_TRUSTED_BLENDER_TESTS=1 python -m unittest discover -s tests/experimental_modeling -p test_robot_blender.py -v
```

The first command does pure geometry tests without native execution.
The second enables author execution with the installed Blender.
It writes six scenes into a temporary directory.
It opens them in new Blender processes and verifies their saved geometry.
This is trusted local development execution, **not a sandbox or security validation**.

For the full controller integration benchmark, use reviewed native mode:
The command keeps evidence in a directory external to the source tree.

```
python tests/experimental_modeling/run_benchmark.py --store /tmp/robot-benchmark --trusted-reviewed-source
```

Use a new empty output directory.
The benchmark records initial and revised artifacts, a rejected body edit,
and a repair candidate with only the permitted change.
It also records four initial/last view PNGs, export/reopen diagnostics, and an independent clean rebuild.
It writes `benchmark-summary.json` in the selected directory.
The benchmark confirms that a rejected candidate cannot change the last-good pointer.
