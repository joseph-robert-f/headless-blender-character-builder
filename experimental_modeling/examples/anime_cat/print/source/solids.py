# SPDX-License-Identifier: GPL-3.0-or-later
"""Original, closed print primitives at the reviewed cat's source coordinates."""
import math
import bmesh
import bpy
from mathutils import Vector

SCALE = 100.0 / 3.15
VOXEL = .011
DERIVATION_VERSION = 'anime-cat-cut-diagonals-v2'


def closed(obj):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        if bm.calc_volume(signed=True) < 0:
            bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        if any(not edge.is_manifold for edge in bm.edges) or any(not vertex.is_manifold for vertex in bm.verts):
            raise ValueError('Primitive is not a closed manifold: ' + obj.name)
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    return obj


def active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def finish(obj, name):
    obj.name = name
    active(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return closed(obj)


def ellipsoid(name, location, scale):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40, ring_count=24, location=location)
    obj = bpy.context.object
    obj.scale = scale
    return finish(obj, name)


def tube(name, points, radius, cyclic=False):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 8
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    curve.use_fill_caps = not cyclic
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    spline.use_cyclic_u = cyclic
    for point, xyz in zip(spline.bezier_points, points):
        point.co = xyz
        point.handle_left_type = point.handle_right_type = 'AUTO'
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    active(obj)
    bpy.ops.object.convert(target='MESH')
    # Weld converted cap rings before using the primitive as a solid.
    return finish(bpy.context.object, name)


def ear(sign, inner):
    x, z = sign * .58, 2.45
    if inner:
        verts = [(x-sign*.21,-.35,z-.13),(x+sign*.15,-.35,z-.13),(x+sign*.12,-.28,z+.34),
                 (x-sign*.21,-.12,z-.13),(x+sign*.15,-.12,z-.13),(x+sign*.12,-.12,z+.34)]
    else:
        verts = [(x-sign*.29,-.31,z-.20),(x+sign*.23,-.31,z-.20),(x+sign*.16,-.22,z+.48),
                 (x-sign*.29,.21,z-.20),(x+sign*.23,.21,z-.20),(x+sign*.16,.16,z+.48)]
    mesh = bpy.data.meshes.new('ear')
    mesh.from_pydata(verts, [], [(0,2,1),(3,4,5),(0,1,4,3),(1,2,5,4),(2,0,3,5)])
    obj = bpy.data.objects.new('ear', mesh)
    bpy.context.collection.objects.link(obj)
    closed(obj)
    active(obj)
    bevel = obj.modifiers.new('Rounded ear', 'BEVEL')
    bevel.width = .022 if inner else .045
    bevel.segments = 4
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return finish(obj, 'inner-ear' if inner else 'ear')


def join(objects, name):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    return obj


def boolean(obj, tool, operation='UNION'):
    triangulated(obj)
    triangulated(tool)
    active(obj)
    modifier = obj.modifiers.new('Closed-solid fusion', 'BOOLEAN')
    modifier.operation = operation
    modifier.solver = 'MANIFOLD'
    modifier.object = tool
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(tool, do_unlink=True)
    return closed(obj)


def cylinder(name, radius, depth, z):
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=depth, location=(0, -.02, z))
    obj = bpy.context.object
    active(obj)
    bevel = obj.modifiers.new('Rounded hat', 'BEVEL')
    bevel.width = .025
    bevel.segments = 4
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return finish(obj, name)


