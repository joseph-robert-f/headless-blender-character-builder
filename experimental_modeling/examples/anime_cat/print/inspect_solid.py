# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent bounded observer of the complete evaluated print surfaces.

This script does not import the author. Partial feature probes and renders do
not establish physical printability or authorize artifact promotion.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

MAX_TRIANGLES = 500000
MAX_REPORT_BYTES = 4 * 1024**2
SCALE = 100.0 / 3.15  # Independently fixed by provisional_fdm_v1.
DEFAULT_PROFILE_ID = 'anime-cat-fdm-provisional-v1'
X1C_PROFILE_ID = 'anime-cat-x1c-pla-04-bare100-v2'
PROFILE_ID = DEFAULT_PROFILE_ID
PROFILE_SHA256 = '0c718776d23213ce6182ca0cf302b6e48827a2205d6a9f8fe69f381e4b646f32'
FINAL_SCALE = 1.0


# Coordinates below are millimeters. Tests use this explicit numerical tolerance.
INTERSECTION_TOLERANCE = 1e-5
MAX_INTERSECTION_PAIRS = 20000000
PROTECTED_EXCLUSIONS_MM = {
    'r1': ((-20,-20,80),(20,20,103)),
    'r2': ((-26,-32,54),(26,2,76)),
}


def configure_profile(profile_id=DEFAULT_PROFILE_ID):
    """Select independently reviewed fixed policy; never derive it from a mesh."""
    global PROFILE_ID, PROFILE_SHA256, FINAL_SCALE, PROTECTED_EXCLUSIONS_MM
    if profile_id == DEFAULT_PROFILE_ID:
        PROFILE_SHA256 = '0c718776d23213ce6182ca0cf302b6e48827a2205d6a9f8fe69f381e4b646f32'
        FINAL_SCALE = 1.0
        PROTECTED_EXCLUSIONS_MM = {'r1':((-20,-20,80),(20,20,103)),
                                   'r2':((-26,-32,54),(26,2,76))}
    elif profile_id == X1C_PROFILE_ID:
        PROFILE_SHA256 = '7c7f84e3749e08d24bb163e3364e4831278ba3908f780f1b44ac2b0a928da915'
        FINAL_SCALE = 1.0854632543541882
        # Fixed float32-scaled endpoints retain exact boundary facets.
        PROTECTED_EXCLUSIONS_MM = {
            'r1':((-21.709264755249023,-21.709264755249023,86.8370590209961),
                  (21.709264755249023,21.709264755249023,111.8027114868164)),
            'r2':((-28.222043991088867,-34.734825134277344,58.61501693725586),
                  (28.222043991088867,2.170926570892334,82.49520874023438)),
        }
    else:
        raise ValueError('Unknown independently reviewed print profile')
    PROFILE_ID = profile_id


def profile_binding():
    return {'profile_id':PROFILE_ID,'profile_sha256':PROFILE_SHA256}


def require_profile_binding(report):
    if any(report.get(key) != value for key,value in profile_binding().items()):
        raise ValueError('Observation uses a different print profile')


def _cross2(a, b):
    return a[0]*b[1] - a[1]*b[0]


def _coplanar_crossing(points_a,points_b,shared_point,normal):
    """Clip exact triangle interiors; proximity alone is not intersection."""
    drop = max(range(3),key=lambda i:abs(normal[i]))
    axes = [i for i in range(3) if i != drop]
    triangles = [[(p[axes[0]],p[axes[1]]) for p in points] for points in (points_a,points_b)]
    def subtract(a,b):
        return (a[0]-b[0],a[1]-b[1])
    polygon,clip = triangles
    if _cross2(subtract(clip[1],clip[0]),subtract(clip[2],clip[0])) < 0:
        clip = clip[::-1]
    for i in range(3):
        start,end = clip[i],clip[(i+1)%3]
        edge = subtract(end,start)
        output = []
        if not polygon:
            return False
        previous = polygon[-1]
        previous_side = _cross2(edge,subtract(previous,start))
        for current in polygon:
            current_side = _cross2(edge,subtract(current,start))
            if (previous_side >= 0) != (current_side >= 0):
                t = previous_side/(previous_side-current_side)
                output.append((previous[0]+t*(current[0]-previous[0]),previous[1]+t*(current[1]-previous[1])))
            if current_side >= 0:
                output.append(current)
            previous,previous_side = current,current_side
        polygon = output
    if not polygon:
        return False
    origin = polygon[0]
    area = abs(sum(_cross2(subtract(polygon[i],origin),subtract(polygon[(i+1)%len(polygon)],origin)) for i in range(len(polygon))))/2
    if area > 1e-10:
        return True
    shared = (shared_point[axes[0]],shared_point[axes[1]])
    return any(math.dist(point,shared) > INTERSECTION_TOLERANCE for point in polygon)


