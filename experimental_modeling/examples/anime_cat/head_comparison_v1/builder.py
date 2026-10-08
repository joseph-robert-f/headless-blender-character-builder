# SPDX-License-Identifier: GPL-3.0-or-later
"""A distinct gray head comparison, never an accepted print-profile author."""
import argparse
import json
from pathlib import Path
import sys
import struct

import bpy
import bmesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'print'/'source'))
sys.path.insert(0, str(HERE.parent/'print'))
from sculpt import COMPARISON_ID, sculpt
from solids import boolean, cylinder, face_components, glasses, millimeters, triangulated
from x1c_solids import mapped
from x1c_bambu_solids import build_x1c_bambu
from inspect_solid import evaluated_surface, geometry_hash, _normal3

BASE_EXACT = 'bd2b018053fc7686603a3f27f36b309460cd1d9507c24a85205b5d81a9e8b8a7'
ACCESSORY_BOXES = {
    'r1': ((-21.709264755249023, -21.709264755249023, 86.8370590209961),
           (21.709264755249023, 21.709264755249023, 111.8027114868164)),
    'r2': ((-28.222043991088867, -34.734825134277344, 58.61501693725586),
           (28.222043991088867, 2.170926570892334, 82.49520874023438))}


def restore_exterior(obj, base, revision):
    """Assemble exact base facets outside the unchanged scaled accessory box.

    Use the existing protected-assembly rule in final millimeters. Retain all
    boundary-touching base facets and every union facet wholly inside the box.
    Join only identical coordinates; reject changed interfaces transactionally.
    """
    low, high = ACCESSORY_BOXES[revision]
    vertices, faces, indices = [], [], {}
    for mesh, keep_inside in ((obj.data, True), (base.data, False)):
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            if (face_components(bm) != 1 or bm.calc_volume(signed=True) <= 0
                    or any(not e.is_manifold or not e.is_contiguous for e in bm.edges)
                    or any(not v.is_manifold for v in bm.verts)):
                raise ValueError('Exact assembly requires complete closed single-shell operands')
        finally:
            bm.free()
        for face in mesh.polygons:
            points = [tuple(mesh.vertices[index].co) for index in face.vertices]
            if len(points) != 3:
                raise ValueError('Exact assembly requires finalized triangles')
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
    replacement = bpy.data.meshes.new('Exact comparison base and accessory')
    replacement.from_pydata(vertices, [], faces)
    bm = bmesh.new()
    try:
        bm.from_mesh(replacement)
        if (face_components(bm) != 1 or bm.calc_volume(signed=True) <= 0
                or any(not e.is_manifold or not e.is_contiguous for e in bm.edges)
                or any(not v.is_manifold for v in bm.verts)):
            raise ValueError('Exact comparison interface must retain one closed oriented solid')
    except Exception:
        bpy.data.meshes.remove(replacement)
        raise
    finally:
        bm.free()
    previous = obj.data
    obj.data = replacement
    if previous.users == 0:
        bpy.data.meshes.remove(previous)


def accessory(revision):
    if revision == 'r1':
        obj = millimeters(cylinder('brim', .56, .14, 2.64))
        boolean(obj, millimeters(cylinder('crown', .37, .48, 2.91)))
        boolean(obj, millimeters(cylinder('band', .39, .12, 2.76)))
    elif revision == 'r2':
        obj = millimeters(glasses())
    else:
        raise ValueError('Unknown comparison accessory')
    for vertex in obj.data.vertices:
        vertex.co = mapped(tuple(vertex.co))
    obj.data.update()
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--params', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--baseline')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    params = json.loads(Path(args.params).read_text())
    if set(params) != {'revision'} or params['revision'] not in ('r0', 'r1', 'r2'):
        raise ValueError('Select one fixed comparison revision')
    if args.baseline:
        bpy.ops.wm.open_mainfile(filepath=str(Path(args.baseline).resolve()))
        candidate, base = bpy.data.objects['PrintCandidate'], bpy.data.objects['PrintBase']
    else:
        candidate, base = build_x1c_bambu('r0')
    for obj in (candidate, base):
        with evaluated_surface(obj) as (_, bm):
            if geometry_hash(bm, exact=True) != BASE_EXACT:
                raise ValueError('Comparison requires the exact finalized v3 bare baseline')
    evidence = sculpt(candidate)
    base.name = 'ComparisonBaseline'
    base.hide_render = True
    base.hide_set(True)
    base = candidate.copy()
    base.data = candidate.data.copy()
    bpy.context.collection.objects.link(base)
    base.name = 'PrintBase'
    base.hide_render = True
    base.hide_set(True)
    revision = params['revision']
    if revision != 'r0':
        boolean(candidate, accessory(revision))
        triangulated(candidate, weld_mm=True)
        restore_exterior(candidate, base, revision)
    candidate.name = 'PrintCandidate'
    for obj in (candidate, base):
        obj['comparison_id'] = COMPARISON_ID
        obj['comparison_revision'] = revision
        obj['print_profile_id'] = COMPARISON_ID
        obj['promotion_eligible'] = False
        for face in obj.data.polygons:
            face.use_smooth = True
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False)
    with evaluated_surface(candidate) as (_, bm):
        triangles = []
        for face in bm.faces:
            points = tuple(tuple(float(value) for value in vertex.co) for vertex in face.verts)
            triangles.append(min(points[i:]+points[:i] for i in range(3)))
        with (output.parent/'model.stl').open('xb') as stream:
            stream.write(b'Head comparison v1 millimeter STL'.ljust(80, b'\0'))
            stream.write(struct.pack('<I', len(triangles)))
            for points in sorted(triangles):
                stream.write(struct.pack('<12fH', *_normal3(points),
                                         *(v for point in points for v in point), 0))
    (output.parent/'author-observation.json').write_text(json.dumps({
        'comparison_id': COMPARISON_ID, 'revision': revision,
        'baseline_exact_surface_sha256': BASE_EXACT, 'head_edit': evidence,
        'promotion_eligible': False, 'physical_validation': 'pending'}, indent=2)+'\n')


if __name__ == '__main__':
    main()
