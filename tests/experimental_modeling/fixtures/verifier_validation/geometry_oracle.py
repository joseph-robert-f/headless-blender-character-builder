# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent, analytic box/L-prism artifact oracle; standard library only.

This module imports neither author code nor production observation/comparison
code. Coordinates, material attachment, face boundaries, and inverse-transpose
normals below are hand-derived. GLB indices may split at export seams: they are
attached to named coordinates before checking each original face's coverage.
This is bounded fixture evidence, not general mesh or shading equivalence.
"""
from collections import Counter
import math


COLORS = {'Cobalt': (.04, .20, .80, 1.), 'Ember': (.85, .12, .04, 1.)}
DELTA = (.015, -.02, .03)
BOX_BOUNDARIES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                  (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
BOX_NAMES = ('bottom', 'top', 'south', 'east', 'north', 'west')
L_FOOTPRINT = ((0., 0.), (.06, 0.), (.06, .02), (.02, .02), (.02, .05), (0., .05))
L_TOP_TRIANGLES = ((6, 7, 9), (7, 8, 9), (6, 9, 11), (9, 10, 11))


def _sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _unit(a):
    length = math.sqrt(_dot(a, a))
    assert length > 1e-14, 'Degenerate vector'
    return tuple(x/length for x in a)


def _angle(a, b):
    assert len(a) == len(b) == 3 and all(math.isfinite(x) for x in (*a, *b)), 'Invalid corner normal'
    a, b = _unit(a), _unit(b)
    return math.atan2(math.sqrt(_dot(_cross(a, b), _cross(a, b))), _dot(a, b))


def _cycle(labels):
    return Counter((labels[i], labels[(i+1) % len(labels)]) for i in range(len(labels)))


def _color(value):
    assert len(value['base_color']) == 4
    numbers = (*value['base_color'], value['metallic'], value['roughness'])
    assert all(math.isfinite(x) for x in numbers), 'Nonfinite material'
    matches = [name for name, rgba in COLORS.items()
               if max(abs(x-y) for x, y in zip(value['base_color'], rgba)) <= 1e-6
               and abs(value['metallic']) <= 1e-6 and abs(value['roughness']-.5) <= 1e-6]
    assert len(matches) == 1, ('Unexpected material', value)
    return matches[0]


def _box_points(x, y, z):
    return ((0., 0., 0.), (x, 0., 0.), (x, y, 0.), (0., y, 0.),
            (0., 0., z), (x, 0., z), (x, y, z), (0., y, z))


def _specifications(fixture, step, defect):
    assert fixture in ('box', 'l_prism'), ('Unknown fixture', fixture)
    assert type(step) is int and step in (0, 1, 2), ('Invalid revision step', step)
    allowed = ('none', 'protected_base', 'deformation' if fixture == 'box' else 'retessellation')
    assert defect in allowed, ('Unknown fixture defect', fixture, defect)
    base_points = {i: (x-.04 + (.005 if defect == 'protected_base' else 0.), y-.03, z-.01)
                   for i, (x, y, z) in enumerate(_box_points(.08, .06, .01))}
    ordinary_normals = ((0., 0., -1.), (0., 0., 1.), (0., -1., 0.),
                        (1., 0., 0.), (0., 1., 0.), (-1., 0., 0.))
    base_faces = {name: {'boundary': boundary, 'normal': normal, 'color': 'Cobalt'}
                  for name, boundary, normal in zip(BOX_NAMES, BOX_BOUNDARIES, ordinary_normals)}
    base = {'points': base_points, 'faces': base_faces, 'mesh_faces': list(base_faces.items()),
            'surface_area': .0124, 'volume': .000048, 'edge_lengths': (.08, .06, .01),
            'matrix_world': ((1., 0., 0., -.04 + (.005 if defect == 'protected_base' else 0.)),
                             (0., 1., 0., -.03), (0., 0., 1., -.01), (0., 0., 0., 1.))}
    if fixture == 'box':
        height = .024 if defect == 'deformation' else .02
        points = {i: (x-.45*y+.11 + step*DELTA[0], .75*x+.6*y-.07 + step*DELTA[1],
                      1.5*z+.09 + step*DELTA[2])
                  for i, (x, y, z) in enumerate(_box_points(.04, .03, height))}
        # A's columns are orthogonal: scales 1.25, .75, 1.5 followed by
        # xy rotation (cos,sin)=(.8,.6). These are A^-T flat normals.
        normals = ((0., 0., -1.), (0., 0., 1.), (.6, -.8, 0.),
                   (.8, .6, 0.), (-.6, .8, 0.), (-.8, -.6, 0.))
        faces = {name: {'boundary': boundary, 'normal': normal,
                        'color': ('Cobalt', 'Ember')[i % 2]}
                 for i, (name, boundary, normal) in enumerate(zip(BOX_NAMES, BOX_BOUNDARIES, normals))}
        # Local custom normal (.6,0,-.8) is deliberately non-flat.
        # A^-T followed by normalization gives (36,27,-50)/sqrt(4525).
        faces['bottom']['corners'] = {0: tuple(n/math.sqrt(4525) for n in (36, 27, -50))}
        mesh_faces = list(faces.items())
        z = 1.5*height
        area, volume, lengths = 2*(.05*.0225 + .05*z + .0225*z), .05*.0225*z, (.05, .0225, z)
        matrix = ((1., -.45, 0., .11+step*DELTA[0]),
                  (.75, .6, 0., -.07+step*DELTA[1]),
                  (0., 0., 1.5, .09+step*DELTA[2]), (0., 0., 0., 1.))
    else:
        points = {i: (x-.09+step*DELTA[0], y+.08+step*DELTA[1], z+.07+step*DELTA[2])
                  for i, (x, y, z) in enumerate(tuple((x, y, 0.) for x, y in L_FOOTPRINT)
                                                + tuple((x, y, .03) for x, y in L_FOOTPRINT))}
        boundaries = ((5, 4, 3, 2, 1, 0), (6, 7, 8, 9, 10, 11)) + tuple(
            (i, (i+1) % 6, (i+1) % 6+6, i+6) for i in range(6))
        names = ('bottom', 'top') + tuple('side_'+str(i) for i in range(6))
        normals = ((0., 0., -1.), (0., 0., 1.), (0., -1., 0.), (1., 0., 0.),
                   (0., 1., 0.), (1., 0., 0.), (0., 1., 0.), (-1., 0., 0.))
        faces = {name: {'boundary': boundary, 'normal': normal,
                        'color': ('Cobalt', 'Ember')[i % 2]}
                 for i, (name, boundary, normal) in enumerate(zip(names, boundaries, normals))}
        mesh_faces = []
        for name, face in faces.items():
            if name == 'top' and defect == 'retessellation':
                mesh_faces.extend(('top/'+str(i), dict(face, boundary=triangle, original='top'))
                                  for i, triangle in enumerate(L_TOP_TRIANGLES))
            else:
                mesh_faces.append((name, face))
        area, volume, lengths = .0102, .000054, None
        matrix = ((1., 0., 0., -.09+step*DELTA[0]),
                  (0., 1., 0., .08+step*DELTA[1]),
                  (0., 0., 1., .07+step*DELTA[2]), (0., 0., 0., 1.))
    body = {'points': points, 'faces': faces, 'mesh_faces': mesh_faces,
            'surface_area': area, 'volume': volume, 'edge_lengths': lengths,
            'matrix_world': matrix}
    return {'body': body, 'base': base}


def _cross2(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _area2(polygon):
    return sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(polygon, polygon[1:]+polygon[:1]))/2


def _inside(point, polygon, epsilon):
    inside = False
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        if (abs(_cross2(a, b, point)) <= epsilon
                and min(a[0], b[0])-epsilon <= point[0] <= max(a[0], b[0])+epsilon
                and min(a[1], b[1])-epsilon <= point[1] <= max(a[1], b[1])+epsilon):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < a[0]+(point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1]):
                inside = not inside
    return inside


def _contained(triangle, polygon, epsilon):
    """Check all edge intervals, not just a concave face's triangle centroid."""
    if not all(_inside(p, polygon, epsilon) for p in triangle):
        return False
    for p, q in zip(triangle, triangle[1:]+triangle[:1]):
        r = _sub(q, p)
        parameters = [0., 1.]
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            s, ap = _sub(b, a), _sub(a, p)
            determinant = r[0]*s[1]-r[1]*s[0]
            if abs(determinant) > epsilon:
                t = (ap[0]*s[1]-ap[1]*s[0])/determinant
                u = (ap[0]*r[1]-ap[1]*r[0])/determinant
                if -epsilon <= t <= 1+epsilon and -epsilon <= u <= 1+epsilon:
                    parameters.append(max(0., min(1., t)))
            elif abs(ap[0]*r[1]-ap[1]*r[0]) <= epsilon:
                rr = _dot(r, r)
                for endpoint in (a, b):
                    t = _dot(_sub(endpoint, p), r)/rr
                    if 0. < t < 1.:
                        parameters.append(t)
        parameters.sort()
        for lo, hi in zip(parameters, parameters[1:]):
            midpoint = tuple(p[i]+(lo+hi)/2*r[i] for i in range(2))
            if not _inside(midpoint, polygon, epsilon):
                return False
    center = tuple(sum(p[i] for p in triangle)/3 for i in range(2))
    return _inside(center, polygon, epsilon)


