# SPDX-License-Identifier: GPL-3.0-or-later
"""A new planar base may never reuse either historical profile identity."""
from pathlib import Path
import unittest

from experimental_modeling.print_contract import DEFAULT_PROFILE_ID, X1C_PROFILE_ID, X1C_BAMBU_PROFILE_ID, PrintProfile
from experimental_modeling.print_preservation import protected_boxes, require_profile_binding

FIXTURE=Path(__file__).resolve().parents[2]/'experimental_modeling/examples/anime_cat/print'


class BambuProfileTests(unittest.TestCase):
    def setUp(self):
        self.v1=PrintProfile.reviewed(DEFAULT_PROFILE_ID)
        self.v2=PrintProfile.reviewed(X1C_PROFILE_ID)
        self.v3=PrintProfile.load(FIXTURE/'x1c_pla_bare100_v3.json')

    def test_legacy_defaults_and_canonical_identities_remain_immutable(self):
        self.assertEqual(PrintProfile.reviewed(),self.v1)
        self.assertEqual(self.v1.sha256,'0c718776d23213ce6182ca0cf302b6e48827a2205d6a9f8fe69f381e4b646f32')
        self.assertEqual(self.v2.sha256,'7c7f84e3749e08d24bb163e3364e4831278ba3908f780f1b44ac2b0a928da915')
        self.assertEqual(self.v2.author_entry,'builder_x1c.py')
        self.assertEqual(self.v2.derivation_entry,'x1c_solids.py')

    def test_new_version_changes_only_modeling_identity_and_author_routes(self):
        self.assertEqual(self.v3.sha256,'8283c21798d388a16f979b085ca0940707bf0f0367630ec59b5643464efe0f7b')
        self.assertEqual(self.v3.raw,self.v2.raw|{'profile_id':X1C_BAMBU_PROFILE_ID})
        self.assertEqual(self.v3.fixture_name,'x1c_pla_bare100_v3.json')
        self.assertEqual(self.v3.author_entry,'builder_x1c_v3.py')
        self.assertEqual(self.v3.derivation_entry,'x1c_bambu_solids.py')
        self.assertEqual(self.v3.final_scale,self.v2.final_scale)
        self.assertEqual(self.v3.mm_per_source_meter,self.v2.mm_per_source_meter)

    def test_all_geometry_and_protected_box_limits_are_unchanged(self):
        for key in ('minimum_feature_mm','height_tolerance_mm','maximum_triangles','maximum_dimension_mm','revision_heights_mm'):
            self.assertEqual(self.v3.raw[key],self.v2.raw[key])
        self.assertEqual(protected_boxes(self.v3),protected_boxes(self.v2))

    def test_every_mixed_source_export_reference_or_render_version_rejects(self):
        profiles=(self.v1,self.v2,self.v3)
        for target in profiles:
            good={'profile_id':target.profile_id,'profile_sha256':target.sha256}
            for other in profiles:
                if other==target:continue
                for index in range(5):
                    with self.subTest(target=target.profile_id,other=other.profile_id,index=index):
                        reports=[good.copy() for _ in range(5)]
                        reports[index]={'profile_id':other.profile_id,'profile_sha256':other.sha256}
                        with self.assertRaisesRegex(ValueError,'different print profile'):
                            require_profile_binding(target,*reports)

    def test_new_version_cannot_relax_frozen_thresholds_or_dimensions(self):
        for edit in ({'height_tolerance_mm':2.0},{'minimum_feature_mm':.4},{'maximum_triangles':600000},
                     {'revision_heights_mm':{'r0':99.0,'r1':108.54632543541882,'r2':99.0}},
                     {'profile_id':'anime-cat-x1c-pla-04-bare100-v4'},{'status':'accepted'}):
            with self.subTest(edit=edit),self.assertRaises(ValueError):PrintProfile.parse(self.v3.raw|edit)

    def test_mutable_raw_and_noncanonical_constructor_cannot_change_profile(self):
        raw=self.v3.raw;raw['maximum_triangles']=1000000
        self.assertEqual(self.v3.raw['maximum_triangles'],500000)
        with self.assertRaises(ValueError):PrintProfile(bytearray(self.v3._json))


if __name__=='__main__':unittest.main()
