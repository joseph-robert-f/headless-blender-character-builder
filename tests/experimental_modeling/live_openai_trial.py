"""Fixed CI-only OpenAI proposal smoke test. Never executes generated source.

The production workbench still uses its existing Linux Secret Service reader.
This standalone manual lane accepts a GitHub Environment secret in one process.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling import model_provider as provider
from experimental_modeling.request_contract import read_bytes

REPOSITORY = "joseph-robert-f/headless-blender-character-builder"
OWNER = "joseph-robert-f"
BRANCH = "refs/heads/experimental/live-openai-lamp"
WORKFLOW = ".github/workflows/experimental-modeling-sandbox.yml"
TRIAL = "lamp-openai-2026-10-03"
LIVE_PREFIX = "HBCB live lamp proposal "
SECRET_NAME = "HBCB_OPENAI_TRIAL_KEY"
REQUEST_HASH = "98f98db99814205f7c5ba5d6d82314e0a8146c4460981748d25befa72549921a"
MODEL = "gpt-4.1-mini-2025-04-14"
FOLDER = ROOT / "experimental_modeling/live_trial"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_ARTIFACT_BYTES = 1024 * 1024


class TrialError(RuntimeError):
    """Fixed diagnostic only; never echo input, key, or external response."""


def reject():
    raise TrialError("Trial prerequisites failed. No automatic retry is permitted.")


def fixed_request():
    data = read_bytes(FOLDER / "request.json", 32768)
    if hashlib.sha256(data).hexdigest() != REQUEST_HASH:
        reject()
    request = provider._parse_json(data, 32768, "invalid_request")
    if (provider._request_bytes(request) != data or request["model"] != MODEL or
            request["max_output_tokens"] != 8192):
        reject()
    manifest = json.loads(read_bytes(FOLDER / "manifest.json", 16384))
    if (manifest["request_sha256"] != REQUEST_HASH or manifest["request_bytes"] != len(data) or
            manifest["conservative_cost_estimate_usd"] != 0.0278528):
        reject()
    for name, digest in manifest["source_inputs"].items():
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT) or hashlib.sha256(read_bytes(path, 32768)).hexdigest() != digest:
            reject()
    return request, data, manifest


def gate(env):
    commit = env.get("TRIAL_REVIEWED_COMMIT", "")
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or
            env.get("GITHUB_REPOSITORY") != REPOSITORY or env.get("GITHUB_ACTOR") != OWNER or
            env.get("GITHUB_TRIGGERING_ACTOR") != OWNER or env.get("GITHUB_REF") != BRANCH or
            env.get("GITHUB_RUN_ATTEMPT") != "1" or not SHA.fullmatch(commit) or
            env.get("GITHUB_SHA") != commit or env.get("GITHUB_WORKFLOW_SHA") != commit or
            env.get("TRIAL_MODE") != "live-propose" or
            env.get("TRIAL_REQUEST_SHA256") != REQUEST_HASH or
            env.get("TRIAL_SETUP_CONFIRMATION") != "protected-provider-environment-verified" or
            not re.fullmatch(r"[1-9][0-9]{0,19}", env.get("GITHUB_RUN_ID", ""))):
        reject()
    return {"commit": commit, "run_id": env["GITHUB_RUN_ID"], "run_attempt": 1,
            "request_sha256": REQUEST_HASH, "trial_id": TRIAL}


def github_get(path, token):
    """Read one fixed-host page. No redirects, proxy discovery, or retries."""
    connection = http.client.HTTPSConnection("api.github.com", timeout=20,
                                              context=provider._system_tls_context())
    try:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "hbcb-fixed-live-trial",
                   "Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2022-11-28"}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            reject()
        data = response.read(2 * 1024 * 1024 + 1)
        return provider._parse_json(data, 2 * 1024 * 1024, "invalid_response")
    except Exception:
        reject()
    finally:
        connection.close()


def github_page(commit, page, token):
    path = (f"/repos/{REPOSITORY}/actions/workflows/experimental-modeling-sandbox.yml/runs"
            f"?event=workflow_dispatch&head_sha={commit}&per_page=100&page={page}")
    return github_get(path, token)


def check_protection(environment, branches):
    """Require actual environment protection; missing API fields fail closed."""
    if (not isinstance(environment, dict) or environment.get("name") != "hbcb-live-provider" or
            environment.get("can_admins_bypass") is not False or
            environment.get("deployment_branch_policy") !=
            {"protected_branches": False, "custom_branch_policies": True}):
        reject()
    rules = environment.get("protection_rules")
    if not isinstance(rules, list):
        reject()
    reviewers = [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers"]
    if len(reviewers) != 1 or reviewers[0].get("prevent_self_review") is not False:
        reject()
    people = reviewers[0].get("reviewers")
    if (not isinstance(people, list) or len(people) != 1 or people[0].get("type") != "User" or
            people[0].get("reviewer", {}).get("login") != OWNER or
            people[0].get("reviewer", {}).get("id") != 216030357):
        reject()
    policies = branches.get("branch_policies") if isinstance(branches, dict) else None
    if (not isinstance(branches, dict) or branches.get("total_count") != 1 or
            not isinstance(policies, list) or len(policies) != 1 or
            policies[0].get("name") != BRANCH.removeprefix("refs/heads/") or
            policies[0].get("type") != "branch"):
        reject()


def check_history(identity, fetch):
    """Conservatively consume every earlier live dispatch, including cancellation.