def _intersection_area(first, second, epsilon):
    """Convex triangle clipping; positive-area overlap is forbidden."""
    clipped = list(first)
    for a, b in zip(second, second[1:]+second[:1]):
        source, clipped = clipped, []
        if not source:
            break
        for p, q in zip(source, source[1:]+source[:1]):
            dp, dq = _cross2(a, b, p), _cross2(a, b, q)
            pin, qin = dp >= -epsilon, dq >= -epsilon
            if pin:
                clipped.append(p)
            if pin != qin:
                t = dp/(dp-dq)
                clipped.append(tuple(p[i]+t*(q[i]-p[i]) for i in range(2)))
    return abs(_area2(clipped)) if len(clipped) >= 3 else 0.


def _triangle_coverage(name, face, triangles, points):
    boundary = face['boundary']
    origin = points[boundary[0]]
    u = _unit(_sub(points[boundary[1]], origin))
    v = _cross(face['normal'], u)
    def project(label):
        d = _sub(points[label], origin)
        return (_dot(d, u), _dot(d, v))
    polygon = [project(label) for label in boundary]
    wanted_area = _area2(polygon)
    assert wanted_area > 0., ('Analytic face winding', name)
    epsilon = max(1e-15, wanted_area*1e-10)
    projected, directed, areas = [], Counter(), []
    for labels in triangles:
        assert len(labels) == len(set(labels)) == 3, ('Degenerate triangle', name, labels)
        triangle = [project(label) for label in labels]
        area = _area2(triangle)
        assert area > epsilon, ('Degenerate or wrong-winding triangle', name, labels)
        assert _contained(triangle, polygon, epsilon), ('Triangle outside original face', name, labels)
        for earlier in projected:
            assert _intersection_area(earlier, triangle, epsilon) <= epsilon, ('Triangle overlap', name)
        projected.append(triangle)
        areas.append(area)
        directed.update(_cycle(labels))
    assert abs(sum(areas)-wanted_area) <= epsilon, ('Incomplete face area coverage', name, sum(areas), wanted_area)
    # Interior diagonals cancel as directed edges. Each exterior edge must occur
    # once with the original winding, including every edge around the L notch.
    net = Counter({edge: count-directed[edge[::-1]] for edge, count in directed.items()
                   if count > directed[edge[::-1]]})
    assert net == _cycle(boundary), ('Signed boundary mismatch', name, net)
    return {'triangles': len(triangles), 'area_m2': sum(areas),
            'boundary': list(boundary), 'signed_boundary_verified': True,
            'containment_verified': True, 'overlap_area_m2': 0.}


