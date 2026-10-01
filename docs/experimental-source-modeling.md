<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Source-directed modeling experiment

**This optional experiment has no product support.**
The stable geometric-character v1 JSON runner, CLI, schemas, and service do not change.
Do not merge or deploy the experiment before review.

A coding agent can write a modular Blender Python source bundle with parameters and assets.
The controller can rebuild the source and evaluate the scene against an independently reviewed acceptance policy.
Python is the construction source.
The `.blend` file is derived evidence.
The source-build command has no fixed operation catalog, new MCP, service endpoint, built-in model API, or automatic natural-language planner.
Read [Local model review](local-model-review.md) for the review UI that operates independently.

The robot benchmark is a handwritten test fixture.
It demonstrates source rebuilding, revision checks with a fixed scope, and artifact verification for that fixture.
It does not show general text-to-3D capability, artistic quality, arbitrary topology repairs, or manufacturing fitness.
A coding agent proposes source.
A person or trusted controller must examine the policy.
Generated code must not set its own success result.

## Trust boundary and current execution mode

The default command rejects untrusted execution before source access unless `--sandbox-image` identifies a verified local Docker image.
The [Docker backend](EXPERIMENTAL_MODELING_SANDBOX.md) passed live CI boundary tests and the two full modeling benchmarks.
Its guide records the tested commit and limits.
These tests are not a security audit or an assurance against hostile production workloads.
The current PR head must pass CI again.

`--trusted-reviewed-source` selects native **trusted local development**.
Before use, examine all Python imports and assets.
This mode executes arbitrary Python with the authority of your OS account.
A new subprocess, restricted environment, resource limits, and post-execution hashes are **not a sandbox**.
They cannot prevent hostile code from changes to the controller, verifier, policy, accepted history, or host.
Post-execution hashes can find accidental changes, but cannot identify an attacker who restores the bytes.

**CAUTION:** Do not use newly generated or unreviewed code in native mode.
Such code can change host files and acceptance evidence.

Untrusted execution must use an audited container or OS boundary with these controls:

- Read-only source
- No controller or policy access
- No network or host credentials
- Fixed resource limits
- Isolated author and inspector jobs
- Output-only mounts.

If that boundary is not available, stop.
Do not automatically change to native execution.
Blender is also a native file parser.
`--disable-autoexec` does not make hostile `.blend` files safe without a sandbox.

## Contract

The source directory contains `builder.py`, modular `.py` files, and local assets with fixed limits.
Permitted asset extensions are `.json`, `.png`, `.jpg`, `.jpeg`, `.txt`, and `.md`.
The source contract excludes symlinks and remote downloads.
The source bundle limit is 16 MiB and 512 files.

The author entry receives `--params FILE --output SCENE.BLEND`.
Each modeled part has one unique object custom property, `semantic_id`.
Object names do not show part identity.
The source must realize instances.
Semantic IDs identify independently evaluated geometry, not measurements from the author.

Policy v1 has the exact fields `schema_version`, `parts`, `changed_parts`, `constraints`, and `profile`.
Semantic IDs and revision IDs are strings with fixed character and size limits.
The scene profile is implemented.
The print profile is reserved and rejects requests.
A scene can contain intersecting parts or disconnected components.
Raw STL export by the observer does not show print acceptance.

Constraints measure evaluated world vertices.
Measurements include anchors, axis extents, distances, indexed ring-centroid path lengths, centroid positions, pure translations, and manifold edge counts.
Stable-index constraints apply to the fixture.
General remeshing must use new measurement definitions after review.
These constraints do not give universal shape QA.

For each unchanged part, `geometry_hash`, `transform_hash`, and `material_hash` must stay the same.
The geometry hash includes topology and corner-normal data.
A changed-part list gives permission to change only the listed parts.
The constraints decide if the model includes the requested change.

To add a semantic part, declare it in `parts` and `changed_parts`.
This policy version cannot represent semantic-part removal and rejects it.
Removal is not permitted without a future explicit contract and its own review.

The controller uses meters (numeric Blender unit = 1 m).
It rejects a source unit scale other than 1.
It includes scene geometry regardless of source camera, light, visibility, or render flags.
Permitted materials use constant Principled base color, alpha, metallic, and roughness values.
The observer rejects shader changes that it cannot represent.
It does not silently discard them.

