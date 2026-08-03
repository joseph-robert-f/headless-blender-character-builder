"""Integration tests that need a real Blender.

Run with `make test-blender`, which launches these inside Blender. They are
slower than the unit suite and are the only place the geometry claims -- single
watertight shell, exact height, honest manifest -- are actually proven.
"""

import json
import os
import shutil
import tempfile
import unittest

import bmesh
import bpy

from blender import build as build_module
from blender import compat, generator, qa, scene
from hbcb import layout, presets, spec
from hbcb.exit_codes import VERIFY_FAILED, BuildError

# print-only-v1 skips the renders. Rendering is by far the slowest stage and
# proves nothing about geometry, so the tests that do not inspect an image
# avoid it and the suite stays runnable in CI.
FAST_PROFILE = "print-only-v1"


def _request(name, **overrides):
    raw = presets.get(name)
    raw["output_profile"] = FAST_PROFILE
    raw["spec"].update(overrides.pop("spec", {}))
    raw.update(overrides)
    return spec.resolve(raw)


def _topology(mesh_object):
    bm = bmesh.new()
    bm.from_mesh(mesh_object.data)
    bm.faces.ensure_lookup_table()
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) not in (1, 2))

    seen = set()
    shells = 0
    for face in bm.faces:
        if face.index in seen:
            continue
        shells += 1
        stack = [face]
        seen.add(face.index)
        while stack:
            for edge in stack.pop().edges:
                for neighbour in edge.link_faces:
                    if neighbour.index not in seen:
                        seen.add(neighbour.index)
                        stack.append(neighbour)
    triangles = sum(max(0, len(face.verts) - 2) for face in bm.faces)
    bm.free()
    return {
        "boundary": boundary,
        "non_manifold": non_manifold,
        "shells": shells,
        "triangles": triangles,
    }


class GeometryTests(unittest.TestCase):
    """Claims made in the README about the mesh itself."""

    def test_every_preset_is_one_watertight_shell(self):
        for name in presets.names():
            with self.subTest(preset=name):
                request = _request(name)
                scene.reset()
                model, _ = generator.generate(request.spec, request.print_profile)
                topology = _topology(model)
                self.assertEqual(topology["boundary"], 0, "mesh has holes")
                self.assertEqual(topology["non_manifold"], 0, "mesh is non-manifold")
                self.assertEqual(topology["shells"], 1, "mesh is not a single body")

    def test_height_matches_the_request(self):
        for height in (25.0, 60.0, 137.5, 250.0):
            with self.subTest(height=height):
                request = _request("facet-bot", spec={"height_mm": height})
                scene.reset()
                model, _ = generator.generate(request.spec, request.print_profile)
                self.assertAlmostEqual(scene.dimensions_mm(model)[2], height, delta=0.05)

    def test_model_rests_on_the_build_plate(self):
        request = _request("crystal-scout")
        scene.reset()
        model, _ = generator.generate(request.spec, request.print_profile)
        low, _ = scene.world_bounds(model)
        self.assertAlmostEqual(low[2], 0.0, delta=0.01)

    def test_generation_is_deterministic(self):
        """Same request in, same structure out."""
        request = _request("cocoa-cub")
        fingerprints = []
        for _ in range(2):
            scene.reset()
            model, _ = generator.generate(request.spec, request.print_profile)
            fingerprints.append(
                (
                    _topology(model),
                    [round(value, 6) for value in scene.dimensions_mm(model)],
                    len(model.data.vertices),
                )
            )
        self.assertEqual(fingerprints[0], fingerprints[1])

    def test_small_models_get_thickened_limbs(self):
        """The generator must enforce the profile, not just measure it."""
        request = _request("facet-bot", spec={"height_mm": 25})
        scene.reset()
        model, report = generator.generate(request.spec, request.print_profile)
        self.assertTrue(
            report.adjustments,
            "a 25 mm model should have needed thickening for a 2 mm minimum feature",
        )
        measurements = qa.measure(model, request.print_profile)
        verdict = qa.evaluate(measurements, request.print_profile, strict=True)
        self.assertNotIn("minimum_thickness", verdict["failed"])

    def test_disabling_the_base_still_sits_flat(self):
        request = _request("facet-bot", spec={"base": {"enabled": False}})
        scene.reset()
        model, _ = generator.generate(request.spec, request.print_profile)
        low, _ = scene.world_bounds(model)
        self.assertAlmostEqual(low[2], 0.0, delta=0.01)
        self.assertEqual(_topology(model)["shells"], 1)


