"""Fixture-only authoring journal tests. No key access or provider charges."""
import http.client
from decimal import Decimal
import json
import threading
import unittest
from unittest.mock import Mock

from experimental_modeling.authoring import AuthorConfig, Authoring, money
from experimental_modeling.request_contract import read_json
import test_workbench


class AuthoringTests(test_workbench.WorkbenchTests):
    def setup_author(self, **config):
        self.provider = Mock()
        self.provider.generate.return_value = {
            "proposal": {"source": [{"name": "builder.py", "content": "# inert proposal\n"}], "params_json": '{"size": 1}'},
            "usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 0}}
        values = dict(model="gpt-4.1-mini", input_usd_per_million="1", output_usd_per_million="2", budget_usd="100")
        values.update(config)
        self.wb.authoring = Authoring(self.wb, AuthorConfig(**values), self.provider)
        self.addCleanup(self.wb.authoring.close)
        self.wb.prepare({**self.payload, "brief": "Make a small lamp. <script>inert</script>"})
        choice = self.wb.state()["choices"]["handoffs"][0]["id"]
        self.preview = self.wb.authoring.preview({**self.payload, "handoff_id": choice})
        return self.wb.authoring

    def submit_model(self, author):
        return author.submit({**self.payload, "preview_id": self.preview["id"], "digest": self.preview["digest"], "approve_transmission": True})

    def wait_model(self, author):
        author.thread.join(5)
        self.assertFalse(author.thread.is_alive())
        return author.calls()[0]

    def test_model_preview_never_calls_or_executes(self):
        author = self.setup_author()
        self.provider.generate.assert_not_called()
        self.assertIn('Make a small lamp.', json.dumps(self.preview["outbound"]))
        self.assertEqual(self.preview["config"]["provider"], "openai")
        self.assertGreater(Decimal(self.preview["estimate_usd"]), 0)
        self.assertEqual(author.calls(), [])
        self.assertEqual(self.wb.records("operation"), [])

    def test_model_proposal_and_replay_do_not_execute(self):
        author = self.setup_author()
        self.submit_model(author)
        row = self.wait_model(author)
        self.assertEqual(row["state"], "completed")
        output = self.roots[1] / row["proposal_label"]
        self.assertEqual(read_json(output / "params.json"), {"size": 1})
        self.assertEqual((output / "source/builder.py").read_text(), "# inert proposal\n")
        self.assertFalse((output / "policy.json").exists())
        self.assertEqual(self.wb.records("operation"), [])
        self.submit_model(author)
        self.assertEqual(self.provider.generate.call_count, 1)
        self.assertEqual(author.state()["reserved_usd"], self.preview["estimate_usd"])
        restarted = Authoring(self.wb, author.config, self.provider)
        self.submit_model(restarted)
        self.assertEqual(self.provider.generate.call_count, 1)

    def test_model_requires_exact_consent_and_digest(self):
        author = self.setup_author()
        for extra in ({"digest": "0" * 64}, {"approve_transmission": False}, {"approve_transmission": 1}, {"api_key": "never-accepted"}):
            payload = {**self.payload, "preview_id": self.preview["id"], "digest": self.preview["digest"], "approve_transmission": True, **extra}
            with self.assertRaises(ValueError):
                author.submit(payload)
        self.provider.generate.assert_not_called()
        self.assertEqual(author.calls(), [])

    def test_model_changed_context_rejects_before_send(self):
        author = self.setup_author()
        (self.roots[0] / self.preview["handoff_label"] / "AUTHORING.md").write_text("Changed")
        with self.assertRaises(ValueError):
            self.submit_model(author)
        self.provider.generate.assert_not_called()

    def test_model_budget_rejects_before_send(self):
        author = self.setup_author(budget_usd="0.000001")
        with self.assertRaisesRegex(ValueError, "budget"):
            self.submit_model(author)
        self.provider.generate.assert_not_called()
        self.assertEqual(author.calls(), [])

    def test_model_crash_reserves_and_blocks_new_calls(self):
        author = self.setup_author()
        self.wb.save("modelcall", {"id": self.preview["id"], "state": "sending", "reserved_usd": self.preview["estimate_usd"]})
        restarted = Authoring(self.wb, author.config, self.provider)
        self.assertEqual(restarted.state()["calls"][0]["state"], "uncertain")
        choice = self.wb.state()["choices"]["handoffs"][0]["id"]
        self.preview = restarted.preview({**self.payload, "handoff_id": choice})
        with self.assertRaisesRegex(ValueError, "uncertain"):
            self.submit_model(restarted)
        self.provider.generate.assert_not_called()

    def test_model_cancel_retains_reservation_no_proposal(self):
        author = self.setup_author()
        started, release = threading.Event(), threading.Event()
        result = self.provider.generate.return_value
        def generate(request, cancel):
            started.set()
            self.assertTrue(release.wait(5))
            return result
        self.provider.generate.side_effect = generate
        self.submit_model(author)
        self.assertTrue(started.wait(5))
        author.interrupt({**self.payload, "call_id": self.preview["id"]})
        release.set()
        row = self.wait_model(author)
        self.assertEqual(row["state"], "cancelled")
        self.assertIsNone(row["proposal_label"])
        self.assertEqual(row["reserved_usd"], self.preview["estimate_usd"])
        self.submit_model(author)
        self.assertEqual(self.provider.generate.call_count, 1)

    def test_model_bad_proposal_is_never_published(self):
        author = self.setup_author()
        self.provider.generate.return_value["proposal"]["source"][0]["name"] = "../policy.json"
        self.submit_model(author)
        row = self.wait_model(author)
        self.assertEqual(row["state"], "failed")
        self.assertIsNone(row["proposal_label"])
        self.assertFalse((self.roots[1] / ("model-" + self.preview["id"])).exists())

    def test_model_internal_errors_are_redacted(self):
        author = self.setup_author()
        self.provider.generate.side_effect = RuntimeError("secret-fixture-must-not-leak")
        self.submit_model(author)
        self.wait_model(author)
        self.assertNotIn("secret-fixture-must-not-leak", json.dumps(author.state()))
        self.assertNotIn("secret-fixture-must-not-leak", (self.wb.directory / ("modelcall-" + self.preview["id"] + ".json")).read_text())

    def test_money_rejects_bad_values(self):
        for value in (True, 1, "NaN", "Infinity", "-1", "0", "1e99999999", "1e-99999999", "1" * 25):
            with self.assertRaises(ValueError):
                money(value)


    def test_model_http_csrf_origin_and_unknown_fields(self):
        author = self.setup_author()
        server = self.start_server()
        def post(payload, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            conn.request("POST", "/api/workbench/model/submit", json.dumps(payload),
                         {"Content-Type": "application/json", "Origin": server.origin, **(headers or {})})
            response = conn.getresponse()
            status, body = response.status, response.read()
            conn.close()
            return status, body
        good = {**self.payload, "preview_id": self.preview["id"], "digest": self.preview["digest"], "approve_transmission": True}
        for headers in ({"Origin": "null"}, {"Origin": "http://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(post(good, headers)[0], 403)
        self.assertEqual(post({**good, "csrf_token": "wrong"})[0], 403)
        self.assertEqual(post({**good, "api_key": "must-not-be-accepted"})[0], 409)
        self.assertEqual(post(good, {"Content-Type": "text/plain"})[0], 409)
        self.provider.generate.assert_not_called()
        self.assertEqual(author.calls(), [])

    def test_model_changed_settings_require_new_preview(self):
        author = self.setup_author()
        changed = Authoring(self.wb, AuthorConfig("gpt-4.1", "1", "2", "100"), self.provider)
        with self.assertRaisesRegex(ValueError, "settings changed"):
            self.submit_model(changed)
        self.provider.generate.assert_not_called()

    def test_model_binary_context_is_rejected_not_omitted(self):
        from experimental_modeling.requirements import canonical_hash
        from experimental_modeling.request_contract import encoded, sha
        author = self.setup_author()
        handoff = self.roots[0] / self.preview["handoff_label"]
        target = handoff / "context/source/asset.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"\x89PNG\xff\x00")
        request = read_json(handoff / "request.json")
        request["context_files"]["context/source/asset.png"] = sha(target.read_bytes())
        del request["request_id"]
        request["request_id"] = canonical_hash(request)
        (handoff / "request.json").write_bytes(encoded(request))
        with self.assertRaisesRegex(ValueError, "text context only"):
            author.preview({**self.payload, "handoff_id": self.preview["handoff_id"]})
        self.provider.generate.assert_not_called()

    def test_model_failed_response_retains_usage_reservation(self):
        from experimental_modeling.model_provider import ProviderError
        author = self.setup_author()
        error = ProviderError("refusal")
        error.usage = {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 0}
        self.provider.generate.side_effect = error
        self.submit_model(author)
        row = self.wait_model(author)
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["usage"], error.usage)
        self.assertEqual(row["reserved_usd"], self.preview["estimate_usd"])

    def test_model_timeout_is_uncertain_and_does_not_retry(self):
        from experimental_modeling.model_provider import ProviderError
        author = self.setup_author()
        self.provider.generate.side_effect = ProviderError("timeout")
        self.submit_model(author)
        row = self.wait_model(author)
        self.assertEqual(row["state"], "uncertain")
        self.submit_model(author)
        self.assertEqual(self.provider.generate.call_count, 1)
        self.assertTrue(all(value is None for value in row["usage"].values()))
