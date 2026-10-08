# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed regressions for complete print-candidate observations."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_anime_cat_print import FIXTURE, PrintProfile, verify


def reports():
    result = []
    for revision in ('r0','r1','r2'):
        base = {'non_manifold_edges':0,'non_manifold_vertices':0,'loose_vertices':0,
                'inconsistent_winding_edges':0,'degenerate_triangles':0,'self_intersections':0,
                'intersection_measurement':{'complete':True},'face_connected_shells':1,'evaluated_triangles':1000,'measured_triangles':1000,
                'signed_volume_mm3':100000,'surface_sha256':'a'*64,
                'bounds_mm':{'min':[-30,-26,0],'max':[40,19,92.2]}}
        candidate = copy.deepcopy(base)
        if revision == 'r1':
            candidate['bounds_mm']['max'][2] = 100
        if revision != 'r0':
            candidate['surface_sha256'] = 'b'*64
        samples = [{'feature':f'whisker-{sign}-{i}','minimum_chord_mm':2.3,'chords':8}
                   for sign in (-1,1) for i in range(2)]
        if revision == 'r1':
            samples.append({'feature':'hat-brim','minimum_chord_mm':4.0,'chords':1})
        if revision == 'r2':
            samples.append({'feature':'glasses-bridge','minimum_chord_mm':2.4,'chords':8})
        candidate['feature_probes'] = {'minimum_mm':2.3,'sample_count':sum(s['chords'] for s in samples),
                                       'coverage':'partial','samples':samples}
        result.append({'revision':revision,'unit':'millimeter','promotion_eligible':False,
                       'meshes':{'PrintBase':base,'PrintCandidate':candidate}})
    return result


class PrintCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = PrintProfile.load(FIXTURE/'provisional_fdm_v1.json')

    def test_valid_candidate_still_has_unresolved_print_gates(self):
        result = verify(reports(), self.profile)
        self.assertEqual(result['status'],'closed_candidates')
        self.assertFalse(result['promotion_eligible'])
        self.assertEqual(result['feature_coverage'],'unknown')
        self.assertEqual(result['protected_regions'],'unknown')
        self.assertEqual(result['physical_validation'],'pending')

    def test_topology_and_intersection_failures(self):
        for field in ('non_manifold_edges','non_manifold_vertices','loose_vertices',
                      'inconsistent_winding_edges','degenerate_triangles','self_intersections'):
            with self.subTest(field=field):
                data = reports()
                data[2]['meshes']['PrintCandidate'][field] = 1
                with self.assertRaises(ValueError):
                    verify(data,self.profile)

    def test_touching_or_detached_shell_is_rejected(self):
        data = reports()
        data[1]['meshes']['PrintCandidate']['face_connected_shells'] = 2
        with self.assertRaises(ValueError):
            verify(data,self.profile)

    def test_measurement_cannot_substitute_a_small_cage(self):
        for changes in ({'evaluated_triangles':500001,'measured_triangles':500001},
                        {'evaluated_triangles':1000,'measured_triangles':12},
                        {'evaluated_triangles':True,'measured_triangles':True}):
            with self.subTest(changes=changes):
                data = reports()
                data[2]['meshes']['PrintCandidate'].update(changes)
                with self.assertRaises(ValueError):
                    verify(data,self.profile)

    def test_nonfinite_or_inverted_volume_is_rejected(self):
        for value in (float('nan'),float('inf'),-1,0,True):
            with self.subTest(value=value):
                data = reports()
                data[0]['meshes']['PrintBase']['signed_volume_mm3'] = value
                with self.assertRaises(ValueError):
                    verify(data,self.profile)

    def test_wrong_units_scale_and_ground_are_rejected(self):
        for unit, high, low in [('meter',92.2,0),('millimeter',3.0,0),
                                ('millimeter',200,0),('millimeter',92.2,1)]:
            with self.subTest(unit=unit,high=high,low=low):
                data = reports()
                data[0]['unit'] = unit
                data[0]['meshes']['PrintCandidate']['bounds_mm']['max'][2] = high
                data[0]['meshes']['PrintCandidate']['bounds_mm']['min'][2] = low
                with self.assertRaises(ValueError):
                    verify(data,self.profile)

    def test_base_mutation_is_rejected(self):
        data = reports()
        data[2]['meshes']['PrintBase']['surface_sha256'] = 'c'*64
        with self.assertRaises(ValueError):
            verify(data,self.profile)

    def test_thin_or_missing_feature_probes_are_rejected(self):
        for change in ({'minimum_mm':1.0},{'minimum_mm':float('nan')},
                        {'sample_count':0},{'sample_count':True},{'samples':[]}):
            with self.subTest(change=change):
                data = reports()
                data[2]['meshes']['PrintCandidate']['feature_probes'].update(change)
                with self.assertRaises(ValueError):
                    verify(data,self.profile)


if __name__ == '__main__':
    unittest.main()
