"""The fixtures test coordination only. They are not AI or Blender evidence."""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from experimental_modeling import controller, requests
from experimental_modeling.project import initialize, atomic_json
from experimental_modeling.request_contract import (BINDING_FILE, BINDING_VERSION, encoded, legacy_request,
    read_json, runtime_identity, sha, source_manifest, validate_binding, validate_result_binding)
from experimental_modeling.requirements import canonical_hash
from experimental_modeling.review_server import ReviewProject, verified_revision
from experimental_modeling.runtime import RuntimeSelection

IMAGE = "sha256:" + "a" * 64
POLICY = {"schema_version": 1, "parts": ["body", "hook"], "changed_parts": ["body", "hook"], "constraints": [], "profile": "scene"}


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


class FakeSandbox:
    """No generated code is executed. Synthetic geometry is unit-test input."""
    blender = "/opt/blender/blender"
    security_boundary = "UNIT_TEST_ONLY"
    def __init__(self, binary):
        self.docker = str(binary)
        self.calls = []
        self.error = None
        self.observation = None
    def verify_runtime(self):
        return {}
    def run(self, stage, arguments, inputs, output, log):
        self.calls.append(stage)
        if self.error:
            raise RuntimeError(self.error)
        if stage == "author":
            params = read_json(inputs["params"])
            self.observation = {"parts": {name: {
                "world_vertices": [[0, 0, 0], [params.get(name, 1), 0, 0], [0, 1, 0]],
                "triangle_indices": [[0, 1, 2]], "face_indices": [[0, 1, 2]],
                "edge_indices": [[0, 1], [1, 2], [2, 0]],
                "geometry_hash": name + str(params.get(name, 1)), "transform_hash": "t", "material_hash": "m"
            } for name in ("body", "hook")}}
            (output / "scene.blend").write_bytes(b"unit fixture, not Blender")
        elif stage == "inspect":
            put(output / "observation.json", self.observation)
            (output / "scene.blend").write_bytes(b"unit fixture, not Blender")
            (output / "model.glb").write_bytes(b"unit fixture, not GLB")
        else:
            put(output / "check.json", {"passed": True})
        return {"exit_code": 0}


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = initialize(self.root / "Project 雪")
        self.brief = self.root / "brief.txt"
        self.brief.write_text("Create an asymmetric wall hook.\nKeep its base flat.\n", encoding="utf-8")
        self.handoff = self.root / "handoff"
        self.proposal = self.root / "proposal"
        (self.proposal / "source").mkdir(parents=True)
        (self.proposal / "source/builder.py").write_text("# Unit test only. Never execute.\n")
        put(self.proposal / "params.json", {})
        self.policy = self.root / "policy.json"
        put(self.policy, POLICY)
        self.binary = self.root / "docker-unit-fixture"
        self.binary.write_text("not executable code")
        self.binary.chmod(0o700)
        self.socket_path = self.root / "docker.sock"
        self.socket_path.write_text("synthetic socket identity; not a socket")
        self.selection = RuntimeSelection(docker=self.binary, socket=self.socket_path, image=IMAGE)
        self.backend = FakeSandbox(self.binary)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch("experimental_modeling.requests.platform.system", return_value="Linux"))
        self.patches.enter_context(patch("experimental_modeling.requests.platform.machine", return_value="x86_64"))
        self.patches.enter_context(patch("experimental_modeling.launcher.doctor", return_value={"build_prerequisites_ready": True}))
        self.patches.enter_context(patch("experimental_modeling.sandbox.DockerSandbox", return_value=self.backend))
        def fixture_runtime(docker, socket_path, image):
            return {"mode": "docker-isolated", "image": image, "docker_sha256": sha(Path(docker).read_bytes()),
                    "docker_path_sha256": sha(str(docker).encode()), "socket_path_sha256": sha(str(socket_path).encode()),
                    "socket_device": 1, "socket_inode": 2}
        self.patches.enter_context(patch("experimental_modeling.requests.runtime_identity", side_effect=fixture_runtime))
        self.patches.enter_context(patch("experimental_modeling.request_contract.runtime_identity", side_effect=fixture_runtime))
    def prepare(self, **kwargs):
        return requests.prepare(self.project, self.handoff, brief_file=self.brief, **kwargs)
    def inspect(self, **kwargs):
        return requests.inspect_proposal(self.project, self.handoff, self.proposal, self.policy, self.selection, **kwargs)
    def execute(self, revision="r0", expected=None, **kwargs):
        if expected is None:
            expected = self.inspect(requirements_path=kwargs.get("requirements_path"))[0]["inspection_digest"]
        return requests.run_proposal(self.project, self.handoff, self.proposal, self.policy, self.selection,
            expected_digest=expected, revision=revision, **kwargs)
    def queue(self, revision, prompt="Change only the hook."):
        review = ReviewProject(self.project.folder("evidence"))
        response = review.revision(revision)
        return review.request({"csrf_token": review.token, "revision_id": revision,
            "expected_result_hash": response["revision"]["result_hash"], "prompt": prompt})["request_id"]
    def edit(self, revision="r0", prompt="Change only the hook."):
        request_id = self.queue(revision, prompt)
        self.handoff = self.root / ("handoff-" + revision)
        requests.prepare(self.project, self.handoff, request_id=request_id)
        put(self.policy, POLICY | {"changed_parts": ["hook"]})
        return request_id

    def test_prepare_and_inspect_preserve_unicode_prompt_without_execution(self):
        prompt = "😀" * 7997 + "\n \n"
        self.brief.write_text(prompt, encoding="utf-8")
        with patch("subprocess.Popen", side_effect=AssertionError("spawn")):
            prepared = self.prepare()
            summary, request, *_ = self.inspect()
        self.assertEqual(request["prompt"], prompt)
        self.assertEqual(prepared["request_id"], request["request_id"])
        self.assertEqual(summary["execution"], "not_started")
        self.assertFalse(self.backend.calls)
        self.assertFalse(list(self.project.folder("accepted").iterdir()))
        self.assertEqual({p.name for p in self.project.folder("source").iterdir()}, {"assets"})

    def test_handoff_no_clobber_overlap_and_partial_manifest(self):
        self.prepare()
        before = (self.handoff / "request.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.prepare()
        self.assertEqual((self.handoff / "request.json").read_bytes(), before)
        for output in (self.project.root / "handoff", self.project.folder("source"), self.root):
            with self.subTest(output=output), self.assertRaises(ValueError):
                requests.prepare(self.project, output, brief_file=self.brief)
        output = self.root / "incomplete"
        with patch("experimental_modeling.requests.atomic_json", side_effect=OSError("write interrupted")):
            with self.assertRaises(OSError):
                requests.prepare(self.project, output, brief_file=self.brief)
        self.assertFalse((output / "request.json").exists())
        with self.assertRaises(OSError):
            requests.load_handoff(self.project, output)

    def test_changed_handoff_duplicate_json_and_unknown_files_rejected(self):
        self.prepare()
        path = self.handoff / "AUTHORING.md"
        path.write_text("changed")
        with self.assertRaisesRegex(ValueError, "context changed"):
            self.inspect()
        path.write_text(requests.AUTHORING)
        (self.handoff / "extra.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "unknown file"):
            self.inspect()
        (self.handoff / "extra.txt").unlink()
        (self.proposal / "params.json").write_text('{"x": 1, "x": 2}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.inspect()

    def test_source_links_config_and_budget_rejected(self):
        self.prepare()
        for filename in ("CLAUDE.md", "AGENTS.md", ".env", "setup.sh"):
            path = self.proposal / "source" / filename
            path.write_text("untrusted")
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.inspect()
            path.unlink()
        link = self.proposal / "source/link.py"
        link.symlink_to(self.proposal / "source/builder.py")
        with self.assertRaises(ValueError): self.inspect()
        link.unlink()
        os.link(self.proposal / "source/builder.py", link)
        with self.assertRaisesRegex(ValueError, "hard links"): self.inspect()
        link.unlink()
        with patch("experimental_modeling.request_contract.MAX_SOURCE", 3):
            with self.assertRaises(ValueError): self.inspect()

    def test_initial_run_binds_full_request_before_promotion_and_keeps_source(self):
        self.prepare()
        expected = self.inspect()[0]["inspection_digest"]
        before = {p.relative_to(self.project.root).as_posix(): p.read_bytes() for p in self.project.folder("source").rglob("*") if p.is_file()}
        original_promote = controller.promote
        def checked_promote(attempt, store, revision):
            result = read_json(attempt / "result.json")
            self.assertIsNotNone(validate_result_binding(attempt, result))
            return original_promote(attempt, store, revision)
        with patch("experimental_modeling.controller.promote", side_effect=checked_promote):
            result = self.execute(expected=expected)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.backend.calls, ["author", "inspect", "roundtrip", "reopen"])
        directory, saved, _ = verified_revision(self.project.folder("evidence"), "r0")
        binding = validate_result_binding(directory, saved)
        self.assertEqual(binding["request"]["prompt"], self.brief.read_text())
        self.assertEqual(binding["inspection_digest"], expected)
        self.assertNotEqual(saved["intent"], self.brief.read_text())
        self.assertEqual(saved["artifacts"][BINDING_FILE], saved["request_binding_hash"])
        self.assertEqual(before, {p.relative_to(self.project.root).as_posix(): p.read_bytes() for p in self.project.folder("source").rglob("*") if p.is_file()})
        self.assertFalse(list(self.project.root.glob(".request-proposal-*")))
        self.assertFalse((self.project.folder("evidence") / "requirements.json").exists())

    def test_replay_after_promotion_never_reexecutes_or_clears_recovery(self):
        self.prepare()
        expected = self.inspect()[0]["inspection_digest"]
        first = self.execute(expected=expected)
        calls = list(self.backend.calls)
        marker = self.project.root / ".launcher-build.json"
        atomic_json(marker, {"schema_version": 1, "status": "recovery_required", "revision": "r0"})
        before = marker.read_bytes()
        self.assertEqual(self.execute(expected=expected), first)
        self.assertEqual(self.backend.calls, calls)
        self.assertEqual(marker.read_bytes(), before)

    def test_digest_changes_with_source_policy_params_and_runtime(self):
        self.prepare()
        expected = self.inspect()[0]["inspection_digest"]
        for target, data in ((self.proposal / "source/builder.py", b"# changed\n"), (self.proposal / "params.json", encoded({"hook": 2})),
                             (self.policy, encoded(POLICY | {"changed_parts": []})), (self.binary, b"changed runtime")):
            original = target.read_bytes()
            target.write_bytes(data)
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "changed"):
                self.execute(expected=expected)
            target.write_bytes(original)
        self.assertFalse(self.backend.calls)

    def test_new_execution_fails_on_stale_parent_but_replay_is_valid(self):
        self.prepare(); expected = self.inspect()[0]["inspection_digest"]
        self.execute(expected=expected)
        with self.assertRaisesRegex(ValueError, "accepted parent changed"):
            self.execute(revision="another", expected=expected)
        self.assertEqual(len(self.backend.calls), 4)

    def test_edit_rejection_repair_and_status_overlay(self):
        self.prepare(); self.execute()
        original_request = self.edit()
        old_record = self.project.folder("evidence") / "review/requests" / (original_request + ".json")
        before_record = old_record.read_bytes()
        put(self.proposal / "params.json", {"body": 2, "hook": 2})
        before_pointer = (self.project.folder("evidence") / "last_good.json").read_bytes()
        result = self.execute("bad")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual((self.project.folder("evidence") / "last_good.json").read_bytes(), before_pointer)
        self.assertEqual(old_record.read_bytes(), before_record)
        self.edit("bad", "Repair the body. Keep the new hook.")
        summary = self.inspect()[0]
        self.assertEqual(summary["reference"]["revision"], "bad")
        self.assertEqual(summary["execution_parent"]["revision"], "r0")
        put(self.proposal / "params.json", {"hook": 2})
        self.assertEqual(self.execute("repair")["status"], "accepted")
        review = ReviewProject(self.project.folder("evidence"))
        outcomes = [r["outcome"] for req in review.requests() for r in req.get("results", [])]
        self.assertIn("checks_rejected", outcomes)
        self.assertIn("machine_accepted", outcomes)
        self.assertFalse(any(r["human_accepted"] for req in review.requests() for r in req.get("results", [])))

    def test_malformed_legacy_id_and_wrong_filename_rejected(self):
        self.prepare(); self.execute(); key = self.queue("r0")
        path = self.project.folder("evidence") / "review/requests" / (key + ".json")
        value = read_json(path); value["prompt"] += " changed"
        put(path, value)
        with self.assertRaisesRegex(ValueError, "full content"):
            requests.prepare(self.project, self.root / "edit", request_id=key)

    def test_source_mutation_during_import_stops_before_execution(self):
        self.prepare(); expected = self.inspect()[0]["inspection_digest"]
        real = requests.source_manifest
        def changed(root, **kwargs):
            if kwargs.get("copy_to") is not None:
                (root / "builder.py").write_text("# changed after inspection")
            return real(root, **kwargs)
        with patch("experimental_modeling.requests.source_manifest", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "source changed"):
                self.execute(expected=expected)
        self.assertFalse(self.backend.calls)
        self.assertFalse(list(self.project.root.glob(".request-proposal-*")))

    def test_execution_failure_and_explicit_new_revision_retry(self):
        self.prepare(); expected = self.inspect()[0]["inspection_digest"]
        self.backend.error = "unit cleanup failed"
        result = self.execute(expected=expected)
        self.assertEqual(result["status"], "needs_review")
        review = ReviewProject(self.project.folder("evidence"))
        self.assertEqual(review.requests()[0]["results"][0]["outcome"], "execution_failed")
        self.backend.error = None
        with self.assertRaisesRegex(RuntimeError, "Build recovery is necessary"):
            self.execute("retry", expected=expected)
        self.assertEqual(self.execute("retry", expected=expected, acknowledge_interrupted=True)["status"], "accepted")
        self.assertTrue((self.project.folder("candidates") / "r0/result.json").exists())

    def test_interruption_keeps_marker_and_stops_reentry(self):
        self.prepare(); expected = self.inspect()[0]["inspection_digest"]
        with patch.object(self.backend, "run", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.execute(expected=expected)
        marker = read_json(self.project.root / ".launcher-build.json")
        self.assertEqual(marker["status"], "running")
        self.assertFalse(list(self.project.root.glob(".request-proposal-*")))
        with self.assertRaisesRegex(RuntimeError, "Build recovery is necessary"):
            self.execute("retry", expected=expected)

    def test_bad_initial_rules_binding_does_not_initialize_rules_or_history(self):
        self.prepare()
        values = self.inspect()
        _, request, approval, *_ = values
        approval = copy.deepcopy(approval); approval["requirements_hash"] = "b" * 64
        binding = {"schema_version": BINDING_VERSION, "revision": "r0", "request": request,
                   "approval": approval, "inspection_digest": canonical_hash(approval)}
        rules = self.root / "rules.json"; put(rules, {"schema_version": 1, "requirements": []})
        with self.assertRaisesRegex(ValueError, "requirements differ"):
            controller.build(source=self.proposal / "source", params=self.proposal / "params.json", policy_path=self.policy,
                store=self.project.folder("evidence"), revision="r0", sandbox_image=IMAGE,
                docker_executable=self.binary, docker_socket=self.socket_path, requirements_path=rules, request_binding=binding)
        self.assertFalse((self.project.folder("evidence") / "requirements.json").exists())
        self.assertFalse(list(self.project.folder("candidates").iterdir()))
        self.assertFalse(self.backend.calls)

    def test_binding_tamper_and_partial_binding_fail_even_with_rehashed_artifacts(self):
        self.prepare(); self.execute()
        directory = self.project.folder("accepted") / "r0"
        original_binding = (directory / BINDING_FILE).read_bytes()
        original_result = read_json(directory / "result.json")
        original_pointer = (self.project.folder("evidence") / "last_good.json").read_bytes()
        def replace_result(result):
            put(directory / "result.json", result)
            put(self.project.folder("evidence") / "last_good.json", {"revision": "r0", "result_hash": controller.digest(directory / "result.json")})
        for mutation in ("wrong_source", "wrong_params", "wrong_parent", "missing_marker"):
            result = copy.deepcopy(original_result)
            binding = json.loads(original_binding)
            if mutation == "missing_marker":
                del result["request_binding_hash"]
            else:
                if mutation == "wrong_source": binding["approval"]["source_files"]["builder.py"] = "f" * 64
                elif mutation == "wrong_params": binding["approval"]["params_hash"] = "f" * 64
                else:
                    binding["request"]["parent"] = {"revision": "other", "result_hash": "f" * 64}
                binding["inspection_digest"] = canonical_hash(binding["approval"])
                put(directory / BINDING_FILE, binding)
                result["artifacts"][BINDING_FILE] = controller.digest(directory / BINDING_FILE)
                result["request_binding_hash"] = result["artifacts"][BINDING_FILE]
            replace_result(result)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verified_revision(self.project.folder("evidence"), "r0")
            (directory / BINDING_FILE).write_bytes(original_binding)
        put(directory / "result.json", original_result)
        (self.project.folder("evidence") / "last_good.json").write_bytes(original_pointer)
        self.assertTrue(ReviewProject(self.project.folder("evidence")).revision("r0")["report"]["machine_verified"])

    def test_native_and_unsupported_platform_never_execute(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "Native execution"):
            requests.inspect_proposal(self.project, self.handoff, self.proposal, self.policy, RuntimeSelection(mode="trusted-native", blender=self.binary))
        with patch("experimental_modeling.requests.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(RuntimeError, "Linux x64"):
                self.inspect()
        self.assertFalse(self.backend.calls)

    def test_pointer_symlink_is_not_treated_as_initial_project(self):
        (self.project.folder("evidence") / "last_good.json").symlink_to(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO fixture")
    def test_fifo_and_device_inputs_fail_without_reading(self):
        import time
        from experimental_modeling.request_contract import read_bytes
        fifo = self.root / "input.fifo"
        os.mkfifo(fifo)
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, "regular file"):
            read_bytes(fifo, 100)
        self.assertLess(time.monotonic() - started, 2)
        with self.assertRaisesRegex(ValueError, "regular file"):
            read_bytes(Path("/dev/null"), 100)

    def test_empty_directory_and_path_limits_apply_to_enumeration(self):
        self.prepare()
        for index in range(129):
            (self.proposal / "source" / ("empty" + str(index))).mkdir()
        with self.assertRaisesRegex(ValueError, "directory count"):
            self.inspect()
        for path in (self.proposal / "source").glob("empty*"):
            path.rmdir()
        path = self.proposal / "source"
        for _ in range(17):
            path = path / "deep"
            path.mkdir()
        with self.assertRaisesRegex(ValueError, "depth limit"):
            self.inspect()

    def test_unknown_proposal_root_and_inspection_details(self):
        self.prepare()
        (self.proposal / "setup.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "only source"):
            self.inspect()
        (self.proposal / "setup.json").unlink()
        put(self.proposal / "params.json", {"hook": 2})
        summary = self.inspect()[0]
        self.assertEqual(summary["parameter_changes"]["fields"][0]["after"], 2)
        self.assertEqual(summary["reviewed_policy"]["path"], str(self.policy))
        self.assertIn("constraints", summary["reviewed_policy"])
        self.assertIn("definitions", summary["reviewed_requirements"])
        self.assertFalse(self.backend.calls)

    def test_dangling_binding_link_is_not_legacy_absence(self):
        directory = self.root / "legacy"
        directory.mkdir()
        (directory / BINDING_FILE).symlink_to(self.root / "missing-binding")
        with self.assertRaisesRegex(ValueError, "symlink"):
            validate_result_binding(directory, {"artifacts": {}})

    def test_real_runtime_identity_rejects_regular_socket_file(self):
        with self.assertRaisesRegex(ValueError, "Unix socket"):
            runtime_identity(self.binary, self.socket_path, IMAGE)

    def test_repair_reference_is_checked_again_under_controller_lock(self):
        self.prepare(); self.execute(); self.edit()
        put(self.proposal / "params.json", {"body": 2})
        self.assertEqual(self.execute("bad")["status"], "rejected")
        self.edit("bad", "Repair the rejected body change.")
        put(self.proposal / "params.json", {})
        _, request, approval, *_ = self.inspect()
        binding = {"schema_version": BINDING_VERSION, "revision": "repair", "request": request,
                   "approval": approval, "inspection_digest": canonical_hash(approval)}
        result_path = self.project.folder("candidates") / "bad/result.json"
        with result_path.open("a") as stream:
            stream.write(" ")
        before = list(self.backend.calls)
        with self.assertRaisesRegex(ValueError, "reference result changed"):
            controller.build(source=self.proposal / "source", params=self.proposal / "params.json", policy_path=self.policy,
                store=self.project.folder("evidence"), revision="repair", parent="r0", sandbox_image=IMAGE,
                docker_executable=self.binary, docker_socket=self.socket_path, request_binding=binding)
        self.assertEqual(self.backend.calls, before)
        self.assertFalse((self.project.folder("candidates") / "repair").exists())

    def test_queue_window_keeps_latest_times_instead_of_hash_order(self):
        self.prepare(); self.execute()
        review = ReviewProject(self.project.folder("evidence"))
        for index in range(60):
            with patch("experimental_modeling.review_server.now", return_value=f"2026-10-01T00:{index:02d}:00+00:00"):
                self.queue("r0", f"Recorded request {index:02d}")
        paths = list((self.project.folder("evidence") / "review/requests").glob("*.json"))
        hash_order = [read_json(path)["prompt"] for path in sorted(paths)]
        chronological = [f"Recorded request {index:02d}" for index in range(60)]
        self.assertNotEqual(hash_order, chronological)
        rows = review.requests()
        self.assertEqual([row["prompt"] for row in rows], chronological[-50:])
        # Without truncation, timestamp-free initial evidence precedes its edits.
        for path in paths[1:]:
            path.unlink()
        rows = review.requests()
        self.assertIsNone(rows[0]["revision_id"])
        self.assertEqual(rows[0]["results"][0]["revision_id"], "r0")
        self.assertEqual(rows[1]["revision_id"], "r0")


if __name__ == "__main__":
    unittest.main()