def cat():
    parts = [ellipsoid('body', (0, 0, .96), (.64, .48, .82)),
             ellipsoid('bib', (0, -.438, 1.01), (.40, .095, .55)),
             ellipsoid('foot-contact', (0, -.12, .075), (.74, .50, .12))]
    for s in (-1, 1):
        for name, location, scale in (
            ('haunch', (s*.46,.08,.43), (.36,.42,.40)),
            ('foot', (s*.36,-.32,.18), (.28,.38,.18)),
            ('arm', (s*.47,-.35,.77), (.16,.20,.45)),
            ('paw', (s*.47,-.43,.43), (.18,.19,.20))):
            parts.append(ellipsoid(name, location, scale))
    parts.append(tube('curl-tail', [(.43,.22,.45),(.97,.25,.43),(1.15,.20,.80),(1.06,.12,1.13),(.89,.10,1.16)], .13))
    parts.append(ellipsoid('head', (0,-.05,1.96), (.83,.62,.72)))
    for s in (-1, 1):
        parts.extend([ear(s, False), ear(s, True)])
        for name, location, scale in (
            ('eye-white', (s*.32,-.594,2.02), (.255,.11,.30)),
            ('iris-relief', (s*.31,-.686,2.03), (.174,.07,.23)),
            ('pupil-relief', (s*.30,-.741,2.04), (.097,.045,.18)),
            ('sparkle-relief', (s*.30-.043,-.778,2.12), (.052,.026,.065)),
            ('muzzle', (s*.14,-.619,1.75), (.20,.13,.15)),
            ('cheek-relief', (s*.55,-.525,1.78), (.13,.055,.064))):
            parts.append(ellipsoid(name, location, scale))
        for i in range(2):
            parts.append(tube('thick-whisker', [(s*.46,-.51,1.79-i*.10),(s*.72,-.55,1.82-i*.14),(s*.94,-.51,1.84-i*.16)], .040))
        parts.append(tube('smile-relief', [(0,-.733,1.75),(s*.065,-.735,1.68),(s*.13,-.720,1.70)], .035))
    parts.append(ellipsoid('nose', (0,-.757,1.79), (.075,.04,.052)))
    obj = join(parts, 'PrintCandidate')
    active(obj)
    remesh = obj.modifiers.new('Union complete cat surfaces', 'REMESH')
    remesh.mode = 'VOXEL'
    remesh.voxel_size = VOXEL
    remesh.adaptivity = 0
    remesh.use_remove_disconnected = False
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    smooth = obj.modifiers.new('Smooth print surface', 'SMOOTH')
    smooth.factor = .35
    smooth.iterations = 3
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 3))
    tool = bpy.context.object
    tool.scale = (3, 3, 3)
    finish(tool, 'Ground cut')
    return boolean(obj, tool, 'INTERSECT')



def capsule_path(name, points, radius):
    # Closed spherical joints and cylinders avoid converted curve cap seams.
    parts = [ellipsoid(name, points[0], (radius,)*3)]
    for start,end in zip(points,points[1:]):
        direction = Vector(end)-Vector(start)
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=direction.length,
                                          location=(Vector(start)+Vector(end))/2)
        segment = bpy.context.object
        segment.rotation_euler = direction.to_track_quat('Z','Y').to_euler()
        parts.append(finish(segment,name+' segment'))
        parts.append(ellipsoid(name+' joint',end,(radius,)*3))
    return join(parts,name)


def glasses():
    parts = []
    for s in (-1, 1):
        parts.append(ellipsoid('lens', (s*.32,-.80,2.04), (.27,.11,.215)))
        points = [(s*.32+.285*math.cos(i*math.pi/6),-.80,2.04+.228*math.sin(i*math.pi/6)) for i in range(12)]
        parts.append(tube('rim', points, .040, cyclic=True))
        parts.append(capsule_path('temple', [(s*.59,-.78,2.08),(s*.73,-.49,2.13),(s*.70,-.13,2.09)], .042))
    parts.append(capsule_path('bridge', [(-.10,-.82,2.10),(0,-.845,2.13),(.10,-.82,2.10)], .044))
    # Fuse only the accessory; preserve the cat outside its attachment joins.
    obj = join(parts,'Closed glasses')
    active(obj)
    remesh = obj.modifiers.new('Union complete glasses surfaces','REMESH')
    remesh.mode = 'VOXEL'
    remesh.voxel_size = VOXEL
    remesh.adaptivity = 0
    remesh.use_remove_disconnected = False
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    smooth = obj.modifiers.new('Smooth glasses surface','SMOOTH')
    smooth.factor = .25
    smooth.iterations = 2
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    return closed(obj)


