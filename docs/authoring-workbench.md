<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental external-author workbench

This source-only program connects the browser to the existing
[external request bridge](model-request-bridge.md).
It requires Linux x64, Python 3.11+, a trusted source checkout, and the existing
[isolated Docker runtime](EXPERIMENTAL_MODELING_SANDBOX.md).
It does not call a model provider, store credentials, or run saved prompts automatically.
Windows and Mac review packages do not include an authoring execution adapter.
The ordinary review server does not execute source.

## Start one explicit session

Initialize a project with the [project launcher](local-project-launcher.md).
Create three different intake directories outside the project and trusted checkout.
Use an empty handoff directory, a proposal directory, and a reviewed-rules directory.
These directories must not overlap each other.

```sh
python3 -m experimental_modeling.workbench \
  --project /absolute/path/project \
  --handoff-root /absolute/path/handoffs \
  --proposal-root /absolute/path/proposals \
  --rules-root /absolute/path/reviewed-rules \
  --python /absolute/path/trusted/python3.11 \
  --docker /absolute/path/trusted/docker \
  --docker-socket /run/docker.sock \
  --sandbox-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID
```

Supply real absolute paths without symbolic links.
The Python executable must be outside the project and intake directories.
The program pins the project, intake roots, source modules, Python executable,
Docker executable, local socket identity, and immutable image at startup.
A changed trusted input requires a new session after review.
The program does not discover, install, or download a runtime.

Open the printed numeric-loopback address in your browser.
Keep the terminal open.
Only one workbench session can hold the project lease.
Do not expose its port through a proxy or network tunnel.

This program is for one trusted local operator.
It trusts the Docker daemon, selected image, Python installation, and checkout.
Exact-origin and CSRF checks protect against unrelated browser sites.
They do not authenticate against hostile processes or other users on the same machine.
Do not use the workbench as a hosted or multi-user service.

## Prepare and examine

1. Enter the complete initial brief. A new project can start without model source.
   You can also select a saved change request from the existing review program.
2. Select **Prepare initial handoff** or **Prepare refinement handoff**. This writes the existing request contract and context
   to a new directory. It does not contact an external author.
3. Examine the handoff before sending it to your selected source author.
   Use that tool's own account, payment, and permission controls.
4. Put the returned proposal in one child directory of the proposal root.
   It must contain only `source/` and `params.json`.
5. Independently examine the proposed policy and requirements.
   Put the selected reviewed JSON files directly in the reviewed-rules root.
   Selecting a file or checking a box is not proof of independent human review.
6. Refresh the selections. Select the handoff, proposal, policy, and optional
   initial requirements. Existing locked project requirements cannot be replaced.
7. Select **Inspect selected inputs**. Read the complete prompt, full parameter and rule JSON,
   source inventory, text, and before/after inputs. Binary files have byte sizes
   and SHA-256 identities. Examine original binary assets separately when needed.
   The bridge's abbreviated summary is not the complete review.
8. Confirm that you examined the rules and exact inputs. Select **Run inspected candidate** only
   when you intend to execute that inspected proposal in the selected Docker runtime.

Intake roots have a limit of 128 direct entries each.
The workbench retains at most 31 inspection permissions in a session journal.
It also bounds brief preparation attempts, including partial handoffs.
The bridge retains its file, byte, depth, and directory limits.
Links, hard links, special files, hidden author configuration, and arbitrary host
paths from browser requests are not permitted.

## One permission, one operation

An inspection has one fixed revision and durable operation ID.
Before execution, the server records that the permission was consumed.
It then checks the original digest again and starts the unchanged request CLI
in one supervised child process.
The bridge stages and checks the source under its existing build lease.
No native execution fallback is available.

Repeated clicks, another tab, a browser reload, or a lost response return the same
operation. They do not create another revision or start the child again.
A failed or rejected operation requires another explicit inspection and permission.
Changed input, rules, runtime, or accepted parent cannot inherit an older approval.
The program does not automatically repair, retry, or rebase a proposal.

The results panel reads artifacts through the existing verifier.
A process exit code alone does not prove that a model passed.
Use **Open model review and comparison** to see the candidate and its parent.
Select the displayed revision in the existing review history.
Machine acceptance and human acceptance remain separate.
Appearance and requirements without declared checks still need human review.

## Stop and recovery

Closing the browser does not stop the active operation.
Use its **Request interruption** button, or push Ctrl-C in the workbench terminal.
The server signals only its currently owned child and waits for bridge cleanup.
It never kills a PID read from a previous session.

After a server crash, a consumed operation with no known terminal outcome is
**uncertain**. The workbench never restarts it and blocks additional execution.
A verified candidate can still be shown without certifying runtime cleanup.
Keep the workbench journal and all project recovery files.
Do not delete them to make the Run button available.

Use the request bridge's existing terminal recovery procedure after examining
runtime resources and retained evidence. The browser does not acknowledge
interrupted builds or clear recovery flags. This first workbench version does
not reset an uncertain journal. Continue a recovered project through the explicit
request CLI. A future recovery interface needs separate ownership checks.

## Verification

```sh
python3 -m unittest discover -s tests/experimental_modeling -v
```

Focused tests exercise complete snapshots, single-use permissions, repeated
requests, stale inputs, crash records, filesystem constraints, and HTTP boundaries.
The opt-in experimental CI workflow exercises the browser with the real Docker
request bridge. A passing earlier commit does not certify this increment.
Mocked controller tests do not prove Blender execution or AI generation.
