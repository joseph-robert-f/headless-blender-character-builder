<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Local verification and review program

This is an unsupported experimental local program, stacked on the
[source-modeling lane](experimental-source-modeling.md). It does not change the
stable v1 builder or service. It is not a hosted service or a native Mac app.

## Run locally

From a checkout with Python 3.11+, open an existing trusted project store:

```sh
python3 -m experimental_modeling review --store /absolute/path/to/project
```

The command prints a random-port `http://127.0.0.1:PORT` address. Open that address
in a browser on the **same computer**. `--port` may select a local port; there is
no bind-host option. Stop the program with Ctrl-C. The review program needs
neither Blender nor Node to view existing evidence. It requires no CDN, remote
account, browser extension or internet upload. No network-facing deployment is
part of this feature.

The app shows the independently evaluated model, keyboard/pointer orbit controls,
shared-camera before/after comparison, fixed inspector renders, requirement
measurements and coverage, revision history, and GLB downloads. Its triangle
preview is a simple engineering view, not a physically accurate material render.
Arrow keys rotate the focused model canvas; reset and comparison are buttons.

Three states are deliberately separate:

1. **Built:** independently inspected geometry exists
2. **Machine verified:** all applicable hard requirements and the full integrity,
   policy, export, reopen and preservation checks pass
3. **Human accepted:** the local user has separately recorded a review decision

An observer's successful exit cannot establish the second state. For example,
a body deformation can pass mesh observation and export while failing comparison
with the protected region of its accepted baseline.

## Requirements and evidence

Pass a reviewed requirement definition when first establishing project rules:

```sh
python3 -m experimental_modeling build \
  --source experimental_modeling/examples/watering_can/source \
  --params experimental_modeling/examples/watering_can/params/r0.json \
  --policy /absolute/path/to/reviewed-policy.json \
  --requirements experimental_modeling/examples/watering_can/requirements.json \
  --store /absolute/path/to/new-project --revision r0 \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID
```

The normal source-execution boundary still applies. The explicit native
`--trusted-reviewed-source` alternative is **not sandboxed** and is for reviewed
local development only. The UI shows the execution mode; a verified geometry
report never means native Python became safe to run unreviewed.

Requirement definition v1 has exact fields `schema_version: 1` and
`requirements`. Each requirement has `id`, `title`, `kind`, `hard`, `phase` and
`params`. Supported bounded checks are:

- `connected_path`: a mesh-edge path between two selected regions, inside a
  declared axis-aligned region; it does not prove load-bearing strength
- `clearance_path`: segment/triangle obstruction checks and sampled nearest-mesh
  clearance, using trusted explicit points or inspected vertex centroids; it is
  not exhaustive flow, cross-section or manufacturing validation
- `preserved_region`: a selected world-vertex multiset, oriented contained
  triangles, per-triangle material assignments, quantized corner normals and
  part materials compared with the actual accepted parent. Boundary-crossing
  faces are excluded; harmless retessellation may conservatively fail this check
- `preserved_rays`: first-hit distances along declared rays compared with the
  accepted parent, covering only those samples
- `manual_review`: explicitly unknown machine evidence. If declared hard and
  applicable, it blocks machine verification; the UI cannot override it

Each report row includes pass/fail/unknown, its stage, hard/applicable flags,
measured values, expected values and a coverage statement. Missing data,
unsupported coverage and work-budget limits produce **unknown**, never a pass.
A hard applicable failure rejects the candidate; a hard applicable unknown
prevents acceptance and leaves it needing review. A revision-only preservation
rule is explicitly non-applicable for an initial model. Missing evidence for an
actual parent is not treated as an initial model and cannot skip preservation.

The first explicit requirement file is copied to `STORE/requirements.json` and
hash-bound. Later builds use it even when `--requirements` is omitted. Different,
removed or historically inconsistent rules fail closed; the app has no edit-rule
control. Restoring a lost file requires the exact recorded definition, not a
weaker replacement. A fresh default build without explicit rules does not lock an
empty set. Rules can be established later, but older models are visibly not
verified against the newly introduced requirements. There is no in-place policy
migration mechanism in this version.