def millimeters(obj):
    for vertex in obj.data.vertices:
        vertex.co *= SCALE
    obj.data.update()
    return obj


def face_components(bm):
    remaining = set(bm.faces)
    count = 0
    while remaining:
        count += 1
        pending = [remaining.pop()]
        while pending:
            for edge in pending.pop().edges:
                for neighbor in edge.link_faces:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        pending.append(neighbor)
    return count


def triangulated(obj, weld_mm=False):
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        if weld_mm:
            before = face_components(bm)
            # Boolean cuts can leave distinct vertices at identical float32
            # coordinates. Weld only 0.00001 mm before defining final facets.
            bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-5)
            bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=1e-5)
            if face_components(bm) != before:
                raise ValueError('Numerical cleanup must preserve every face-connected component')
        bmesh.ops.triangulate(bm,faces=list(bm.faces))
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    return closed(obj)


def restore_protected(obj, base, revision):
    """Construct the union using the exact finalized base outside its edit box.

    Retain every base triangle touching the box boundary. Use union triangles
    only when all three vertices lie inside it. Exact coordinate joins must
    produce a single closed consistently oriented solid without a tolerance
    weld; any changed interface therefore fails construction.
    """
    boxes = {'r1':((-20,-20,80),(20,20,103)),
             'r2':((-26,-32,54),(26,2,76))}
    low,high = boxes[revision]
    vertices, faces, indices = [], [], {}
    for mesh, keep_inside in ((obj.data,True),(base.data,False)):
        original = bmesh.new()
        try:
            original.from_mesh(mesh)
            if (face_components(original) != 1 or
                    any(not edge.is_manifold or not edge.is_contiguous for edge in original.edges) or
                    any(not vertex.is_manifold for vertex in original.verts)):
                raise ValueError('Protected assembly must retain every component of closed single-shell operands')
        finally:
            original.free()
        for face in mesh.polygons:
            points = [tuple(mesh.vertices[index].co) for index in face.vertices]
            inside = all(low[i] < point[i] < high[i] for point in points for i in range(3))
            if inside != keep_inside:
                continue
            row = []
            for point in points:
                if point not in indices:
                    indices[point] = len(vertices)
                    vertices.append(point)
                row.append(indices[point])
            faces.append(row)
    replacement = bpy.data.meshes.new('Preserved base and accessory union')
    replacement.from_pydata(vertices,[],faces)
    bm = bmesh.new()
    try:
        bm.from_mesh(replacement)
        if (face_components(bm) != 1 or
                any(not edge.is_manifold or not edge.is_contiguous for edge in bm.edges) or
                any(not vertex.is_manifold for vertex in bm.verts)):
            raise ValueError('Exact protected base must retain one closed consistently oriented solid')
    finally:
        bm.free()
    previous = obj.data
    obj.data = replacement
    if previous.users == 0:
        bpy.data.meshes.remove(previous)


