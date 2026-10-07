# SPDX-License-Identifier: GPL-3.0-or-later
"""Version, reference-revision and complete-evidence identity cannot be mixed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from experimental_modeling.print_contract import DEFAULT_PROFILE_ID, X1C_PROFILE_ID, PrintProfile
from experimental_modeling.print_preservation import protected_boxes, require_profile_binding
from tests.experimental_modeling.test_anime_cat_print import reports, verify
from tests.experimental_modeling.test_print_contract import PROFILE_PATH
from tests.experimental_modeling import test_print_preservation


class X1CProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = PrintProfile.load(PROFILE_PATH.with_name('x1c_pla_bare100_v2.json'))
        self.v1 = PrintProfile.load(PROFILE_PATH)

    def test_old_canonical_profile_and_default_are_unchanged(self):
        self.assertEqual(self.v1.sha256,'0c718776d23213ce6182ca0cf302b6e48827a2205d6a9f8fe69f381e4b646f32')
        self.assertEqual(PrintProfile.reviewed(),self.v1)
        self.assertEqual(self.v1.author_entry,'builder.py')
        self.assertEqual(self.v1.final_scale,1.0)
        self.assertEqual(self.v1.raw['revision_heights_mm'],{'r0':92.2,'r1':100.0,'r2':92.2})

    def test_bare_cat_reference_and_single_frozen_factor(self):
        self.assertEqual(self.profile.sha256,'7c7f84e3749e08d24bb163e3364e4831278ba3908f780f1b44ac2b0a928da915')
        self.assertEqual(self.profile.raw['revision_heights_mm'],{'r0':100.0,'r1':108.54632543541882,'r2':100.0})
        self.assertEqual(self.profile.final_scale,100.0/92.1265640258789)
        self.assertAlmostEqual(self.profile.mm_per_source_meter,self.v1.mm_per_source_meter*self.profile.final_scale)
        for key in ('minimum_feature_mm','height_tolerance_mm','maximum_triangles','maximum_dimension_mm'):
            self.assertEqual(self.profile.raw[key],self.v1.raw[key])

    def test_mixed_unknown_or_reassigned_reference_version_is_rejected(self):
        edits = ({'profile_id':DEFAULT_PROFILE_ID},{'profile_id':'unknown'}, {'profile_id':[]},
                 {'reference_height_m':3.15},{'revision_heights_mm':{'r0':92.2,'r1':100.0,'r2':92.2}},
                 {'reference_height_mm':108.54632543541882}, {'minimum_feature_mm':True})
        for edit in edits:
            with self.subTest(edit=edit),self.assertRaises(ValueError):
                PrintProfile.parse(self.profile.raw|edit)
        with self.assertRaises(ValueError):PrintProfile.parse(self.v1.raw|{'profile_id':X1C_PROFILE_ID})

    def test_direct_constructor_and_mutable_raw_remain_closed(self):
        for value in (bytearray(self.profile._json),json.dumps(self.profile.raw|{'minimum_feature_mm':.4}).encode()):
            with self.assertRaises(ValueError):PrintProfile(value)
        raw=self.profile.raw;raw['revision_heights_mm']['r0']=1
        self.assertEqual(self.profile.raw['revision_heights_mm']['r0'],100.0)
        self.assertEqual(PrintProfile.parse(self.profile.raw|{'reference_height_mm':100}),self.profile)

    def test_duplicate_new_profile_and_nested_height_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json';original=json.dumps(self.profile.raw)
            for text in (original.replace('"status": "provisional"','"status": "other", "status": "provisional"'),
                         original.replace('"r0": 100.0','"r0": 1.0, "r0": 100.0')):
                path.write_text(text)
                with self.assertRaisesRegex(ValueError,'duplicate print profile'):PrintProfile.load(path)

    def test_candidate_evidence_requires_new_identity_and_new_dimensions(self):
        data=reports()
        for report in data:
            report.update(profile_id=X1C_PROFILE_ID,profile_sha256=self.profile.sha256)
            for name,mesh in report['meshes'].items():
                mesh['bounds_mm']['max'][2]=self.profile.raw['revision_heights_mm'][report['revision'] if name=='PrintCandidate' else 'r0']
        self.assertEqual(verify(data,self.profile)['status'],'closed_candidates')
        for key,value in (('profile_id',DEFAULT_PROFILE_ID),('profile_sha256',self.v1.sha256)):
            changed=copy.deepcopy(data);changed[1][key]=value
            with self.assertRaisesRegex(ValueError,'different print profile'):verify(changed,self.profile)
        data[0]['meshes']['PrintCandidate']['bounds_mm']['max'][2]=92.1265640258789
        with self.assertRaises(ValueError):verify(data,self.profile)

    def test_each_source_export_reimport_baseline_and_render_binding_is_fixed(self):
        good={'profile_id':X1C_PROFILE_ID,'profile_sha256':self.profile.sha256}
        for index in range(5):
            rows=[good.copy() for _ in range(5)]
            for edit in ({'profile_id':DEFAULT_PROFILE_ID},{'profile_sha256':self.v1.sha256},{}):
                rows[index]=good|edit if edit else {}
                with self.assertRaisesRegex(ValueError,'different print profile'):require_profile_binding(self.profile,*rows)

    def test_new_protected_policy_cannot_use_previous_base_or_boxes(self):
        fixture=test_print_preservation.PrintPreservationTests();fixture.setUp();fixture.profile=self.profile
        for report in (fixture.source,fixture.exported,fixture.result,fixture.baseline):
            report.update(profile_id=X1C_PROFILE_ID,profile_sha256=self.profile.sha256)
            for mesh in report['meshes'].values():
                if 'bounds_mm' in mesh:mesh['bounds_mm']['max'][2]=100.0
                for revision,row in mesh.get('protected_regions',{}).items():
                    row['excluded_box_mm']=protected_boxes(self.profile)[revision]
        self.assertFalse(fixture.assess()['failures'])
        fixture.baseline['profile_sha256']=self.v1.sha256
        with self.assertRaisesRegex(ValueError,'different print profile'):fixture.assess()
        fixture.baseline['profile_sha256']=self.profile.sha256
        fixture.result['meshes']['PrintCandidate']['protected_regions']['r2']['excluded_box_mm']=protected_boxes(self.v1)['r2']
        with self.assertRaisesRegex(ValueError,'protected-region scope'):fixture.assess()


if __name__=='__main__':unittest.main()
