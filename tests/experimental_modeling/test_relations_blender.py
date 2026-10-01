# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in actual-Blender relation regression; default discovery never executes authors."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_water_relations import FIXTURE, read, run
from experimental_modeling.requirements import RequirementSet


class WaterRequirementFixtureTests(unittest.TestCase):
    def test_five_pinned_requirements_and_bounded_selectors(self):
        spec = RequirementSet.parse(read(FIXTURE/'requirements.json'))
        rows = {row.id: row for row in spec.requirements}
        self.assertEqual(set(rows), {'handle_upper', 'handle_lower', 'water_passage',
                                     'protected_body_region', 'protected_body_rays'})
        self.assertTrue(all(row.hard for row in rows.values()))
        self.assertEqual(len(rows['water_passage'].params['points']), 26)
        self.assertEqual(len(rows['protected_body_rays'].params['rays']), 80)
        self.assertEqual(rows['protected_body_region'].phase, 'revision')
        self.assertEqual(rows['protected_body_rays'].phase, 'revision')


@unittest.skipUnless(os.environ.get('RUN_TRUSTED_BLENDER_TESTS') == '1' and shutil.which('blender'),
                     'reviewed native Blender fixture execution requires explicit opt-in')
class WaterRelationsBlenderTests(unittest.TestCase):
    def test_positive_revisions_and_three_actual_saved_geometry_mutants(self):
        with tempfile.TemporaryDirectory(prefix='water-relations-') as tmp:
            summary = run(Path(tmp)/'evidence', trusted_reviewed_source=True)
            self.assertEqual(summary['security_boundary'], 'NOT_SANDBOXED')
            self.assertEqual(set(summary['cases']), {'r0', 'r1', 'r2', 'detach_upper', 'block_spout', 'alter_body'})


if __name__ == '__main__':
    unittest.main()
