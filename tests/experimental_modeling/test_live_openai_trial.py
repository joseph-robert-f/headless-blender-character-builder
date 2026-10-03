"""Offline fixture checks. Real network and credential access are forbidden."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("live_trial", Path(__file__).with_name("live_openai_trial.py"))
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)

KEY = "fixture-live-trial-not-a-credential"
COMMIT = "a" * 40
ENV = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": trial.REPOSITORY,
       "GITHUB_ACTOR": trial.OWNER, "GITHUB_TRIGGERING_ACTOR": trial.OWNER, "GITHUB_REF": trial.BRANCH,
       "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": COMMIT, "GITHUB_WORKFLOW_SHA": COMMIT,
       "GITHUB_RUN_ID": "123", "TRIAL_REVIEWED_COMMIT": COMMIT, "TRIAL_MODE": "live-propose",
       "TRIAL_REQUEST_SHA256": trial.REQUEST_HASH, "TRIAL_SETUP_CONFIRMATION": "protected-provider-environment-verified"}
PROTECTION = {"name": "hbcb-live-provider", "can_admins_bypass": False,
              "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
              "protection_rules": [{"type": "required_reviewers", "prevent_self_review": False,
                                    "reviewers": [{"type": "User", "reviewer": {"login": trial.OWNER, "id": 216030357}}]}]}
BRANCHES = {"total_count": 1, "branch_policies": [{"name": trial.BRANCH.removeprefix("refs/heads/"), "type": "branch"}]}
PROPOSAL = {"source": [{"name": "builder.py", "content": "raise RuntimeError('MUST NEVER EXECUTE')\n"}], "params_json": "{}"}
RESULT = {"proposal": PROPOSAL, "usage": {"input_tokens": 1200, "output_tokens": 2500, "cached_input_tokens": 0}}


def run(run_id=123, title=None):
    return {"id": run_id, "head_sha": COMMIT, "path": trial.WORKFLOW,
            "event": "workflow_dispatch", "display_title": title or trial.LIVE_PREFIX + COMMIT}


class TrialFixtureTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(trial.provider, "direct_https_request", side_effect=AssertionError("Real provider network forbidden"))
        self.credentials = patch.object(trial.provider, "read_secret_service_key", side_effect=AssertionError("Real credentials forbidden"))
        self.network.start(); self.credentials.start()
        self.addCleanup(self.network.stop); self.addCleanup(self.credentials.stop)

    def test_fixed_request_no_example_source_private_context_or_tools(self):
        request, data, manifest = trial.fixed_request()
        self.assertEqual(hashlib.sha256(data).hexdigest(), trial.REQUEST_HASH)
        self.assertEqual(len(data), 5398)
        self.assertLess(manifest["conservative_cost_estimate_usd"], .03)
        self.assertEqual(request["model"], trial.MODEL)
        self.assertFalse(request["store"])
        self.assertEqual(request["tools"], [])
        context = json.loads(request["input"][0]["content"][0]["text"])
        self.assertEqual(set(context), {"brief", "builder_contract", "policy", "requirements"})
        self.assertNotIn("proposal/source", data.decode())

    def test_gate_rejects_every_missing_or_changed_field(self):
        trial.gate(ENV)
        for key in ENV:
            for change in (None, "wrong", ""):
                env = ENV.copy()
                if change is None: env.pop(key)
                else: env[key] = change
                with self.subTest(key=key, change=change), self.assertRaises(trial.TrialError): trial.gate(env)
        for event in ("pull_request", "pull_request_target", "push"):
            with self.assertRaises(trial.TrialError): trial.gate(ENV | {"GITHUB_EVENT_NAME": event})
        with self.assertRaises(trial.TrialError): trial.gate(ENV | {"GITHUB_RUN_ATTEMPT": "2"})

    def test_unprotected_or_auto_created_environment_fails_closed(self):
        trial.check_protection(PROTECTION, BRANCHES)
        cases = [{}, PROTECTION | {"can_admins_bypass": True}, PROTECTION | {"deployment_branch_policy": None},
                 PROTECTION | {"protection_rules": []}, PROTECTION | {"name": "other"}]
        for field in PROTECTION:
            value = copy.deepcopy(PROTECTION); value.pop(field); cases.append(value)
        for value in cases:
            with self.assertRaises(trial.TrialError): trial.check_protection(value, BRANCHES)
        for value in ({}, BRANCHES | {"total_count": 2}, {"total_count": 1, "branch_policies": [{"name": "*", "type": "branch"}]},
                      {"total_count": 1, "branch_policies": [{"name": trial.BRANCH.removeprefix("refs/heads/"), "type": "tag"}]}):
            with self.assertRaises(trial.TrialError): trial.check_protection(PROTECTION, value)
        for mutate in ("self", "other", "extra"):
            value = copy.deepcopy(PROTECTION); rule = value["protection_rules"][0]
            if mutate == "self": rule["prevent_self_review"] = True
            elif mutate == "other": rule["reviewers"][0]["reviewer"]["login"] = "other"
            else: rule["reviewers"].append(copy.deepcopy(rule["reviewers"][0]))
            with self.assertRaises(trial.TrialError): trial.check_protection(value, BRANCHES)

    def test_history_requires_current_and_consumes_prior_failed_or_cancelled(self):
        identity = trial.gate(ENV)
        trial.check_history(identity, lambda *_: {"total_count": 1, "workflow_runs": [run()]})
        trial.check_history(identity, lambda *_: {"total_count": 2, "workflow_runs": [run(), run(122, "Offline tests")]})
        for value in ({}, {"total_count": 1, "workflow_runs": []}, {"total_count": 1001, "workflow_runs": []},
                      {"total_count": 2, "workflow_runs": [run(), run()]},
                      {"total_count": 1, "workflow_runs": [run(122, "Offline tests")]},
                      {"total_count": 2, "workflow_runs": [run(), run(122)]}):
            with self.assertRaises(trial.TrialError): trial.check_history(identity, lambda *_: value)

    def test_history_full_pagination_and_incomplete_or_changing_history(self):
        identity = trial.gate(ENV | {"GITHUB_RUN_ID": "500"})
        first = {"total_count": 101, "workflow_runs": [run(500)] + [run(i, "Offline") for i in range(1, 100)]}
        second = {"total_count": 101, "workflow_runs": [run(100, "Offline")]}
        fetch = Mock(side_effect=[first, second]); trial.check_history(identity, fetch)
        self.assertEqual(fetch.call_count, 2)
        for changed in ({"total_count": 102, "workflow_runs": [run(100, "Offline")]}, {"total_count": 101, "workflow_runs": []}):
            with self.assertRaises(trial.TrialError): trial.check_history(identity, Mock(side_effect=[first, changed]))

    def prepare(self, root):
        output = root / "trial"
        trial.preflight(output, ENV, lambda *_: {"total_count": 1, "workflow_runs": [run()]}, lambda: (PROTECTION, BRANCHES))
        return output

    def test_fixture_success_one_call_no_execution_and_manifest_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            output = self.prepare(Path(folder)); instance = Mock(); instance.generate.return_value = RESULT
            factory = Mock(return_value=instance)
            result = trial.propose(output, ENV, KEY, factory=factory)
            self.assertEqual(result["status"], "proposal_validated_not_executed")
            self.assertFalse(result["generated_source_executed"])
            instance.generate.assert_called_once()
            self.assertEqual(factory.call_args.kwargs["credential_reader"](), None)  # cleared after return
            files = {p.name for p in (output / "public").iterdir()}
            self.assertEqual(files, {"request.json", "request-manifest.json", "summary.json", "proposal.json", "artifact-manifest.json"})
            for p in output.rglob("*"):
                if p.is_file(): self.assertNotIn(KEY.encode(), p.read_bytes())
            manifest = json.loads((output / "public/artifact-manifest.json").read_bytes())
            for name, record in manifest["files"].items():
                content = (output / "public" / name).read_bytes()
                self.assertEqual(record, {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
            with self.assertRaises(FileExistsError): trial.propose(output, ENV, KEY, factory=factory)
            instance.generate.assert_called_once()

    def test_refusal_timeout_unexpected_error_never_retries_or_leaks(self):
        for error in (trial.provider.ProviderError("timeout"), trial.provider.ProviderError("refusal"), RuntimeError(KEY)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                output = self.prepare(Path(folder)); instance = Mock(); instance.generate.side_effect = error
                result = trial.propose(output, ENV, KEY, factory=Mock(return_value=instance))
                self.assertEqual(result["status"], "failed_or_uncertain")
                self.assertFalse((output / "public/proposal.json").exists())
                instance.generate.assert_called_once()
                self.assertTrue((output / "consumed.json").exists())
                for p in output.rglob("*"):
                    if p.is_file(): self.assertNotIn(KEY.encode(), p.read_bytes())

    def test_real_adapter_fixture_uses_only_injected_reader_and_transport(self):
        body = trial.provider._encode({"status": "completed", "output": [{"type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(PROPOSAL)}]}], "usage": {"input_tokens": 1200, "output_tokens": 2500}})
        transport = Mock(return_value=(200, body))
        def factory(**kwargs): return trial.provider.OpenAIProvider(transport=transport, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            output = self.prepare(Path(folder)); result = trial.propose(output, ENV, KEY, factory=factory)
            self.assertEqual(result["status"], "proposal_validated_not_executed")
            transport.assert_called_once()
            self.assertEqual(transport.call_args.kwargs["body"], trial.fixed_request()[1])

    def test_missing_key_preflight_or_mutated_binding_never_calls_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            output = self.prepare(Path(folder)); factory = Mock()
            for key in (None, "", "bad\nheader"):
                with self.assertRaises(trial.TrialError): trial.propose(output, ENV, key, factory=factory)
            (output / "preflight.json").write_text("{}")
            with self.assertRaises(trial.TrialError): trial.propose(output, ENV, KEY, factory=factory)
            factory.assert_not_called()

    def test_changed_request_or_manifest_fails_before_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); output = self.prepare(root); data_root = root / "fixed"; data_root.mkdir()
            original_request = (trial.FOLDER / "request.json").read_bytes()
            original_manifest = (trial.FOLDER / "manifest.json").read_bytes()
            for request, manifest in ((original_request + b" ", original_manifest),
                                      (original_request, b'{}'),
                                      (original_request, original_manifest.replace(b"5398", b"5399"))):
                (data_root / "request.json").write_bytes(request)
                (data_root / "manifest.json").write_bytes(manifest)
                factory = Mock()
                with patch.object(trial, "FOLDER", data_root), self.assertRaises((trial.TrialError, KeyError)):
                    trial.propose(output, ENV, KEY, factory=factory)
                factory.assert_not_called()

    def test_github_read_wrapper_is_fixed_host_bounded_no_redirect_or_retry(self):
        for status, content, valid in ((200, b'{"ok":true}', True), (302, b'', False),
                                       (403, b'forbidden', False), (200, b'{', False),
                                       (200, b'x' * (2 * 1024 * 1024 + 1), False)):
            connection = Mock(); response = Mock(status=status); response.read.return_value = content
            connection.getresponse.return_value = response
            with patch.object(trial.http.client, "HTTPSConnection", return_value=connection) as factory, patch.object(trial.provider, "_system_tls_context", return_value="verified-fixture"):
                if valid: self.assertEqual(trial.github_get("/fixed", "fixture-read-token"), {"ok": True})
                else:
                    with self.assertRaises(trial.TrialError): trial.github_get("/fixed", "fixture-read-token")
                factory.assert_called_once_with("api.github.com", timeout=20, context="verified-fixture")
                connection.request.assert_called_once()
                self.assertEqual(connection.request.call_args.args, ("GET", "/fixed"))
                connection.close.assert_called_once()
                if status != 200: response.read.assert_not_called()

    def test_main_removes_key_before_proposal_and_does_not_expose_it(self):
        import contextlib
        import io
        captured = []
        def fake_propose(output, env, key):
            captured.append((trial.SECRET_NAME not in env, key))
            return {"status": "proposal_validated_not_executed"}
        with patch.dict(os.environ, {trial.SECRET_NAME: KEY}, clear=True), patch.object(trial.sys, "argv", ["trial", "propose", "--output", "/tmp/fixture-only"]), patch.object(trial, "propose", side_effect=fake_propose), contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(trial.main(), 0)
            self.assertNotIn(trial.SECRET_NAME, os.environ)
        self.assertEqual(captured, [(True, KEY)])
        self.assertNotIn(KEY, stream.getvalue())

    def test_workflow_live_is_manual_owner_only_separate_and_no_execution(self):
        workflow = json.loads((trial.ROOT / trial.WORKFLOW).read_text())
        self.assertEqual(workflow["on"]["workflow_dispatch"]["inputs"]["trial_mode"]["default"], "offline")
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        job = workflow["jobs"]["live-lamp-proposal"]
        for guard in ("workflow_dispatch", "live-propose", "github.actor", "github.triggering_actor", "github.run_attempt == 1", trial.BRANCH):
            self.assertIn(guard, job["if"])
        self.assertEqual(job["environment"]["name"], "hbcb-live-provider")
        self.assertEqual(job["permissions"], {"contents": "read", "actions": "read"})
        secret_steps = [step for step in job["steps"] if trial.SECRET_NAME in json.dumps(step)]
        self.assertEqual(len(secret_steps), 1)
        self.assertEqual(secret_steps[0]["id"], "propose")
        for step in job["steps"]:
            self.assertNotIn("run_proposal", json.dumps(step))
            self.assertNotIn("docker", json.dumps(step))
        self.assertNotIn("secrets.", json.dumps(workflow["jobs"]["docker-boundary-and-benchmark"]))


if __name__ == "__main__":
    unittest.main()
