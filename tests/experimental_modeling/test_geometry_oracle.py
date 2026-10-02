# SPDX-License-Identifier: GPL-3.0-or-later
"""Mutation tests for the standalone geometry oracle, without Blender.

Probe-shaped data here are hand-authored synthetic measurements. These test the
oracle's rejection power; they do not claim artifact export or policy execution.
No production or fixture-author module supplies expected geometry or normals.
"""
import copy
import importlib.util
import math
from pathlib import Path
import unittest

_PATH = Path(__file__).with_name('fixtures') / 'verifier_validation' / 'geometry_oracle.py'
_SPEC = importlib.util.spec_from_file_location('independent_geometry_oracle', _PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
inspect_geometry = _MODULE.inspect_geometry


# These raw, synthetic records intentionally do not use oracle data/builders.
_BOX = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
_L = ((5, 4, 3, 2, 1, 0), (6, 7, 8, 9, 10, 11),
      (0, 1, 7, 6), (1, 2, 8, 7), (2, 3, 9, 8),
      (3, 4, 10, 9), (4, 5, 11, 10), (5, 0, 6, 11))
_TOP = ((6, 7, 9), (7, 8, 9), (6, 9, 11), (9, 10, 11))
_BOTTOM = ((0, 3, 1), (1, 3, 2), (0, 5, 3), (3, 5, 4))
_FLAT = ((0, 0, -1), (0, 0, 1), (0, -1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0))
_PALETTE = ({'base_color': [.04, .20, .80, 1.], 'metallic': 0., 'roughness': .5},
            {'base_color': [.85, .12, .04, 1.], 'metallic': 0., 'roughness': .5})


def _edges(faces):
    return [list(edge) for edge in sorted({tuple(sorted((indices[i], indices[(i+1) % len(indices)])))
            for face in faces for indices in (face['indices'],) for i in range(len(indices))})]


def _part(points, boundaries, normals, *, matrix, glb, base=False, fixture='box', retessellation=False,
          top_triangles=None, split=True):
    faces = []
    output_points = [] if glb and split else copy.deepcopy(points)
    for ordinal, boundary in enumerate(boundaries):
        if glb:
            if fixture == 'l_prism' and not base and ordinal == 0:
                rows = _BOTTOM
            elif fixture == 'l_prism' and not base and ordinal == 1:
                rows = _TOP if top_triangles is None else top_triangles
            else:
                rows = tuple((boundary[0], boundary[i], boundary[i+1]) for i in range(1, len(boundary)-1))
        elif retessellation and ordinal == 1 and not base:
            rows = _TOP
        else:
            rows = (boundary,)
        for labels in rows:
            corner_normals = []
            for label in labels:
                if not base and fixture == 'box' and ordinal == 0 and label == 0:
                    normal = tuple(n/math.sqrt(4525) for n in (36., 27., -50.))
                else:
                    normal = normals[ordinal]
                corner_normals.append(list(normal))
            if glb and split:
                indices = list(range(len(output_points), len(output_points)+len(labels)))
                output_points.extend(copy.deepcopy(points[label]) for label in labels)
            else:
                indices = list(labels)
            faces.append({'indices': indices, 'corner_normals': corner_normals,
                          'material_index': 0 if base else ordinal % 2})
    return {'points': output_points, 'edges': _edges(faces), 'faces': faces,
            'palette': copy.deepcopy(list(_PALETTE[:1] if base else _PALETTE)),
            'matrix_world': copy.deepcopy(matrix)}


def _probe(fixture='box', step=0, defect='none', fmt='blend', top_triangles=None, split=True):
    glb = fmt == 'glb'
    if fixture == 'box':
        h = .024 if defect == 'deformation' else .02
        local = ((0., 0., 0.), (.04, 0., 0.), (.04, .03, 0.), (0., .03, 0.),
                 (0., 0., h), (.04, 0., h), (.04, .03, h), (0., .03, h))
        points = [[x-.45*y+.11+.015*step, .75*x+.6*y-.07-.02*step, 1.5*z+.09+.03*step]
                  for x, y, z in local]
        normals = ((0, 0, -1), (0, 0, 1), (.6, -.8, 0), (.8, .6, 0), (-.6, .8, 0), (-.8, -.6, 0))
        boundaries = _BOX
        matrix = [[1., -.45, 0., .11+.015*step], [.75, .6, 0., -.07-.02*step],
                  [0., 0., 1.5, .09+.03*step], [0., 0., 0., 1.]]
    else:
        footprint = ((0., 0.), (.06, 0.), (.06, .02), (.02, .02), (.02, .05), (0., .05))
        points = [[x-.09+.015*step, y+.08-.02*step, z+.07+.03*step]
                  for z in (0., .03) for x, y in footprint]
        normals = ((0, 0, -1), (0, 0, 1), (0, -1, 0), (1, 0, 0),
                   (0, 1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0))
        boundaries = _L
        matrix = [[1., 0., 0., -.09+.015*step], [0., 1., 0., .08-.02*step],
                  [0., 0., 1., .07+.03*step], [0., 0., 0., 1.]]
    body = _part(points, boundaries, normals, matrix=matrix, glb=glb, fixture=fixture,
                 retessellation=defect == 'retessellation', top_triangles=top_triangles, split=split)
    base_points = [[x + (.005 if defect == 'protected_base' else 0.), y, z]
                   for x, y, z in ((-.04, -.03, -.01), (.04, -.03, -.01), (.04, .03, -.01), (-.04, .03, -.01),
                                   (-.04, -.03, 0.), (.04, -.03, 0.), (.04, .03, 0.), (-.04, .03, 0.))]
    base_matrix = [[1., 0., 0., -.035 if defect == 'protected_base' else -.04],
                   [0., 1., 0., -.03], [0., 0., 1., -.01], [0., 0., 0., 1.]]
    base = _part(base_points, _BOX, _FLAT, matrix=base_matrix, glb=glb, base=True, split=split)
    return {'probe_schema_version': 1, 'input_format': fmt, 'autoexec_enabled': False,
            'scale_length': 1., 'parts': {'body': body, 'base': base}}


def _inspect(probe, fixture='box', step=0, defect='none'):
    return inspect_geometry(probe, fixture, step, defect, tolerance=1e-7, normal_tolerance=1e-5)


class IndependentGeometryOracleTests(unittest.TestCase):
    def test_all_declared_cases_both_artifact_formats_and_revisions(self):
        for fixture in ('box', 'l_prism'):
            for defect in ('none', 'protected_base', 'deformation' if fixture == 'box' else 'retessellation'):
                for fmt in ('blend', 'glb'):
                    for step in (0, 1, 2):
                        with self.subTest(fixture=fixture, defect=defect, fmt=fmt, step=step):
                            report = _inspect(_probe(fixture, step, defect, fmt), fixture, step, defect)
                            self.assertLess(report['max_position_error_m'], 1e-14)
                            self.assertLess(report['max_matrix_element_error'], 1e-14)
                            self.assertLess(report['max_normal_angle_deviation_radians'], 1e-14)
                            self.assertEqual(report['parts']['body']['render_triangles'], 12 if fixture == 'box' else 20)
                            self.assertEqual(report['parts']['base']['render_triangles'], 12)

    def test_hand_derived_metrics_and_native_polygon_counts(self):
        box = _inspect(_probe())['parts']['body']
        self.assertEqual((box['vertices'], box['edges'], box['polygons'], box['render_triangles']), (8, 12, 6, 12))
        for actual, expected in zip(box['world_axis_dimensions_m'], (.0535, .048, .03)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(box['reference_edge_lengths_m'], (.05, .0225, .03))
        self.assertAlmostEqual(box['surface_area_m2'], .0066)
        self.assertAlmostEqual(box['signed_volume_m3'], .00003375)
        for defect, counts in (('none', (12, 18, 8, 20)), ('retessellation', (12, 21, 11, 20))):
            report = _inspect(_probe('l_prism', defect=defect), 'l_prism', defect=defect)['parts']['body']
            self.assertEqual(tuple(report[k] for k in ('vertices', 'edges', 'polygons', 'render_triangles')), counts)
            self.assertAlmostEqual(report['surface_area_m2'], .0102)
            self.assertAlmostEqual(report['signed_volume_m3'], .000054)

    def test_glb_accepts_valid_alternate_l_diagonal_with_split_indices(self):
        alternate = ((6, 7, 8), (6, 8, 9), (6, 9, 10), (6, 10, 11))
        for split in (False, True):
            with self.subTest(split=split):
                probe = _probe('l_prism', fmt='glb', top_triangles=alternate, split=split)
                report = _inspect(probe, 'l_prism')['parts']['body']
                self.assertEqual(report['unique_named_vertices'], 12)
                self.assertEqual(report['vertices'], 60 if split else 12)
                top = report['original_face_coverage']['top']
                self.assertTrue(top['signed_boundary_verified'])
                self.assertTrue(top['containment_verified'])
                self.assertEqual(top['overlap_area_m2'], 0.)
                self.assertAlmostEqual(top['area_m2'], .0018)

    def test_l_rejects_triangle_outside_concave_outline(self):
        triangles = ((6, 7, 10),) + _TOP[1:]
        with self.assertRaisesRegex(AssertionError, 'outside original face'):
            _inspect(_probe('l_prism', fmt='glb', top_triangles=triangles), 'l_prism')

    def test_l_rejects_positive_area_triangle_overlap(self):
        triangles = (_TOP[0], _TOP[0], _TOP[2], _TOP[3])
        with self.assertRaisesRegex(AssertionError, 'Triangle overlap'):
            _inspect(_probe('l_prism', fmt='glb', top_triangles=triangles), 'l_prism')

    def test_l_rejects_gap_in_top_coverage(self):
        with self.assertRaisesRegex(AssertionError, 'Incomplete face area coverage'):
            _inspect(_probe('l_prism', fmt='glb', top_triangles=_TOP[1:]), 'l_prism')

    def test_l_rejects_reversed_triangle(self):
        triangles = ((_TOP[0][0], _TOP[0][2], _TOP[0][1]),) + _TOP[1:]
        with self.assertRaisesRegex(AssertionError, 'wrong-winding triangle'):
            _inspect(_probe('l_prism', fmt='glb', top_triangles=triangles), 'l_prism')

    def test_l_rejects_degenerate_triangle(self):
        triangles = ((6, 7, 7),) + _TOP[1:]
        with self.assertRaisesRegex(AssertionError, 'Degenerate named polygon'):
            _inspect(_probe('l_prism', fmt='glb', top_triangles=triangles), 'l_prism')

    def test_box_rejects_forward_transform_in_place_of_inverse_transpose(self):
        probe = _probe()
        # This is normalized A*n instead of A^-T*n, a plausible correlated bug.
        wrong = (.6, .45, -1.2)
        length = math.sqrt(sum(x*x for x in wrong))
        probe['parts']['body']['faces'][0]['corner_normals'][0] = [x/length for x in wrong]
        with self.assertRaisesRegex(AssertionError, 'Incorrect independently expected corner normal'):
            _inspect(probe)

    def test_box_glb_rejects_normal_attached_to_wrong_named_corner(self):
        probe = _probe(fmt='glb')
        normals = probe['parts']['body']['faces'][0]['corner_normals']
        normals[0], normals[1] = normals[1], normals[0]
        with self.assertRaisesRegex(AssertionError, 'Incorrect independently expected corner normal'):
            _inspect(probe)

    def test_rejects_missing_corner_normal_in_both_formats(self):
        for fmt in ('blend', 'glb'):
            probe = _probe(fmt=fmt)
            probe['parts']['body']['faces'][0]['corner_normals'].pop()
            with self.subTest(fmt=fmt), self.assertRaisesRegex(AssertionError, 'Missing corner normal'):
                _inspect(probe)

    def test_rejects_missing_named_vertex_in_both_formats(self):
        for fmt in ('blend', 'glb'):
            probe = _probe(fmt=fmt)
            part = probe['parts']['body']
            part['points'] = [point for point in part['points']
                              if math.dist(point, (.0965, -.052, .12)) > 1e-12]
            with self.subTest(fmt=fmt), self.assertRaisesRegex(AssertionError, 'Missing named corner'):
                _inspect(probe)

    def test_rejects_material_swap_despite_unchanged_histogram(self):
        probe = _probe()
        faces = probe['parts']['body']['faces']
        faces[0]['material_index'], faces[1]['material_index'] = faces[1]['material_index'], faces[0]['material_index']
        with self.assertRaisesRegex(AssertionError, 'Material attached to wrong face'):
            _inspect(probe)

    def test_rejects_body_deformation_unless_explicit_negative_case(self):
        for fmt in ('blend', 'glb'):
            with self.subTest(fmt=fmt), self.assertRaisesRegex(AssertionError, 'Unexpected independently measured vertex'):
                _inspect(_probe(defect='deformation', fmt=fmt))

    def test_rejects_identity_baked_body_even_with_correct_world_geometry(self):
        for fixture in ('box', 'l_prism'):
            for fmt in ('blend', 'glb'):
                probe = _probe(fixture, step=2, fmt=fmt)
                probe['parts']['body']['matrix_world'] = [[1., 0., 0., 0.], [0., 1., 0., 0.],
                                                         [0., 0., 1., 0.], [0., 0., 0., 1.]]
                with self.subTest(fixture=fixture, fmt=fmt), self.assertRaisesRegex(AssertionError, 'matrix_world'):
                    _inspect(probe, fixture, step=2)

    def test_rejects_wrong_base_transform_even_with_correct_world_geometry(self):
        for fixture in ('box', 'l_prism'):
            for fmt in ('blend', 'glb'):
                for defect in ('none', 'protected_base'):
                    probe = _probe(fixture, step=1, defect=defect, fmt=fmt)
                    probe['parts']['base']['matrix_world'][0][3] += .005
                    with self.subTest(fixture=fixture, fmt=fmt, defect=defect), self.assertRaisesRegex(AssertionError, 'matrix_world'):
                        _inspect(probe, fixture, step=1, defect=defect)

    def test_rejects_protected_base_move_unless_explicit_negative_case(self):
        for fixture in ('box', 'l_prism'):
            for fmt in ('blend', 'glb'):
                with self.subTest(fixture=fixture, fmt=fmt), self.assertRaisesRegex(AssertionError, 'Unexpected independently measured matrix_world'):
                    _inspect(_probe(fixture, defect='protected_base', fmt=fmt), fixture)

    def test_declared_negative_case_cannot_silently_remain_baseline(self):
        for fixture, defect in (('box', 'deformation'), ('l_prism', 'retessellation'), ('box', 'protected_base')):
            with self.subTest(fixture=fixture, defect=defect), self.assertRaises(AssertionError):
                _inspect(_probe(fixture), fixture, defect=defect)

    def test_blend_accepts_cyclic_starts_but_rejects_reversed_winding(self):
        probe = _probe()
        face = probe['parts']['body']['faces'][0]
        for key in ('indices', 'corner_normals'):
            face[key] = face[key][1:]+face[key][:1]
        _inspect(probe)
        for key in ('indices', 'corner_normals'):
            face[key].reverse()
        with self.assertRaisesRegex(AssertionError, 'Unexpected oriented Blend boundary'):
            _inspect(probe)

    def test_rejects_loose_or_missing_edges(self):
        for mode in ('loose', 'missing'):
            probe = _probe()
            edges = probe['parts']['body']['edges']
            edges.append([0, 6]) if mode == 'loose' else edges.pop()
            with self.subTest(mode=mode), self.assertRaisesRegex(AssertionError, 'Raw edge inventory'):
                _inspect(probe)

    def test_rejects_nonfinite_positions_and_zero_normals(self):
        probe = _probe()
        probe['parts']['body']['points'][0][0] = math.nan
        with self.assertRaisesRegex(AssertionError, 'Invalid measured point'):
            _inspect(probe)
        probe = _probe()
        probe['parts']['body']['faces'][0]['corner_normals'][0] = [0., 0., 0.]
        with self.assertRaisesRegex(AssertionError, 'Degenerate vector'):
            _inspect(probe)

    def test_honors_position_and_normal_tolerances(self):
        probe = _probe()
        probe['parts']['body']['points'][0][0] += 2e-8
        _inspect(probe)
        probe['parts']['body']['points'][0][0] += 2e-6
        with self.assertRaisesRegex(AssertionError, 'Unexpected independently measured vertex'):
            _inspect(probe)
        probe = _probe()
        probe['parts']['body']['faces'][1]['corner_normals'][0] = [1e-7, 0., 1.]
        _inspect(probe)
        probe['parts']['body']['faces'][1]['corner_normals'][0] = [.01, 0., 1.]
        with self.assertRaisesRegex(AssertionError, 'Incorrect independently expected corner normal'):
            _inspect(probe)


if __name__ == '__main__':
    unittest.main()
