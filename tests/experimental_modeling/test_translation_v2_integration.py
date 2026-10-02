"""Offline integration tests for version-bound review and controller routing.

All author/Blender execution is replaced with a synthetic Docker backend. These
exercise real policy parsing, controller filesystem transitions, requirements
locks, saved-report validation, and ReviewProject.revision. They are not evidence
of actual Docker isolation, Blender execution, or artifact rendering fidelity.
"""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from experimental_modeling.contracts import Policy
from experimental_modeling.controller import build, digest, write_json
from experimental_modeling.requirements import RequirementSet, canonical_hash
from experimental_modeling.review_server import ReviewProject
from experimental_modeling.verification import make_report

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name("fixtures")
GOLDEN = json.loads((FIXTURES / "translated_golden.json").read_text())
IMAGE = "sha256:" + "a" * 64
ALL = [[None, None], [None, None], [None, None]]
LOCKED_RULES = {"schema_version": 1, "requirements": [{
    "id": "connected-body", "title": "Keep the body connected", "kind": "connected_path",
    "hard": True, "phase": "always", "params": {
        "part": "body", "region": ALL, "from": ALL, "to": ALL}}]}


def raw_policy(version=2, translated=False):
    policy = {"schema_version": version, "parts": ["body"], "changed_parts": ["body"],
              "constraints": [], "profile": "scene"}
    if translated:
        data = {"delta": [.25, -.5, .125], "tolerance": 0.}
        if version == 2:
            data["normal_tolerance_radians"] = 0.
        policy["constraints"] = [{"kind": "translated", "part": "body", "data": data}]
    return policy


def observed(version=2, translated=False):
    observation = copy.deepcopy(GOLDEN["models"]["tetrahedron"]["previous"])
    observation["schema_version"] = version
    if translated:
        p = observation["parts"]["body"]
        delta = [.25, -.5, .125]
        p["world_vertices"] = [[x + d for x, d in zip(vertex, delta)] for vertex in p["world_vertices"]]
        for i, d in enumerate(delta):
            p["matrix_world"][i][3] += d
        p["transform_hash"] = canonical_hash(p["matrix_world"])
        p["world_bounds"] = {key: [x + d for x, d in zip(values, delta)]
                             for key, values in p["world_bounds"].items()}
    if version == 1:
        del observation["parts"]["body"]["face_material_indices"]
        del observation["parts"]["body"]["face_world_corner_normals"]
    return observation


def replace_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def saved_revision(store, version=2, revision="r0", parent=None, status="accepted"):
    """Build a synthetic hash-bound history without running any author code."""
    directory = store / ("accepted" if status == "accepted" else "attempts") / revision
    directory.mkdir(parents=True)
    (directory / "inspection").mkdir()
    policy = raw_policy(version, translated=parent is not None)
    observation = observed(version, translated=parent is not None)
    spec = {"schema_version": 1, "requirements": []}
    write_json(directory / "policy.json", policy)
    write_json(directory / "requirements.json", spec)
    write_json(directory / "inspection/observation.json", observation)
    if not (store / "requirements.json").exists():
        write_json(store / "requirements.json", spec)
    previous = (json.loads((store / "accepted" / parent / "inspection/observation.json").read_text())
                if parent else None)
    result = {"schema_version": 1, "revision": revision, "parent": parent,
              "parent_result_hash": digest(store / "accepted" / parent / "result.json") if parent else None,
              "status": status, "jobs": {name: {"exit_code": 0} for name in
                       ("author", "inspect", "roundtrip", "reopen")},
              "provenance_verified": True, "source_files": {}, "controller_files": {},
              "requirements_hash": canonical_hash(spec), "requirements_lock_hash": canonical_hash(spec),
              "policy_hash": digest(directory / "policy.json"), "runtime_hash": "synthetic-no-execution",
              "execution_mode": "synthetic-offline", "security_boundary": "not-a-model-execution",
              "failures": []}
    report = make_report(result, Policy.parse(policy), observation, previous, RequirementSet.parse(spec))
    write_json(directory / "verification.json", report)
    result["artifacts"] = {p.relative_to(directory).as_posix(): digest(p)
                           for p in directory.rglob("*") if p.is_file()}
    write_json(directory / "result.json", result)
    if status == "accepted":
        replace_json(store / "last_good.json", {"revision": revision, "result_hash": digest(directory / "result.json")})
    return directory


