<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Manual OpenAI lamp proposal trial

This experimental CI lane prepares one live model proposal.
It does not execute generated source or start Blender.
The normal workbench credential contract does not change.
Windows and Mac review packages remain read-only.

## Before setup

Keep this change in draft until its exact source passes review and offline CI.
The repository owner must separately approve the exact request before a live run.
A budget approval alone does not approve transmission or generated-source execution.
Do not start a workflow while setup or review is incomplete.

The fixed request contains the public lamp brief, builder contract, policy, and requirements.
It also contains the fixed provider instructions and output schema.
It contains no previous generated example source, images, Git history, or private files.
The recipient is OpenAI at `https://api.openai.com/v1/responses`.
The request uses `store:false`.
This does not promise zero provider retention.

Read the [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

Review these files before approval:

- [Exact serialized outbound request](../experimental_modeling/live_trial/request.json)
- [Request, price, and data manifest](../experimental_modeling/live_trial/manifest.json)
- [Trusted trial harness](../tests/experimental_modeling/live_openai_trial.py)
- [Manual workflow](../.github/workflows/experimental-modeling-sandbox.yml)

The request has 5,398 bytes.
Its SHA-256 is `98f98db99814205f7c5ba5d6d82314e0a8146c4460981748d25befa72549921a`.
The selected model is `gpt-4.1-mini-2025-04-14`.
The output limit is 8,192 tokens.
The timeout is 90 seconds.
There is one request and no automatic retry.

The model has no tools.

The [official model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini) lists the snapshot and structured output support.
Prices checked on October 3, 2026 were USD 0.40 per million input tokens and USD 1.60 per million output tokens.
The conservative estimate is USD 0.0278528.
This estimate allows 32,768 request bytes, 4,096 additional input tokens, and the full output limit.
It does not use a tokenizer or establish actual charges.
It is below the owner's USD 5 trial ceiling.

Check current prices again before approval.
Stop if the approved terms change.
Account limits and billing remain separate from this estimate.

## Enter the key yourself

Use a dedicated, revocable OpenAI project key.
Limit its permissions to the Responses request capability required for this trial.
Check the [OpenAI key-permission guide](https://help.openai.com/en/articles/8867743-assign-api-key-permissions).
Configure any account-level spend controls directly in OpenAI.
Verify their actual enforcement.
Do not assume that a budget notice prevents charges.

Never paste the key into chat, source, a brief, a workflow input, or command arguments.
Do not share a screenshot that contains the key.
Enter it only in GitHub's environment secret field below.

1. Open this repository on GitHub.
2. Select **Settings**, then **Environments**.
3. Create the environment `hbcb-live-provider`.
4. Under **Required reviewers**, select only `joseph-robert-f`.
5. Leave **Prevent self-review** clear for this sole-owner procedure.
6. Clear **Allow administrators to bypass configured protection rules**.
7. Save the protection rules.
8. Select **Selected branches and tags** for deployment restrictions.
9. Add only the branch `experimental/live-openai-lamp`.
10. Under **Environment secrets**, select **Add secret**.
11. Enter the name `HBCB_OPENAI_TRIAL_KEY`.
12. Paste the dedicated key into the secret value field and save it.

Use an environment secret, not a repository or organization secret.
The branch restriction must match exactly.
Do not select **Protected branches only**.
The owner must verify these settings before dispatch.
See [GitHub environment protection](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

The workflow also reads the actual environment and branch policies before the key step.
It requires the exact owner reviewer, branch restriction, and disabled administrator bypass.
Missing settings, missing API fields, or unavailable read access stop the trial.
It does not create or repair protection rules or read the secret through the API.
A missing environment that GitHub creates automatically has no valid protections and fails this check.

The GitHub read token is available only in the preflight step.
The OpenAI key is available only in the request step.

## Approve one exact run

After setup, review the exact immutable commit and request manifest with the owner.
Do not use a branch name as a substitute for the reviewed commit ID.

In **Actions**, select **Experimental modeling sandbox** and **Run workflow**.
Select the branch `experimental/live-openai-lamp`.
Supply these inputs only after the owner approves the request:

- `trial_mode`: `live-propose`
- `reviewed_commit`: the complete reviewed 40-character commit ID
- `request_sha256`: the complete request SHA-256 shown above
- `setup_confirmation`: `protected-provider-environment-verified`

Review the pending `hbcb-live-provider` deployment for that exact run.
Approve it only if the commit, request, price, and actual protection rules still match.
Do not bypass the gate.
This approval permits one paid proposal request only.
The default `offline` mode and all pull-request events remain secret-free fixture runs.

Preflight checks the workflow and checkout commit against the supplied commit.
It requires the repository owner, the exact branch, and the first run attempt.
It rejects an earlier live dispatch for the same reviewed commit, including failed or cancelled dispatches.
It reads all bounded history pages and stops if history is incomplete or unavailable.
The fixed concurrency group prevents overlapping live runs and does not cancel an active run.

Deleting GitHub history can defeat the history guard.
Do not delete trial history or treat the guard as a global exactly-once guarantee.
Every new run needs its own explicit owner approval.

The harness records consumption before transmission.
It removes the key from its process environment and starts no child process.
Python cannot promise secure erasure of strings from memory.
The provider uses its reviewed fixed HTTPS connection, strict response checks, and safe error codes.
No response body, exception text, key, or request-debug log is published.

## Review the result and stop

Download the `live-lamp-proposal-RUN_ID-1` artifact from the same run.
This public-repository artifact contains the exact request and manifest.
It also contains safe status, bounded usage, file hashes, and any validated proposal.
Treat the proposal as untrusted data.
Do not import it, install it, or run it on a host.
The artifact retention period is seven days.

A validated proposal is not a verified Blender model.
The initial trial stops at this boundary.
Review every source file, the parameters, and the exact proposal SHA-256.
Then prepare a separate secret-free execution request with the existing isolated Docker bridge.
The owner must approve that exact proposal before execution.

A future `hbcb-live-verify` environment needs separate verified protection setup.
This workflow does not reference or create that environment.
No verification dispatch is implemented by this increment.

A timeout, cancellation, or lost response can still incur charges.
Do not rerun, repair, or issue another request automatically.
Keep the run record and inspect the OpenAI account's actual usage.
If another attempt is necessary, obtain new approval after investigating the first attempt.
Revoke the dedicated key directly in OpenAI when the trial no longer needs it.

## Offline checks

Run the fixed request preview without a key:

```sh
python3 tests/experimental_modeling/live_openai_trial.py preview
python3 -m unittest discover -s tests/experimental_modeling -p test_live_openai_trial.py -v
```

Fixtures forbid real credential access and provider network calls.
They do not prove account permissions, live API compatibility, actual charges, or geometry quality.
The full experimental suite remains necessary before publication.
