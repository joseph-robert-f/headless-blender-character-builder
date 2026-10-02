# SPDX-License-Identifier: GPL-3.0-or-later
"""Handwritten multipart fixtures; never import into the controller or oracle."""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


def box(width, depth, height):
    vertices = [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0),
                (0, 0, height), (width, 0, height), (width, depth, height), (0, depth, height)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    normals = [(0, 0, -1), (0, 0, 1), (0, -1, 0),
               (1, 0, 0), (0, 1, 0), (-1, 0, 0)]
    return vertices, faces, normals


def author_mesh(name, vertices, faces, normals, matrix, *, serialization,
                palette, alternating=True, oblique_corner=False):
    records = []
    for face_id, (indices, normal) in enumerate(zip(faces, normals)):
        corners = [normal for _ in indices]
        if oblique_corner and face_id == 0:
            corners[indices.index(0)] = (.6, 0, -.8)
        records.append((indices, face_id % 2 if alternating else 0, corners))
    if serialization != 'initial':
        records = records[::-1] if serialization == 'permuted' else records[2:] + records[:2]
        rotated = []
        for index, (indices, material, corners) in enumerate(records):
            offset = (index % (len(indices) - 1)) + 1
            rotated.append((indices[offset:] + indices[:offset], material,
                            corners[offset:] + corners[:offset]))
        records = rotated
    mesh = bpy.data.meshes.new(name + '-mesh')
    mesh.from_pydata(vertices, [], [row[0] for row in records])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj['semantic_id'] = name
    bpy.context.scene.collection.objects.link(obj)
    obj.matrix_world = Matrix(matrix)
    for material in palette:
        mesh.materials.append(material)
    for polygon, (_, material, _) in zip(mesh.polygons, records):
        polygon.material_index = material
        polygon.use_smooth = True
    mesh.normals_split_custom_set([normal for _, _, corners in records for normal in corners])
    mesh.update()
    return obj


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--params', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    values = json.loads(Path(args.params).read_text())
    if set(values) != {'fixture', 'step', 'defect', 'serialization'}:
        raise ValueError('Unexpected fixture parameters')
    if values['fixture'] not in {'box', 'l_prism'} or type(values['step']) is not int or values['step'] not in {0, 1, 2}:
        raise ValueError('Unknown geometry fixture or step')
    allowed = {'none', 'protected_base', 'deformation' if values['fixture'] == 'box' else 'retessellation'}
    if values['defect'] not in allowed or values['serialization'] not in {'initial', 'permuted', 'repair'}:
        raise ValueError('Unknown fixture defect or serialization')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.
    palette = []
    for name, color in [('Cobalt', (.04, .20, .80, 1)), ('Ember', (.85, .12, .04, 1))]:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = color
        shader = material.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Metallic'].default_value = 0
        shader.inputs['Roughness'].default_value = .5
        palette.append(material)
    dx, dy, dz = [value * values['step'] for value in (.015, -.02, .03)]
    if values['fixture'] == 'box':
        vertices, faces, normals = box(.04, .03, .024 if values['defect'] == 'deformation' else .02)
        matrix = [(1, -.45, 0, .11 + dx), (.75, .6, 0, -.07 + dy),
                  (0, 0, 1.5, .09 + dz), (0, 0, 0, 1)]
    else:
        footprint = [(0, 0), (.06, 0), (.06, .02), (.02, .02), (.02, .05), (0, .05)]
        vertices = [(x, y, z) for z in (0, .03) for x, y in footprint]
        faces = [(5, 4, 3, 2, 1, 0), (6, 7, 8, 9, 10, 11)]
        faces += [(i, (i+1) % 6, (i+1) % 6 + 6, i+6) for i in range(6)]
        normals = [(0, 0, -1), (0, 0, 1), (0, -1, 0), (1, 0, 0),
                   (0, 1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0)]
        matrix = [(1, 0, 0, -.09 + dx), (0, 1, 0, .08 + dy),
                  (0, 0, 1, .07 + dz), (0, 0, 0, 1)]
    body = author_mesh('body', vertices, faces, normals, matrix,
                       serialization=values['serialization'], palette=palette,
                       oblique_corner=values['fixture'] == 'box')
    if values['defect'] == 'retessellation':
        # Retessellate only the top cap. Keep original face IDs/materials and
        # loop normals attached to all other surfaces. This is an indexed
        # representation negative, not a change to the L-shaped solid.
        old = body.data
        records = []
        for polygon in old.polygons:
            indices = tuple(polygon.vertices)
            if set(indices) == {6, 7, 8, 9, 10, 11}:
                for triangle in [(6, 7, 9), (7, 8, 9), (6, 9, 11), (9, 10, 11)]:
                    records.append((triangle, polygon.material_index, [(0, 0, 1)] * 3))
            else:
                records.append((indices, polygon.material_index,
                                [tuple(old.corner_normals[loop].vector) for loop in polygon.loop_indices]))
        mesh = bpy.data.meshes.new('retessellated-body-mesh')
        mesh.from_pydata(vertices, [], [row[0] for row in records])
        mesh.update()
        for material in palette:
            mesh.materials.append(material)
        for polygon, (_, material, _) in zip(mesh.polygons, records):
            polygon.material_index = material
            polygon.use_smooth = True
        mesh.normals_split_custom_set([normal for _, _, corners in records for normal in corners])
        mesh.update()
        body.data = mesh
        bpy.data.meshes.remove(old)
    vertices, faces, normals = box(.08, .06, .01)
    base_x = -.035 if values['defect'] == 'protected_base' else -.04
    author_mesh('base', vertices, faces, normals,
                [(1, 0, 0, base_x), (0, 1, 0, -.03), (0, 0, 1, -.01), (0, 0, 0, 1)],
                serialization='initial', palette=palette[:1], alternating=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output)), check_existing=False)


if __name__ == '__main__':
    main()
