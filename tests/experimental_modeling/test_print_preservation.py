# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed linkage of complete STL, source and protected-base evidence."""
import copy
import unittest
from pathlib import Path

from experimental_modeling.print_contract import PrintProfile
from experimental_modeling.print_preservation import assess, BOXES, METHOD


class PrintPreservationTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[2]/'experimental_modeling/examples/anime_cat/print/provisional_fdm_v1.json'
        self.profile = PrintProfile.load(path)
        mesh = {'evaluated_triangles':1000,'measured_triangles':1000,
                'surface_sha256':'c'*64,'exact_surface_sha256':'d'*64,
                'face_connected_shells':1,'boundary_edges':0,'non_manifold_edges':0,
                'non_manifold_vertices':0,'loose_vertices':0,'inconsistent_winding_edges':0,
                'degenerate_triangles':0,'signed_volume_mm3':100000,
                'bounds_mm':{'min':[-34,-29,0],'max':[34,29,92.2]},
                'self_intersections':0,'intersection_measurement':{'complete':True},
                'feature_probes':{'minimum_mm':2,'sample_count':40},
                'protected_regions':{key:{'excluded_box_mm':copy.deepcopy(box),'triangles':900,
                                         'surface_sha256':'e'*64,'method':METHOD} for key,box in BOXES.items()}}
        self.source = {'revision':'r2','unit':'millimeter','input_sha256':'b'*64,
                       'measurement_source':'evaluated_saved_blend',
                       'meshes':{'PrintCandidate':copy.deepcopy(mesh),'PrintBase':copy.deepcopy(mesh)}}
        self.exported = {'unit':'millimeter','input_sha256':'b'*64,'meshes':{
            'PrintCandidate':{'evaluated_triangles':1000,'surface_sha256':'c'*64,
                              'exact_surface_sha256':'d'*64,'stl_sha256':'a'*64},
            'PrintBase':{'evaluated_triangles':1000,'exact_surface_sha256':'d'*64}}}
        self.result = {'revision':'r2','unit':'millimeter','measurement_source':'reimported_final_stl',
                       'input_sha256':'a'*64,'stl_triangle_count':1000,'meshes':{'PrintCandidate':copy.deepcopy(mesh)}}
        self.baseline = copy.deepcopy(self.result)
        self.baseline['revision'] = 'r0'
        for report in (self.source,self.exported,self.result,self.baseline):
            report.update(profile_id=self.profile.profile_id,profile_sha256=self.profile.sha256)
        self.hashes = {'stl_sha256':'a'*64,'source_observation_sha256':'f'*64,
                       'observer_sha256':'1'*64,'derivation_sha256':'2'*64}

    def assess(self):
        return assess(self.profile,'r2',self.source,self.exported,self.result,self.baseline,**self.hashes)

    def test_complete_evidence_still_requires_review_and_physical_validation(self):
        result = self.assess()
        self.assertEqual(result['measurement_gate'],'needs_review')
        self.assertEqual(result['unknowns'],['feature_coverage','visual_fidelity'])
        self.assertTrue(result['full_source_stl_surface_equal'])
        self.assertTrue(result['hat_region_matches_hat_free_base'])
        self.assertFalse(result['promotion_eligible'])
        self.assertEqual(result['physical_validation'],'pending')

    def test_exact_source_identity_required_even_when_rounded_hash_matches(self):
        self.source['meshes']['PrintCandidate']['exact_surface_sha256'] = '3'*64
        self.assertIn('roundtrip_surface',self.assess()['failures'])
        self.assertFalse(self.assess()['full_source_stl_surface_equal'])

    def test_cage_measurement_cannot_replace_full_source_or_stl(self):
        for report,key in ((self.source,'measured_triangles'),(self.result,'evaluated_triangles')):
            original = report['meshes']['PrintCandidate'][key]
            report['meshes']['PrintCandidate'][key] = 500
            self.assertIn('roundtrip_surface',self.assess()['failures'])
            report['meshes']['PrintCandidate'][key] = original

    def test_changed_final_surface_and_hidden_base_fail_independently(self):
        self.result['meshes']['PrintCandidate']['protected_regions']['r2']['surface_sha256'] = '3'*64
        result = self.assess()
        self.assertIn('protected_regions',result['failures'])
        self.assertFalse(result['hat_region_matches_hat_free_base'])
        self.assertTrue(result['hidden_base_unchanged'])
        self.result['meshes']['PrintCandidate']['protected_regions']['r2']['surface_sha256'] = 'e'*64
        self.exported['meshes']['PrintBase']['exact_surface_sha256'] = '3'*64
        result = self.assess()
        self.assertTrue(result['final_protected_surface_unchanged'])
        self.assertFalse(result['hidden_base_unchanged'])
        self.assertIn('protected_regions',result['failures'])

    def test_malformed_matching_fingerprints_and_impossible_counts_rejected(self):
        actual = self.result['meshes']['PrintCandidate']['protected_regions']['r2']
        expected = self.baseline['meshes']['PrintCandidate']['protected_regions']['r2']
        for key,value in (('surface_sha256',''),('surface_sha256','invalid'),
                          ('surface_sha256','E'*64),('triangles',True),('triangles',1001),('triangles',0)):
            with self.subTest(key=key,value=value):
                old = actual[key]; actual[key] = expected[key] = value
                with self.assertRaises(ValueError): self.assess()
                actual[key] = expected[key] = old

    def test_scope_and_boundary_method_cannot_be_weakened(self):
        for value in ('aabb_overlap_excluded','canonical_rounded_6'):
            self.result['meshes']['PrintCandidate']['protected_regions']['r2']['method'] = value
            with self.assertRaises(ValueError): self.assess()
        self.result['meshes']['PrintCandidate']['protected_regions']['r2']['method'] = METHOD
        self.result['meshes']['PrintCandidate']['protected_regions']['r2']['excluded_box_mm']['max'][2] = 110
        with self.assertRaises(ValueError): self.assess()

    def test_baseline_provenance_and_completeness_required(self):
        for key,value in (('revision','r1'),('unit','meter'),('measurement_source','source_scene'),
                          ('stl_triangle_count',999)):
            old = self.baseline[key]; self.baseline[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.assess()
            self.baseline[key] = old

    def test_invalid_baseline_geometry_cannot_authorize_preservation(self):
        mesh = self.baseline['meshes']['PrintCandidate']
        for key,value in (('boundary_edges',1),('face_connected_shells',2),('self_intersections',1),
                          ('signed_volume_mm3',-1),('measured_triangles',999)):
            old=mesh[key]; mesh[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): self.assess()
            mesh[key]=old
        mesh['intersection_measurement']['complete'] = False
        with self.assertRaises(ValueError): self.assess()

    def test_boolean_counts_cannot_pass_as_zero(self):
        mesh=self.result['meshes']['PrintCandidate']
        for key in ('self_intersections','evaluated_triangles','measured_triangles','boundary_edges'):
            old=mesh[key];mesh[key]=False
            with self.subTest(key=key),self.assertRaises(ValueError):self.assess()
            mesh[key]=old

    def test_wrong_export_or_input_digest_cannot_bind_evidence(self):
        self.source['input_sha256'] = self.exported['input_sha256'] = ''
        with self.assertRaises(ValueError): self.assess()
        self.source['input_sha256'] = self.exported['input_sha256'] = 'b'*64
        self.exported['meshes']['PrintCandidate']['stl_sha256'] = '3'*64
        self.assertIn('roundtrip_surface',self.assess()['failures'])
        self.result['input_sha256'] = '3'*64
        with self.assertRaises(ValueError): self.assess()


if __name__ == '__main__':
    unittest.main()
