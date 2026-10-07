# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned fixed final resize; the original author and frozen base stay intact."""
from collections import Counter
import math
import struct

import bmesh

from solids import build, face_components

PROFILE_ID = 'anime-cat-x1c-pla-04-bare100-v2'
FACTOR = 1.0854632543541882  # 100 / reviewed dd5c8b4 bare height92.1265640258789.
DERIVATION_VERSION = 'anime-cat-x1c-final-scale-hat-diagonals-v3'
# A,B,C,P: only these two previously reviewed oriented hat quads may change.
# These are coordinates, never mesh indices or freshly measured revision bounds.
HAT_QUADS = (
    ((16.34115219116211,5.2262043952941895,81.71055603027344),
     (16.373092651367188,5.2470245361328125,81.73533630371094),
     (16.397661209106445,5.2630391120910645,81.75439453125),
     (16.39879035949707,5.266449451446533,81.75271606445312)),
    ((17.55213737487793,-3.3214824199676514,84.03997039794922),
     (17.552589416503906,-3.3184375762939453,84.0406494140625),
     (17.552734375,-3.317460060119629,84.0408706665039),
     (17.436182022094727,-4.103193283081055,85.23809814453125)),
)


def f32(value):
    return struct.unpack('<f',struct.pack('<f',value))[0]


def mapped(point):
    return tuple(f32(value*FACTOR) for value in point)


def canonical(points):
    row = tuple(points)
    return min(row[i:]+row[:i] for i in range(3))


def cross(points):
    a,b,c = points
    u,v = [b[i]-a[i] for i in range(3)],[c[i]-a[i] for i in range(3)]
    return (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def altitude(row):
    return math.sqrt(dot(cross(row),cross(row))) / max(math.dist(row[i],row[(i+1)%3]) for i in range(3))


def boundary(rows):
    edges = Counter((row[i],row[(i+1)%3]) for row in rows for i in range(3))
    return Counter({(a,b):n-edges[(b,a)] for (a,b),n in edges.items() if n>edges[(b,a)]})


def solid(bm):
    return (face_components(bm)==1 and all(e.is_manifold and e.is_contiguous for e in bm.edges)
            and all(v.is_manifold and v.link_faces for v in bm.verts) and bm.calc_volume(signed=True)>0)


def resize(obj, *, repair_hat=False):
    """Keep mesh changes transactional; reject every unreviewed local rotation."""
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        if not solid(bm) or any(len(f.verts)!=3 for f in bm.faces):
            raise ValueError('Fixed resize requires the complete closed triangulated source')
        original = {v:tuple(float(x) for x in v.co) for v in bm.verts}
        def points(face, coords=None):
            return tuple(coords[v] if coords else tuple(float(x) for x in v.co) for v in face.verts)
        old_normals = {f:cross(points(f,original)) for f in bm.faces}
        for vertex,point in original.items():
            vertex.co = mapped(point)
        coordinates = {v:tuple(float(x) for x in v.co) for v in bm.verts}
        if len(set(coordinates.values())) != len(set(original.values())):
            raise ValueError('Fixed resize collapsed distinct vertices')
        inverted = [f for f in bm.faces if dot(old_normals[f],cross(points(f)))<=0]
        expected = {canonical((a,b,c)) for a,b,c,p in HAT_QUADS}
        if (repair_hat and (len(inverted)!=2 or {canonical(points(f,original)) for f in inverted} != expected)) or (not repair_hat and inverted):
            raise ValueError('Fixed resize has unreviewed orientation reversals')
        before = Counter(canonical(points(f)) for f in bm.faces)
        plans = []
        if repair_hat:
            for quad in HAT_QUADS:
                a,b,c,p = quad
                face = next(f for f in inverted if canonical(points(f,original))==canonical((a,b,c)))
                edge = max(face.edges,key=lambda e:math.dist(original[e.verts[0]],original[e.verts[1]]))
                if {original[v] for v in edge.verts}!={a,c} or len(edge.link_faces)!=2:
                    raise ValueError('Reviewed hat diagonal incidence changed')
                other = next(f for f in edge.link_faces if f is not face)
                if canonical(points(other,original)) != canonical((a,c,p)):
                    raise ValueError('Reviewed hat neighbor or orientation changed')
                vertices = set(face.verts)|set(other.verts)
                opposite = [next(v for v in f.verts if v not in edge.verts) for f in (face,other)]
                if len(vertices)!=4 or {original[v] for v in vertices}!=set(quad):
                    raise ValueError('Reviewed hat quadrilateral changed')
                if not all(-20<x<20 and -20<y<20 and 80<z<103 for x,y,z in quad):
                    raise ValueError('Hat repair exceeds the reviewed accessory region')
                if any(opposite[1] in e.verts for e in opposite[0].link_edges):
                    raise ValueError('Replacement hat diagonal already exists')
                old = (points(face),points(other))
                A,B,C,P = map(mapped,quad)
                new = ((A,B,P),(B,C,P))
                if (boundary(new)!=boundary(old) or min(altitude(row) for row in new)<=4*min(altitude(row) for row in old)
                        or any(dot(cross(row),cross(points(other)))<=0 for row in new)):
                    raise ValueError('Hat replacement lost boundary, quality or orientation')
                plans.append((edge,opposite,old,new))
            # Both patches pass before any rotation; obj.data is untouched on failure.
            for edge,opposite,old,new in plans:
                rotated = bmesh.ops.rotate_edges(bm,edges=[edge],use_ccw=False)['edges']
                if len(rotated)!=1 or set(rotated[0].verts)!=set(opposite) or len(rotated[0].link_faces)!=2:
                    raise ValueError('Unexpected hat diagonal rotation')
                actual = tuple(points(f) for f in rotated[0].link_faces)
                if Counter(map(canonical,actual))!=Counter(map(canonical,new)) or boundary(actual)!=boundary(old):
                    raise ValueError('Hat rotation differs from the reviewed replacement')
        after = Counter(canonical(points(f)) for f in bm.faces)
        removed,added = before-after,after-before
        if (sum(removed.values())!=4*bool(repair_hat) or sum(added.values())!=4*bool(repair_hat)
                or sum(after.values())!=sum(before.values()) or len(bm.verts)!=len(coordinates)
                or any(tuple(v.co)!=point for v,point in coordinates.items()) or not solid(bm)
                or any(dot(cross(points(f)),cross(points(f)))<=4e-20 for f in bm.faces)):
            raise ValueError('Fixed resize changed unreviewed facets, coordinates or solid topology')
        bm.to_mesh(obj.data)
        obj.data.update()
        obj['print_profile_id'] = PROFILE_ID
        obj['print_derivation_version'] = DERIVATION_VERSION
    finally:
        bm.free()


def build_x1c(revision):
    candidate,base = build(revision)
    resize(base)
    resize(candidate,repair_hat=revision=='r1')
    return candidate,base
