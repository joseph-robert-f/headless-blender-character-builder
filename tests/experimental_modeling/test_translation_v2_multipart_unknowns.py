"""Offline composition checks for an edited body and a protected part.

The capped box and expected verdicts below are declared independently of the
production observer and translation predicates. Controller jobs write synthetic
observations only: these tests do not execute author code, Docker, or Blender.
"""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experimental_modeling.acceptance import check
from experimental_modeling.contracts import Policy
from experimental_modeling.controller import build, write_json

from tests.experimental_modeling.test_translation_v2 import (
    GOLDEN, canonical_sha256, policy_raw, report_for, row,
)
from tests.experimental_modeling.test_translation_v2_integration import FakeDocker, IMAGE


DELTA = (.25, -.5, .125)
HASHES = ("geometry_hash", "transform_hash", "material_hash")


def multipart_policy(*, initial=False):
    raw = policy_raw(DELTA)
    raw["parts"].append("protected")
    if initial:
        raw["changed_parts"].append("protected")
        raw["constraints"] = []
    return raw


def multipart_observations():
    """Explicit outward box caps/sides, plus the hand-derived golden tetrahedron."""
    vertices = [[0., 0., 0.], [2., 0., 0.], [2., 1., 0.], [0., 1., 0.],
                [0., 0., 3.], [2., 0., 3.], [2., 1., 3.], [0., 1., 3.]]
    faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4],
             [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    normals = [[0., 0., -1.], [0., 0., 1.], [0., -1., 0.],
               [1., 0., 0.], [0., 1., 0.], [-1., 0., 0.]]
    edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6],
             [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]]
    palette = [{"base_color": [1., 0., 0., 1.], "metallic": 0., "roughness": .5}]
    body = {"world_vertices": vertices, "face_indices": faces, "edge_indices": edges,
            "face_material_indices": [0] * 6,
            "face_world_corner_normals": [[normal[:] for _ in range(4)] for normal in normals],
            "materials": palette, "geometry_hash": canonical_sha256([vertices, faces, edges]),
            "transform_hash": canonical_sha256([0., 0., 0.]),
            "material_hash": canonical_sha256(palette)}
    golden = GOLDEN["models"]["tetrahedron"]["previous"]["parts"]["body"]
    protected = {key: copy.deepcopy(golden[key]) for key in body}
    previous = {"schema_version": 2, "parts": {"body": body, "protected": protected}}
    observed = copy.deepcopy(previous)
    edited = observed["parts"]["body"]
    edited["world_vertices"] = [[x + d for x, d in zip(vertex, DELTA)] for vertex in vertices]
    edited["transform_hash"] = canonical_sha256(DELTA)
    return observed, previous


def surface_work(observation):
    """Count declared input sizes without preparing or comparing surfaces."""
    return sum(len(part["world_vertices"]) + len(part["edge_indices"])
               + sum(map(len, part["face_indices"])) for part in observation["parts"].values())


class CompactFakeDocker(FakeDocker):
    """Keep large valid observations inside the real controller's JSON byte cap."""

    def run(self, stage, arguments, inputs, output, log):
        result = super().run(stage, arguments, inputs, output, log)
        if stage != "author":
            (output / "observation.json").write_text(
                json.dumps(self.observation, separators=(",", ":"), allow_nan=False))
        return result