def reseal(store, directory):
    """Rebind synthetic manifest to distinguish semantic checks from byte checks."""
    result = json.loads((directory / "result.json").read_text())
    result["artifacts"] = {p.relative_to(directory).as_posix(): digest(p)
                           for p in directory.rglob("*") if p.is_file() and p.name != "result.json"}
    replace_json(directory / "result.json", result)
    pointer = store / "last_good.json"
    if pointer.exists() and json.loads(pointer.read_text())["revision"] == result["revision"]:
        replace_json(pointer, {"revision": result["revision"], "result_hash": digest(directory / "result.json")})


class FakeDocker:
    """Writes only test data; never imports or executes the snapshotted source."""
    blender = "/synthetic/blender"
    security_boundary = "MOCK_ONLY_NO_EXECUTION"
    docker = "/synthetic/docker"

    def __init__(self, observation=None):
        self.observation = observation
        self.calls = []
        self.preflights = 0

    def verify_runtime(self):
        self.preflights += 1
        return {"image_id": IMAGE, "test_double": True}

    def run(self, stage, arguments, inputs, output, log):
        self.calls.append({"stage": stage, "arguments": list(arguments), "inputs": dict(inputs)})
        log.write_text("Synthetic offline stage; no author, Docker, or Blender execution\n")
        if stage == "author":
            (output / "scene.blend").write_bytes(b"synthetic, not a Blender file")
        else:
            version = int(arguments[arguments.index("--observation-version") + 1])
            value = copy.deepcopy(self.observation if self.observation is not None else observed(version))
            write_json(output / "observation.json", value)
            if stage == "inspect":
                (output / "model.glb").write_bytes(b"synthetic, not a GLB file")
                (output / "scene.blend").write_bytes(b"synthetic, not a Blender file")
        return {"exit_code": 0, "test_double": True}


class ControllerHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "builder.py").write_text("raise AssertionError('Author source must never execute in offline tests')\n")
        self.params = self.root / "params.json"
        write_json(self.params, {})
        self.policy_path = self.root / "policy.json"
        self.rules_path = self.root / "rules.json"
        write_json(self.rules_path, LOCKED_RULES)
        self.store = self.root / "store"
        self.backend = FakeDocker()
        self.backend_patch = patch("experimental_modeling.sandbox.DockerSandbox", return_value=self.backend)
        self.backend_patch.start()
        self.addCleanup(self.backend_patch.stop)
        # A native fallback is forbidden, including if the synthetic backend fails.
        self.native_patch = patch("experimental_modeling.controller.run_job",
                                  side_effect=AssertionError("Native author execution is forbidden"))
        self.native = self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def run_build(self, *, version=2, revision="r0", parent=None, rules=True, translated=False):
        replace_json(self.policy_path, raw_policy(version, translated))
        return build(source=self.source, params=self.params, policy_path=self.policy_path,
                     store=self.store, revision=revision, parent=parent, renders=False,
                     sandbox_image=IMAGE, requirements_path=self.rules_path if rules else None)


