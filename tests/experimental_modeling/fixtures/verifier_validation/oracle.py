# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent fixture oracle, standard library only.

No production or author imports. The tetrahedron's named vertices, directed
face boundaries, constant colors and outward normals are hand-derived below.
Artifact GLB vertex splitting is matched to those names by measured coordinates;
that is a test of export fidelity, not a claim of policy vertex-reindex support.
"""
from collections import Counter
import math

POINTS = {'O': (0., 0., 0.), 'X': (.04, 0., 0.), 'Y': (0., .03, 0.), 'Z': (0., 0., .02)}
# Looking from outside: bottom winds O->Y->X, front O->X->Z,
# left O->Z->Y, and sloping plane X->Y->Z. Plane equation
# x/.04 + y/.03 + z/.02 = 1 gives unit normal (3,4,6)/sqrt(61).
FACES = {
    'floor': {'boundary': ('O', 'Y', 'X'), 'normal': (0., 0., -1.), 'color': 'Cobalt'},
    'south': {'boundary': ('O', 'X', 'Z'), 'normal': (0., -1., 0.), 'color': 'Ember'},
    'west': {'boundary': ('O', 'Z', 'Y'), 'normal': (-1., 0., 0.), 'color': 'Cobalt'},
    'slope': {'boundary': ('X', 'Y', 'Z'), 'normal': (3/math.sqrt(61), 4/math.sqrt(61), 6/math.sqrt(61)), 'color': 'Ember'},
}
COLORS = {'Cobalt': (.04, .20, .80, 1.), 'Ember': (.85, .12, .04, 1.)}


def angle(a, b):
    if len(a) != 3 or len(b) != 3 or any(not math.isfinite(x) for x in (*a, *b)):
        raise AssertionError('Invalid measured normal')
    length_a, length_b = math.sqrt(sum(x*x for x in a)), math.sqrt(sum(x*x for x in b))
    if length_a < 1e-12 or length_b < 1e-12:
        raise AssertionError('Missing measured normal')
    cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    return math.atan2(math.sqrt(sum(x*x for x in cross)), sum(x*y for x, y in zip(a, b)))


def close_material(a, b, tolerance=1e-6):
    return (len(a['base_color']) == len(b['base_color']) == 4
            and max(abs(x-y) for x, y in zip(a['base_color'], b['base_color'])) <= tolerance
            and abs(a['metallic']-b['metallic']) <= tolerance
            and abs(a['roughness']-b['roughness']) <= tolerance)


def color_name(value):
    matches = [name for name, rgba in COLORS.items()
               if close_material(value, {'base_color': rgba, 'metallic': 0., 'roughness': .5})]
    assert len(matches) == 1, ('Unexpected independently measured material', value)
    return matches[0]


def boundary_edges(labels):
    return {(labels[index], labels[(index+1) % len(labels)]) for index in range(len(labels))}


def inspect_tetra(probe, height, *, tolerance, normal_tolerance):
    assert set(probe['parts']) == {'tetra'}
    assert probe['autoexec_enabled'] is False
    assert probe['scale_length'] == 1.
    part = probe['parts']['tetra']
    palette = [color_name(value) for value in part['palette']]
    assert len(palette) == 2 and set(palette) == set(COLORS), palette
    if probe['input_format'] == 'blend':
        assert palette == ['Cobalt', 'Ember'], 'Blend palette order changed'
        assert len(part['points']) == 4 and len(part['edges']) == 6
    names, point_errors = [], []
    expected = {name: (point[0], point[1], point[2] + height) for name, point in POINTS.items()}
    for point in part['points']:
        distances = {name: math.dist(point, coordinate) for name, coordinate in expected.items()}
        matches = [name for name, distance in distances.items() if distance <= tolerance]
        assert len(matches) == 1, ('Unexpected independently measured vertex', point, distances)
        names.append(matches[0]); point_errors.append(distances[matches[0]])
    assert set(names) == set(POINTS)
    assert len(part['faces']) == 4
    observed, material_errors, normal_errors, all_angles = {}, [], [], []
    incidence = Counter()
    for face in part['faces']:
        labels = tuple(names[index] for index in face['indices'])
        assert len(labels) == 3 and len(set(labels)) == 3
        matches = [name for name, wanted in FACES.items() if set(wanted['boundary']) == set(labels)]
        assert len(matches) == 1
        name = matches[0]; wanted = FACES[name]
        assert name not in observed, 'Repeated tetra face'
        assert boundary_edges(labels) == boundary_edges(wanted['boundary']), (name, 'wrong winding')
        for edge in boundary_edges(labels):
            incidence[tuple(sorted(edge))] += 1
        actual_color = palette[face['material_index']]
        if actual_color != wanted['color']:
            material_errors.append(name)
        assert len(face['corner_normals']) == 3
        errors = {}
        for label, normal in zip(labels, face['corner_normals']):
            error = angle(normal, wanted['normal']); errors[label] = error; all_angles.append(error)
            if error > normal_tolerance:
                normal_errors.append(name + '/' + label)
        observed[name] = {'boundary': labels, 'color': actual_color, 'normal_errors_radians': errors}
    assert set(observed) == set(FACES)
    assert len(incidence) == 6 and set(incidence.values()) == {2}, 'Tetrahedron is not closed'
    histogram = dict(Counter(face['color'] for face in observed.values()))
    return {'max_position_error_m': max(point_errors), 'max_normal_angle_deviation_radians': max(all_angles),
            'material_mismatch_faces': sorted(material_errors), 'normal_mismatch_corners': sorted(normal_errors),
            'palette': palette, 'material_histogram': histogram, 'named_faces': observed,
            'closed_edges': 6, 'face_count': 4, 'unique_named_vertices': 4}


def assert_tetra_case(report, defect, *, normal_tolerance):
    assert report['material_histogram'] == {'Cobalt': 2, 'Ember': 2}, report
    assert report['material_mismatch_faces'] == (['floor', 'south'] if defect == 'material' else []), report
    assert report['normal_mismatch_corners'] == (['floor/O'] if defect == 'normal' else []), report
    if defect == 'normal':
        # A known 0.12rad single-loop error, well above the explicit tolerance.
        assert abs(report['max_normal_angle_deviation_radians'] - .12) < normal_tolerance, report
    else:
        assert report['max_normal_angle_deviation_radians'] <= normal_tolerance, report


def indexed_translation(before, after, delta, *, tolerance, normal_tolerance):
    """Independent lamp check: face lookup by directed-edge sets, not sorting.

    Assumes indexed vertex correspondence as does the bounded v2 policy. A
    directed boundary set proves winding for these unique-vertex lamp faces;
    duplicate oriented face keys are rejected rather than guessed.
    """
    assert len(before['points']) == len(after['points'])
    point_error = max(math.dist(new, [old[i]+delta[i] for i in range(3)])
                      for old, new in zip(before['points'], after['points']))
    assert point_error <= tolerance, point_error
    assert len(before['palette']) == len(after['palette'])
    assert all(close_material(a, b) for a, b in zip(before['palette'], after['palette']))
    assert Counter(frozenset(edge) for edge in before['edges']) == Counter(frozenset(edge) for edge in after['edges'])
    def keyed(part):
        result = {}
        for face in part['faces']:
            indices = face['indices']
            assert len(indices) == len(set(indices))
            key = frozenset(boundary_edges(indices))
            assert key not in result, 'Duplicate oriented polygon has no independent correspondence'
            assert len(face['corner_normals']) == len(indices)
            result[key] = (face['material_index'], dict(zip(indices, face['corner_normals'])))
        return result
    old_faces, new_faces = keyed(before), keyed(after)
    assert old_faces.keys() == new_faces.keys(), 'Indexed oriented topology changed'
    maximum = 0.
    for key, (material_index, corners) in old_faces.items():
        new_material, new_corners = new_faces[key]
        assert material_index == new_material, 'Face material attachment changed'
        for vertex, normal in corners.items():
            maximum = max(maximum, angle(normal, new_corners[vertex]))
    assert maximum <= normal_tolerance, maximum
    return {'max_position_error_m': point_error, 'max_normal_angle_deviation_radians': maximum,
            'oriented_faces': len(old_faces),
            'raw_face_order_changed': [face['indices'] for face in before['faces']] != [face['indices'] for face in after['faces']],
            'raw_edge_serialization_changed': before['edges'] != after['edges']}