def _indices(values, count, minimum):
    assert len(values) >= minimum and all(type(i) is int and 0 <= i < count for i in values), 'Invalid vertex indices'
    assert len(values) == len(set(values)), 'Repeated polygon corner'


def _inspect_part(part, specification, input_format, tolerance, normal_tolerance):
    expected = specification['points']
    matrix = part['matrix_world']
    assert len(matrix) == 4 and all(len(row) == 4 for row in matrix), 'Invalid measured matrix_world'
    assert all(math.isfinite(value) for row in matrix for value in row), 'Nonfinite measured matrix_world'
    matrix_error = max(abs(actual-wanted)
                       for actual_row, wanted_row in zip(matrix, specification['matrix_world'])
                       for actual, wanted in zip(actual_row, wanted_row))
    assert matrix_error <= tolerance, ('Unexpected independently measured matrix_world', matrix_error, matrix)
    assert part['points'] and part['faces'], 'Missing geometry'
    names, position_errors = [], []
    for point in part['points']:
        assert len(point) == 3 and all(math.isfinite(x) for x in point), 'Invalid measured point'
        distances = {name: math.dist(point, wanted) for name, wanted in expected.items()}
        matches = [name for name, distance in distances.items() if distance <= tolerance]
        assert len(matches) == 1, ('Unexpected independently measured vertex', point, distances)
        names.append(matches[0])
        position_errors.append(distances[matches[0]])
    assert set(names) == set(expected), 'Missing named corner'
    if input_format == 'blend':
        assert len(names) == len(expected), 'Unexpected Blend vertex count'
    palette = [_color(value) for value in part['palette']]
    wanted_palette = ['Cobalt', 'Ember'] if any(f['color'] == 'Ember' for f in specification['faces'].values()) else ['Cobalt']
    assert len(palette) == len(wanted_palette) and set(palette) == set(wanted_palette), 'Material palette mismatch'
    if input_format == 'blend':
        assert palette == wanted_palette, 'Blend palette order changed'
    raw_edges = Counter()
    for edge in part['edges']:
        _indices(edge, len(names), 2)
        assert len(edge) == 2
        raw_edges[tuple(sorted(edge))] += 1
    used_indices, polygon_edges, incidence = set(), set(), Counter()
    groups = {name: [] for name in specification['faces']}
    observed, normal_errors = {}, []
    material_histogram = Counter()
    surface_area, volume = 0., 0.
    for ordinal, face in enumerate(part['faces']):
        indices = face['indices']
        _indices(indices, len(names), 3)
        labels = tuple(names[i] for i in indices)
        assert len(labels) == len(set(labels)), 'Degenerate named polygon'
        used_indices.update(indices)
        for a, b in _cycle(indices):
            polygon_edges.add(tuple(sorted((a, b))))
        incidence.update(tuple(sorted(edge)) for edge in _cycle(labels))
        if input_format == 'blend':
            matches = [(name, wanted) for name, wanted in specification['mesh_faces']
                       if _cycle(wanted['boundary']) == _cycle(labels)]
            assert len(matches) == 1, ('Unexpected oriented Blend boundary', labels)
            name, wanted = matches[0]
            original = wanted.get('original', name)
            assert name not in observed, ('Duplicate Blend polygon', name)
        else:
            assert len(labels) == 3, 'GLB contains a non-triangle polygon'
            matches = [(name, wanted) for name, wanted in specification['faces'].items()
                       if set(labels) <= set(wanted['boundary'])]
            assert len(matches) == 1, ('Triangle does not belong to exactly one original face', labels)
            original, wanted = matches[0]
            name = original+'/'+str(ordinal)
        groups[original].append(labels)
        assert type(face['material_index']) is int and 0 <= face['material_index'] < len(palette), 'Invalid material index'
        color = palette[face['material_index']]
        assert color == wanted['color'], ('Material attached to wrong face', original, color)
        material_histogram[color] += 1
        assert len(face['corner_normals']) == len(indices), ('Missing corner normal', name)
        errors = {}
        for label, normal in zip(labels, face['corner_normals']):
            target = wanted.get('corners', {}).get(label, wanted['normal'])
            error = _angle(normal, target)
            assert error <= normal_tolerance, ('Incorrect independently expected corner normal', original, label, error)
            normal_errors.append(error)
            errors[str(label)] = error
        observed[name] = {'boundary': list(labels), 'color': color, 'normal_errors_radians': errors}
        measured = [part['points'][i] for i in indices]
        area_vector = [0., 0., 0.]
        for i in range(1, len(measured)-1):
            product = _cross(_sub(measured[i], measured[0]), _sub(measured[i+1], measured[0]))
            for axis in range(3):
                area_vector[axis] += product[axis]/2
            volume += _dot(measured[0], _cross(measured[i], measured[i+1]))/6
        surface_area += math.sqrt(_dot(area_vector, area_vector))
    assert used_indices == set(range(len(names))), 'Unused measured vertices'
    assert raw_edges == Counter({edge: 1 for edge in polygon_edges}), 'Raw edge inventory differs from polygon boundaries'
    coverage = {}
    if input_format == 'blend':
        assert set(observed) == {name for name, _ in specification['mesh_faces']}, 'Missing Blend polygon'
    for name, face in specification['faces'].items():
        # Also prove the native negative case's explicitly triangulated L top.
        # Untessellated Blend n-gons have already passed exact boundary checks.
        if input_format == 'glb' or all(len(labels) == 3 for labels in groups[name]):
            coverage[name] = _triangle_coverage(name, face, groups[name], expected)
    assert set(incidence.values()) == {2}, 'Named surface is not closed'
    low = [min(point[i] for point in part['points']) for i in range(3)]
    high = [max(point[i] for point in part['points']) for i in range(3)]
    dimensions = [high[i]-low[i] for i in range(3)]
    extent = max(dimensions)
    assert abs(surface_area-specification['surface_area']) <= max(1e-12, 32*tolerance*extent), 'Surface area mismatch'
    assert abs(volume-specification['volume']) <= max(1e-14, 32*tolerance*extent*extent), 'Signed volume mismatch'
    return {'max_position_error_m': max(position_errors),
            'max_matrix_element_error': matrix_error,
            'max_normal_angle_deviation_radians': max(normal_errors),
            'vertices': len(names), 'edges': len(part['edges']), 'polygons': len(part['faces']),
            'render_triangles': sum(len(face['indices'])-2 for face in part['faces']),
            'unique_named_vertices': len(expected), 'closed_edges': len(incidence),
            'world_bounds_m': {'min': low, 'max': high}, 'world_axis_dimensions_m': dimensions,
            'reference_edge_lengths_m': specification['edge_lengths'],
            'surface_area_m2': surface_area, 'signed_volume_m3': volume,
            'expected_surface_area_m2': specification['surface_area'],
            'expected_volume_m3': specification['volume'],
            'palette': palette, 'material_histogram': dict(material_histogram),
            'named_faces': observed, 'original_face_coverage': coverage}