class MultipartUnknownCompositionTests(unittest.TestCase):
    def assert_unknown(self, observed, previous, reason, *, preserved="pass", before_surface=False):
        policy = Policy.parse(multipart_policy())
        with ExitStack() as stack:
            measure = stack.enter_context(patch("experimental_modeling.acceptance.measure",
                side_effect=AssertionError("Unknown evidence must stop before translation measurement")))
            surface = (stack.enter_context(patch("experimental_modeling.acceptance.surface",
                side_effect=AssertionError("Surface budget must stop before preparation")))
                if before_surface else None)
            with self.assertRaisesRegex(ValueError, reason):
                check(policy, observed, previous)
            # Claim every pipeline stage completed so missing evidence, rather
            # than an unrelated incomplete pipeline, must block verification.
            report = report_for(policy, observed, previous)
            measure.assert_not_called()
            if surface is not None:
                surface.assert_not_called()
        self.assertEqual(row(report, "policy-overall")["status"], "unknown")
        self.assertEqual(row(report, "policy-001")["status"], "unknown")
        self.assertRegex(row(report, "policy-overall")["evidence"]["reason"], reason)
        self.assertEqual(row(report, "preserved-protected")["status"], preserved)
        self.assertFalse(report["machine_verified"])
        self.assertFalse(report["human_accepted"])
        json.dumps(report, allow_nan=False)

    def assert_not_promoted(self, observed, previous, reason, *, preserved="pass", before_surface=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, store = root / "source", root / "store"
            source.mkdir()
            (source / "builder.py").write_text(
                "raise AssertionError('Author source must not execute in offline tests')\n")
            params, policy_path = root / "params.json", root / "policy.json"
            write_json(params, {})
            write_json(policy_path, multipart_policy(initial=True))
            backend = CompactFakeDocker(previous)
            with patch("experimental_modeling.sandbox.DockerSandbox", return_value=backend), \
                 patch("experimental_modeling.controller.run_job",
                       side_effect=AssertionError("Native execution is forbidden")) as native:
                initial = build(source=source, params=params, policy_path=policy_path,
                                store=store, revision="baseline", renders=False, sandbox_image=IMAGE)
                self.assertEqual(initial["status"], "accepted", initial.get("error"))
                accepted = store / "accepted/baseline"
                self.assertTrue(json.loads((accepted / "verification.json").read_text())["machine_verified"])
                pointer = (store / "last_good.json").read_bytes()
                baseline = {path.relative_to(accepted): path.read_bytes()
                            for path in accepted.rglob("*") if path.is_file()}
                policy_path.write_text(json.dumps(multipart_policy(), allow_nan=False))
                backend.observation = observed
                backend.calls.clear()
                with ExitStack() as stack:
                    promote = stack.enter_context(patch("experimental_modeling.controller.promote",
                        side_effect=AssertionError("Unknown multipart revision must not be promoted")))
                    measure = stack.enter_context(patch("experimental_modeling.acceptance.measure",
                        side_effect=AssertionError("Unknown evidence must stop before measurement")))
                    surface = (stack.enter_context(patch("experimental_modeling.acceptance.surface",
                        side_effect=AssertionError("Surface budget must stop before preparation")))
                        if before_surface else None)
                    result = build(source=source, params=params, policy_path=policy_path,
                                   store=store, revision="unknown", parent="baseline",
                                   renders=False, sandbox_image=IMAGE)
                    promote.assert_not_called()
                    measure.assert_not_called()
                    if surface is not None:
                        surface.assert_not_called()
                native.assert_not_called()
            self.assertEqual(result["status"], "needs_review")
            self.assertRegex(result["error"], reason)
            self.assertEqual([call["stage"] for call in backend.calls], ["author", "inspect"])
            self.assertFalse((store / "accepted/unknown").exists())
            self.assertEqual((store / "last_good.json").read_bytes(), pointer)
            for relative, content in baseline.items():
                self.assertEqual((accepted / relative).read_bytes(), content)
            report = json.loads((store / "attempts/unknown/verification.json").read_text())
            self.assertEqual(row(report, "policy-overall")["status"], "unknown")
            self.assertEqual(row(report, "policy-001")["status"], "unknown")
            self.assertEqual(row(report, "preserved-protected")["status"], preserved)
            self.assertFalse(report["machine_verified"])

    def test_protected_corner_normals_missing_blocks_composed_revision(self):
        observed, previous = multipart_observations()
        self.assertFalse(check(Policy.parse(multipart_policy()), observed, previous))
        del observed["parts"]["protected"]["face_world_corner_normals"]
        self.assertEqual({key: observed["parts"]["protected"][key] for key in HASHES},
                         {key: previous["parts"]["protected"][key] for key in HASHES})
        # A protected hash row still passes, but every part must supply valid
        # surface evidence before the overall policy or translation can pass.
        self.assert_unknown(observed, previous, "face_world_corner_normals")
        self.assert_not_promoted(observed, previous, "face_world_corner_normals")

    def test_protected_valid_hash_missing_blocks_composed_revision(self):
        for component in HASHES:
            with self.subTest(component=component):
                observed, previous = multipart_observations()
                self.assertFalse(check(Policy.parse(multipart_policy()), observed, previous))
                del observed["parts"]["protected"][component]
                self.assert_unknown(observed, previous, "protected part has no valid hash", preserved="unknown")
                self.assert_not_promoted(observed, previous, "protected part has no valid hash", preserved="unknown")

    def test_duplicate_oriented_body_cap_blocks_composed_revision(self):
        observed, previous = multipart_observations()
        self.assertFalse(check(Policy.parse(multipart_policy()), observed, previous))
        body = observed["parts"]["body"]
        self.assertEqual(body["face_indices"][1], [4, 5, 6, 7])
        body["face_indices"].append([5, 6, 7, 4])
        body["face_material_indices"].append(body["face_material_indices"][1])
        body["face_world_corner_normals"].append([[0., 0., 1.]] * 4)
        self.assertEqual(observed["parts"]["protected"], previous["parts"]["protected"])
        self.assert_unknown(observed, previous, "Duplicate oriented faces")
        self.assert_not_promoted(observed, previous, "Duplicate oriented faces")

    def test_protected_surface_work_exhausts_total_budget_with_small_edited_body(self):
        observed, previous = multipart_observations()
        protected = previous["parts"]["protected"]
        # 100000 vertices + 24945 distinct edges + 12 face corners = 124957.
        # Each eight-vertex body costs 44. Across both observations the sum is
        # 2 * (124957 + 44) = 250002, above 250000 despite a tiny edit scope.
        protected["world_vertices"] += [[0., 0., 0.] for _ in range(100000 - 4)]
        protected["edge_indices"] += [[index, index + 1] for index in range(4, 24943)]
        protected["geometry_hash"] = canonical_sha256(protected["world_vertices"] + protected["edge_indices"])
        observed["parts"]["protected"] = copy.deepcopy(protected)
        self.assertEqual(len(protected["world_vertices"]), 100000)
        self.assertEqual(len(protected["edge_indices"]), 24945)
        self.assertEqual(surface_work(observed) + surface_work(previous), 250002)
        self.assertEqual(observed["parts"]["protected"], previous["parts"]["protected"])
        self.assertEqual(len(observed["parts"]["body"]["world_vertices"]), 8)
        # The edited body alone meets every translated constraint. The total
        # budget also includes unchanged parts and their accepted-parent data.
        body_policy = Policy.parse(policy_raw(DELTA))
        self.assertFalse(check(body_policy,
            {"schema_version": 2, "parts": {"body": observed["parts"]["body"]}},
            {"schema_version": 2, "parts": {"body": previous["parts"]["body"]}}))
        self.assert_unknown(observed, previous, "Surface work exceeds", before_surface=True)
        self.assert_not_promoted(observed, previous, "Surface work exceeds", before_surface=True)


if __name__ == "__main__":
    unittest.main()