class PrintProfileEnforcementTests(unittest.TestCase):
    def test_resin_profile_permits_finer_features(self):
        """A profile that allows thinner walls should not force the same thickening."""
        fine = _request(
            "facet-bot", spec={"height_mm": 30}, print_profile={"preset": "resin-standard"}
        )
        coarse = _request(
            "facet-bot", spec={"height_mm": 30}, print_profile={"preset": "fdm-0.6-draft"}
        )
        scene.reset()
        _, fine_report = generator.generate(fine.spec, fine.print_profile)
        scene.reset()
        _, coarse_report = generator.generate(coarse.spec, coarse.print_profile)
        self.assertLessEqual(len(fine_report.adjustments), len(coarse_report.adjustments))


class BuildOutputTests(unittest.TestCase):
    """The published artifacts and the manifest that describes them."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix="hbcb-test-")
        request = _request("facet-bot")
        cls.manifest = build_module.run(request, cls.directory, log=lambda *_: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_publishes_exactly_the_expected_artifacts(self):
        for relative in layout.expected(FAST_PROFILE, "diagnostic-v1"):
            self.assertTrue(
                os.path.isfile(os.path.join(self.directory, relative)),
                "missing %s" % relative,
            )

    def test_staging_directory_is_removed(self):
        self.assertFalse(os.path.exists(os.path.join(self.directory, layout.STAGING_DIR)))

    def test_manifest_matches_its_schema(self):
        document = self._load(layout.MANIFEST)
        spec.store().validate("manifest-v1.schema.json", document)
        self.assertEqual(document["status"], "succeeded")

    def test_qa_report_matches_its_schema(self):
        spec.store().validate("qa-v1.schema.json", self._load(layout.QA))

    def test_manifest_hashes_are_correct(self):
        from hbcb import manifest as manifest_module

        problems = manifest_module.verify_artifacts(self.directory, self.manifest)
        self.assertEqual(problems, [])

    def test_manifest_does_not_hash_itself(self):
        self.assertNotIn(layout.MANIFEST, self.manifest["artifacts"])

    def test_exported_stl_reimports_watertight_at_the_right_size(self):
        scene.reset("reimport")
        compat.import_stl(os.path.join(self.directory, layout.MODEL_STL))
        imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        self.assertEqual(len(imported), 1)

        topology = _topology(imported[0])
        self.assertEqual(topology["boundary"], 0, "exported STL has holes")
        self.assertEqual(topology["non_manifold"], 0)
        self.assertEqual(topology["shells"], 1)

        expected = self.manifest["model"]["dimensions_mm"]
        actual = scene.dimensions_mm(imported[0])
        for axis in range(3):
            self.assertAlmostEqual(
                actual[axis], expected[axis], delta=max(0.2, expected[axis] * 0.005)
            )

    def _load(self, relative):
        with open(os.path.join(self.directory, relative), encoding="utf-8") as handle:
            return json.load(handle)


class FailureHandlingTests(unittest.TestCase):
    def test_failing_qa_publishes_evidence_and_marks_needs_review(self):
        """A failed check must still leave the model and report to look at."""
        directory = tempfile.mkdtemp(prefix="hbcb-fail-")
        try:
            # A wall minimum no geometric character can satisfy.
            request = _request(
                "facet-bot",
                spec={"height_mm": 30},
                print_profile={
                    "preset": "custom",
                    "technology": "fdm",
                    "nozzle_mm": 0.4,
                    "min_wall_mm": 5.0,
                    "min_feature_mm": 5.0,
                },
            )
            with self.assertRaises(BuildError) as caught:
                build_module.run(request, directory, log=lambda *_: None)
            self.assertEqual(caught.exception.code, VERIFY_FAILED)

            manifest_path = os.path.join(directory, layout.MANIFEST)
            self.assertTrue(os.path.isfile(manifest_path), "evidence was not published")
            with open(manifest_path, encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["status"], "needs_review")
            self.assertIn("minimum_thickness", document["qa"]["failed_checks"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_advisory_profile_passes_the_same_build(self):
        directory = tempfile.mkdtemp(prefix="hbcb-advisory-")
        try:
            request = _request(
                "facet-bot",
                spec={"height_mm": 30},
                quality_profile="advisory-v1",
                print_profile={
                    "preset": "custom",
                    "technology": "fdm",
                    "nozzle_mm": 0.4,
                    "min_wall_mm": 5.0,
                    "min_feature_mm": 5.0,
                },
            )
            document = build_module.run(request, directory, log=lambda *_: None)
            self.assertEqual(document["status"], "succeeded")
            self.assertTrue(document["qa"]["failed_checks"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
