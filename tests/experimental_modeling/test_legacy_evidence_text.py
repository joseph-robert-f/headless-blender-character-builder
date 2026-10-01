"""Keep version-1 machine evidence unchanged during documentation edits."""
import json
from pathlib import Path
import unittest

from experimental_modeling.contracts import Policy
from experimental_modeling.requirements import RequirementSet, canonical_hash
from experimental_modeling.verification import make_report, validate_saved_report


class LegacyEvidenceTextTests(unittest.TestCase):
    def test_saved_unknown_reports_keep_indirect_validation_error_text(self):
        fixture = json.loads((Path(__file__).with_name("fixtures") / "legacy_unknown_reports.json").read_text())
        self.assertEqual(fixture["baseline_commit"], "e5efac203e04672830c9d6772f88f510f8127123")
        self.assertEqual({case["name"] for case in fixture["cases"]},
                         {"invalid-edge", "invalid-vertex", "nonfinite-vertex"})
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                saved = case["report"]
                self.assertEqual(canonical_hash(saved), case["report_sha256"])
                current = make_report(case["result"], Policy.parse(case["policy"]),
                                      case["observation"], None,
                                      RequirementSet.parse(case["requirements"]))
                self.assertFalse(saved["machine_verified"])
                self.assertFalse(current["machine_verified"])
                self.assertGreater(saved["summary"]["unknown"], 0)
                validate_saved_report(saved, current)
                self.assertEqual(current, saved)


if __name__ == "__main__":
    unittest.main()
