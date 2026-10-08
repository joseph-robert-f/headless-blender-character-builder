# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent complete geometry and matched gray comparison views."""
import argparse
from collections import Counter
import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

COMPARISON_ID = 'anime-cat-head-comparison-v1'
BASE_EXACT = 'bd2b018053fc7686603a3f27f36b309460cd1d9507c24a85205b5d81a9e8b8a7'
HEAD_BOX_MM = ((-36.0, -36.0, 54.0), (36.0, 24.0, 100.5))
ACCESSORY_BOXES = {
    'r1': ((-21.709264755249023, -21.709264755249023, 86.8370590209961),
           (21.709264755249023, 21.709264755249023, 111.8027114868164)),
    'r2': ((-28.222043991088867, -34.734825134277344, 58.61501693725586),
           (28.222043991088867, 2.170926570892334, 82.49520874023438))}


def exterior(observer, obj, box):
    with observer.evaluated_surface(obj) as (_, bm):
        return observer.geometry_hash(bm, box, exact=True)


def render(obj, root):
    # The same fixed camera, lighting, gray material and scale for every A/B
    # image. No camera fitting can make a narrower head appear equally full.
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    shading = scene.display.shading
    shading.light, shading.color_type = 'STUDIO', 'SINGLE'
    shading.single_color = (.72, .72, .72)
    shading.show_shadows = True
    shading.show_cavity = True
    shading.cavity_type = 'BOTH'
    shading.background_type = 'WORLD'
    scene.world.color = (.12, .12, .12)
    camera_data = bpy.data.cameras.new('Matched comparison camera')
    camera = bpy.data.objects.new('Matched comparison camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = 74.0
    camera_data.clip_start, camera_data.clip_end = .1, 500.0
    center = Vector((0, -3, 76))
    root.mkdir()
    for name, direction in [('front', (0, -1, 0)), ('side', (1, 0, 0)),
                            ('three-quarter', (1, -1, .35))]:
        camera.location = center+Vector(direction).normalized()*200
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(root/(name+'.png'))
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--observer', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--revision', choices=('r0', 'r1', 'r2'), required=True)
    parser.add_argument('--target', choices=('PrintCandidate', 'PrintBase'), default='PrintCandidate')
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--stl', action='store_true')
    parser.add_argument('--render-reference')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    spec = importlib.util.spec_from_loader('frozen_geometry_observer', SourceFileLoader('frozen_geometry_observer', args.observer))
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    observer.configure_profile('anime-cat-x1c-pla-04-bare100-v3')
    if args.stl:
        observer.stl_object(args.input)
    else:
        bpy.ops.wm.open_mainfile(filepath=str(Path(args.input).resolve()))
    names = {o.name for o in bpy.context.scene.objects if o.type == 'MESH'}
    expected = ({'PrintCandidate'} if args.stl else {'PrintBase', 'PrintCandidate'}
                if args.baseline else {'ComparisonBaseline', 'PrintBase', 'PrintCandidate'})
    if names != expected or any(o.type not in {'MESH', 'CAMERA', 'LIGHT'} or o.instance_type != 'NONE' for o in bpy.context.scene.objects):
        raise ValueError('Unexpected comparison geometry inventory')
    units = bpy.context.scene.unit_settings
    if units.system != 'METRIC' or abs(units.scale_length-.001) > 1e-10 or units.length_unit != 'MILLIMETERS':
        raise ValueError('Comparison requires final millimeter coordinates')
    obj = bpy.data.objects[args.target]
    output = Path(args.output)
    output.mkdir(exist_ok=True)
    input_sha = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
    with observer.evaluated_surface(obj) as (_, bm):
        exact = observer.geometry_hash(bm, exact=True)
    if args.render_reference:
        reference = json.loads(Path(args.render_reference).read_text())
        if (reference['input_sha256'] != input_sha or reference['mesh']['exact_surface_sha256'] != exact
                or reference['mesh']['intersection_measurement']['complete'] is not True):
            raise ValueError('Preview must bind to the fully observed saved surface')
        render(obj, output/'views')
        (output/'render-binding.json').write_text(json.dumps({
            'comparison_id': COMPARISON_ID, 'baseline': args.baseline,
            'input_sha256': input_sha, 'exact_surface_sha256': exact,
            'observation_sha256': hashlib.sha256(Path(args.render_reference).read_bytes()).hexdigest(),
            'camera_center_mm': [0, -3, 76], 'ortho_scale_mm': 74,
            'views': ['front', 'side', 'three-quarter'], 'material': 'plain_gray'}, indent=2)+'\n')
        return
    measured = observer.observe(obj, args.revision)
    ear_chords = []
    with observer.evaluated_surface(obj) as (_, bm):
        bvh = BVHTree.FromBMesh(bm, epsilon=0)
        for sign in (-1, 1):
            for x in (.61, .65, .69):
                for z in (2.56, 2.60, 2.64):
                    center = Vector((sign*x, -.12, z))*(100.0/3.15)*1.0854632543541882
                    hits = [bvh.ray_cast(center, Vector((0, direction, 0)), 25)
                            for direction in (-1, 1)]
                    if any(hit[0] is None or hit[1].y*direction <= 0
                           for hit, direction in zip(hits, (-1, 1))):
                        raise ValueError('Fixed ear probe is outside the intended solid')
                    ear_chords.append(sum(hit[3] for hit in hits))
    protected = None
    accessory = None
    base_exact = None
    if not args.baseline and not args.stl:
        original = bpy.data.objects['ComparisonBaseline']
        with observer.evaluated_surface(original) as (_, bm):
            if observer.geometry_hash(bm, exact=True) != BASE_EXACT:
                raise ValueError('Hidden original baseline identity changed')
        base = bpy.data.objects['PrintBase']
        with observer.evaluated_surface(base) as (_, bm):
            base_exact = observer.geometry_hash(bm, exact=True)
        protected = exterior(observer, original, HEAD_BOX_MM) == exterior(observer, base, HEAD_BOX_MM)
        if args.revision != 'r0' and args.target == 'PrintCandidate':
            box = ACCESSORY_BOXES[args.revision]
            accessory = exterior(observer, base, box) == exterior(observer, obj, box)
    report = {'comparison_id': COMPARISON_ID, 'baseline': args.baseline, 'revision': args.revision,
              'measurement_policy_reference': 'anime-cat-x1c-pla-04-bare100-v3',
              'input_sha256': input_sha, 'observer_sha256': hashlib.sha256(Path(args.observer).read_bytes()).hexdigest(),
              'unit': 'millimeter', 'mesh': measured, 'body_exterior_bit_exact': protected,
              'base_exact_surface_sha256': base_exact, 'stl': args.stl,
              'accessory_exterior_bit_exact': accessory, 'head_box_mm': HEAD_BOX_MM,
              'feature_coverage': 'unknown', 'visual_fidelity': 'pending',
              'ear_partial_probes': {'minimum_chord_mm': min(ear_chords),
                                     'sample_count': len(ear_chords), 'chords_mm': ear_chords,
                                     'coverage': 'partial'},
              'promotion_eligible': False, 'physical_validation': 'pending'}
    encoded = json.dumps(report, indent=2, allow_nan=False).encode()
    if len(encoded) > observer.MAX_REPORT_BYTES:
        raise ValueError('Comparison exceeds the unchanged 4 MiB observation limit')
    (output/'observation.json').write_bytes(encoded)


if __name__ == '__main__':
    main()
