# SPDX-License-Identifier: GPL-3.0-or-later
"""Original deterministic test fixture. Only reads supplied JSON and writes supplied blend.
No provider calls, assets, network, credentials, subprocesses or dynamic code.
"""
import argparse
import json
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector

parser = argparse.ArgumentParser()
parser.add_argument('--params', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
params = json.loads(Path(args.params).read_text())
assert params['accessory'] in ('none', 'hat', 'sunglasses')
assert params.get('cat_shift', 0) in (0, 0.15)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

palette = {
    'cream': (0.93, 0.70, 0.43, 1), 'white': (1, 0.94, 0.78, 1),
    'pink': (0.95, 0.34, 0.43, 1), 'ink': (0.035, 0.027, 0.055, 1),
    'iris': (0.18, 0.54, 0.42, 1), 'shine': (1, 1, 1, 1),
    'hat': (0.21, 0.12, 0.39, 1), 'ribbon': (0.94, 0.45, 0.26, 1),
    'lens': (0.025, 0.07, 0.10, 1), 'gold': (0.95, 0.63, 0.19, 1),
}
materials = {}
for name, color in palette.items():
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.roughness = 0.32 if name in ('lens', 'ink', 'iris') else 0.62
    materials[name] = mat
parts = {'cat': [], 'accessory': []}
def finish(obj, name, material, group='cat'):
    obj.name = name
    obj.data.materials.append(materials[material])
    for face in obj.data.polygons:
        face.use_smooth = True
    parts[group].append(obj)
    return obj

def ellipsoid(name, loc, scale, material, group='cat'):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=8, ring_count=5, location=loc)
    obj = bpy.context.object
    obj.scale = scale
    return finish(obj, name, material, group)

def tube(name, points, radius, material, group='cat'):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 3
    curve.bevel_depth = radius
    curve.bevel_resolution = 1
    curve.use_fill_caps = True
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    for point, xyz in zip(spline.bezier_points, points):
        point.co = xyz
        point.handle_left_type = point.handle_right_type = 'AUTO'
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target='MESH')
    return finish(bpy.context.object, name, material, group)

# Front is negative Y. The pose and all cat construction are identical in every state.
ellipsoid('body', (0, 0, 0.96), (0.64, 0.48, 0.82), 'cream')
ellipsoid('bib', (0, -0.438, 1.01), (0.40, 0.095, 0.55), 'white')
for s in (-1, 1):
    ellipsoid('haunch', (s * 0.46, 0.08, 0.43), (0.36, 0.42, 0.40), 'cream')
    ellipsoid('foot', (s * 0.36, -0.32, 0.18), (0.28, 0.38, 0.18), 'white')
    ellipsoid('arm', (s * 0.47, -0.35, 0.77), (0.16, 0.20, 0.45), 'cream')
    ellipsoid('paw', (s * 0.47, -0.43, 0.43), (0.18, 0.19, 0.20), 'white')