This is an additional guard, not an exactly-once claim against deleted GitHub
history or malicious administrators. Every run still requires owner approval.
"""
    total, seen, found_current = None, set(), False
    for page in range(1, 11):
        value = fetch(identity["commit"], page)
        if not isinstance(value, dict) or type(value.get("total_count")) is not int:
            reject()
        count, runs = value["total_count"], value.get("workflow_runs")
        if not 1 <= count <= 1000 or not isinstance(runs, list) or len(runs) > 100:
            reject()
        if total is not None and total != count:
            reject()
        total = count
        for run in runs:
            if (not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] in seen or
                    run.get("head_sha") != identity["commit"] or run.get("event") != "workflow_dispatch" or
                    run.get("path") != WORKFLOW or not isinstance(run.get("display_title"), str)):
                reject()
            seen.add(run["id"])
            if str(run["id"]) == identity["run_id"]:
                found_current = run["display_title"].startswith(LIVE_PREFIX)
            elif run["id"] < int(identity["run_id"]) and run["display_title"].startswith(LIVE_PREFIX):
                reject()
        if len(seen) == total:
            if not found_current:
                reject()
            return
        if len(runs) != 100:
            reject()
    reject()


def save_json(path, value):
    data = provider._encode(value)
    if len(data) > MAX_ARTIFACT_BYTES:
        reject()
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def preflight(output, env, fetch, protection):
    identity = gate(env)
    fixed_request()
    check_protection(*protection())
    check_history(identity, fetch)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    save_json(output / "preflight.json", identity)
    return identity


def propose(output, env, key, *, factory=provider.OpenAIProvider):
    """Only a validated fixed request may reach the supplied provider once."""
    identity = gate(env)
    request, data, manifest = fixed_request()
    recorded = json.loads(read_bytes(output / "preflight.json", 4096))
    if recorded != identity or not isinstance(key, str) or not provider._KEY.fullmatch(key):
        reject()
    # O_EXCL plus fsync records consumption before credential access/network.
    # Workflow attempts >1 and earlier live dispatches are separately refused.
    save_json(output / "consumed.json", identity | {"status": "consumed_before_send"})
    artifact = output / "public"
    artifact.mkdir(mode=0o700, exist_ok=False)
    (artifact / "request.json").write_bytes(data)
    save_json(artifact / "request-manifest.json", manifest)
    summary = identity | {"status": "uncertain", "usage": None,
                          "automatic_retries": 0, "generated_source_executed": False,
                          "reservation_usd": manifest["conservative_cost_estimate_usd"]}
    try:
        result = factory(credential_reader=lambda: key).generate(request, threading.Event())
        proposal = provider.validate_proposal(result["proposal"])
        # Validate again before saving. The provider also rejects credential reflection.
        serialized = provider._encode(proposal)
        if key.encode() in serialized:
            reject()
        summary["proposal_sha256"] = save_json(artifact / "proposal.json", proposal)
        summary["usage"] = provider._response_usage({"usage": {
            "input_tokens": result["usage"]["input_tokens"],
            "output_tokens": result["usage"]["output_tokens"],
            "input_tokens_details": {"cached_tokens": result["usage"]["cached_input_tokens"]}}})
        summary["status"] = "proposal_validated_not_executed"
    except provider.ProviderError as error:
        summary["status"] = "failed_or_uncertain"
        summary["error_code"] = error.code
        summary["usage"] = error.usage
    except Exception:
        summary["status"] = "failed_or_uncertain"
        summary["error_code"] = "trial_failure"
    finally:
        key = None
    save_json(artifact / "summary.json", summary)
    # Only these exact bounded regular files are eligible for the upload step.
    allowed = {"request.json", "request-manifest.json", "summary.json", "proposal.json"}
    files, size = {}, 0
    for path in artifact.iterdir():
        if path.name not in allowed:
            reject()
        content = read_bytes(path, MAX_ARTIFACT_BYTES)
        size += len(content)
        files[path.name] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    if size > MAX_ARTIFACT_BYTES:
        reject()
    save_json(artifact / "artifact-manifest.json", identity | {"files": files, "bytes": size})
    return summary


def main():
    # Immediately remove process-environment credentials. Do not spawn children.
    key = os.environ.pop(SECRET_NAME, None)
    token = os.environ.pop("TRIAL_GITHUB_READ_TOKEN", None)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preview", "preflight", "propose"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "preview":
            if key is not None or token is not None:
                reject()
            _, _, manifest = fixed_request()
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        if args.output is None or not args.output.is_absolute():
            reject()
        if args.mode == "preflight":
            if key is not None or not isinstance(token, str) or not token:
                reject()
            preflight(args.output, os.environ, lambda commit, page: github_page(commit, page, token),
                      lambda: (github_get(f"/repos/{REPOSITORY}/environments/hbcb-live-provider", token),
                               github_get(f"/repos/{REPOSITORY}/environments/hbcb-live-provider/deployment-branch-policies?per_page=100", token)))
            print("Fixed request, exact commit, and prior run history checked. No model request was sent.")
            return 0
        if token is not None:
            reject()
        result = propose(args.output, os.environ, key)
        print("Trial result: " + result["status"] + ". Inspect the bounded public artifact. Do not retry.")
        return 0 if result["status"] == "proposal_validated_not_executed" else 1
    except Exception:
        print("Trial stopped. Inspect the safe status if present. No automatic retry is permitted.")
        return 1
    finally:
        key = token = None


if __name__ == "__main__":
    raise SystemExit(main())
