<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Source-directed modeling experiment

**Unsupported, opt-in experiment. The stable geometric-character v1 JSON runner,
CLI, schemas and service are unchanged. Do not merge or deploy this experiment
without review.**

This lane lets a coding agent author a modular Blender Python source bundle plus
parameters/assets, rebuild it, and evaluate the resulting scene against a
separately reviewed acceptance policy. Python is the construction source; `.blend`
is derived evidence. There is no finite operation catalog and no new MCP, UI,
service endpoint, built-in model API or automatic natural-language planner.

The robot benchmark is a handwritten harness fixture. It proves source rebuilding,
scoped revision checking and artifact verification for that fixture. It does not
prove general text-to-3D capability, artistic quality, arbitrary topology repairs,
or manufacturing fitness. A coding agent must propose source and a human/trusted
controller must review its policy; generated code must never set its own success.

## Trust boundary and current execution mode

The default command refuses untrusted execution before reading or importing
source unless `--sandbox-image` names a verified local Docker image.
The separate [Docker backend](EXPERIMENTAL_MODELING_SANDBOX.md) has passed live
CI boundary probes and both complete modeling benchmarks. Its limitations and
exact tested commit are documented; this is not a security audit or a guarantee
against hostile production workloads. The current PR head must pass CI again.
`--trusted-reviewed-source` explicitly opts into native **trusted local
development**. Review all Python imports and assets first. This runs arbitrary
Python with the user's OS authority. A fresh subprocess, stripped environment,
resource limits and post-execution hashes are **not a sandbox**. They cannot
prevent hostile code from modifying the controller, verifier, policy, accepted
history or host. Post-execution hashes detect accidental edits, not an adversary
who can restore bytes. Do not pass newly generated/unreviewed code to this mode.

Untrusted execution needs an audited container/OS boundary with read-only source,
no controller/policy exposure, no network or host credentials, bounded resources,
separate isolated author and inspector jobs, and output-only mounts. When that
boundary is unavailable, fail closed; never automatically downgrade to native.
Blender is also a native file parser: `--disable-autoexec` does not make hostile
`.blend` files safe outside a sandbox.

## Contract

- Source directory contains `builder.py` and modular `.py` plus bounded local
  `.json`, `.png`, `.jpg`, `.jpeg`, `.txt`, `.md` assets. No symlinks or remote fetch
  contract. Maximum source bundle 16 MiB, 512 files
- Author entry receives `--params FILE --output SCENE.BLEND`. Every modeled part
  has one unique object custom property `semantic_id`; object names are not the
  authority. Instances must be realized. Semantic IDs map to independently
  evaluated geometry, not author-provided measurements
- Policy v1 has exact fields `schema_version`, `parts`, `changed_parts`,
  `constraints`, `profile`. Semantic IDs/revision IDs are bounded safe strings
- Scene profile is implemented. Print profile is reserved and fails closed;
  generic scenes may contain intersecting parts or disconnected components. Raw
  STL export inside the observer is not print acceptance
- Constraints measure actual evaluated world vertices: anchors, axis extents,
  distances, indexed ring-centroid path lengths, centroid positions, pure translations and manifold
  edge counts. Stable-index constraints are fixture-specific; general remeshing
  needs newly reviewed measurement definitions. They are not universal shape QA
- Every unchanged part must preserve geometry/topology/corner-normal hash,
  transform hash and material hash. A changed-part list only grants change scope;
  constraints still decide whether the requested edit was achieved

Adding a new semantic part requires declaring it in both `parts` and
`changed_parts`. Deleting semantic parts is not represented by this policy version
and fails closed; removal needs a future explicit, reviewed contract.

Units are controller-owned meters (numeric Blender unit = 1 m). Source unit scale
other than 1 is rejected. Scene geometry is included regardless of source camera,
light, hiding or render flags. Supported materials are constant Principled base
color/alpha, metallic and roughness; unsupported shader changes fail rather than
silently disappearing. The trusted observer creates canonical evaluated meshes,
materials and four fixed orthographic views (front/right/top/isometric).

## Pipeline and evidence

1. Validate policy and immutable revision/parent, lock store, verify all last-good
   manifest and artifact hashes
2. Snapshot source and parameters; hash source files, policy, controller scripts
   and Blender executable
3. Author a candidate in a separate process with blank factory startup
4. Fresh trusted observer loads without auto-execution; independently evaluates,
   fingerprints, renders and exports canonical `.blend` and GLB
5. Pure controller checks constraints and protects unchanged parts against the
   independently recorded parent observation
6. Separate fresh Blender jobs reopen canonical `.blend` and import GLB, checking
   every part's world triangle geometry, material, transform and corner normals
7. Recheck frozen provenance and prior accepted integrity. Only all-pass attempts
   fsync the bounded artifact tree, move into `accepted/REVISION`, fsync both
   rename parents, then atomically replace `last_good.json` last and fsync store

A process crash between accepted-directory rename and pointer replacement may
leave an unreferenced accepted revision; only `last_good.json` selects current.
No automatic orphan deletion occurs. An I/O/durability failure aborts publication;
inspect the pointer before retrying. Fsync ordering tests are not physical
power-loss tests.

GLB is allowed 1e-4 absolute numeric tolerance for coordinates/material/transform
and 0.01 radians for corner normals (Blender export/import quantization); measured
normal deviation is recorded. Same-runtime clean rebuild uses stricter normalized
hash equality. No cross-version determinism claim is made.

`attempts/REVISION` keeps rejected and `needs_review` runs separately from accepted
exports: bounded logs, source/params/policy, observations, failed comparisons and
structured `result.json`. Unsafe generated entries/over-budget files are removed
without following links and listed in the report. Each job has 120-second wall/CPU
limits, 8-GiB address-space limit, 256-MiB individual file limit, 128-KiB retained log
limit and 512-MiB aggregate attempt budget. Native enforcement is best-effort
trusted-development resource control, not host containment. Stores accumulate
history; no automatic deletion/retention schedule is implemented.

## Reproduce the robot benchmark

From the repository root, with reviewed fixture source and installed Blender:

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
RUN_TRUSTED_BLENDER_TESTS=1 python3 -m unittest discover \
  -s tests/experimental_modeling -p test_robot_blender.py -v
python3 tests/experimental_modeling/run_benchmark.py --help
```

The benchmark builds a six-legged robot with a curved asymmetric mast and rear
concave cargo tray, translates only the mast, lengthens front-leg centerlines 20%
without moving body/ground anchors, and widens the tray preserving mount anchors
and measured walls/floor. It submits a deliberately bad body shift during the
tray edit, requires rejection and an unchanged last-good pointer, then applies a
narrow repair and checks an independent clean rebuild. Source is the same modular
program across parameter revisions; it is not six separately handwritten meshes.

Single reviewed-source invocation:

```sh
python3 -m experimental_modeling build \
  --source experimental_modeling/examples/robot/source \
  --params experimental_modeling/examples/robot/initial.json \
  --policy experimental_modeling/examples/robot/initial.policy.json \
  --store /tmp/reviewed-model-store --revision r0 \
  --trusted-reviewed-source
```

Use `--intent "requested edit"` to record the text instruction with each revision.
The text is audit context; the external authoring agent creates the source.

A subsequent revision must name `--parent` equal to current last-good. Rejected
attempt IDs cannot be reused. Inspect `result.json`, independent observations,
rendered views and export checks before accepting a scene for any external use.