def stabilize_cut_diagonals(obj, kind):
    """Rotate only the three reviewed precision-sensitive cut diagonals.

    The ground rotation preserves the exact planar surface but defines a new
    frozen base triangulation. The two glasses rotations stay wholly inside
    the existing r2 edit box. No coordinate, vertex or facet is discarded.
    """
    import struct
    from collections import Counter
    from fractions import Fraction

    def points(face):
        return tuple(tuple(vertex.co) for vertex in face.verts)

    def normal(row):
        a,b,c = row
        u,v = tuple(b[i]-a[i] for i in range(3)),tuple(c[i]-a[i] for i in range(3))
        return (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])

    def dot(a,b):
        return sum(x*y for x,y in zip(a,b))

    def altitude(row):
        return math.sqrt(dot(normal(row),normal(row)))/max(math.dist(a,b) for a,b in zip(row,row[1:]+row[:1]))

    def f32(value):
        return struct.unpack('<f',struct.pack('<f',value))[0]

    def outer_boundary(rows):
        edges = Counter((a,b) for row in rows for a,b in zip(row,row[1:]+row[:1]))
        return {edge for edge,count in edges.items() if count and not edges[(edge[1],edge[0])]}

    if kind not in ('ground','glasses'):
        raise ValueError('Unknown cut-diagonal scope')
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        coordinates = {vertex:tuple(vertex.co) for vertex in bm.verts}
        original_faces = len(bm.faces)
        if face_components(bm) != 1 or any(not edge.is_manifold or not edge.is_contiguous for edge in bm.edges):
            raise ValueError('Cut-diagonal input must be one closed oriented solid')
        shift = tuple((min(p[i] for p in coordinates.values())+max(p[i] for p in coordinates.values()))/2 for i in range(3))
        def centered(row):
            return tuple(tuple(f32(p[i]-f32(shift[i])) for i in range(3)) for p in row)

        candidates = []
        for face in bm.faces:
            if len(face.verts) != 3:
                raise ValueError('Cut-diagonal input must already be triangulated')
            row = points(face)
            if kind == 'ground':
                if not all(-16<x<-14 and 2<y<4 and z==0 for x,y,z in row):
                    continue
                if normal(row)[2]*normal(centered(row))[2] > 0:
                    continue
            else:
                if not all(8.8<abs(x)<9 and -23.6<y<-23.3 and 59<z<59.2 for x,y,z in row):
                    continue
                precision = 2*max(2**(math.frexp(abs(value))[1]-24) if value else 2**-149 for p in row for value in p)
                if altitude(row) >= precision:
                    continue
            candidates.append(face)
        expected = 1 if kind == 'ground' else 2
        if len(candidates) != expected:
            raise ValueError('Reviewed cut-diagonal count changed')
        if kind == 'glasses' and sorted(1 if points(face)[0][0]>0 else -1 for face in candidates)!=[-1,1]:
            raise ValueError('Reviewed cut-diagonal side count changed')
        for face in sorted(candidates,key=lambda face:tuple(sorted(points(face)))):
            edge = max(face.edges,key=lambda e:(math.dist(tuple(e.verts[0].co),tuple(e.verts[1].co)),
                                                tuple(sorted(tuple(v.co) for v in e.verts))))
            if len(edge.link_faces) != 2:
                raise ValueError('Reviewed diagonal must have two incident facets')
            other = next(item for item in edge.link_faces if item is not face)
            old = [points(face),points(other)]
            vertices = set(face.verts)|set(other.verts)
            if len(vertices) != 4:
                raise ValueError('Reviewed diagonal needs four distinct vertices')
            opposite = [next(v for v in item.verts if v not in edge.verts) for item in (face,other)]
            if kind == 'ground':
                if not all(-16<v.co.x<-14 and 2<v.co.y<4 and v.co.z==0 for v in vertices):
                    raise ValueError('Reviewed cut-diagonal quadrilateral exceeds its local window')
                boundary = outer_boundary(old)
                chain = dict(boundary)
                first = min(chain);quad = [first]
                for _ in range(3):quad.append(chain[quad[-1]])
                if len(chain)!=4 or chain[quad[-1]]!=first:
                    raise ValueError('Ground boundary is not one quadrilateral')
                turns=[]
                for i in range(4):
                    a,b,c = (tuple(Fraction(v) for v in quad[j%4]) for j in (i,i+1,i+2))
                    turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
                if not (all(v<0 for v in turns) or all(v>0 for v in turns)):
                    raise ValueError('Ground quad must be strictly convex before rotation')
            else:
                side = 1 if points(face)[0][0]>0 else -1
                if not all(8.8<side*v.co.x<9 and -23.6<v.co.y<-23.3 and 59<v.co.z<59.2 for v in vertices):
                    raise ValueError('Reviewed cut-diagonal quadrilateral exceeds its local window')
                if not all(-26<v.co.x<26 and -32<v.co.y<2 and 54<v.co.z<76 for v in vertices):
                    raise ValueError('Glasses rotation exceeds the exact existing edit box')
            if any(opposite[1] in e.verts for e in opposite[0].link_edges):
                raise ValueError('Replacement diagonal already exists')
            boundary = outer_boundary(old)
            main_normal = normal(points(other))
            old_minimum = min(altitude(row) for row in old)
            changed = bmesh.ops.rotate_edges(bm,edges=[edge],use_ccw=False)['edges']
            if len(changed)!=1 or set(changed[0].verts)!=set(opposite) or len(changed[0].link_faces)!=2:
                raise ValueError('Unexpected cut-diagonal rotation result')
            new = [points(item) for item in changed[0].link_faces]
            if outer_boundary(new)!=boundary or {p for row in new for p in row}!={p for row in old for p in row}:
                raise ValueError('Cut-diagonal rotation changed the oriented boundary or vertices')
            if min(altitude(row) for row in new) <= 4*old_minimum:
                raise ValueError('Cut-diagonal rotation did not improve the reviewed sliver')
            if any(dot(normal(row),main_normal)<=0 or dot(normal(centered(row)),main_normal)<=0 for row in new):
                raise ValueError('Cut-diagonal rotation lost source or centered orientation')
        if (len(bm.verts)!=len(coordinates) or len(bm.faces)!=original_faces or
                any(tuple(v.co)!=p for v,p in coordinates.items()) or face_components(bm)!=1 or
                any(not edge.is_manifold or not edge.is_contiguous for edge in bm.edges) or
                any(not v.is_manifold for v in bm.verts) or bm.calc_volume(signed=True)<=0):
            raise ValueError('Cut-diagonal rotation changed solid coordinates or topology')
        bm.to_mesh(obj.data)
        obj.data.update()
        return expected
    finally:
        bm.free()