tube('curl_tail', [(0.43, 0.22, 0.45), (0.97, 0.25, 0.43), (1.15, 0.20, 0.80), (1.06, 0.12, 1.13), (0.89, 0.10, 1.16)], 0.13, 'cream')
ellipsoid('head', (0, -0.05, 1.96), (0.83, 0.62, 0.72), 'cream')
# Rounded triangular ears, made as closed beveled triangular prisms.
for s in (-1, 1):
    for inner in (False, True):
        x, y, z = s * 0.58, -0.01, 2.45
        if inner:
            verts = [(x-s*.21,-.345,z-.13),(x+s*.15,-.345,z-.13),(x+s*.12,-.345,z+.34),
                     (x-s*.21,-.31,z-.13),(x+s*.15,-.31,z-.13),(x+s*.12,-.31,z+.34)]
        else:
            verts = [(x-s*.29,-.31,z-.20),(x+s*.23,-.31,z-.20),(x+s*.16,-.22,z+.48),
                     (x-s*.29,.21,z-.20),(x+s*.23,.21,z-.20),(x+s*.16,.16,z+.48)]
        mesh = bpy.data.meshes.new('ear')
        faces = [(0,2,1),(3,4,5),(0,1,4,3),(1,2,5,4),(2,0,3,5)]
        if s == 1:
            faces = [tuple(reversed(face)) for face in faces]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new('ear', mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        mod = obj.modifiers.new('rounded_edges', 'BEVEL'); mod.width = .045 if not inner else .022; mod.segments = 3
        bpy.ops.object.modifier_apply(modifier=mod.name)
        finish(obj, 'inner_ear' if inner else 'ear', 'pink' if inner else 'cream')
for s in (-1, 1):
    ellipsoid('eye_white', (s*.32, -.594, 2.02), (.255, .11, .30), 'white')
    ellipsoid('eye_iris', (s*.31, -.686, 2.03), (.174, .055, .23), 'iris')
    ellipsoid('eye_pupil', (s*.30, -.731, 2.04), (.097, .028, .18), 'ink')
    ellipsoid('eye_sparkle', (s*.30-.043, -.754, 2.12), (.049, .016, .064), 'shine')
    ellipsoid('small_sparkle', (s*.30+.039, -.756, 1.97), (.023, .012, .028), 'shine')
    ellipsoid('muzzle', (s*.14, -.619, 1.75), (.20, .13, .15), 'white')
    ellipsoid('blush', (s*.55, -.538, 1.78), (.13, .033, .064), 'pink')
    for i in range(2):
        tube('whisker', [(s*.52,-.58,1.79-i*.10), (s*.76,-.55,1.82-i*.14), (s*.92,-.51,1.84-i*.16)], .013, 'ink')
ellipsoid('nose', (0, -.757, 1.79), (.075, .04, .052), 'pink')
for s in (-1, 1):
    tube('smile', [(0,-.750,1.75),(s*.065,-.754,1.68),(s*.13,-.737,1.70)], .018, 'ink')

if params['accessory'] == 'hat':
    for name, radius, depth, z, material in [('hat_brim',.56,.09,2.64,'hat'),('hat_crown',.37,.48,2.91,'hat'),('hat_band',.38,.12,2.76,'ribbon')]:
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius, depth=depth, location=(0,-.02,z))
        obj=bpy.context.object
        mod=obj.modifiers.new('hat_rounding','BEVEL');mod.width=.035;mod.segments=1
        bpy.ops.object.modifier_apply(modifier=mod.name)
        finish(obj,name,material,'accessory')
elif params['accessory'] == 'sunglasses':
    for s in (-1,1):
        ellipsoid('sunglass_lens',(s*.32,-.81,2.04),(.27,.065,.215),'lens','accessory')
        # Closed elliptical metal rims, with temples extending back along the head.
        pts=[(s*.32+.285*math.cos(i*math.pi/6),-.81,2.04+.228*math.sin(i*math.pi/6)) for i in range(13)]
        tube('sunglass_rim',pts,.027,'gold','accessory')
        tube('temple',[(s*.59,-.79,2.08),(s*.73,-.49,2.13),(s*.73,-.13,2.09)],.028,'gold','accessory')
        tube('lens_glint',[(s*.32-.12,-.877,2.12),(s*.32-.035,-.88,2.16)],.014,'shine','accessory')
    tube('bridge',[(-.07,-.82,2.10),(0,-.845,2.13),(.07,-.82,2.10)],.026,'gold','accessory')

for semantic, objects in parts.items():
    if not objects:
        continue
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj=bpy.context.object
    # Stable face order removes Blender construction-order variability.
    old = obj.data
    rows = []
    for face in old.polygons:
        indices = list(face.vertices)
        start = indices.index(min(indices))
        indices = indices[start:] + indices[:start]
        rows.append((indices, face.material_index, face.use_smooth))
    rows.sort(key=lambda row: tuple(row[0]))
    stable = bpy.data.meshes.new(semantic + '_stable')
    stable.from_pydata([tuple(vertex.co) for vertex in old.vertices], [], [row[0] for row in rows])
    for mat in old.materials:
        stable.materials.append(mat)
    for face, (_, material_index, smooth) in zip(stable.polygons, rows):
        face.material_index = material_index
        face.use_smooth = smooth
    stable.update()
    obj.data = stable
    bpy.data.meshes.remove(old)
    obj.name=semantic
    obj['semantic_id']=semantic
    if semantic == 'cat':
        obj.location.x += params.get('cat_shift',0)
bpy.context.scene.unit_settings.system='METRIC'
bpy.context.scene.unit_settings.scale_length=1
bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()))
