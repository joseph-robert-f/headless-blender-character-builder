# Six-legged robot revision fixture

This is a handwritten modeling program made from ordinary Python modules. It is
an experiment in artifact inspection and bounded revisions, **not evidence that
an autonomous system can translate arbitrary text into correct 3D models**. It
does not register a shape in the existing v1 recipe catalog or modify that path.

## Program and semantic parts

- `source/geometry.py`: reusable mesh constructors (box, tube, Bézier sampling, tray)
- `source/parts.py`: the robot's composition and independently adjustable dimensions
- `source/builder.py`: Blender author entrypoint; `--params JSON --output SCENE.BLEND`
- Nine semantic objects: body, curved asymmetric sensor mast, concave cargo tray,
  and six individually named legs

Each object has a unique `semantic_id` for identification. Measurements come
from saved mesh geometry, never numeric claims in object custom properties.
The composition has a display-oriented scene profile. The overlapping mounting
tabs are part of the tray object but are not Boolean-unioned with its shell;
closed edge incidence alone does not establish print readiness or the absence
of intersections. No print-ready claim is made.

## Benchmark sequence

| Parameters | Intended change against accepted predecessor |
| --- | --- |
| `initial.json` | Create robot |
| `revision_1_mast.json` | Translate only mast by `(0.25, -0.10, 0)` |
| `revision_2_front_legs.json` | Increase each front-leg centerline by 20%, preserving both endpoints |
| `revision_3_tray.json` | Widen tray from 1.4 to 1.9, preserve mounts and 0.1 wall/floor thickness |
| `bad_edit.json` | Same tray edit plus forbidden body translation of 0.08 |
| `repair.json` | Remove only the unintended body translation |

The deliberate bad edit and repair are both evaluated against accepted revision
2 with the tray-only change scope. A rejected candidate must not become an
accepted parent. Equivalently, compare the bad candidate's mesh against repair:
only the body changes. Repair's geometry is identical to revision 3.

The `.policy.json` files are predeclared benchmark acceptance inputs for the
controller. They must be reviewed and held separately from author permissions in
a real untrusted workflow. Their presence in this example bundle is convenient
fixture packaging, not authority for authored source to choose its own policy.

## Independent measurements

- Every leg has three 12-vertex rings, in consecutive index groups `0..11`,
  `12..23`, and `24..35`. The centers are computed from actual world vertices.
  Summing the two center-to-center distances measures this fixture's centerline.
- Leg vertices 36 and 37 are face-connected endpoint cap centers, not unattached
  metadata markers. Trusted anchor coordinates are fixed by the benchmark.
- Tray shell indices `0..3` form the outer bottom, `4..7` the outer top,
  `8..11` the inner top, and `12..15` the inner floor. Each top-rim outer/inner
  midpoint pair measures one wall thickness. Bottom/floor centroid distance
  measures floor thickness.
- Two fixed mounting tabs occupy vertices `16..23` and `24..31`. Their anchor
  corners remain `(-0.56,-1.16,1.35)` and `(0.44,-1.16,1.35)`.
- Policies constrain tray X extent and all six leg lengths and endpoint pairs;
  unchanged semantic-object mesh hashes constrain the unrelated geometry.

The index groups intentionally bind this benchmark to a stable authored
mesh topology. They are not a generic way to establish arbitrary-part thickness,
recover a skeleton, resist malicious geometry chosen to fool measurements, or
prove every possible downstream manufacturing requirement.

## Native development tests

From the repository root:

```
python -m unittest discover -s tests/experimental_modeling -p test_robot_blender.py -v
RUN_TRUSTED_BLENDER_TESTS=1 python -m unittest discover -s tests/experimental_modeling -p test_robot_blender.py -v
```

The first command tests pure geometry and skips native execution. The second
explicitly opts into author execution with the installed Blender, writes all
six scenes into a temporary directory, opens them in fresh Blender processes,
and verifies their saved geometry. This is trusted local development execution,
**not a sandbox or security validation**.

The full controller integration benchmark (with retained evidence outside the
source tree) can be run in reviewed native mode using:

```
python tests/experimental_modeling/run_benchmark.py --store /tmp/robot-benchmark --trusted-reviewed-source
```

Use a fresh empty output directory. It records initial/revised artifacts, a
rejected body edit, a narrowly repaired candidate, four initial/final view PNGs,
export/reopen diagnostics, and a separate clean rebuild. The summary is written
to `benchmark-summary.json` in the chosen directory. The benchmark asserts that
a rejected candidate never advances the last-good pointer.
