# Independent real-Blender verifier validation

This is a handwritten test fixture for policy/observation schema 2. It is not a
recorded external-author success and does not modify the original lamp example.

Run from the repository root with an existing, reviewed immutable Docker image:

```sh
python3 tests/experimental_modeling/run_verifier_validation.py \
  --store /absolute/path/new-verifier-evidence \
  --sandbox-image sha256:YOUR_LOCAL_IMAGE_ID \
  --docker /absolute/path/docker --docker-socket /run/docker.sock
```

`--output` is an alias for `--store`. The destination must be new or empty.
There is no native-source option, implicit fallback, baseline migration, or
artifact reuse. The ordinary controller isolates author, inspector, GLB
roundtrip and reopened-Blend stages. Additional independent probes each run in
a new restricted container through the trusted `inspect` sandbox role. Author
source cannot see the oracle, policy, earlier evidence, or test expectations.

## Hand-derived oracle

`source/builder.py` authors a closed tetrahedron. `oracle.py` independently
defines its named vertices O=(0,0,0), X=(.04,0,0), Y=(0,.03,0), Z=(0,0,.02), in
meters. The outward face boundaries are:

- Floor: O,Y,X. normal (0,0,-1). Cobalt
- South: O,X,Z. normal (0,-1,0). Ember
- West: O,Z,Y. normal (-1,0,0). Cobalt
- Slope: X,Y,Z. normal (3,4,6)/sqrt(61). Ember

Cobalt's RGBA is (.04,.20,.80,1). Ember's is (.85,.12,.04,1). Both have metallic
0 and roughness .5. Face and cyclic corner serialization changes in the positive
and repair cases, while indexed vertex identities remain fixed.

The sequence is baseline at z=0, accepted +30 mm, two attempted +30 mm edits
from that accepted parent, then repair at z=60 mm. The material defect exchanges
the floor and south assignments while keeping the identical palette and a
2/2 face histogram. The normal defect rotates only floor/O by .12 radians. Both rejections must keep the last-good pointer bytes unchanged.

All four pipeline stages must complete.
A runtime error does not establish a correct negative result. Repair must pass the same +30 mm policy.

`probe_artifact.py` reads each actual authored `.blend`, saved inspection
`.blend`, and exported GLB independently. It imports no production observer,
acceptance/comparison helper, canonicalizer, or author code. It emits raw face,
material and corner-normal values. The oracle attaches these values to the
hand-derived named faces, checks outward directed boundaries and closed edges,
and identifies the exact altered faces/corner. This catches observer-side
material-slot or custom-normal loss as well as acceptance defects.

GLB can split vertices.
Matching those measured corners to the known fixture coordinates
validates export fidelity and does not extend the v2 policy's indexed scope.

## Original lamp ordering regression

The runner verifies the recorded source hashes, copies source into its fresh
output, and removes only the later light-face ordering workaround. The resulting
geometry module must exactly match historical SHA-256
`4104a88f029ea1ced220f0aa1ba3633957e7ed7e9d6210e7bfd1a8ede857cfcb`.
The recorded example does not change.
A new version-2 lamp baseline and height revision must pass.
Independent artifact checks must show a 30 mm translation.
They must also show unchanged oriented polygons, material assignments, and corner normals.

The raw light polygon order must differ. Frozen v1 checks must
reject that light order on the same measured observations. If the ordering
difference is not reproduced, the gate fails rather than claiming coverage.

## Evidence and tolerance

The runner retains raw probes, bounded sandbox logs, immutable controller result
stores and `verifier-validation-summary.json`, including on failure. That summary
records source/probe/oracle hashes, runtime image identity, exact statuses,
independent named surface ledgers, pointer preservation and measured normal
errors. Original lamp file hashes are rechecked after success or failure.

The .001-radian threshold is an explicit provisional fixture policy, not a
production default or a calibrated universal value. An actual passing run
records the maximum measured positive error for the recorded runtime and marks
only that fixture calibration as measured. The runner never widens the threshold
to make a run pass. Until a real isolated run completes, compilation and synthetic
oracle checks provide no Blender execution or calibration evidence.