`verification.json` is a versioned machine artifact bound to source, runtime,
policy, requirements and parent-result hashes. The UI validates complete artifact
hashes, accepted-history bindings, the active rules and the report before showing
or accepting a revision. Legacy artifacts without this report stay inspectable
but are not silently upgraded to a verified badge. First-view revalidation can
take several seconds for geometric relations; unchanged reports are cached only
after validation, while artifact hashes are checked again on subsequent reads.

## Human decisions and queued edits

**Accept this revision** records the selected result hash, review notes and time
under `STORE/review/acceptances/`. It is idempotent and requires current complete
machine verification. It does not rewrite machine evidence, change the last-good
pointer, revert a model or execute Blender. An earlier human decision remains a
historical fact if later rules introduce an unverified requirement.

**Request a revision** preserves the exact text and selected result hash in
`STORE/review/requests/`. Identical requests deduplicate, persist across reloads,
and remain visibly **queued / execution not started**. The queue is bounded at
256 records; no automated deletion is performed. A coding agent or operator may
read those JSON requests as task input. There is no built-in language model,
automatic queue consumer or execution endpoint. A rejected candidate may be the
subject of a repair request, but only a valid accepted last-good revision can be
the controller's build parent. There are no nonfunctional build/revert buttons.

## Local security boundary

- IPv4 loopback binding only, exact Host and Origin validation, cross-site request
  rejection, per-process CSRF token and bounded JSON bodies
- No arbitrary filesystem path, source execution, shell command, upload,
  requirements edit or remote-control endpoint
- Fixed artifact roles, no-store responses, restrictive CSP, no iframe embedding,
  no external scripts/fonts/assets and text-only rendering of user content
- Symlink/path checks, result/artifact hash validation, accepted parent-hash
  chains, stale-result conflict checks and persisted idempotent operations
- Review state is separate from immutable machine artifacts; it cannot promote a
  failed model or overwrite the last-good state

This assumes one trusted local OS user and project store. It is not a signed
identity/attestation service and cannot defend against the owner or another
process with equivalent filesystem authority rewriting all trust roots. Do not
reverse-proxy it, expose it on a network, or use it as a multi-user service.

## Reproduce verification and UI tests

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
python3 tests/experimental_modeling/run_water_relations.py \
  --store /tmp/water-relations --trusted-reviewed-source
python3 tests/experimental_modeling/run_review_project.py \
  --store /tmp/water-review-project --trusted-reviewed-source
python3 -m experimental_modeling review --store /tmp/water-review-project/project
```

The relation harness regenerates three positive models and three saved-geometry
mutations: one detached handle attachment, a blocked spout, and a changed
protected body. The aggregate harness also performs a real source edit that
passes observation/export but fails protected-body requirements, proving that the
last-good pointer and human-acceptance gate remain protected.

Both harnesses support `--sandbox-image` instead of native execution. The separate
experimental CI workflow runs them using actual container Blender, then runs
Playwright against disposable copies of real generated stores. Browser tests cover
orbit/comparison, measured evidence, mobile layout, initial non-applicability,
rejected acceptance, persistence, duplicate requests, stale/CSRF errors, tampered
artifacts and server outage. Screenshots and summaries are retained with the CI
artifacts; a script or skipped test is not a visual pass.

Browser QA dependencies are test-only: Node 20+ and Playwright 1.62.1 with npm
integrity lock in `tests/review_ui`. The app itself has no JavaScript dependencies.
This implementation environment blocked cloud-browser loopback with
`net::ERR_BLOCKED_BY_CLIENT`; local Chromium could not create its process socket.
No proxy, public exposure or OS security change was used. Actual browser evidence
must come from the supported CI test runner. Native Mac packaging/runtime remains
unverified until tested on a Mac.
