from __future__ import annotations

import unittest

from blender.qa_failure_summary import (
    MAX_FAILURE_DETAILS,
    MAX_FAILURE_SUMMARY_CHARACTERS,
    SAFE_DIAGNOSTIC_PREFIX,
    geometry_qa_failure_summary,
)
from shared.quality_report import QualityReport
from tests.support import passed_qa_report


class GeometryQaFailureSummaryTests(unittest.TestCase):
    def test_needs_review_uses_fixed_phrase_and_ignores_private_notes(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["minimum_wall_mm"] = None
        raw["status"] = "needs_review"
        canary = "PRIVATE request-name /private/path short strict candidates and ray misses"
        raw["notes"] = [canary]

        summary = geometry_qa_failure_summary(QualityReport.from_mapping(raw))

        self.assertEqual(
            summary,
            "safe diagnostics: minimum wall measurement unavailable",
        )
        self.assertNotIn(canary, summary)
        self.assertNotIn("short strict candidates", summary)
        self.assertNotIn("ray misses", summary)

    def test_measurable_failure_reports_policy_without_observed_value(self) -> None:
        raw = passed_qa_report()
        raw["measurements"]["minimum_wall_mm"] = 0.123456
        raw["status"] = "failed"
        raw["notes"] = ["PRIVATE geometry note"]

        summary = geometry_qa_failure_summary(QualityReport.from_mapping(raw))

        self.assertEqual(
            summary,
            "safe diagnostics: minimum wall is below the 1.2 mm requirement",
        )
        self.assertNotIn("0.123456", summary)
        self.assertNotIn("PRIVATE", summary)

    def test_many_failures_are_ascii_and_bounded_with_fixed_overflow(self) -> None:
        raw = passed_qa_report()
        raw["checks"] = {field: False for field in raw["checks"]}
        raw["measurements"].update(
            {
                "glb_dimensions_mm": [66, 51, 95],
                "stl_dimensions_mm": [62, 51, 95],
                "triangle_count": 3,
                "object_count": 0,
                "material_count": 0,
                "non_manifold_edges": 9,
                "zero_area_faces": 7,
                "minimum_wall_mm": 0.5,
                "minimum_feature_mm": 0.5,
                "connected_shells": 2,
            }
        )
        raw["status"] = "failed"
        raw["notes"] = ["PRIVATE overflow canary"]

        summary = geometry_qa_failure_summary(QualityReport.from_mapping(raw))

        self.assertTrue(summary.startswith(SAFE_DIAGNOSTIC_PREFIX))
        self.assertIn("manifold check failed", summary)
        self.assertTrue(summary.endswith("additional mandatory checks did not pass"))
        self.assertEqual(summary.count("; "), MAX_FAILURE_DETAILS)
        self.assertLessEqual(len(summary), MAX_FAILURE_SUMMARY_CHARACTERS)
        self.assertTrue(all(32 <= ord(character) <= 126 for character in summary))
        self.assertNotIn("PRIVATE overflow canary", summary)

    def test_passing_report_has_no_failure_summary(self) -> None:
        with self.assertRaisesRegex(ValueError, "passing QA report"):
            geometry_qa_failure_summary(QualityReport.from_mapping(passed_qa_report()))


if __name__ == "__main__":
    unittest.main()
