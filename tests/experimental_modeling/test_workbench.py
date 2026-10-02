"""Workbench tests use inert fixtures; they do not claim Blender verification."""
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from experimental_modeling import workbench
from experimental_modeling.project import initialize
from experimental_modeling.request_contract import encoded, read_json
from experimental_modeling.runtime import RuntimeSelection


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = initialize(self.root / "project")
        self.roots = [self.root / name for name in ("handoffs", "proposals", "rules")]
        for root in self.roots:
            root.mkdir()
        docker = self.root / "docker"
        docker.write_text("#!/bin/sh\nexit 3\n")
        docker.chmod(0o700)
        (self.root / "docker.sock").write_text("inert socket fixture")
        def fixture_runtime(docker, socket_path, image):
            from experimental_modeling.request_contract import sha
            return {"mode": "docker-isolated", "image": image, "docker_sha256": sha(Path(docker).read_bytes()),
                    "docker_path_sha256": sha(str(docker).encode()), "socket_path_sha256": sha(str(socket_path).encode()),
                    "socket_device": 1, "socket_inode": 2}
        for target in ("experimental_modeling.workbench.runtime_identity", "experimental_modeling.requests.runtime_identity"):
            patcher = patch(target, side_effect=fixture_runtime)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.selection = RuntimeSelection(docker=docker, socket=self.root / "docker.sock", image="sha256:" + "a" * 64)
        self.wb = self.create()
        self.payload = {"csrf_token": self.wb.token}
        self.proposal = self.roots[1] / "proposal"
        (self.proposal / "source").mkdir(parents=True)
        (self.proposal / "source/builder.py").write_text("# <script>alert('inert')</script>\n")
        (self.proposal / "params.json").write_bytes(encoded({"length": 1}))
        self.policy = self.roots[2] / "policy.json"
        self.policy.write_bytes(encoded({"schema_version": 1, "parts": ["body"], "changed_parts": ["body"], "constraints": [], "profile": "scene"}))

    def create(self):
        return workbench.Workbench(self.project, self.selection, *self.roots, Path(sys.executable).resolve())

    def inspect(self):
        self.wb.prepare({**self.payload, "brief": "Create a model.\nKeep all details. 雪"})
        choices = self.wb.state()["choices"]
        return self.wb.inspect({**self.payload, "handoff_id": choices["handoffs"][0]["id"],
                               "proposal_id": choices["proposals"][0]["id"], "policy_id": choices["rules"][0]["id"], "requirements_id": None})

    def test_complete_inspection_and_stable_revision(self):
        snapshot = self.inspect()
        self.assertEqual(snapshot["revision"], "wb-" + snapshot["id"])
        self.assertEqual(snapshot["inputs"]["parameters"], {"length": 1})
        self.assertIn("<script>", snapshot["inputs"]["source"][0]["text"])
        self.assertEqual(snapshot["inputs"]["policy"], read_json(self.policy))
        self.assertEqual(snapshot, self.wb.record("inspection", snapshot["id"]))
        self.assertFalse((self.project.root / "source/builder.py").exists())

    def test_stale_input_consumes_once_without_spawn(self):
        snapshot = self.inspect()
        (self.proposal / "params.json").write_bytes(encoded({"length": 2}))
        with patch.object(workbench.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "Inputs changed"):
                self.wb.run(snapshot["id"])
            again = self.wb.run(snapshot["id"])
            self.assertEqual(again["state"], "failed_before_execution")
            spawn.assert_not_called()

    def test_spawn_failure_is_consumed_and_restart_never_retries(self):
        snapshot = self.inspect()
        with patch.object(workbench.subprocess, "Popen", side_effect=OSError("fixture launch failure")) as spawn:
            with self.assertRaises(OSError):
                self.wb.run(snapshot["id"])
            self.assertEqual(self.wb.run(snapshot["id"])["state"], "failed_before_execution")
            self.assertEqual(self.create().run(snapshot["id"])["state"], "failed_before_execution")
            self.assertEqual(spawn.call_count, 1)

    def test_durable_claim_blocks_restart_and_new_inspections(self):
        snapshot = self.inspect()
        record = {"id": snapshot["id"], "revision": snapshot["revision"], "inspection_digest": snapshot["inspection_digest"], "state": "claimed", "detail": "fixture crash"}
        self.wb.save("operation", record)
        restarted = self.create()
        with patch.object(workbench.subprocess, "Popen") as spawn:
            self.assertEqual(restarted.run(snapshot["id"])["state"], "uncertain")
            other = self.inspect()
            with self.assertRaisesRegex(ValueError, "active or uncertain"):
                restarted.run(other["id"])
            spawn.assert_not_called()
        self.assertEqual(read_json(self.wb.directory / ("operation-" + snapshot["id"] + ".json")), record)

    def test_duplicate_concurrent_permission_spawns_once_fixed_argv(self):
        snapshot = self.inspect()
        process = Mock()
        process.stdout = io.BytesIO(b"deliberate fixture failure")
        process.wait.return_value = 2
        process.poll.return_value = None
        results = []
        with patch.object(workbench.subprocess, "Popen", return_value=process) as spawn:
            threads = [threading.Thread(target=lambda: results.append(self.wb.run(snapshot["id"]))) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.wb.monitor.join()
            self.assertEqual(len(results), 4)
            self.assertEqual(spawn.call_count, 1)
            args, options = spawn.call_args
            self.assertEqual(args[0][1], "-I")
            self.assertFalse(options["shell"])
            self.assertNotIn("PYTHONPATH", options["env"])
            self.assertIn(snapshot["inspection_digest"], args[0])
            self.assertIn(snapshot["revision"], args[0])

    def test_post_spawn_monitor_failure_signals_and_reaps(self):
        snapshot = self.inspect()
        process = Mock()
        process.stdout = io.BytesIO(b"interrupted fixture")
        process.poll.return_value = None
        process.wait.return_value = 130
        with patch.object(workbench.subprocess, "Popen", return_value=process), patch.object(workbench.threading.Thread, "start", side_effect=RuntimeError("fixture thread failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture thread failure"):
                self.wb.run(snapshot["id"])
        process.send_signal.assert_called_once()
        process.wait.assert_called_once()
        self.assertTrue(process.stdout.closed)
        self.assertEqual(self.wb.operation(snapshot["id"])["state"], "interrupted")
        process.poll.return_value = 130
        self.wb.close()

    def test_post_spawn_journal_failure_still_reaps(self):
        snapshot = self.inspect()
        process = Mock()
        process.stdout = io.BytesIO(b"stopped fixture")
        process.poll.return_value = None
        process.wait.return_value = 130
        original = self.wb.save
        def save(kind, value, **kwargs):
            if kind == "operation" and value["state"] == "running":
                raise OSError("fixture journal failure")
            return original(kind, value, **kwargs)
        with patch.object(workbench.subprocess, "Popen", return_value=process), patch.object(self.wb, "save", side_effect=save):
            with self.assertRaisesRegex(OSError, "fixture journal failure"):
                self.wb.run(snapshot["id"])
            self.wb.monitor.join()
        process.send_signal.assert_called_once()
        process.wait.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_close_does_not_depend_on_journal(self):
        process = Mock()
        process.poll.return_value = None
        process.stdout = io.BytesIO()
        self.wb.child = process
        self.wb.child_id = "a" * 32
        with patch.object(self.wb, "record", side_effect=OSError("damaged journal")), patch.object(self.wb, "save", side_effect=OSError("disk full")):
            self.wb.close()
        process.send_signal.assert_called_once()
        process.wait.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_repeated_interrupt_then_close_signals_only_once(self):
        snapshot = self.inspect()
        record = {"id": snapshot["id"], "revision": snapshot["revision"], "inspection_digest": snapshot["inspection_digest"], "state": "running", "detail": "fixture"}
        self.wb.save("operation", record)
        process = Mock()
        process.poll.return_value = None
        process.stdout = io.BytesIO()
        self.wb.child = process
        self.wb.child_id = snapshot["id"]
        self.wb.interrupt(snapshot["id"])
        self.wb.interrupt(snapshot["id"])
        self.wb.close()
        process.send_signal.assert_called_once()
        process.wait.assert_called_once()

    def test_pipe_failure_still_signals_and_reaps(self):
        process = Mock()
        process.poll.return_value = None
        process.stdout.read.side_effect = OSError("fixture pipe failure")
        process.wait.return_value = 130
        record = {"id": "a" * 32, "revision": "wb-a", "inspection_digest": "b" * 64, "state": "claimed", "detail": "fixture"}
        with patch.object(self.wb, "save", side_effect=OSError("disk full")):
            self.wb.watch(process, record)
        process.send_signal.assert_called_once()
        process.wait.assert_called_once()
        process.stdout.close.assert_called_once()

    def test_handoff_capacity_checked_before_writes(self):
        for number in range(128):
            (self.roots[0] / str(number)).mkdir()
        with self.assertRaisesRegex(ValueError, "limit reached"):
            self.wb.prepare({**self.payload, "brief": "A model"})
        self.assertEqual(len(list(self.roots[0].iterdir())), 128)
        self.assertEqual(list(self.wb.directory.glob("brief-*.txt")), [])

    def test_full_rules_not_abbreviated(self):
        rules = read_json(self.policy)
        # Many declared parts and parameters exceed the bridge summary cutoffs.
        rules["parts"] = ["part" + str(i) for i in range(40)]
        rules["changed_parts"] = list(rules["parts"])
        self.policy.write_bytes(encoded(rules))
        params = {"field" + str(i): "value" * 200 for i in range(40)}
        (self.proposal / "params.json").write_bytes(encoded(params))
        snapshot = self.inspect()
        self.assertEqual(snapshot["inputs"]["policy"], rules)
        self.assertEqual(snapshot["inputs"]["parameters"], params)
        self.assertEqual(snapshot["summary"]["parameter_changes"]["omitted_fields"], 8)

    def test_runtime_or_root_changed_rejected(self):
        self.selection.docker.write_text("changed")
        with self.assertRaisesRegex(ValueError, "startup input"):
            self.wb.state()

    def test_opaque_selection_cannot_be_path(self):
        self.inspect()
        with self.assertRaises(ValueError):
            self.wb.selected("../../etc/passwd", "rules")
        choices = self.wb.state()["choices"]
        with self.assertRaises(ValueError):
            self.wb.selected(choices["rules"][0]["id"], "proposals")

    def test_links_and_special_files_rejected(self):
        link = self.roots[2] / "linked.json"
        os.link(self.policy, link)
        with self.assertRaisesRegex(ValueError, "regular JSON"):
            self.wb.state()
        link.unlink()
        link.symlink_to(self.policy)
        with self.assertRaises(ValueError):
            self.wb.state()
        link.unlink()
        os.mkfifo(link)
        with self.assertRaises(ValueError):
            self.wb.state()

    def test_proposal_hardlink_rejected_before_inspection(self):
        os.link(self.proposal / "source/builder.py", self.root / "copy.py")
        with self.assertRaisesRegex(ValueError, "hard links"):
            self.inspect()

    def test_overlapping_roots_rejected(self):
        with self.assertRaises(ValueError):
            workbench.Workbench(self.project, self.selection, self.roots[0], self.roots[0], self.roots[2], Path(sys.executable).resolve())

    def start_server(self):
        try:
            server = workbench.WorkbenchServer(self.wb)
        except PermissionError:
            self.skipTest("Local socket creation is prohibited by this executor; live HTTP boundary runs in CI.")
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), thread.join(), server.server_close()))
        return server

    def test_http_boundary_and_strict_json(self):
        server = self.start_server()
        def call(body, headers=None, path="/api/workbench/prepare", method="POST"):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            conn.request(method, path, body, {"Content-Type": "application/json", "Origin": server.origin, **(headers or {})})
            response = conn.getresponse()
            data = response.read()
            conn.close()
            return response.status, data, dict(response.headers)
        good = json.dumps({**self.payload, "brief": "A model"})
        for headers in ({"Origin": "null"}, {"Origin": "http://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(call(good, headers)[0], 403)
        self.assertEqual(call('{"csrf_token":"wrong","brief":"A"}')[0], 403)
        self.assertEqual(call('{"csrf_token":"a","csrf_token":"b"}')[0], 409)
        self.assertEqual(call(good, {"Content-Type": "text/plain"})[0], 409)
        self.assertEqual(call('x' * 65537)[0], 409)
        self.assertEqual(call(good, path="/api/workbench/../prepare")[0], 409)
        status, body, headers = call(None, method="GET", path="/api/workbench")
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.putrequest("GET", "/api/workbench")
        conn.putheader("Host", f"127.0.0.1:{server.server_port}")
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        conn.close()


if __name__ == "__main__":
    unittest.main()
