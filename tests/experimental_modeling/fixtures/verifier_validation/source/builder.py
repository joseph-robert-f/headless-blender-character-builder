# SPDX-License-Identifier: GPL-3.0-or-later
"""Handwritten tetrahedron author fixture. Never import this in the controller."""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--params', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    values = json.loads(Path(args.params).read_text())
    if set(values) != {'height_m', 'defect', 'serialization'}:
        raise ValueError('Unexpected fixture parameters')
    if values['defect'] not in {'none', 'material', 'normal'}:
        raise ValueError('Unknown fixture defect')
    if values['serialization'] not in {'initial', 'permuted', 'repair'}:
        raise ValueError('Unknown fixture serialization')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    # O, X, Y, Z. The oracle independently spells out the expected named faces.
    vertices = [(0, 0, 0), (.04, 0, 0), (0, .03, 0), (0, 0, .02)]
    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    materials = [0, 1, 0, 1]
    slant = math.sqrt(61)
    normals = [(0, 0, -1), (0, -1, 0), (-1, 0, 0), (3/slant, 4/slant, 6/slant)]
    order = {'initial': [0, 1, 2, 3], 'permuted': [3, 2, 0, 1], 'repair': [1, 0, 3, 2]}[values['serialization']]
    rotations = {'initial': [0, 0, 0, 0], 'permuted': [1, 2, 1, 2], 'repair': [2, 1, 2, 1]}[values['serialization']]
    records = []
    for face_id, offset in zip(order, rotations):
        indices = faces[face_id]
        indices = indices[offset:] + indices[:offset]
        material = (1 - materials[face_id]) if values['defect'] == 'material' and face_id in (0, 1) else materials[face_id]
        corner_normals = [normals[face_id] for _ in indices]
        if values['defect'] == 'normal' and face_id == 0:
            corner_normals[indices.index(0)] = (math.sin(.12), 0, -math.cos(.12))
        records.append((indices, material, corner_normals))
    mesh = bpy.data.meshes.new('handwritten-tetra-mesh')
    mesh.from_pydata(vertices, [], [item[0] for item in records])
    mesh.update()
    obj = bpy.data.objects.new('tetra', mesh)
    obj['semantic_id'] = 'tetra'
    scene.collection.objects.link(obj)
    obj.location.z = float(values['height_m'])
    for name, color in [('Cobalt', (.04, .20, .80, 1)), ('Ember', (.85, .12, .04, 1))]:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        mat.diffuse_color = color
        shader = mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Metallic'].default_value = 0
        shader.inputs['Roughness'].default_value = .5
        mesh.materials.append(mat)
    for polygon, (_, material, _) in zip(mesh.polygons, records):
        polygon.material_index = material
        polygon.use_smooth = True
    mesh.normals_split_custom_set([normal for _, _, corners in records for normal in corners])
    mesh.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output)), check_existing=False)


if __name__ == '__main__':
    main()