def inspect_geometry(probe, fixture, step, defect, *, tolerance, normal_tolerance):
    """Assert raw artifact geometry against the requested analytic fixture case.

    Negative cases describe *known desired negative geometry*: deformation,
    retessellation, or a protected-base move must be present exactly as declared.
    Policy rejection is evaluated separately by the runner. Blend boundaries are
    checked exactly up to cyclic start/order; GLB triangles must fully cover each
    original face with no outside area, overlap, gap, or reversed winding.
    """
    assert math.isfinite(tolerance) and tolerance >= 0.
    assert math.isfinite(normal_tolerance) and normal_tolerance >= 0.
    assert probe['autoexec_enabled'] is False
    assert probe['scale_length'] == 1.
    assert probe['input_format'] in ('blend', 'glb')
    assert set(probe['parts']) == {'body', 'base'}
    specifications = _specifications(fixture, step, defect)
    reports = {name: _inspect_part(probe['parts'][name], specification, probe['input_format'], tolerance, normal_tolerance)
               for name, specification in specifications.items()}
    return {'fixture': fixture, 'step': step, 'defect': defect, 'input_format': probe['input_format'],
            'max_position_error_m': max(p['max_position_error_m'] for p in reports.values()),
            'max_matrix_element_error': max(p['max_matrix_element_error'] for p in reports.values()),
            'max_normal_angle_deviation_radians': max(p['max_normal_angle_deviation_radians'] for p in reports.values()),
            'parts': reports}
