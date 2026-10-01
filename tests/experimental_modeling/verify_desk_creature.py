# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent saved-geometry assertions; never imports the authored mesh program."""
import math

HASHES = ('geometry_hash', 'transform_hash', 'material_hash')


def fingerprints(observation):
    return {name: tuple(part[k] for k in HASHES) for name, part in observation['parts'].items()}


def verify(observations):
    parts = [o['parts'] for o in observations]
    assert len(parts) == 3 and all(len(p) == 8 for p in parts)
    tolerance = 2e-6
    def center(vertices):
        return [sum(v[j] for v in vertices) / len(vertices) for j in range(3)]
    for name in parts[0]:
        for p in parts:
            assert p[name]['nonmanifold_edges'] == 0, name
            assert p[name]['signed_volume'] > 0, name
        for before, after, change in [(parts[0], parts[1], 'tail'), (parts[1], parts[2], 'crescent')]:
            if name != change:
                assert all(before[name][k] == after[name][k] for k in HASHES), name
    old, new = (p['tail']['world_vertices'] for p in parts[:2])
    max_station_error = max_radius_error = 0
    for i in range(17):
        a, b = center(old[8*i:8*i+8]), center(new[8*i:8*i+8])
        expected = [a[0], a[1], a[2] + .35 * math.sin(math.pi*i/16)]
        error = math.dist(b, expected)
        max_station_error = max(max_station_error, error)
        assert error < tolerance
        for vertex in new[8*i:8*i+8]:
            error = abs(math.dist(vertex, b) - (.16-.10*i/16))
            max_radius_error = max(max_radius_error, error)
            assert error < tolerance
    v0, v1 = (p['crescent']['world_vertices'] for p in parts[1:])
    assert len(v0) == len(v1) == 200
    for i, (a, b) in enumerate(zip(v0, v1)):
        assert abs(a[0]-b[0]) < tolerance and abs(a[1]-b[1]) < tolerance
        delta = .15 if i % 8 in (1, 2, 5, 6) else 0
        assert abs((b[2]-a[2])-delta) < tolerance
    for i in range(25):
        ring = v1[i*8:i*8+8]
        assert abs(ring[3][2]-.08) < tolerance and abs(ring[4][2]-.08) < tolerance
        assert abs(math.dist(ring[1], ring[2])-.08) < tolerance
        assert abs(math.dist(ring[5], ring[6])-.08) < tolerance
    for name in ('leg_left', 'leg_right', 'leg_rear'):
        for p in parts:
            vertices = p[name]['world_vertices']
            assert min(v[2] for v in vertices) == 0
            assert all(v[2] == 0 for v in vertices[-8:])
    return {'passed': True, 'semantic_parts': 8, 'unchanged_parts_per_revision': 7,
            'tail_max_station_error': max_station_error, 'tail_max_radius_error': max_radius_error,
            'tail_endpoint_centers_preserved': True, 'container_all_xy_preserved': True,
            'container_heights': [.35, .50], 'container_floor_and_radial_wall': .08,
            'three_flat_ground_caps_z0': True}
