<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# External model request bridge

This experimental feature connects a text request, external source author, and verified model result.
It does not call an AI provider or start a coding agent.
It does not execute saved requests automatically.
It does not change the stable v1 builder.

The commands require a source checkout, Python 3.11+, and Linux x64.
Execution requires the existing [isolated Docker runtime](EXPERIMENTAL_MODELING_SANDBOX.md).
Windows and Mac source execution are not available.
The packaged review previews remain read-only.

## Prepare an initial brief

First, create a [portable project](local-project-launcher.md).
Save the complete initial brief as a UTF-8 text file.
The limit is 8,000 characters and 32,000 UTF-8 bytes.
The program preserves spaces, Unicode characters, and line breaks.

Use a new handoff directory outside the project:

```sh
python3 -m experimental_modeling.requests prepare \
  --project /absolute/path/project \
  --brief-file /absolute/path/brief.txt \
  --output /absolute/path/handoff-r0
```

An initial brief requires a project without an accepted model.
The handoff contains the request and the source author contract.
It is a durable file handoff, not a queued background job.
Preparation does not make a model or change project source.

The program creates the directory without replacement of an existing directory.
It publishes `request.json` last.
An interrupted handoff without that file cannot be consumed.
Keep partial files for examination, and select a new output directory.

## Prepare a saved edit

In the review program, select a revision.
Use **Save change request** to record the desired change.
Then use its saved request ID:

```sh
python3 -m experimental_modeling.requests prepare \
  --project /absolute/path/project \
  --request-id REQUEST_ID \
  --output /absolute/path/handoff-edit
```

An edit must reference the current accepted model.
A repair can reference a rejected direct child of that model.
The rejected reference and accepted execution parent remain separate identities.
The program rejects an older reference instead of an automatic rebase.

The handoff includes fixed source, parameters, rules, and observations from the selected reference.
It excludes repository metadata, agent configuration, and execution logs.
The program does not scan source for secrets.
Examine the selected content before transmission to an external author or provider.

## Get an external source proposal

Give the handoff to your chosen coding agent or source author.
Use that tool's normal authentication and permission controls.
This program does not manage those controls or provider charges.
A separate directory does not make an external coding agent a sandbox.

The author must return a different proposal directory with these entries:

- `source/`, with `builder.py` and permitted local modules or assets
- `params.json`, with one JSON object

The proposal must not overlap the handoff or project directory.
Do not add setup commands, agent configuration, or claimed success evidence.
The source limit is 16 MiB and 512 files.
The directory limit is 128.

Relative paths have a maximum of 16 components and 1,024 UTF-8 bytes.
Each component has a maximum of 240 UTF-8 bytes.
Links and redirected paths are not permitted.

The [source contract](experimental-source-modeling.md) defines the Blender interface and permitted file types.
The author can propose a policy separately.
A person or trusted operator must examine that policy independently.
Generated source cannot approve its own policy or result.

## Inspect the proposal and selected runtime

Select a reviewed policy, trusted Docker executable, local Unix socket, and existing immutable image.
Use the same selections for inspection and execution:

```sh
python3 -m experimental_modeling.requests inspect \
  --project /absolute/path/project \
  --handoff /absolute/path/handoff-r0 \
  --proposal /absolute/path/proposal-r0 \
  --policy /absolute/path/reviewed-policy.json \
  --docker /absolute/path/docker \
  --docker-socket /run/docker.sock \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID
```

Inspection does not start a program or contact the Docker daemon.
It shows parameter and policy changes, declared change scope, selected checks, and exact input locations.
Large values have a hash and size summary.
Read the full selected files where the summary omits content.
The parameter and policy hashes describe the controller's normalized JSON snapshots.
Source hashes describe exact file bytes.

The `inspection_digest` binds the complete request, proposal, reviewed rules, and selected runtime identity.
The runtime identity includes the image, Docker executable bytes and path, and local socket identity.
A runtime change requires another inspection.

Use `--requirements PATH` to select initial reviewed requirements.
Existing locked requirements must stay unchanged.
A failed first build can establish those initial rules.
If that changes the prepared rule identity, prepare another initial handoff before retry.

These checks do not prove full agreement with a natural-language brief.
Appearance and uncovered requirements need human review.

## Execute one inspected proposal

Copy the `inspection_digest` from the inspection result:

```sh
python3 -m experimental_modeling.requests run \
  --project /absolute/path/project \
  --handoff /absolute/path/handoff-r0 \
  --proposal /absolute/path/proposal-r0 \
  --policy /absolute/path/reviewed-policy.json \
  --docker /absolute/path/docker \
  --docker-socket /run/docker.sock \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID \
  --expected-digest INSPECTION_DIGEST \
  --revision r0
```

The command gives permission for this exact proposal and runtime.
It does not give permission for other proposals or automatic retries.
Repeat `--requirements PATH` if inspection used it.

The program copies source into private project staging under the existing build lease.
It checks the copied files again before execution.
It does not replace project source or constraints.
Only the existing controller can publish a machine-accepted result.
Each author, inspector, export check, and saved-scene check uses the existing isolated stages.
A Docker error never selects native execution.

The result includes a strict `model-execution/v1` request binding before publication.
That artifact binds the full prompt, selected reference, accepted parent, executed inputs, rules, and runtime.
The current verifier rejects a changed or partial binding.
Older results without this feature remain readable under their existing verification contract.
The version-1 verification report does not change.

The review program links recorded requests to results.
It distinguishes machine acceptance, human acceptance, rejected checks, and execution failure.
The original queued request records remain unchanged.
Human acceptance remains a separate action.

## Interruption, replay, and retry

Push Ctrl-C to stop the active command.
Examine the saved recovery state and runtime resources before another build.
Use `--acknowledge-interrupted-build` only after the existing recovery procedure is complete.
The flag removes no evidence.

A repeated command for the same revision and binding returns the verified recorded outcome.
It does not execute the proposal again.
A recorded outcome does not clear an uncertain runtime cleanup state.
A retry needs a new revision ID.
If the accepted parent or prepared rules changed, prepare another request.
The program does not overwrite an interrupted revision or silently rebase its inputs.

## Verification scope

Run the offline contract tests with this command:

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
```

The experimental Docker workflow also runs `run_request_bridge.py` and browser checks.
Its handwritten fixture exercises an initial model, measured edit, rejected change, repair, replay, and request-result links.
Those tests do not demonstrate AI generation.
A separate fresh-source author demonstration must use the same bridge and isolated verification path.
Report that demonstration as external-agent-assisted authoring, not built-in natural-language execution.

The [external lamp example](../experimental_modeling/examples/external_lamp/README.md) preserves one actual assistant-authored proposal and its exported brief.
Its CI replay uses the same isolated request bridge.
Read the exact-commit execution evidence before reporting a verified result.
