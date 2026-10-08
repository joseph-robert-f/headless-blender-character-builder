# SPDX-License-Identifier: GPL-3.0-or-later
"""Head-only comparison geometry; no accepted print profile is changed."""
from collections import Counter
import math

import bmesh
import bpy
from mathutils import Vector

COMPARISON_ID = 'anime-cat-head-comparison-v1'
HEAD_BOX_MM = ((-36.0, -36.0, 54.0), (36.0, 24.0, 100.5))
MM_PER_SOURCE = (100.0 / 3.15) * 1.0854632543541882


def inside(point):
    low, high = HEAD_BOX_MM
    return all(low[i] < point[i] < high[i] for i in range(3))


def canonical(points):
    row = tuple(points)
    return min(row[i:] + row[:i] for i in range(3))


def exterior(mesh):
    return Counter(canonical(tuple(tuple(mesh.vertices[i].co) for i in face.vertices))
                   for face in mesh.polygons
                   if not all(inside(mesh.vertices[i].co) for i in face.vertices))


def ramp(low, high, value):
    t = max(0.0, min(1.0, (value-low)/(high-low)))
    return t*t*(3.0-2.0*t)


def whisker_distance(point):
    distances = []
    for sign in (-1, 1):
        for index in range(2):
            knots = [(sign*.46, -.51, 1.79-index*.10),
                     (sign*.72, -.55, 1.82-index*.14),
                     (sign*.94, -.51, 1.84-index*.16)]
            for start, end in zip(knots, knots[1:]):
                a, b = Vector(start), Vector(end)
                delta = b-a
                t = max(0.0, min(1.0, (point-a).dot(delta)/delta.length_squared))
                distances.append((point-(a+t*delta)).length)
    return min(distances)


def face_weight(point):
    x, y, z = point
    # Pin the whole known eye-relief envelope, nose and smile, rather than
    # using an attractive render as proof that those details survived.
    eye_radius = math.sqrt(min(((abs(x)-cx)/rx)**2 + ((y-cy)/ry)**2 + ((z-cz)/rz)**2
              for cx, cy, cz, rx, ry, rz in (
                  (.32, -.594, 2.02, .255, .11, .30),
                  (.31, -.686, 2.03, .174, .07, .23),
                  (.30, -.741, 2.04, .097, .045, .18),
                  (.257, -.778, 2.12, .10, .035, .08))))
    nose_radius = max(abs(x)/.21, abs(z-1.745)/.135, 1.0+(y+.68)/.05)
    return (ramp(1.18, 1.45, eye_radius)*ramp(1.0, 1.35, nose_radius)
            *ramp(.075, .14, whisker_distance(point)))


def sculpt(obj):
    """Transactionally deform a finalized bare cat; pin every exterior facet."""
    before = exterior(obj.data)
    bm = bmesh.new()
    replacement = None
    try:
        bm.from_mesh(obj.data)
        if any(len(f.verts) != 3 for f in bm.faces):
            raise ValueError('Comparison requires explicit source triangles')
        original = {v: v.co.copy() for v in bm.verts}
        eligible = {v for v in bm.verts
                    if inside(v.co) and all(all(inside(w.co) for w in f.verts)
                                           for f in v.link_faces)}
        moved = 0
        for vertex in eligible:
            point = original[vertex] / MM_PER_SOURCE
            x, y, z = point
            neck = ramp(55.0, 60.0, original[vertex].z)
            tip = 1.0-ramp(98.5, 99.7, original[vertex].z)
            detail = face_weight(point)
            weight = neck*tip*detail
            delta = Vector((0, 0, 0))
            relative = point-Vector((0, -.05, 1.96))
            radius = math.sqrt((relative.x/.83)**2 + (relative.y/.62)**2 + (relative.z/.72)**2)
            if radius > 0:
                skin = 1.0-ramp(.018, .065, abs(radius-1.0))
                front = ramp(-.58, -.43, y)
                delta += relative*(1.0/radius-1.0)*skin*front*.90
            # Symmetric broad cheek fullness; existing detailed relief stays
            # pinned. These are author parameters, not acceptance thresholds.
            cheek = math.exp(-((abs(x)-.57)/.20)**2-((z-1.80)/.19)**2)
            cheek *= (1.0-ramp(-.38, -.20, y))*ramp(-.86, -.67, y)
            delta.x += (1 if x >= 0 else -1)*(.055*cheek)
            delta.y -= .025*cheek
            muzzle = math.exp(-((abs(x)-.22)/.17)**2-((z-1.74)/.12)**2)
            muzzle *= (1.0-ramp(-.57, -.42, y))
            delta.y -= .035*muzzle
            # Recess surrounding skin; never push protected eye relief into
            # the opaque lenses. Accessories are authored after this step.
            socket = math.exp(-((abs(x)-.42)/.24)**2-((z-2.04)/.27)**2)
            socket *= ramp(-.64, -.54, y)*(1.0-ramp(-.45, -.30, y))
            delta.y += .018*socket
            vertex.co = original[vertex] + delta*(MM_PER_SOURCE*weight)
            ear = ramp(2.43, 2.60, z)*ramp(.33, .48, abs(x))
            # Preserve tip height, but allow its rear contour to follow the
            # rounded ear. Pinning X/Y at the top would create an overhang lip.
            vertex.co.y -= .14*ear*ramp(-.26, .12, y)*MM_PER_SOURCE*neck*detail
            if vertex.co != original[vertex]:
                moved += 1
        # A few actual mesh fairing steps soften outer-ear transitions. The
        # raised inner-ear front and final 100 mm tip height remain pinned.
        ears = {v for v in eligible if original[v].z > 84.0
                and original[v].y > -11.6}
        for _ in range(10):
            positions = {v: v.co.copy() for v in bm.verts}
            for vertex in ears:
                neighbors = [e.other_vert(vertex) for e in vertex.link_edges]
                mean = sum((positions[v] for v in neighbors), Vector())/len(neighbors)
                vertex.co = positions[vertex].lerp(mean, .35)
                if original[vertex].z >= 99.7:
                    vertex.co.z = original[vertex].z
        bm.normal_update()
        moved = sum(vertex.co != point for vertex, point in original.items())
        if any(not e.is_manifold or not e.is_contiguous for e in bm.edges) or bm.calc_volume(signed=True) <= 0:
            raise ValueError('Sculpt lost closed orientation or positive volume')
        replacement = obj.data.copy()
        bm.to_mesh(replacement)
        replacement.update()
        if exterior(replacement) != before or len(replacement.vertices) != len(obj.data.vertices) or len(replacement.polygons) != len(obj.data.polygons):
            raise ValueError('Head comparison changed a pinned exterior facet or mesh counts')
        previous = obj.data
        obj.data = replacement
        replacement = None
        if previous.users == 0:
            bpy.data.meshes.remove(previous)
        obj['comparison_id'] = COMPARISON_ID
        obj['print_profile_id'] = COMPARISON_ID
        return {'head_box_mm': HEAD_BOX_MM, 'moved_vertices': moved,
                'ear_fairing_vertices': len(ears), 'protected_triangles': sum(before.values()),
                'method': 'fixed_head_box_pinned_exterior_triangles_actual_vertex_deformation'}
    finally:
        if replacement is not None and replacement.users == 0:
            bpy.data.meshes.remove(replacement)
        bm.free()
