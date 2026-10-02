# SPDX-License-Identifier: GPL-3.0-or-later
"""Test-only raw artifact probe, run in a fresh isolated trusted Blender stage.

Intentionally imports no production observer/check/comparison/canonicalizer and
no author module. It consumes a saved .blend or GLB, not observation.json. It
reports raw face/corner values; all expected results live outside the artifact.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy

_STARTUP_HANDLERS = {name: list(getattr(bpy.app.handlers, name))
                     for name in dir(bpy.app.handlers)
                     if isinstance(getattr(bpy.app.handlers, name), list)}


def vector(values):
    result = [float(x) for x in values]
    if not all(math.isfinite(x) for x in result):
        raise ValueError('Nonfinite artifact value')
    return result


def material(mat):
    if mat is None or not mat.use_nodes:
        raise ValueError('Fixture artifact requires explicit Principled materials')
    shaders = [node for node in mat.node_tree.nodes if node.type == 'BSDF_PRINCIPLED']
    if len(shaders) != 1:
        raise ValueError('Unexpected artifact shader')
    shader = shaders[0]
    rgba = vector(shader.inputs['Base Color'].default_value)
    rgba[3] = float(shader.inputs['Alpha'].default_value)
    return {'base_color': rgba, 'metallic': float(shader.inputs['Metallic'].default_value),
            'roughness': float(shader.inputs['Roughness'].default_value)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--format', choices=('blend', 'glb'), required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    if args.format == 'blend':
        bpy.ops.wm.open_mainfile(filepath=str(Path(args.input).resolve()), use_scripts=False, load_ui=False)
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        bpy.ops.import_scene.gltf(filepath=str(Path(args.input).resolve()))
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    for name in dir(bpy.app.handlers):
        handlers = getattr(bpy.app.handlers, name)
        if isinstance(handlers, list):
            handlers.clear()
    parts = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        sid = obj.get('semantic_id')
        if not isinstance(sid, str) or sid in parts:
            raise ValueError('Invalid or repeated semantic part identity')
        if obj.modifiers or obj.animation_data or obj.data.animation_data:
            raise ValueError('Probe only supports the fixture saved static meshes')
        mesh = obj.data
        # Do not evaluate source dependency graphs or execute stored text.
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        points = [vector(obj.matrix_world @ vertex.co) for vertex in mesh.vertices]
        corners = [vector((normal_matrix @ normal.vector).normalized()) for normal in mesh.corner_normals]
        palette = [material(mat) for mat in mesh.materials]
        faces = []
        for polygon in mesh.polygons:
            faces.append({'indices': list(polygon.vertices), 'material_index': int(polygon.material_index),
                          'corner_normals': [corners[loop] for loop in polygon.loop_indices]})
        parts[sid] = {'points': points, 'edges': [list(edge.vertices) for edge in mesh.edges],
                      'faces': faces, 'palette': palette,
                      'matrix_world': [vector(row) for row in obj.matrix_world]}
    if not parts:
        raise ValueError('No artifact mesh parts')
    result = {'probe_schema_version': 1, 'input_format': args.format,
              'blender_version': bpy.app.version_string,
              'autoexec_enabled': bpy.context.preferences.filepaths.use_scripts_auto_execute,
              'scale_length': bpy.context.scene.unit_settings.scale_length, 'parts': parts}
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')


if __name__ == '__main__':
    try:
        main()
    finally:
        for name, handlers in _STARTUP_HANDLERS.items():
            target = getattr(bpy.app.handlers, name)
            target.clear()
            target.extend(handlers)
