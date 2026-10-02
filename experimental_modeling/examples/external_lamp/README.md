<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# External author lamp example

An external assistant wrote this new source from the exported desk-lamp request on 2026-10-01.
It did not copy the robot, desk-creature, or watering-can source.
The application did not call a model or start that assistant.
An operator selected the policy and requirements separately from the source.

The preserved `handoff/request.json` contains the full initial brief.
Its identity is `55a3819fc372c6a56345739bb7f706485f6a87c5ff98f1ec0f1e1948e52441a7`.
The adjacent `AUTHORING.md` is the exact hash-bound author contract.
Do not edit that historical handoff in place.

The first author version had these source hashes:

- `proposal/source/builder.py`: `8d31b470a31f6a18e90fbcdefe3ecb49c08f1cfc111fffc5d02f1f87a1932cc6`
- `proposal/source/geometry.py`: `4104a88f029ea1ced220f0aa1ba3633957e7ed7e9d6210e7bfd1a8ede857cfcb`

This is a visual scene model.
It is not a working electrical product or a print-ready design.
The policy checks part identity, manifold edges, base dimensions, and selected shade measurements.
The requirements protect the complete base in subsequent revisions.
Appearance remains a human review task.
These checks do not prove electrical safety, structural strength, or manufacturing suitability.

## Replay through the isolated bridge

Use a reviewed local Docker image and explicit runtime paths:

```sh
python3 tests/experimental_modeling/run_external_lamp.py \
  --output /absolute/path/new-lamp-evidence \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID \
  --docker /absolute/path/docker \
  --docker-socket /run/docker.sock
```

This script replays the recorded external source through the normal request bridge.
It does not generate new source or call a provider.
It has no native execution option.
Read its saved summary, measurements, and four inspector renders.
A script in the repository is not evidence that the execution passed.
Use the result from the exact tested commit.

The separate handwritten bridge fixture tests repeatable rejection, repair, and request-state behavior.
Do not describe that fixture as the original source-authoring event.
This lamp example records one external authoring event, not a general text-to-model capability result.

## Recorded refinements

An external assistant prepared the following proposals from operator requests:

1. Increase the lamp height from 260 mm to 290 mm.
   Preserve the complete base and move the unchanged shade and light upward by 30 mm.
2. Change the stem radius from 5 mm to 4 mm in the source.
   The deliberate negative proposal also increases the base width to 170 mm.
3. Repair the rejected proposal with the original 160 mm base width.
   Keep the narrower stem and the 290 mm height.

The `revisions/` directories preserve the exact proposal files, prompts, and selected policies.
The height proposal uses the same source as the current initial model.
The narrower-stem source changes only its radius declaration relative to the corrected initial source.
Its current `geometry.py` hash is `001f2d0690b374745e61001da90b27afd7589e4c62b88c1d526d2b6f65fceadb`.
The negative and repair proposals use those same source bytes.

`revisions/height/recorded-request.json` preserves the historical request metadata.
It refers to the first accepted CI result and its context hashes.
The generated observation file is not committed to this source repository.
Thus, that metadata record is not a complete handoff for execution.

Each CI replay first makes a new initial result.
Its result hash can differ because the runtime and job records are new.
The script then saves the exact recorded prompt against that actual result and prepares a fresh handoff.
It does the same for the narrower-stem request and the repair.
It never changes a parent hash silently or executes the historical request against a different parent.

The replay must reject the 170 mm base and keep the last-good pointer unchanged.
It must then accept the repair against the same accepted baseline.
It compares complete base fingerprints and records the measured height and stem width.
All stages use the normal request bridge and isolated controller.
The separate lamp artifact contains the complete result history and inspector renders.
Read the exact-commit CI results before reporting that this sequence passed.


## Author correction after verification

The first four-stage replay stopped at the height refinement.
The light had the correct displacement, material, vertices, and oriented-face multiset.
But its face sequence differed at 416 of 512 positions.
The strict translation check rejected that sequence change and kept the initial last-good model.
Read the [failed CI record](https://github.com/joseph-robert-f/headless-blender-character-builder/actions/runs/36939197597).

The external source author then corrected the light construction.
The correction preserves the vertex list and oriented polygons.
It rotates each face list to its smallest first vertex, then sorts the face lists.
It rebuilds the light mesh with those ordered faces and the same material.
No coordinate, policy, requirement, tolerance, or verifier change is part of this correction.

The current initial and height `geometry.py` hash is `be64750eba590d2235fc90d26c811cc6232606999c4a53de3e0c27d99b43f1b6`.
The builder module remains unchanged.
The replay uses the corrected source consistently for a new initial model and its refinements.
The original source and failed sequence remain in commit `0c18620807f227540579c66cd1867d1b2faf9bc7` and its CI evidence.
The historical height request remains a record of its original baseline, not permission to change that baseline silently.