class ReviewDispatchIntegrationTests(unittest.TestCase):
    def test_actual_revision_recomputes_using_the_hash_bound_policy(self):
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                store = Path(tmp)
                saved_revision(store, version, "r0")
                child = saved_revision(store, version, "r1", parent="r0")
                original_bytes = (child / "verification.json").read_bytes()
                # A real ReviewProject call recomputes the expected report; only
                # source/artifact creation is synthetic, not the evaluator.
                response = ReviewProject(store).revision("r1")
                self.assertEqual(response["report"]["schema_version"], version)
                self.assertTrue(response["report"]["machine_verified"])
                self.assertTrue(response["state"]["verification_current"])
                self.assertEqual((child / "verification.json").read_bytes(), original_bytes)
                if version == 2:
                    self.assertEqual(response["report"]["verifier_contract"], "indexed-translation/v2")
                else:
                    self.assertNotIn("verifier_contract", response["report"])

    def test_report_cannot_select_its_evaluator_by_lying_about_version(self):
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                store = Path(tmp)
                directory = saved_revision(store, version)
                report = json.loads((directory / "verification.json").read_text())
                report["schema_version"] = 3 - version
                replace_json(directory / "verification.json", report)
                reseal(store, directory)
                with self.assertRaisesRegex(ValueError, "version|match"):
                    ReviewProject(store).revision("r0")

    def test_replacing_entire_v2_report_with_v1_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            directory = saved_revision(store, 2)
            result = json.loads((directory / "result.json").read_text())
            forged = make_report(result, Policy.parse(raw_policy(1)), observed(1), None,
                                 RequirementSet.parse({"schema_version": 1, "requirements": []}))
            replace_json(directory / "verification.json", forged)
            reseal(store, directory)
            with self.assertRaisesRegex(ValueError, "version|match"):
                ReviewProject(store).revision("r0")

    def test_policy_file_cannot_be_swapped_with_only_artifact_manifest_resealed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            directory = saved_revision(store, 2)
            replace_json(directory / "policy.json", raw_policy(1))
            reseal(store, directory)
            with self.assertRaisesRegex(ValueError, "policy binding"):
                ReviewProject(store).revision("r0")

    def test_v2_accepted_then_rejected_surface_revision_cannot_inherit_verified_badge(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            saved_revision(store, 2)
            directory = saved_revision(store, 2, "bad", parent="r0", status="rejected")
            observation = json.loads((directory / "inspection/observation.json").read_text())
            observation["parts"]["body"]["face_material_indices"][0] = 1
            replace_json(directory / "inspection/observation.json", observation)
            result = json.loads((directory / "result.json").read_text())
            previous = json.loads((store / "accepted/r0/inspection/observation.json").read_text())
            report = make_report(result, Policy.parse(raw_policy(2, True)), observation, previous,
                                 RequirementSet.parse({"schema_version": 1, "requirements": []}))
            replace_json(directory / "verification.json", report)
            reseal(store, directory)
            response = ReviewProject(store).revision("bad")
            self.assertFalse(response["state"]["verification_current"])
            self.assertEqual(response["revision"]["status"], "rejected")
            self.assertGreater(response["report"]["summary"]["fail"], 0)


class ControllerVersionIntegrationTests(ControllerHarness):
    def test_controller_passes_explicit_observation_version_to_all_three_stages(self):
        for version in (1, 2):
            with self.subTest(version=version):
                self.store = self.root / ("store-v" + str(version))
                self.backend.calls.clear()
                result = self.run_build(version=version)
                self.assertEqual(result["status"], "accepted", result.get("error"))
                self.assertEqual([c["stage"] for c in self.backend.calls],
                                 ["author", "inspect", "roundtrip", "reopen"])
                for call in self.backend.calls:
                    args = call["arguments"]
                    if call["stage"] == "author":
                        self.assertNotIn("--observation-version", args)
                    else:
                        self.assertEqual(args.count("--observation-version"), 1)
                        self.assertEqual(args[args.index("--observation-version") + 1], str(version))
                stored = self.store / "accepted/r0"
                self.assertEqual(json.loads((stored / "inspection/observation.json").read_text())["schema_version"], version)
                self.assertEqual(ReviewProject(self.store).revision("r0")["report"]["schema_version"], version)
                self.native.assert_not_called()

    def test_v1_accepted_history_requires_a_fresh_v2_store(self):
        self.store.mkdir()
        directory = saved_revision(self.store, 1)
        baseline = {p.relative_to(self.store): p.read_bytes() for p in self.store.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "different policy version|new store"):
            self.run_build(version=2, revision="new", parent="r0", rules=False)
        self.assertFalse((self.store / "attempts/new").exists())
        self.assertEqual(self.backend.calls, [])
        for rel, content in baseline.items():
            self.assertEqual((self.store / rel).read_bytes(), content)
        self.assertEqual(ReviewProject(self.store).revision("r0")["report"]["schema_version"], 1)
        self.assertTrue(directory.exists())

    def test_attempt_only_v1_history_also_requires_a_fresh_v2_store(self):
        self.store.mkdir()
        saved_revision(self.store, 1, "rejected-v1", status="rejected")
        self.assertFalse((self.store / "last_good.json").exists())
        with self.assertRaisesRegex(ValueError, "different policy version|new store"):
            self.run_build(version=2, revision="new", rules=False)
        self.assertFalse((self.store / "attempts/new").exists())
        self.assertEqual(self.backend.calls, [])

    def test_unknown_missing_policy_history_cannot_be_assumed_v2(self):
        for category in ("accepted", "attempts"):
            with self.subTest(category=category):
                self.store = self.root / ("missing-" + category)
                history = self.store / category / "historical"
                history.mkdir(parents=True)
                write_json(history / "result.json", {"schema_version": 1, "revision": "historical",
                           "status": "needs_review", "requirements_lock_hash": None})
                with self.assertRaisesRegex(ValueError, "no policy version|new store"):
                    self.run_build(version=2, revision="new", rules=False)
                self.assertFalse((self.store / "attempts/new").exists())
                self.assertEqual(self.backend.calls, [])

    def test_interrupted_v2_attempt_before_policy_write_requires_fresh_store(self):
        interrupted = self.store / "attempts/interrupted-v2"
        interrupted.mkdir(parents=True)
        # A crash can leave an empty attempt before policy.json is written. Its
        # version is unknown; it is not evidence of an actual legacy v1 attempt.
        with self.assertRaisesRegex(ValueError, "no policy version.*incomplete.*new store"):
            self.run_build(version=2, revision="new", rules=False)
        self.assertTrue(interrupted.is_dir())
        self.assertEqual(list(interrupted.iterdir()), [])
        self.assertFalse((self.store / "attempts/new").exists())
        self.assertEqual(self.backend.calls, [])

    def test_history_version_audit_bounds_combined_entry_enumeration(self):
        for category, count in (("attempts", 257), ("accepted", 256)):
            history = self.store / category
            history.mkdir(parents=True)
            for number in range(count):
                entry = history / ("old-" + str(number))
                entry.mkdir()
                write_json(entry / "policy.json", raw_policy(2))
        with self.assertRaisesRegex(ValueError, "history.*audit limit"):
            self.run_build(version=2, revision="new", rules=False)
        self.assertFalse((self.store / "attempts/new").exists())
        self.assertEqual(self.backend.calls, [])

    def test_history_redirects_are_rejected_before_source_jobs(self):
        for kind in ("category", "entry", "policy"):
            with self.subTest(kind=kind):
                self.store = self.root / ("redirect-" + kind)
                self.store.mkdir()
                actual = self.root / ("real-" + kind)
                actual.mkdir()
                write_json(actual / "policy.json", raw_policy(2))
                if kind == "category":
                    (self.store / "attempts").symlink_to(actual, target_is_directory=True)
                else:
                    attempts = self.store / "attempts"
                    attempts.mkdir()
                    if kind == "entry":
                        (attempts / "old").symlink_to(actual, target_is_directory=True)
                    else:
                        entry = attempts / "old"
                        entry.mkdir()
                        (entry / "policy.json").symlink_to(actual / "policy.json")
                original = (actual / "policy.json").read_bytes()
                with self.assertRaisesRegex(ValueError, "[Ss]ymlink|redirect|reparse"):
                    self.run_build(version=2, revision="new", rules=False)
                self.assertEqual((actual / "policy.json").read_bytes(), original)
                self.assertEqual(self.backend.calls, [])
                self.native.assert_not_called()

    def test_v2_store_rejects_switching_back_to_v1(self):
        self.assertEqual(self.run_build(version=2)["status"], "accepted")
        self.backend.calls.clear()
        with self.assertRaisesRegex(ValueError, "different policy version|new store"):
            self.run_build(version=1, revision="legacy", parent="r0", rules=False)
        self.assertEqual(self.backend.calls, [])
        self.assertFalse((self.store / "attempts/legacy").exists())

    def test_v2_policy_reuse_preserves_locked_requirements_and_prior_artifacts(self):
        first = self.run_build(version=2)
        self.assertEqual(first["status"], "accepted", first.get("error"))
        before_rules = (self.store / "requirements.json").read_bytes()
        prior = self.store / "accepted/r0"
        before_artifacts = {p.relative_to(prior): p.read_bytes() for p in prior.rglob("*") if p.is_file()}
        second = self.run_build(version=2, revision="r1", parent="r0", rules=False)
        self.assertEqual(second["status"], "accepted", second.get("error"))
        self.assertEqual(first["requirements_lock_hash"], canonical_hash(LOCKED_RULES))
        self.assertEqual(second["requirements_lock_hash"], first["requirements_lock_hash"])
        self.assertEqual((self.store / "requirements.json").read_bytes(), before_rules)
        for rel, content in before_artifacts.items():
            self.assertEqual((prior / rel).read_bytes(), content)
        response = ReviewProject(self.store).revision("r1")
        self.assertTrue(response["report"]["machine_verified"])
        self.assertEqual(response["report"]["requirements_hash"], canonical_hash(LOCKED_RULES))
        self.native.assert_not_called()

    def test_new_v2_attempt_cannot_weaken_existing_requirements(self):
        first = self.run_build()
        self.assertEqual(first["status"], "accepted")
        locked = (self.store / "requirements.json").read_bytes()
        replace_json(self.rules_path, {"schema_version": 1, "requirements": []})
        self.backend.calls.clear()
        with self.assertRaisesRegex(ValueError, "locked|weaken"):
            self.run_build(revision="weakened", parent="r0", rules=True)
        self.assertEqual((self.store / "requirements.json").read_bytes(), locked)
        self.assertFalse((self.store / "attempts/weakened").exists())
        self.assertEqual(self.backend.calls, [])

    def test_missing_or_modified_established_requirements_are_rejected_before_jobs(self):
        self.assertEqual(self.run_build()["status"], "accepted")
        lock = self.store / "requirements.json"
        original = lock.read_bytes()
        for action in ("missing", "changed"):
            with self.subTest(action=action):
                if action == "missing":
                    lock.unlink()
                else:
                    replace_json(lock, {"schema_version": 1, "requirements": []})
                self.backend.calls.clear()
                with self.assertRaisesRegex(ValueError, "requirements.*missing|requirements.*changed"):
                    self.run_build(revision=action, parent="r0", rules=False)
                self.assertFalse((self.store / "attempts" / action).exists())
                self.assertEqual(self.backend.calls, [])
                lock.write_bytes(original)

    def test_mock_backend_failure_never_falls_back_to_native(self):
        with patch.object(self.backend, "verify_runtime", side_effect=RuntimeError("synthetic runtime unavailable")):
            with self.assertRaisesRegex(RuntimeError, "runtime unavailable"):
                self.run_build()
        self.native.assert_not_called()
        self.assertEqual(self.backend.calls, [])


class StaticValidationRunnerTests(unittest.TestCase):
    @staticmethod
    def load_runner():
        path = Path(__file__).with_name("run_verifier_validation.py")
        spec = importlib.util.spec_from_file_location("offline_verifier_validation_runner", path)
        module = importlib.util.module_from_spec(spec)
        original_path = sys.path[:]
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path[:] = original_path
        return module

    def test_static_input_validation_and_historical_reconstruction_are_read_only(self):
        runner = self.load_runner()
        before = runner.file_hashes(runner.LAMP)
        # No runner.run(), author import, Blender import, or subprocess call.
        with patch.object(runner, "DockerSandbox", side_effect=AssertionError("Docker execution forbidden")), \
             patch.object(runner, "build", side_effect=AssertionError("Author execution forbidden")):
            original = runner.validate_inputs()
            self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), runner.ORIGINAL_GEOMETRY_HASH)
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "historical-source"
                manifest = runner.prepare_lamp_source(output)
                self.assertEqual(manifest["geometry.py"], runner.ORIGINAL_GEOMETRY_HASH)
                self.assertEqual(manifest["builder.py"], runner.SOURCE_HASHES["builder.py"])
                self.assertEqual((output / "geometry.py").read_text(), original)
                self.assertNotEqual(manifest["geometry.py"], runner.SOURCE_HASHES["geometry.py"])
                ast.parse((output / "geometry.py").read_text())
                ast.parse((output / "builder.py").read_text())
                with self.assertRaises(FileExistsError):
                    runner.prepare_lamp_source(output)
        self.assertEqual(runner.file_hashes(runner.LAMP), before)

    def test_independent_oracle_and_probe_import_no_production_or_author_modules(self):
        directory = FIXTURES / "verifier_validation"
        allowed = {"oracle.py": {"collections", "math"},
                   "probe_artifact.py": {"argparse", "json", "math", "pathlib", "sys", "bpy"}}
        for filename, imports in allowed.items():
            with self.subTest(filename=filename):
                tree = ast.parse((directory / filename).read_text())
                actual = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        actual.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0, "Relative imports can hide author dependencies")
                        actual.add((node.module or "").split(".")[0])
                    elif isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name):
                            self.assertNotIn(node.func.id, {"__import__", "eval", "exec"})
                        elif isinstance(node.func, ast.Attribute):
                            self.assertNotEqual(node.func.attr, "import_module")
                self.assertLessEqual(actual, imports)
                self.assertNotIn("experimental_modeling", actual)
                self.assertNotIn("builder", actual)
                self.assertNotIn("geometry", actual)

    def test_validation_runner_requires_explicit_isolation_and_fresh_output(self):
        runner = self.load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "validation"
            with self.assertRaisesRegex(ValueError, "immutable sandbox image|native execution"):
                runner.run(output, sandbox_image=None)
            self.assertFalse(output.exists())
            output.mkdir()
            (output / "existing.txt").write_text("must be untouched")
            with patch.object(runner, "DockerSandbox", side_effect=AssertionError("must fail before Docker")):
                with self.assertRaisesRegex(ValueError, "fresh empty"):
                    runner.run(output, sandbox_image=IMAGE)
            self.assertEqual((output / "existing.txt").read_text(), "must be untouched")
            self.assertEqual(list(output.iterdir()), [output / "existing.txt"])


if __name__ == "__main__":
    unittest.main()
