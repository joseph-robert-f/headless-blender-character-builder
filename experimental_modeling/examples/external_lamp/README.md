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

The source has these original hashes:

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