The trusted observer makes canonical evaluated meshes and materials.
It makes four fixed orthographic views: front, right, top, and isometric.

## Pipeline and evidence

The controller uses this sequence:

1. Validate the policy and immutable revision and parent IDs.
2. Lock the store.
3. Verify all last-good manifest and artifact hashes.
4. Make a source and parameter snapshot.
5. Calculate hashes for source files, policy, controller scripts, and the Blender executable.
6. Make a candidate in a new process with empty factory startup settings.
7. Load the candidate in a new trusted observer without auto-execution.
8. Independently evaluate, fingerprint, render, and export canonical `.blend` and GLB files.
9. Examine constraints in the controller.
10. Compare unchanged parts with the parent observation that the trusted observer recorded independently.
11. Open the canonical `.blend` in a new Blender job.
12. Import GLB in a different new Blender job.
13. Examine each part's world triangle geometry, material, transform, and corner normals.
14. Verify the fixed provenance and previous accepted-state integrity again.

Only an attempt that passes all checks can publish its artifacts.
The controller calls `fsync` on the artifact tree with its size limits.
It moves the tree into `accepted/REVISION` and calls `fsync` on the source and destination parent directories.
It then atomically replaces `last_good.json` and calls `fsync` on the store.
The pointer replacement is last.

A process crash between the directory rename and pointer replacement can leave an unreferenced accepted revision.
Only `last_good.json` selects the current revision.
The controller does not automatically delete orphan revisions.
An I/O or durability failure stops publication.
Before a retry, examine the pointer.
Tests of `fsync` order are not physical power-loss tests.

GLB comparison permits an absolute numeric tolerance of 1e-4 for coordinates, materials, and transforms.
It permits 0.01 radians for corner normals because Blender export and import use quantization.
The report records the measured normal deviation.
A clean rebuild with the same runtime uses stricter normalized hash equality.
The experiment does not claim determinism across versions.

`attempts/REVISION` keeps rejected and `needs_review` results apart from accepted exports.
It keeps logs, source, parameters, policy, observations, failed comparisons, and `result.json` with fixed limits.
The controller removes unsafe entries and files above the limits without link traversal.
The report lists those removals.

Each job has these limits:

- 120-second wall time and CPU time
- 8-GiB address space
- 256-MiB individual file size
- 128-KiB saved log size
- 512-MiB total attempt size.

Native enforcement gives best-effort resource controls for trusted development.
It does not isolate the host.
Stores keep history without automatic deletion or a retention schedule.

## Reproduce the robot benchmark

Use the repository root with reviewed fixture source and an installed Blender executable.
Enter these commands:

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
RUN_TRUSTED_BLENDER_TESTS=1 python3 -m unittest discover \
  -s tests/experimental_modeling -p test_robot_blender.py -v
python3 tests/experimental_modeling/run_benchmark.py --help
```

The benchmark makes a six-legged robot with a curved asymmetric mast and a rear concave cargo tray.
It translates only the mast.
It increases front-leg centerline length by 20% without changes to body or ground anchors.
It widens the tray without changes to mount anchors and measured walls and floor.

During the tray change, the benchmark submits an incorrect body shift.
The controller must reject that candidate and keep the last-good pointer unchanged.
The benchmark then applies a repair with a small scope and tests a clean rebuild independently.
All parameter revisions use the same modular source program.
They are not six independently handwritten meshes.

For one invocation with reviewed source, enter this command:

```sh
python3 -m experimental_modeling build \
  --source experimental_modeling/examples/robot/source \
  --params experimental_modeling/examples/robot/initial.json \
  --policy experimental_modeling/examples/robot/initial.policy.json \
  --store /tmp/reviewed-model-store --revision r0 \
  --trusted-reviewed-source
```

Use `--intent "requested edit"` to record the text instruction with each revision.
The text gives audit context.
The external authoring agent makes the source.

For a subsequent revision, set `--parent` to the current last-good revision.
Do not reuse a rejected attempt ID.
Before external use, examine `result.json`, independently recorded observations, rendered views, and export checks.
