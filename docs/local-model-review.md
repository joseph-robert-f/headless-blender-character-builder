<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Local verification and review program

This local program is an unsupported experiment.
It uses the [source-modeling workflow](experimental-source-modeling.md).
It does not change the stable v1 builder or service.
It is not a hosted service or a native Mac application.

## Run locally

Use a source checkout with Python 3.11+.
Open an existing trusted project store with this command:

```sh
python3 -m experimental_modeling review --store /absolute/path/to/project
```

The command shows an `http://127.0.0.1:PORT` address with a random port.
Open that address in a browser on the **same computer**.
Use `--port` to select a local port if necessary.
The program has no bind-host option.
To stop the program, press Ctrl-C.

Blender and Node are not necessary to view existing evidence.
A CDN, remote account, browser extension, and internet upload are not necessary.
This feature does not include a network-facing deployment.

The [project launcher](local-project-launcher.md) adds experimental review on other platforms.
On Windows, the launcher forces read-only mode.
The UI gives the reason and disables acceptance and request controls.
It does not write review metadata.
You can examine existing decisions and evidence.
Use `--read-only` on the direct review-server CLI for the same mode on POSIX.

This mode does not show full Windows application support or an execution boundary for generated code.
The program shows these items:

- Independently evaluated model geometry
- Keyboard and pointer orbit controls
- Before and after comparison with a shared camera
- Fixed inspector renders
- Requirement measurements and coverage
- Revision history and GLB downloads.

The triangle preview is a simple engineering view.
It is not a physically accurate material render.
History uses recorded parent links, not file modification times.
Thus, a copy or archive extraction does not change the revision sequence.
Use arrow keys to rotate the focused model canvas.
Use the reset and comparison buttons as necessary.

The program shows three different states:

1. **Built:** Independently inspected geometry exists.
2. **Machine verified:** All applicable hard requirements and integrity, policy, export, reopening, and preservation checks pass.
3. **Human accepted:** The local user recorded a review decision.

An observer exit with a success code does not show machine verification.
For example, a body deformation can pass mesh observation and export.
But comparison with the protected region of its accepted baseline can fail.

## Requirements and evidence

To set the first project rules, supply a reviewed requirement definition:

```sh
python3 -m experimental_modeling build \
  --source experimental_modeling/examples/watering_can/source \
  --params experimental_modeling/examples/watering_can/params/r0.json \
  --policy /absolute/path/to/reviewed-policy.json \
  --requirements experimental_modeling/examples/watering_can/requirements.json \
  --store /absolute/path/to/new-project --revision r0 \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID
```

The source-execution boundary applies.
The native `--trusted-reviewed-source` alternative is **not a sandbox**.
Use it only for reviewed local development.
The UI shows the execution mode.
A verified geometry report does not make unreviewed native Python safe to execute.

Requirement definition v1 has the exact fields `schema_version: 1` and `requirements`.
Each requirement has `id`, `title`, `kind`, `hard`, `phase`, and `params`.
The program has these checks with fixed limits:

- `connected_path`: A mesh-edge path between two selected regions inside a declared axis-aligned region. It does not prove load-bearing strength.
- `clearance_path`: Segment and triangle obstruction checks and sampled nearest-mesh clearance. Inputs are trusted explicit points or inspected vertex centroids.
  It does not fully validate flow, cross-section, or manufacturing.
- `preserved_region`: A comparison with the accepted parent.
  It includes a world-vertex multiset, oriented contained triangles, per-triangle material assignments, quantized corner normals, and part materials.
  It excludes faces that cross the region boundary.
  The check can reject harmless retessellation.
- `preserved_rays`: First-hit distances along declared rays compared with the accepted parent. The result applies only to those samples.
- `manual_review`: Machine evidence with an explicit unknown result.
  If this requirement is hard and applicable, it prevents machine verification.
  The UI cannot override it.

Each report row has a pass, fail, or unknown result.
It includes the stage, hard and applicable flags, measured and expected values, and coverage statement.
Missing data, unsupported coverage, and work-budget limits give **unknown**, not a pass.
A hard applicable failure rejects the candidate.
A hard applicable unknown prevents acceptance and gives a review requirement.

A preservation rule for revisions is not applicable to an initial model.
Missing evidence for an existing parent does not make the model initial.
It cannot bypass preservation checks.