def build(revision):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    # Scale before the final Boolean cuts; do not round newly cut vertices a
    # second time by scaling a fused result from meters to millimeters.
    obj = millimeters(cat())
    base = obj.copy()
    base.data = obj.data.copy()
    bpy.context.collection.objects.link(base)
    base.name = 'PrintBase'
    # Freeze the v2 base after the reviewed exact planar ground rotation.
    # Accessory unions never author or retessellate this frozen reference.
    triangulated(base,weld_mm=True)
    stabilize_cut_diagonals(base,'ground')
    base.hide_render = True
    base.hide_set(True)
    if revision == 'r1':
        hat = millimeters(cylinder('brim', .56, .14, 2.64))
        boolean(hat, millimeters(cylinder('crown', .37, .48, 2.91)))
        boolean(hat, millimeters(cylinder('band', .39, .12, 2.76)))
        boolean(obj, hat)
    elif revision == 'r2':
        boolean(obj, millimeters(glasses()))
    elif revision != 'r0':
        raise ValueError('Unknown print revision')
    triangulated(obj,weld_mm=True)
    if revision=='r0':
        stabilize_cut_diagonals(obj,'ground')
    elif revision=='r2':
        stabilize_cut_diagonals(obj,'glasses')
    if revision != 'r0':
        restore_protected(obj,base,revision)
    material = bpy.data.materials.new('Neutral print preview')
    material.diffuse_color = (.72,.72,.72,1)
    for mesh in (obj,base):
        mesh['print_derivation_version'] = DERIVATION_VERSION
        mesh.data.materials.clear()
        mesh.data.materials.append(material)
        for face in mesh.data.polygons:
            face.use_smooth = True
        mesh.data.update()
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = .001
    bpy.context.scene.unit_settings.length_unit = 'MILLIMETERS'
    return obj,base
