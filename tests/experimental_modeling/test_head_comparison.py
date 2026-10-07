# SPDX-License-Identifier: GPL-3.0-or-later
"""Reject partial, altered, thin or mislabeled head comparison evidence."""
import copy
import unittest

from tests.experimental_modeling.run_anime_cat_head_comparison import COMPARISON_ID, OBSERVER_SHA, verify_pair


def evidence(revision='r0'):
    mesh = {'non_manifold_edges': 0, 'boundary_edges': 0, 'non_manifold_vertices': 0,
            'loose_vertices': 0, 'inconsistent_winding_edges': 0, 'degenerate_triangles': 0,
            'self_intersections': 0, 'measured_triangles': 383540, 'evaluated_triangles': 383540,
            'face_connected_shells': 1, 'intersection_measurement': {'complete': True},
            'signed_volume_mm3': 135150.0, 'dimensions_mm': [44.2-(-32.5), 19.7-(-27.6), 100.0],
            'bounds_mm': {'min': [-32.5, -27.6, 0], 'max': [44.2, 19.7, 100]},
            'exact_surface_sha256': 'a'*64, 'feature_probes': {
                'minimum_mm': 2.59, 'coverage': 'partial', 'sample_count': 32,
                'samples': [{'feature': f'whisker-{sign}-{index}', 'chords': 8,
                             'minimum_chord_mm': 2.59} for sign in (-1, 1) for index in range(2)]}}
    if revision != 'r0':
        mesh['feature_probes']['samples'].append({
            'feature': 'hat-brim' if revision == 'r1' else 'glasses-bridge',
            'chords': 1 if revision == 'r1' else 8, 'minimum_chord_mm': 3.0})
        mesh['feature_probes']['sample_count'] += 1 if revision == 'r1' else 8
    if revision == 'r1':
        mesh['dimensions_mm'][2] = mesh['bounds_mm']['max'][2] = 108.54632568359375
    return {'comparison_id': COMPARISON_ID, 'revision': revision, 'unit': 'millimeter',
            'observer_sha256': OBSERVER_SHA, 'promotion_eligible': False,
            'physical_validation': 'pending', 'feature_coverage': 'unknown',
            'body_exterior_bit_exact': True, 'accessory_exterior_bit_exact': None if revision == 'r0' else True,
            'ear_partial_probes': {'minimum_chord_mm': 11.56, 'coverage': 'partial',
                                   'sample_count': 18, 'chords_mm': [11.56]*18}, 'mesh': mesh}


class HeadComparisonTests(unittest.TestCase):
    def test_complete_geometry_comparison_retains_pending_acceptance(self):
        for revision in ('r0', 'r1', 'r2'):
            source = evidence(revision)
            self.assertEqual(verify_pair(source, copy.deepcopy(source)), source['mesh'])

    def test_each_incomplete_or_invalid_geometry_result_fails(self):
        edits = [('self_intersections', 1), ('non_manifold_vertices', 1),
                 ('face_connected_shells', True), ('measured_triangles', 500001),
                 ('evaluated_triangles', 1), ('signed_volume_mm3', -1),
                 ('intersection_measurement', {'complete': False})]
        for key, value in edits:
            with self.subTest(key=key), self.assertRaises(ValueError):
                source = evidence();source['mesh'][key] = value
                verify_pair(source, evidence())

    def test_changed_body_accessory_or_roundtrip_surface_fails(self):
        source = evidence();source['body_exterior_bit_exact'] = False
        with self.assertRaises(ValueError):verify_pair(source, evidence())
        source = evidence('r2');source['accessory_exterior_bit_exact'] = False
        stl = copy.deepcopy(source)
        with self.assertRaises(ValueError):verify_pair(source, stl)
        stl = evidence();stl['mesh']['exact_surface_sha256'] = 'b'*64
        with self.assertRaises(ValueError):verify_pair(evidence(), stl)

    def test_print_acceptance_unknowns_and_baseline_identity_cannot_be_promoted(self):
        for key, value in [('comparison_id', 'anime-cat-x1c-pla-04-bare100-v3'),
                           ('promotion_eligible', True), ('feature_coverage', 'complete'),
                           ('physical_validation', 'passed'), ('observer_sha256', 'b'*64)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                source = evidence();source[key] = value
                verify_pair(source, evidence())

    def test_thin_ear_and_unscaled_geometry_fail_existing_limits(self):
        source = evidence();source['ear_partial_probes']['minimum_chord_mm'] = 1.0
        with self.assertRaises(ValueError):verify_pair(source, evidence())

    def test_nonfinite_or_boolean_measurements_cannot_pass(self):
        for invalid in (float('nan'), float('inf'), float('-inf'), True):
            edits = [('mesh', 'signed_volume_mm3'), ('mesh', 'dimensions_mm', 0),
                     ('mesh', 'bounds_mm', 'min', 2), ('mesh', 'bounds_mm', 'max', 0),
                     ('mesh', 'feature_probes', 'minimum_mm'),
                     ('mesh', 'feature_probes', 'samples', 0, 'minimum_chord_mm'),
                     ('ear_partial_probes', 'minimum_chord_mm'),
                     ('ear_partial_probes', 'chords_mm', 0)]
            for path in edits:
                with self.subTest(invalid=invalid, path=path), self.assertRaises(ValueError):
                    source = evidence();container = source
                    for key in path[:-1]:container = container[key]
                    container[path[-1]] = invalid
                    verify_pair(source, copy.deepcopy(source))

    def test_missing_or_mislabeled_partial_samples_cannot_pass(self):
        for kind, key, value in [('feature_probes', 'sample_count', 31),
                                 ('feature_probes', 'coverage', 'complete'),
                                 ('ear_partial_probes', 'sample_count', 17),
                                 ('ear_partial_probes', 'coverage', 'complete'),
                                 ('ear_partial_probes', 'chords_mm', [11.56]*17)]:
            with self.subTest(kind=kind, key=key), self.assertRaises(ValueError):
                source = evidence()
                target = source['mesh'][kind] if kind == 'feature_probes' else source[kind]
                target[key] = value
                verify_pair(source, copy.deepcopy(source))
        source = evidence();source['mesh']['dimensions_mm'][2] = 1000
        with self.assertRaises(ValueError):verify_pair(source, evidence())


if __name__ == '__main__':
    unittest.main()