The controller copies the first explicit requirement file to `STORE/requirements.json` and binds its hash.
Subsequent builds use this file, also when you omit `--requirements`.
The controller rejects different, removed, or historically inconsistent rules.
The program has no rule-edit control.
To restore a lost file, use the recorded definition without changes.
Do not substitute a weaker definition.

A new default build without explicit rules does not lock an empty rule set.
You can set rules subsequently.
The UI then shows that older models have no verification against those new requirements.
This version has no in-place policy migration.

`verification.json` is a versioned machine artifact.
It binds source, runtime, policy, requirements, and parent-result hashes.
Before display or acceptance, the UI validates full artifact hashes, accepted-history bindings, active rules, and the report.
You can examine legacy artifacts without this report.
The UI does not silently give them a verified badge.

First-view revalidation can take some seconds for geometric relations.
The program caches unchanged reports only after validation.
It verifies artifact hashes again on subsequent reads.

## Human decisions and queued edits

**Accept this revision** records the selected result hash, review notes, and time under `STORE/review/acceptances/`.
The operation is idempotent.
Current full machine verification is necessary.
It does not change machine evidence or the last-good pointer.
It does not revert a model or execute Blender.
A previous human decision stays in history if new rules introduce an unverified requirement.

**Save change request** keeps the text without changes and the selected result hash in `STORE/review/requests/`.
The program combines identical requests into one record.
Requests survive reloads and show **queued / execution not started**.
The queue limit is 256 records.
The program does not automatically delete records.

A coding agent or operator can read the request JSON as task input.
The program has no built-in language model, automatic queue consumer, or execution endpoint.
You can request a repair for a rejected candidate.
But the controller's build parent must be a valid accepted last-good revision.
The UI has no build or revert controls.

## Local security boundary

The program uses these controls:

- IPv4 loopback binding only
- Exact Host and Origin validation
- Cross-site request rejection
- Per-process CSRF token and JSON body limits
- No arbitrary filesystem path, source execution, shell command, or upload endpoint
- No requirement-edit or remote-control endpoint
- Fixed artifact roles and no-store responses
- Restrictive CSP and no iframe embedding
- No external scripts, fonts, or assets
- Text-only rendering of user content
- Symlink and path checks
- Result and artifact hash validation
- Accepted parent-hash chains
- Stale-result conflict checks and persistent idempotent operations.

Review state is not part of the immutable machine artifacts.
It cannot accept a failed model or overwrite last-good state.

The design assumes one trusted local OS user and project store.
It is not a signed identity or attestation service.
It cannot prevent the owner or a process with equivalent filesystem authority from replacement of all trust roots.
Do not put it behind a reverse proxy.
Do not expose it on a network or use it as a multi-user service.

## Reproduce verification and UI tests

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
python3 tests/experimental_modeling/run_water_relations.py \
  --store /tmp/water-relations --trusted-reviewed-source
python3 tests/experimental_modeling/run_review_project.py \
  --store /tmp/water-review-project --trusted-reviewed-source
python3 -m experimental_modeling review --store /tmp/water-review-project/project
```

The relation harness makes three positive models again.
It also makes three saved-geometry mutations: a detached handle attachment, a blocked spout, and a changed protected body.
The aggregate harness changes source so that observation and export pass but protected-body requirements fail.
This test shows that the last-good pointer and human-acceptance gate do not accept that change.

Each harness can use `--sandbox-image` as an alternative to native execution.
The experimental CI workflow runs them with Blender in containers.
It then runs Playwright against disposable copies of generated stores.
Browser tests include these operations and conditions:

- Orbit controls and comparison
- Measured evidence and mobile layout
- Initial requirement non-applicability
- Rejected acceptance and persistence
- Duplicate requests and stale-result errors
- CSRF errors and changed artifacts
- Server outage.

The CI artifacts contain screenshots and summaries.
A script or skipped test does not show visual verification.

Browser QA dependencies are for tests only: Node 20+ and Playwright 1.62.1.
`tests/review_ui` contains the npm integrity lock.
The application has no JavaScript dependencies.

The historical implementation environment blocked cloud-browser loopback with `net::ERR_BLOCKED_BY_CLIENT`.
Local Chromium could not make its process socket.
That investigation did not use a proxy, public exposure, or OS security change.
Use evidence from the supported CI test runner for browser validation.
Read [HBCB REVIEW PREVIEW](review-preview.md) for the read-only package and its own test results.
Native model generation on Mac is not verified by that package.
