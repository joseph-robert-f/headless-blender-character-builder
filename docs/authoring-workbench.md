<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Experimental authoring workbench

This source-only program connects the browser to the existing
[external request bridge](model-request-bridge.md).
It requires Linux x64, Python 3.11+, a trusted source checkout, and the existing
[isolated Docker runtime](EXPERIMENTAL_MODELING_SANDBOX.md).
Direct model calls are optional and disabled by default.
The workbench never runs saved prompts automatically.
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


## Optional direct OpenAI authoring

This source-only Linux option does not require Codex or Claude Code to be installed.

It makes one OpenAI Responses API request for each approved outbound preview.
It returns a source proposal and parameters. It cannot select or change the
operator's execution policy or locked requirements. It cannot use model tools,
a shell, repository access, or the Docker socket. The normal inspect and run
steps remain necessary. Windows and Mac packages remain read-only.

Add all of these options to the startup command to enable it:

```text
--author-provider openai
--author-model gpt-4.1-mini
--author-input-usd-per-million YOUR_CURRENT_INPUT_PRICE
--author-output-usd-per-million YOUR_CURRENT_OUTPUT_PRICE
--author-budget-usd YOUR_LOCAL_ESTIMATED_BUDGET
--author-max-output-tokens 8192
--author-max-calls 8
```

The supported model selections are `gpt-4.1-mini` and `gpt-4.1`.
Check availability and current prices in your own OpenAI account.

The app does not change models after an error. These options are fixed for a
server session. The browser shows them but cannot change them.
No price is supplied by default. Input estimates use the full serialized request
byte size plus a protocol allowance. They do not use the provider's tokenizer.

The local budget is only an estimate based on the prices you enter. It is not a
provider-enforced hard spending limit. Set separate account limits with OpenAI.
Reported usage is a token count, not an invoice. Missing usage stays unknown.

Every attempt retains its full estimated reservation, even after refusal,
cancellation, or a local failure. The journal and call count survive a restart.

### Credentials and disclosure

The operator must configure a dedicated OpenAI key outside this app, in an
existing unlocked Linux Secret Service store.
The optional [SecretStorage 3.5.0](https://pypi.org/project/SecretStorage/3.5.0/)
Python library and the desktop's running Secret Service must be available.
Install that library in the trusted Python environment before starting the app.
This app does not install it. Fixture tests do not certify your store setup. There is no
plaintext, environment-variable, command-line, or web-form key fallback.

The app reads only the existing designated entry. It does not create or unlock
a collection, create a credential, or change account access. If the store or
entry is missing or locked, generation fails closed.
The existing default collection must contain exactly one unlocked item with
attributes `service=hbcb-authoring` and `username=openai`.
Configure it with your trusted desktop credential manager.

Do not paste a key into the brief, project, browser, or terminal command arguments.
The app never gives the key to Blender, a project export, a browser response, or
a model prompt. Provider error bodies are not displayed or saved.

Before sending, select a prepared handoff and select **Preview outbound model request**.
Read the complete payload and the displayed provider, model, token limit and
local cost estimate. This includes the initial brief or saved refinement and its
exported text context.

Binary context and images are not supported in this first
version. An unsupported asset stops preparation. It is not silently omitted.
The provider receives the displayed data only after you select the consent box
and **Send one model request**. Do not approve data you are not permitted to share.

The request uses `store:false`. This is not a promise of zero provider retention.
OpenAI's account-level data controls and abuse-monitoring policy still apply.

### Outcomes and recovery

Each preview can be sent once. A duplicate click, lost response, browser reload,
or server restart cannot send that preview again. The app makes no automatic
retry or repair request. A fresh preview requires another explicit approval.

The provider response must finish and pass strict local validation before the
app saves a proposal. Refusals, partial output, unsupported fields, unsafe file
names and oversized responses do not become proposals. Model code remains
untrusted even after format validation.

Select the saved `model-...` proposal and the separately reviewed rule files in
the existing inspection step. Examine the source and parameters before you run.
A provider success is not Blender execution, machine verification, or human acceptance.

**Cancel model request** stops local waiting and publication. The provider may
still process or charge for a sent request. A timeout or lost server ownership
has the same uncertainty.
The journal retains the reservation and blocks another
model request if the outcome is uncertain. Keep this journal for examination.
There is no browser reset or automatic recovery that can erase these records.

Closing the browser does not cancel a request. Ctrl-C stops the server's owned work.

### Validation scope and upstream references

Provider unit tests use fixtures and mock HTTP responses. Browser tests use a
simulated provider and, in CI, the existing real isolated Blender execution path.
These checks do not prove live provider compatibility, output quality, account
permissions, credential-store readiness, or actual billing. A live trial requires
operator credential setup and separate approval for a bounded paid request.

The adapter follows the official [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create),
[structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
[image input](https://developers.openai.com/api/docs/guides/images-vision), and
[data controls](https://developers.openai.com/api/docs/guides/your-data) documentation.
Images are intentionally excluded from this first request contract.
