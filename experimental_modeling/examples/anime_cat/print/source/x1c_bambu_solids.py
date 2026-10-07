# SPDX-License-Identifier: GPL-3.0-or-later
"""Additive v3 base: replace one exact planar floor diagonal after v2 authoring."""
from collections import Counter
from fractions import Fraction

import bmesh
import bpy

from x1c_solids import PROFILE_ID as V2_PROFILE_ID, build_x1c, canonical, boundary, cross, dot, altitude, solid

PROFILE_ID = 'anime-cat-x1c-pla-04-bare100-v3'
DERIVATION_VERSION = 'anime-cat-x1c-bambu-planar-floor-v4'
# Source-coordinate identities from the actual v2 Bambu reproducer, never indices
# or placement-derived coordinates. This is distinct from the older Prusa quad.
A = (-16.88590431213379, 2.855515718460083, 0.0)
D = (-16.70351219177246, 3.056802749633789, 0.0)
B = (-16.703372955322266, 3.0569541454315186, 0.0)
C = (-16.84747314453125, -11.167367935180664, 0.0)
OLD = ((A,D,B),(A,B,C))
NEW = ((A,D,C),(D,B,C))
QUAD = (A,D,B,C)


def _prepare(obj):
    """Prepare a new mesh; any failed guard leaves original data and tags intact."""
    if obj.get('print_profile_id') != V2_PROFILE_ID:
        raise ValueError('Floor rotation requires the reviewed completed v2 source')
    bm = bmesh.new()
    replacement = None
    try:
        bm.from_mesh(obj.data)
        if not solid(bm) or any(len(face.verts)!=3 for face in bm.faces):
            raise ValueError('Floor rotation requires one closed triangulated solid')
        coordinates = {v:tuple(float(x) for x in v.co) for v in bm.verts}
        def points(face):return tuple(coordinates[v] for v in face.verts)
        before = Counter(canonical(points(face)) for face in bm.faces)
        expected = Counter(map(canonical,OLD))
        patch = [face for face in bm.faces if canonical(points(face)) in expected]
        if len(patch)!=2 or Counter(canonical(points(f)) for f in patch)!=expected:
            raise ValueError('Reviewed oriented floor pair changed or is not unique')
        vertices = set(patch[0].verts)|set(patch[1].verts)
        if len(vertices)!=4 or {coordinates[v] for v in vertices}!=set(QUAD):
            raise ValueError('Reviewed floor quadrilateral coordinates changed')
        edges = set(patch[0].edges)&set(patch[1].edges)
        if len(edges)!=1:
            raise ValueError('Reviewed floor pair must share exactly one diagonal')
        edge = next(iter(edges))
        if {coordinates[v] for v in edge.verts}!={A,B} or set(edge.link_faces)!=set(patch):
            raise ValueError('Reviewed floor diagonal incidence changed')
        opposite = [next(v for v in vertices if coordinates[v]==point) for point in (D,C)]
        if any(opposite[1] in item.verts for item in opposite[0].link_edges):
            raise ValueError('Replacement floor diagonal already exists')
        # Exact rational convexity and oriented planar area establish the same
        # physical source surface, separately from changed facet identities.
        def turn(a,b,c):
            a,b,c=(tuple(Fraction(x) for x in p) for p in (a,b,c))
            return (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])
        def area(rows):
            return sum(turn(*row) for row in rows)/2
        if (any(point[2]!=0 for point in QUAD) or any(turn(QUAD[i],QUAD[(i+1)%4],QUAD[(i+2)%4])>=0 for i in range(4))
                or boundary(OLD)!=boundary(NEW) or area(OLD)!=area(NEW)
                or any(cross(row)[2]>=0 for row in OLD+NEW)
                or min(map(altitude,NEW))<=4*min(map(altitude,OLD))):
            raise ValueError('Floor replacement lost exact planar surface or quality')
        changed = bmesh.ops.rotate_edges(bm,edges=[edge],use_ccw=False)['edges']
        if len(changed)!=1 or set(changed[0].verts)!=set(opposite) or len(changed[0].link_faces)!=2:
            raise ValueError('Unexpected floor diagonal rotation')
        actual = tuple(points(face) for face in changed[0].link_faces)
        if Counter(map(canonical,actual))!=Counter(map(canonical,NEW)) or boundary(actual)!=boundary(OLD):
            raise ValueError('Floor rotation differs from the reviewed replacement')
        after = Counter(canonical(points(face)) for face in bm.faces)
        if (before-after != expected or after-before != Counter(map(canonical,NEW))
                or sum(before.values())!=sum(after.values()) or len(bm.verts)!=len(coordinates)
                or any(tuple(float(x) for x in v.co)!=point for v,point in coordinates.items())
                or not solid(bm) or any(dot(cross(points(face)),cross(points(face)))<=4e-20 for face in bm.faces)):
            raise ValueError('Floor rotation changed unreviewed facets, coordinates or topology')
        replacement = obj.data.copy()
        bm.to_mesh(replacement)
        replacement.update()
        return replacement
    except Exception:
        if replacement is not None and replacement.users==0:
            bpy.data.meshes.remove(replacement)
        raise
    finally:
        bm.free()


def rotate_floor(obj):
    replacement = _prepare(obj)
    original = obj.data
    obj.data = replacement
    obj['print_profile_id'] = PROFILE_ID
    obj['print_derivation_version'] = DERIVATION_VERSION
    if original.users==0:bpy.data.meshes.remove(original)


def build_x1c_bambu(revision):
    candidate,base = build_x1c(revision)
    prepared = []
    try:
        # Both meshes pass before either object or profile tag is replaced.
        for obj in (candidate,base):prepared.append((obj,_prepare(obj)))
    except Exception:
        for _,mesh in prepared:
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        raise
    originals = [obj.data for obj,_ in prepared]
    for obj,mesh in prepared:
        obj.data = mesh
        obj['print_profile_id'] = PROFILE_ID
        obj['print_derivation_version'] = DERIVATION_VERSION
    for mesh in originals:
        if mesh.users==0:bpy.data.meshes.remove(mesh)
    return candidate,base
