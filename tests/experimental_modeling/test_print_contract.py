# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed checks for the provisional cat print contract; no Blender needed."""
from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from experimental_modeling.print_contract import PrintProfile, assess_final_stl


PROFILE_PATH = (Path(__file__).resolve().parents[2] / "experimental_modeling" /
                "examples" / "anime_cat" / "print" / "provisional_fdm_v1.json")


class PrintContractTests(unittest.TestCase):
    def setUp(self):
        self.profile = PrintProfile.load(PROFILE_PATH)
        self.evidence = {
            "schema_version": 1,
            "profile_sha256": self.profile.sha256,
            "revision": "r1",
            "measurement_source": "reimported_final_stl",
            "units": "millimeter",
            "stl_sha256": "a" * 64,
            "source_observation_sha256": "b" * 64,
            "triangle_count": 120000,
            "evaluated_triangle_count": 120000,
            "measured_triangle_count": 120000,
            "evaluated_mesh_sha256": "c" * 64,
            "observer_sha256": "d" * 64,
            "derivation_sha256": "e" * 64,
            "checks": {"self_intersections": "passed", "feature_coverage": "passed",
                       "roundtrip_surface": "passed", "protected_regions": "passed",
                       "visual_fidelity": "passed"},
            "connected_shells": 1,
            "boundary_edges": 0,
            "nonmanifold_edges": 0,
            "nonmanifold_vertices": 0,
            "loose_vertices": 0,
            "noncontiguous_edges": 0,
            "degenerate_triangles": 0,
            "signed_volume_mm3": 110000.0,
            "bounds_min_mm": [-34.0, -29.0, 0.0],
            "bounds_max_mm": [34.0, 29.0, 100.0],
            "measured_minimum_feature_mm": 1.5,
            "feature_sample_count": 400,
        }

    def test_fixed_scale_is_shared_across_revisions(self):
        self.assertAlmostEqual(3.15 * self.profile.mm_per_source_meter, 100.0)
        self.assertAlmostEqual(2.904417 * self.profile.mm_per_source_meter, 92.2037, places=3)
        self.assertEqual(self.profile.raw["revision_heights_mm"],
                         {"r0": 92.2, "r1": 100.0, "r2": 92.2})
        for revision in ("r0", "r2"):
            report = self.evidence | {"revision": revision, "bounds_max_mm": [34, 29, 92.2]}
            self.assertEqual(assess_final_stl(self.profile, report)["measurement_gate"], "passed")

    def test_report_pass_never_authorizes_promotion(self):
        result = assess_final_stl(self.profile, self.evidence)
        self.assertEqual(result["measurement_gate"], "passed")
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(result["physical_validation"], "pending")

    def test_raw_meter_stl_and_source_scene_evidence_cannot_pass(self):
        for edit in ({"units": "meter"}, {"measurement_source": "source_scene"}):
            with self.subTest(edit=edit), self.assertRaisesRegex(ValueError, "final STL"):
                assess_final_stl(self.profile, self.evidence | edit)
        report = self.evidence | {"bounds_max_mm": [1.1, 0.9, 3.15]}
        self.assertIn("fixed_scale_height", assess_final_stl(self.profile, report)["failures"])

    def test_open_detached_or_inverted_export_fails(self):
        edits = (
            ("connected_shells", 2), ("boundary_edges", 1),
            ("nonmanifold_edges", 1), ("noncontiguous_edges", 1),
            ("nonmanifold_vertices", 1), ("loose_vertices", 1),
            ("degenerate_triangles", 1), ("signed_volume_mm3", -110000.0),
            ("measured_minimum_feature_mm", 0.7), ("feature_sample_count", 0),
        )
        for key, value in edits:
            with self.subTest(key=key):
                result = assess_final_stl(self.profile, self.evidence | {key: value})
                self.assertEqual(result["measurement_gate"], "rejected")
                self.assertTrue(result["failures"])

    def test_profile_and_evidence_malformed_inputs_rejected(self):
        for key, value in (("source_unit", "millimeter"), ("reference_height_m", math.inf),
                           ("maximum_triangles", True), ("revision_heights_mm", {"r1": 100})):
            with self.subTest(profile_key=key), self.assertRaises(ValueError):
                PrintProfile.parse(self.profile.raw | {key: value})
        for key, value in (("profile_sha256", "0" * 64), ("stl_sha256", "abc"),
                           ("triangle_count", True), ("signed_volume_mm3", math.nan)):
            with self.subTest(evidence_key=key), self.assertRaises(ValueError):
                assess_final_stl(self.profile, self.evidence | {key: value})
        missing = copy.deepcopy(self.evidence)
        del missing["feature_sample_count"]
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            assess_final_stl(self.profile, missing)
        with self.assertRaisesRegex(ValueError, "fields mismatch"):
            PrintProfile.parse(self.profile.raw | {"physically_validated": True})

    def test_profile_cannot_silently_change_or_mutate(self):
        for edit in ({"reference_height_mm": 110}, {"height_tolerance_mm": 4},
                     {"minimum_feature_mm": 0.6}, {"source_scale_length": .001},
                     {"nozzle_diameter_mm": .6}, {"maximum_triangles": 1000000}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                PrintProfile.parse(self.profile.raw | edit)
        raw = self.profile.raw
        raw["revision_heights_mm"]["r0"] = 40
        self.assertEqual(self.profile.raw["revision_heights_mm"]["r0"], 92.2)
        integer_spelling = self.profile.raw | {"reference_height_mm": 100}
        self.assertEqual(PrintProfile.parse(integer_spelling).sha256, self.profile.sha256)

    def test_direct_constructor_cannot_bypass_reviewed_profile(self):
        weakened = self.profile.raw | {"reference_height_mm": 3.15, "minimum_feature_mm": .1}
        with self.assertRaisesRegex(ValueError, "reviewed canonical"):
            PrintProfile(json.dumps(weakened).encode("utf-8"))
        with self.assertRaisesRegex(ValueError, "reviewed canonical"):
            PrintProfile(bytearray(self.profile._json))

    def test_duplicate_profile_fields_rejected_even_if_last_value_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.json'
            original = PROFILE_PATH.read_text()
            for modified in (original.replace('"source_unit": "meter"',
                                               '"source_unit": "millimeter", "source_unit": "meter"'),
                             original.replace('"r0": 92.2', '"r0": 1, "r0": 92.2')):
                path.write_text(modified)
                with self.assertRaisesRegex(ValueError, 'duplicate print profile'):
                    PrintProfile.load(path)

    def test_unknown_or_failed_checks_cannot_pass(self):
        for check in self.evidence["checks"]:
            for status, expected in (("unknown", "needs_review"), ("failed", "rejected")):
                report = copy.deepcopy(self.evidence)
                report["checks"][check] = status
                result = assess_final_stl(self.profile, report)
                self.assertEqual(result["measurement_gate"], expected)
                self.assertFalse(result["promotion_eligible"])
        for checks in ({}, {"self_intersections": True}, self.evidence["checks"] | {"certified": "passed"}):
            with self.assertRaises(ValueError):
                assess_final_stl(self.profile, self.evidence | {"checks": checks})

    def test_all_final_triangles_required_with_unchanged_json_limit(self):
        from experimental_modeling.contracts import MAX_JSON
        self.assertEqual(MAX_JSON, 4 * 1024 * 1024)
        for key in ("evaluated_triangle_count", "measured_triangle_count"):
            result = assess_final_stl(self.profile, self.evidence | {key: 500})
            self.assertIn("complete_final_geometry", result["failures"])
        result = assess_final_stl(self.profile, self.evidence | {"triangle_count": 500001})
        self.assertIn("triangle_budget", result["failures"])

    def test_bounds_nonfinite_and_hostile_numeric_inputs(self):
        for value in (True, math.nan, math.inf, 10 ** 1000, "100"):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                assess_final_stl(self.profile, self.evidence | {"signed_volume_mm3": value})
        for bounds in ([34, 29], [34, 29, True], [34, 29, math.inf], [34, 29, 10 ** 1000]):
            with self.subTest(bounds=repr(bounds)[:100]), self.assertRaises(ValueError):
                assess_final_stl(self.profile, self.evidence | {"bounds_max_mm": bounds})
        for edit, failure in (({"bounds_max_mm": [-35, 29, 100]}, "dimensions_mm"),
                              ({"bounds_max_mm": [200, 29, 100]}, "dimensions_mm"),
                              ({"bounds_min_mm": [-34, -29, 1]}, "ground_z_mm")):
            self.assertIn(failure, assess_final_stl(self.profile, self.evidence | edit)["failures"])

    def test_report_provenance_binds_exact_measurements(self):
        result = assess_final_stl(self.profile, self.evidence)
        changed = assess_final_stl(self.profile, self.evidence | {"signed_volume_mm3": 110001})
        self.assertEqual(result["profile_sha256"], self.profile.sha256)
        self.assertNotEqual(result["evidence_sha256"], changed["evidence_sha256"])


if __name__ == "__main__":
    unittest.main()