def _subtract3(a,b):
    return tuple(a[i]-b[i] for i in range(3))


def _dot3(a,b):
    return sum(a[i]*b[i] for i in range(3))


def _cross3(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def _area3(points):
    cross = _cross3(_subtract3(points[1],points[0]),_subtract3(points[2],points[0]))
    return math.sqrt(_dot3(cross,cross))/2


def _normal3(points):
    cross = _cross3(_subtract3(points[1],points[0]),_subtract3(points[2],points[0]))
    length = math.sqrt(_dot3(cross,cross))
    if length == 0:
        raise ValueError('Degenerate intersection triangle')
    return tuple(value/length for value in cross)


def _inside_triangle(point,points,normal):
    drop = max(range(3),key=lambda i:abs(normal[i]))
    axes = [i for i in range(3) if i != drop]
    rows = [(p[axes[0]],p[axes[1]]) for p in points]
    p = (point[axes[0]],point[axes[1]])
    values = [_cross2((rows[(i+1)%3][0]-rows[i][0],rows[(i+1)%3][1]-rows[i][1]),
                      (p[0]-rows[i][0],p[1]-rows[i][1])) for i in range(3)]
    return all(v >= -1e-12 for v in values) or all(v <= 1e-12 for v in values)


def _triangle_crossing(left,right):
    # Double precision avoids false intersections near a shared vertex when
    # float32 ray intersection moves the computed hit away from that vertex.
    points_a,ids_a,normal_a = left[:3]
    points_b,ids_b,normal_b = right[:3]
    shared = set(ids_a).intersection(ids_b)
    epsilon = INTERSECTION_TOLERANCE
    if len(shared) == 3:
        return True
    normal_cross = _cross3(normal_a,normal_b)
    parallel = _dot3(normal_cross,normal_cross) < 1e-18
    if len(shared) == 2:
        if not parallel:
            return False
        common = [point for point,index in zip(points_a,ids_a) if index in shared]
        extra_a = next(point for point,index in zip(points_a,ids_a) if index not in shared)
        extra_b = next(point for point,index in zip(points_b,ids_b) if index not in shared)
        edge = _subtract3(common[1],common[0])
        return _dot3(_cross3(edge,_subtract3(extra_a,common[0])),_cross3(edge,_subtract3(extra_b,common[0]))) > 0
    distances_a = [_dot3(normal_b,_subtract3(point,points_b[0])) for point,index in zip(points_a,ids_a) if index not in shared]
    distances_b = [_dot3(normal_a,_subtract3(point,points_a[0])) for point,index in zip(points_b,ids_b) if index not in shared]
    for distances in (distances_a,distances_b):
        if all(value > epsilon for value in distances) or all(value < -epsilon for value in distances):
            return False
    shared_point = next((point for point,index in zip(points_a,ids_a) if index in shared),(1e30,)*3)
    if parallel and max(abs(value) for value in distances_a+distances_b) <= epsilon:
        return _coplanar_crossing(points_a,points_b,shared_point,normal_a)
    for triangle,other,normal in ((points_a,points_b,normal_b),(points_b,points_a,normal_a)):
        for i in range(3):
            start,end = triangle[i],triangle[(i+1)%3]
            first = _dot3(normal,_subtract3(start,other[0]))
            last = _dot3(normal,_subtract3(end,other[0]))
            denominator = first-last
            if abs(denominator) < 1e-14:
                # An edge on the other plane is covered by its endpoint contacts.
                candidates = [p for p in (start,end) if abs(_dot3(normal,_subtract3(p,other[0]))) < 1e-12]
            else:
                t = first/denominator
                candidates = [tuple(start[j]+t*(end[j]-start[j]) for j in range(3))] if -1e-12 <= t <= 1+1e-12 else []
            for hit in candidates:
                if _inside_triangle(hit,other,normal) and (not shared or math.dist(hit,shared_point) > epsilon):
                    return True
    return False


def intersections(bm):
    """Complete AABB candidates, including coplanar and shared-vertex pairs.

    Radius buckets keep KD-tree queries bounded for both small surface facets
    and large ground triangles. Overlapping triangles have overlapping bounding
    spheres; the query radius includes both spheres and numerical tolerance.
    """
    from mathutils.kdtree import KDTree
    bm.normal_update()
    rows, buckets = [], {}
    for face in bm.faces:
        points = tuple(tuple(float(v) for v in vertex.co) for vertex in face.verts)
        # Keep ordered IDs for correspondence with triangle points.
        ids = tuple(vertex.index for vertex in face.verts)
        center = Vector(tuple(sum(point[i] for point in points)/3 for i in range(3)))
        radius = max(math.dist(point,center) for point in points)
        if radius <= 0 or _area3(points) <= 1e-10:
            raise ValueError('Degenerate triangle cannot support complete intersection measurement')
        low = tuple(min(point[i] for point in points) for i in range(3))
        high = tuple(max(point[i] for point in points) for i in range(3))
        row = (points,ids,_normal3(points),low,high,center,radius)
        rows.append(row)
        buckets.setdefault(math.frexp(radius)[1],[]).append(len(rows)-1)
    trees = []
    for ids in buckets.values():
        tree = KDTree(len(ids))
        for index in ids:
            tree.insert(rows[index][5],index)
        tree.balance()
        low = tuple(min(rows[index][3][i] for index in ids) for i in range(3))
        high = tuple(max(rows[index][4][i] for index in ids) for i in range(3))
        trees.append((tree,max(rows[index][6] for index in ids),low,high))
    examples, tested = [], 0
    epsilon = INTERSECTION_TOLERANCE
    for i,left in enumerate(rows):
        for tree,radius,low,high in trees:
            if any(left[3][axis] > high[axis]+epsilon or left[4][axis] < low[axis]-epsilon for axis in range(3)):
                continue
            for _,j,_ in tree.find_range(left[5],left[6]+radius+2*epsilon):
                if j <= i:
                    continue
                right = rows[j]
                if any(left[3][axis] > right[4][axis]+epsilon or left[4][axis] < right[3][axis]-epsilon for axis in range(3)):
                    continue
                tested += 1
                if tested > MAX_INTERSECTION_PAIRS:
                    raise ValueError('Complete intersection candidate budget exceeded')
                if _triangle_crossing(left,right):
                    examples.append((i,j))
                    if len(examples) >= 20:
                        return {'count_lower_bound':len(examples),'examples':examples,'complete':False,'pairs_tested':tested}
    return {'count_lower_bound':len(examples),'examples':examples,'complete':True,'pairs_tested':tested}


def geometry_hash(bm, excluded_box=None, exact=False):
    """Hash every oriented world triangle, independent of indices and ordering."""
    rows = []
    for face in bm.faces:
        if excluded_box is not None:
            low,high = excluded_box
            if all(low[i] < vertex.co[i] < high[i] for vertex in face.verts for i in range(3)):
                continue
        points = [tuple((float(v) if v else 0.0) if exact else round(float(v),6)
                        for v in vertex.co) for vertex in face.verts]
        rotations = [tuple(points[i:] + points[:i]) for i in range(3)]
        canonical = min(rotations)
        rows.append(struct.pack('<9f',*(v for point in canonical for v in point)) if exact else repr(canonical).encode('ascii'))
    digest = hashlib.sha256()
    for row in sorted(rows):
        digest.update(row if exact else row+b'\n')
    return digest.hexdigest()


def protected_regions(bm):
    result = {}
    for revision,box in PROTECTED_EXCLUSIONS_MM.items():
        low,high = box
        count = sum(not all(low[i] < vertex.co[i] < high[i] for vertex in face.verts for i in range(3)) for face in bm.faces)
        result[revision] = {'excluded_box_mm':{'min':list(low),'max':list(high)},
                            'triangles':count,'surface_sha256':geometry_hash(bm,box,exact=True),
                            'method':'canonical_oriented_exact_float32_boundary_facets_retained'}
    return result


def read_stl(path):
    """Read every binary STL triangle; weld only identical encoded coordinates."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 284 <= path.stat().st_size <= 84+50*MAX_TRIANGLES:
        raise ValueError('STL must be a bounded regular binary file')
    data = path.read_bytes()
    count = struct.unpack_from('<I',data,80)[0]
    if not 4 <= count <= MAX_TRIANGLES or len(data) != 84+50*count:
        raise ValueError('STL length and complete triangle count disagree')
    vertices,faces,indices = [],[],{}
    for row in struct.iter_unpack('<12fH',data[84:]):
        if row[-1] != 0 or any(not math.isfinite(value) for value in row[:-1]):
            raise ValueError('Unsupported STL attributes or non-finite coordinate/normal')
        face = []
        for start in (3,6,9):
            point = tuple(row[start:start+3])
            if point not in indices:
                indices[point] = len(vertices)
                vertices.append(point)
            face.append(indices[point])
        if len(set(face)) != 3:
            raise ValueError('STL contains a collapsed triangle')
        faces.append(face)
    return data,vertices,faces


def stl_object(path):
    data,vertices,faces = read_stl(path)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    mesh = bpy.data.meshes.new('Complete reimported STL')
    mesh.from_pydata(vertices,[],faces)
    obj = bpy.data.objects.new('PrintCandidate',mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    for face in mesh.polygons:
        face.use_smooth = True
    material = bpy.data.materials.new('Neutral print preview')
    material.diffuse_color = (.72,.72,.72,1)
    mesh.materials.append(material)
    units = bpy.context.scene.unit_settings
    units.system,units.scale_length,units.length_unit = 'METRIC',.001,'MILLIMETERS'
    return data,obj,len(faces)


def shells(bm):
    remaining = set(bm.faces)
    groups = []
    while remaining:
        pending = [remaining.pop()]
        group = set(pending)
        while pending:
            for edge in pending.pop().edges:
                for neighbor in edge.link_faces:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        pending.append(neighbor)
                        group.add(neighbor)
        points = [vertex.co for face in group for vertex in face.verts]
        groups.append({"triangles": len(group), "min": [min(p[i] for p in points) for i in range(3)],
                       "max": [max(p[i] for p in points) for i in range(3)]})
    return sorted(groups, key=lambda row: -row["triangles"])


def thickness(bvh, revision):
    probes = []
    for sign in (-1, 1):
        for i in range(2):
            probes.append((f'whisker-{sign}-{i}', (sign*.72, -.55, 1.82-i*.14), 'radial'))
    if revision == 'r1':
        probes.append(('hat-brim', (.50, -.02, 2.64), 'z'))
    if revision == 'r2':
        probes.append(('glasses-bridge', (0, -.845, 2.13), 'radial'))
    results = []
    for name, xyz, axis in probes:
        center = Vector(xyz) * SCALE
        if FINAL_SCALE != 1.0:
            center = Vector(tuple(struct.unpack('<f',struct.pack('<f',float(v)*FINAL_SCALE))[0]
                                  for v in center))
        chords = []
        directions = [Vector((0, 0, 1))] if axis == 'z' else [
            Vector((0, math.cos(i*math.pi/8), math.sin(i*math.pi/8))) for i in range(8)]
        for direction in directions:
            rays = [bvh.ray_cast(center, direction*sign, 8) for sign in (-1, 1)]
            if any(hit[0] is None or hit[1].dot(direction*sign) <= 0 for hit, sign in zip(rays, (-1, 1))):
                raise ValueError('Feature probe does not lie inside the intended solid: ' + name)
            chords.append(sum(hit[3] for hit in rays))
        results.append({'feature': name, 'minimum_chord_mm': min(chords), 'chords': len(chords)})
    return {'method': 'Opposing first-exit surface rays at independently fixed feature centers',
            'coverage': 'partial', 'minimum_mm': min(row['minimum_chord_mm'] for row in results),
            'sample_count': sum(row['chords'] for row in results), 'samples': results}


@contextmanager
def evaluated_surface(obj):
    if obj.modifiers:
        raise ValueError('Apply every modifier before independent print inspection')
    if any(not math.isfinite(value) for row in obj.matrix_world for value in row):
        raise ValueError('Non-finite transform')
    if any(abs(obj.matrix_world[i][j] - Matrix.Identity(4)[i][j]) > 1e-7 for i in range(4) for j in range(4)):
        raise ValueError('Print coordinates require applied identity transforms')
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    bm = bmesh.new()
    try:
        if any(len(face.vertices) != 3 for face in mesh.polygons):
            raise ValueError('Final evaluated polygons must be explicit triangles')
        mesh.calc_loop_triangles()
        if not 0 < len(mesh.loop_triangles) <= MAX_TRIANGLES:
            raise ValueError('Complete evaluated triangle budget exceeded')
        bm.from_mesh(mesh)
        bm.transform(evaluated.matrix_world)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        if any(not math.isfinite(value) for vertex in bm.verts for value in vertex.co):
            raise ValueError('Non-finite evaluated vertex')
        yield mesh,bm
    finally:
        bm.free()
        evaluated.to_mesh_clear()


def observe(obj, revision, include_protected=False, allow_missing_features=False):
    with evaluated_surface(obj) as (mesh,bm):
        bvh = BVHTree.FromBMesh(bm, epsilon=0)
        crossing = intersections(bm)
        coordinates = [vertex.co for vertex in bm.verts]
        low = [min(point[i] for point in coordinates) for i in range(3)]
        high = [max(point[i] for point in coordinates) for i in range(3)]
        components = shells(bm)
        result = {
            'evaluated_triangles': len(mesh.loop_triangles), 'measured_triangles': len(bm.faces),
            'vertices': len(bm.verts), 'non_manifold_edges': sum(not edge.is_manifold for edge in bm.edges),
            'boundary_edges':sum(edge.is_boundary for edge in bm.edges),
            'non_manifold_vertices': sum(not vertex.is_manifold for vertex in bm.verts),
            'loose_vertices': sum(not vertex.link_faces for vertex in bm.verts),
            'inconsistent_winding_edges': sum(edge.is_manifold and not edge.is_contiguous for edge in bm.edges),
            'degenerate_triangles': sum(_area3(tuple(tuple(float(x) for x in vertex.co) for vertex in face.verts)) <= 1e-10 for face in bm.faces),
            'face_connected_shells': len(components), 'components': components[:20], 'signed_volume_mm3': bm.calc_volume(signed=True),
            'bounds_mm': {'min': low, 'max': high}, 'dimensions_mm': [high[i]-low[i] for i in range(3)],
            'self_intersections': crossing['count_lower_bound'], 'intersection_measurement': crossing,
            'intersection_tolerance_mm': INTERSECTION_TOLERANCE,
            'surface_sha256': geometry_hash(bm),
            'exact_surface_sha256': geometry_hash(bm,exact=True),
        }
        if obj.name == 'PrintCandidate':
            try:
                result['feature_probes'] = thickness(bvh, revision)
            except ValueError as exc:
                if not allow_missing_features:
                    raise
                result['feature_probes'] = {'minimum_mm':0,'sample_count':0,'samples':[],
                                          'coverage':'partial','error':str(exc)}
        if include_protected:
            result['protected_regions'] = protected_regions(bm)
        return result



def render_binding(obj, report, revision, input_sha256):
    require_profile_binding(report)
    if (report['revision'] != revision or report['unit'] != 'millimeter' or
            report['input_sha256'] != input_sha256):
        raise ValueError('Render reference does not bind to this saved candidate')
    measured = report['meshes']['PrintCandidate']
    if measured['intersection_measurement']['complete'] is not True:
        raise ValueError('Render requires a complete independent geometry observation')
    with evaluated_surface(obj) as (mesh,bm):
        if (len(mesh.loop_triangles) != measured['evaluated_triangles'] or
                len(bm.faces) != measured['measured_triangles'] or
                geometry_hash(bm) != measured['surface_sha256'] or
                geometry_hash(bm,exact=True) != measured['exact_surface_sha256']):
            raise ValueError('Render surface differs from the complete geometry observation')
        points = [vertex.co for vertex in bm.verts]
        bounds = {'min':[min(p[i] for p in points) for i in range(3)],
                  'max':[max(p[i] for p in points) for i in range(3)]}
        if bounds != measured['bounds_mm']:
            raise ValueError('Render bounds differ from the observed surface')
    return {**profile_binding(),'input_sha256':input_sha256,'surface_sha256':measured['surface_sha256'],
            'exact_surface_sha256':measured['exact_surface_sha256'],
            'measured_triangles':measured['measured_triangles'],'bounds_mm':bounds}


def render_views(obj, directory, bounds):
    scene = bpy.context.scene
    center = (Vector(bounds['min']) + Vector(bounds['max'])) / 2
    radius = (Vector(bounds['max']) - Vector(bounds['min'])).length / 2
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = 'BOTH'
    scene.display.shading.background_type = 'WORLD'
    scene.world.color = (.12, .12, .12)
    camera_data = bpy.data.cameras.new('Independent print camera')
    camera = bpy.data.objects.new('Independent print camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = radius * 2.4
    camera_data.clip_start, camera_data.clip_end = .1, radius * 20 + 100
    directory.mkdir()
    for name, direction in [('front',(0,-1,0)), ('right',(1,0,0)), ('top',(0,0,1)), ('iso',(1,-1,.7))]:
        camera.location = center + Vector(direction).normalized() * radius * 5
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(directory / (name+'.png'))
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)


def validate_inventory():
    if any(obj.type not in {'MESH','CAMERA','LIGHT'} or obj.instance_type != 'NONE' for obj in bpy.context.scene.objects):
        raise ValueError('Unsupported geometry or instances are not permitted in print candidates')
    if any(item.is_instance for item in bpy.context.evaluated_depsgraph_get().object_instances):
        raise ValueError('Instanced evaluated geometry is not permitted')
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.get('print_profile_id',DEFAULT_PROFILE_ID) != PROFILE_ID:
            raise ValueError('Saved mesh uses a different print profile')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--revision', choices=('r0','r1','r2'), required=True)
    parser.add_argument('--no-renders', action='store_true')
    parser.add_argument('--render-reference')
    parser.add_argument('--stl', action='store_true')
    parser.add_argument('--target', choices=('PrintBase','PrintCandidate'))
    parser.add_argument('--profile-id', choices=(DEFAULT_PROFILE_ID,X1C_PROFILE_ID),default=DEFAULT_PROFILE_ID)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    configure_profile(args.profile_id)
    if args.render_reference and (args.no_renders or args.target != 'PrintCandidate'):
        raise ValueError('Render reference requires the visible candidate render stage')
    if args.stl:
        data,obj,count = stl_object(args.input)
        if args.render_reference:
            reference = Path(args.render_reference)
            if reference.is_symlink() or not reference.is_file() or reference.stat().st_size > MAX_REPORT_BYTES:
                raise ValueError('Render reference must be a bounded regular observation')
            raw = reference.read_bytes()
            binding = render_binding(obj,json.loads(raw),args.revision,hashlib.sha256(data).hexdigest())
            binding['observation_sha256'] = hashlib.sha256(raw).hexdigest()
            output = Path(args.output)
            output.mkdir(exist_ok=True)
            render_views(obj,output/'views',binding['bounds_mm'])
            (output/'render-binding.json').write_text(json.dumps(binding,indent=2,allow_nan=False)+'\n')
            return
        measured = observe(obj,args.revision,include_protected=True,allow_missing_features=True)
        if measured['evaluated_triangles'] != count or measured['measured_triangles'] != count:
            raise ValueError('STL measurement omitted input triangles')
        report = {**profile_binding(),'schema_version':1,'revision':args.revision,'unit':'millimeter',
                  'measurement_source':'reimported_final_stl','stl_triangle_count':count,
                  'input_sha256':hashlib.sha256(data).hexdigest(),'blender_version':bpy.app.version_string,
                  'promotion_eligible':False,'physical_validation':'pending',
                  'meshes':{'PrintCandidate':measured}}
        encoded = json.dumps(report,indent=2,allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_REPORT_BYTES:
            raise ValueError('STL observation exceeds the existing 4 MiB bound')
        output = Path(args.output)
        output.mkdir(exist_ok=True)
        (output/'solid-observation.json').write_bytes(encoded)
        return
    bpy.ops.wm.open_mainfile(filepath=str(Path(args.input).resolve()))
    validate_inventory()
    meshes = {obj.name: obj for obj in bpy.context.scene.objects if obj.type == 'MESH'}
    if set(meshes) != {'PrintCandidate','PrintBase'}:
        raise ValueError('Expected one candidate and one preserved base')
    units = bpy.context.scene.unit_settings
    if units.system != 'METRIC' or abs(units.scale_length-.001) > 1e-10 or units.length_unit != 'MILLIMETERS':
        raise ValueError('Expected explicit millimeter scene coordinates')
    if meshes['PrintCandidate'].hide_render or not meshes['PrintBase'].hide_render:
        raise ValueError('Incorrect visible candidate or hidden reference')
    if args.render_reference:
        if args.no_renders or args.target != 'PrintCandidate':
            raise ValueError('Render reference requires the visible candidate render stage')
        reference = Path(args.render_reference)
        if not reference.is_file() or reference.is_symlink() or reference.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('Render reference must be a bounded regular observation')
        encoded = reference.read_bytes()
        binding = render_binding(meshes['PrintCandidate'],json.loads(encoded),args.revision,
                                 hashlib.sha256(Path(args.input).read_bytes()).hexdigest())
        binding['observation_sha256'] = hashlib.sha256(encoded).hexdigest()
        output = Path(args.output)
        output.mkdir(exist_ok=True)
        render_views(meshes['PrintCandidate'],output/'views',binding['bounds_mm'])
        (output/'render-binding.json').write_text(json.dumps(binding,indent=2,allow_nan=False)+'\n')
        return
    report = {**profile_binding(),'schema_version': 1, 'revision': args.revision, 'unit': 'millimeter',
              'measurement_source': 'evaluated_saved_blend',
              'blender_version': bpy.app.version_string, 'promotion_eligible': False,
              'physical_validation': 'pending', 'feature_coverage': 'unknown',
              'input_sha256': hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
              'meshes': {name: observe(obj,args.revision) for name,obj in sorted(meshes.items()) if args.target is None or name == args.target}}
    encoded = json.dumps(report, indent=2, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError('Observation exceeds the existing 4 MiB bound')
    output = Path(args.output)
    output.mkdir(exist_ok=True)
    (output/'solid-observation.json').write_bytes(encoded)
    if not args.no_renders and args.target != 'PrintBase':
        render_views(meshes['PrintCandidate'], output/'views', report['meshes']['PrintCandidate']['bounds_mm'])


if __name__ == '__main__':
    main()
