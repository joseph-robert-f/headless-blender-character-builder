"""Static contracts for recorded external proposals. No model execution."""
from pathlib import Path
import unittest
from unittest.mock import patch

from run_external_lamp import EXAMPLE, SOURCE_HASHES, SLIM_HASHES, validate_examples


class RecordedAuthorTests(unittest.TestCase):
    def test_recorded_source_and_operator_inputs_without_execution(self):
        with patch("subprocess.Popen", side_effect=AssertionError("No source or runtime execution")):
            records = validate_examples()
        self.assertEqual(records["height"]["source_files"], SOURCE_HASHES)
        self.assertEqual(records["slim-negative"]["source_files"], SLIM_HASHES)
        self.assertEqual(records["slim-repair"]["source_files"], SLIM_HASHES)
        self.assertIn("290 mm", records["height"]["prompt"])
        self.assertIn("8 mm", records["slim-negative"]["prompt"])
        original = (EXAMPLE / "proposal/source/geometry.py").read_text()
        changed = (EXAMPLE / "revisions/slim-repair/proposal/source/geometry.py").read_text()
        self.assertEqual(original.replace("steps, sides, radius = 40, 16, 0.005", "steps, sides, radius = 40, 16, 0.004"), changed)

    def test_original_source_is_identical_in_height_proposal(self):
        for name in SOURCE_HASHES:
            self.assertEqual((EXAMPLE / "proposal/source" / name).read_bytes(),
                (EXAMPLE / "revisions/height/proposal/source" / name).read_bytes())
        for name in SLIM_HASHES:
            self.assertEqual((EXAMPLE / "revisions/slim-negative/proposal/source" / name).read_bytes(),
                (EXAMPLE / "revisions/slim-repair/proposal/source" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
