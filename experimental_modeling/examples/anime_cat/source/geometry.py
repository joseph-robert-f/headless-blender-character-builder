# SPDX-License-Identifier: GPL-3.0-or-later
"""Small deterministic closed meshes for the reviewed anime-cat fixture.

Coordinates are in the repository scene contract's meters.  No Blender state,
assets, randomness, or files are consulted here.
"""

import math


def _positive(vertices, faces):
    volume_six = 0.0
    for face in faces:
        a = vertices[face[0]]
        for i in range(1, len(face) - 1):
            b, c = vertices[face[i]], vertices[face[i + 1]]
            volume_six += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                + a[1] * (b[2] * c[0] - b[0] * c[2])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            )
    if abs(volume_six) < 1e-12:
        raise ValueError("Fixture primitive has zero signed volume")
    if volume_six < 0:
        faces = [tuple(reversed(face)) for face in faces]
    return vertices, faces


def combine(*meshes):
    vertices, faces = [], []
    for mesh_vertices, mesh_faces in meshes:
        offset = len(vertices)
        vertices.extend(mesh_vertices)
        faces.extend(tuple(offset + index for index in face) for face in mesh_faces)
    return vertices, faces


def ellipsoid(center, radii, *, slices=32, rings=16):
    cx, cy, cz = center
    rx, ry, rz = radii
    vertices = [(cx, cy, cz + rz)]
    for ring in range(1, rings):
        polar = math.pi * ring / rings
        for section in range(slices):
            azimuth = 2 * math.pi * section / slices
            vertices.append((
                cx + rx * math.sin(polar) * math.cos(azimuth),
                cy + ry * math.sin(polar) * math.sin(azimuth),
                cz + rz * math.cos(polar),
            ))
    bottom = len(vertices)
    vertices.append((cx, cy, cz - rz))
    faces = []
    for section in range(slices):
        following = (section + 1) % slices
        faces.append((0, 1 + section, 1 + following))
    for ring in range(rings - 2):
        upper = 1 + ring * slices
        lower = upper + slices
        for section in range(slices):
            following = (section + 1) % slices
            faces.append((upper + section, lower + section,
                          lower + following, upper + following))
    last = 1 + (rings - 2) * slices
    for section in range(slices):
        following = (section + 1) % slices
        faces.append((bottom, last + following, last + section))
    return _positive(vertices, faces)


def prism_xz(outline, front_y, back_y):
    """Closed ear/nose prism from a simple CCW XZ outline."""
    count = len(outline)
    if count < 3 or not front_y < back_y:
        raise ValueError("Invalid prism")
    vertices = [(x, front_y, z) for x, z in outline]
    vertices += [(x, back_y, z) for x, z in outline]
    faces = [tuple(range(count)), tuple(reversed(range(count, 2 * count)))]
    for index in range(count):
        following = (index + 1) % count
        faces.append((index, index + count, following + count, following))
    return _positive(vertices, faces)


def torus_xy(center, major, minor, *, sections=48, sides=12):
    cx, cy, cz = center
    vertices = []
    for section in range(sections):
        azimuth = 2 * math.pi * section / sections
        for side in range(sides):
            polar = 2 * math.pi * side / sides
            radius = major + minor * math.cos(polar)
            vertices.append((cx + radius * math.cos(azimuth),
                             cy + radius * math.sin(azimuth),
                             cz + minor * math.sin(polar)))
    faces = []
    for section in range(sections):
        following_section = (section + 1) % sections
        for side in range(sides):
            following_side = (side + 1) % sides
            faces.append((section * sides + side,
                          following_section * sides + side,
                          following_section * sides + following_side,
                          section * sides + following_side))
    return _positive(vertices, faces)


def tube(points, radii, *, sides=10):
    if len(points) < 2 or len(points) != len(radii):
        raise ValueError("Invalid tube centerline")

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    def normalize(v):
        length = math.sqrt(sum(value * value for value in v))
        if length < 1e-9:
            raise ValueError("Degenerate tube tangent")
        return tuple(value / length for value in v)

    vertices = []
    for index, point in enumerate(points):
        previous = points[max(index - 1, 0)]
        following = points[min(index + 1, len(points) - 1)]
        tangent = normalize(tuple(following[axis] - previous[axis]
                                  for axis in range(3)))
        reference = (0, 0, 1) if abs(tangent[2]) < .85 else (0, 1, 0)
        u = normalize(cross(tangent, reference))
        v = cross(tangent, u)
        for side in range(sides):
            angle = 2 * math.pi * side / sides
            vertices.append(tuple(point[axis] + radii[index] *
                                  (u[axis] * math.cos(angle) +
                                   v[axis] * math.sin(angle))
                                  for axis in range(3)))
    faces = [tuple(reversed(range(sides)))]
    for index in range(len(points) - 1):
        for side in range(sides):
            following_side = (side + 1) % sides
            a = index * sides + side
            b = index * sides + following_side
            faces.append((a, b, b + sides, a + sides))
    faces.append(tuple((len(points) - 1) * sides + side
                       for side in range(sides)))
    return _positive(vertices, faces)
