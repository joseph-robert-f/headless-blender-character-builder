"""Trusted, process-isolated Blender observer for the experimental modeling lane.

Run with --background --factory-startup --disable-autoexec --python this.py --
--input source.blend --output DIR. Never execute this file via source .blend text.
This is an observer, not a sandbox: callers must bound process resources and IO.
"""
import argparse
import collections
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

# Retain only startup handlers for clean Blender shutdown after inspection.
_STARTUP_HANDLERS = {name: list(getattr(bpy.app.handlers, name))
                     for name in dir(bpy.app.handlers)
                     if isinstance(getattr(bpy.app.handlers, name), list)}

SCHEMA_VERSION = 1
TOLERANCE = 1e-4
NORMAL_ANGLE_TOLERANCE = 0.01  # radians; Blender imports split normals with quantization


def finite(value):
    if isinstance(value, (list, tuple)):
        return [finite(x) for x in value]
    x = float(value)
    if not math.isfinite(x):
        raise ValueError('Non-finite geometry/material value')
    return x


def digest(value):
    def normalized(v):
        if isinstance(v, float):
            return round(v, 6) + 0.0
        if isinstance(v, dict):
            return {k: normalized(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [normalized(x) for x in v]
        return v
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def clear_active_content():
    # --disable-autoexec and use_scripts=False are mandatory, independently of
    # scene preferences. Drivers are removed before requesting dependency graph.
    for name in dir(bpy.app.handlers):
        handlers = getattr(bpy.app.handlers, name)
        if isinstance(handlers, list):
            handlers.clear()
    for collection in (bpy.data.objects, bpy.data.scenes, bpy.data.meshes,
                       bpy.data.curves, bpy.data.materials, bpy.data.worlds,
                       bpy.data.node_groups, bpy.data.shape_keys):
        for block in collection:
            if hasattr(block, 'animation_data_clear'):
                block.animation_data_clear()
            tree = getattr(block, 'node_tree', None)
            if tree:
                tree.animation_data_clear()
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False


def material_value(mat):
    if mat is None:
        return {'base_color': [0.8, 0.8, 0.8, 1.0], 'metallic': 0.0, 'roughness': 0.5}
    color, metallic, roughness = list(mat.diffuse_color), mat.metallic, mat.roughness
    if mat.use_nodes:
        nodes = [n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']
        outputs = [n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
        if len(nodes) != 1 or len(outputs) != 1:
            raise ValueError('Only a single Principled material is supported: ' + mat.name)
        node = nodes[0]
        surface = outputs[0].inputs['Surface']
        if not surface.is_linked or surface.links[0].from_node != node:
            raise ValueError('Material output must use the Principled shader directly')
        if any(s.is_linked for s in node.inputs):
            raise ValueError('The experimental contract does not include linked or procedural material inputs.')
        # Compare every other value against Blender's own default shader so
        # e.g. altered IOR, anisotropy or thin-film inputs cannot disappear.
        default_mat = bpy.data.materials.new('__trusted_defaults__')
        default_mat.use_nodes = True
        defaults = default_mat.node_tree.nodes.get('Principled BSDF')
        allowed = {'Base Color', 'Metallic', 'Roughness', 'Alpha'}
        try:
            for socket in node.inputs:
                if socket.name in allowed or not hasattr(socket, 'default_value'):
                    continue
                other = defaults.inputs.get(socket.name)
                if other is None or not hasattr(other, 'default_value'):
                    continue
                actual, baseline = socket.default_value, other.default_value
                if hasattr(actual, '__len__') and not isinstance(actual, str):
                    differs = any(abs(a - b) > 1e-6 for a, b in zip(actual, baseline))
                elif isinstance(actual, (float, int)):
                    differs = abs(actual - baseline) > 1e-6
                else:
                    differs = actual != baseline
                if differs:
                    raise ValueError('Unsupported non-default material input: ' + socket.name)
        finally:
            bpy.data.materials.remove(default_mat)
        color = list(node.inputs['Base Color'].default_value)
        color[3] = node.inputs['Alpha'].default_value
        metallic = node.inputs['Metallic'].default_value
        roughness = node.inputs['Roughness'].default_value
        # Additional shading features would be silently lost in the canonical
        # material, so explicitly reject non-default effects used by source.
        for name in ('Transmission Weight', 'Coat Weight', 'Sheen Weight', 'Subsurface Weight'):
            if name in node.inputs and abs(node.inputs[name].default_value) > 1e-6:
                raise ValueError('Unsupported material feature: ' + name)
        if 'Emission Color' in node.inputs and 'Emission Strength' in node.inputs:
            if node.inputs['Emission Strength'].default_value and any(node.inputs['Emission Color'].default_value[:3]):
                raise ValueError('The experimental contract does not include emission materials.')
    return {'base_color': finite(color), 'metallic': finite(metallic), 'roughness': finite(roughness)}


def make_material(value, name):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = value['base_color']
    mat.metallic = value['metallic']
    mat.roughness = value['roughness']
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = value['base_color']
    shader.inputs['Alpha'].default_value = value['base_color'][3]
    shader.inputs['Metallic'].default_value = value['metallic']
    shader.inputs['Roughness'].default_value = value['roughness']
    return mat


def snapshot_source(expected_ids):
    clear_active_content()
    if abs(bpy.context.scene.unit_settings.scale_length - 1.0) > 1e-9:
        raise ValueError('Experimental contract requires scale_length=1. Coordinates are meters')
    source_objects = [o for o in bpy.context.scene.objects if o.type in {'MESH', 'CURVE', 'SURFACE', 'FONT'}]
    if not source_objects:
        raise ValueError('Scene has no semantic geometry')
    ids = []
    for obj in source_objects:
        sid = obj.get('semantic_id')
        if not isinstance(sid, str) or not sid.strip() or len(sid) > 128:
            raise ValueError('Every geometry object requires a nonempty semantic_id: ' + obj.name)
        if sid in ids:
            raise ValueError('Duplicate semantic_id: ' + sid)
        ids.append(sid)
    if expected_ids and set(ids) != set(expected_ids):
        raise ValueError('Semantic IDs differ: observed=%s expected=%s' % (sorted(ids), sorted(expected_ids)))
    unsupported = [o.name for o in bpy.context.scene.objects if o.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'EMPTY', 'LIGHT', 'CAMERA'}]
    if unsupported:
        raise ValueError('Unsupported geometry object types: ' + ', '.join(unsupported))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if any(instance.is_instance for instance in depsgraph.object_instances):
        raise ValueError('Instances must be realized into individually labeled mesh parts')
    copies = []
    for obj, sid in zip(source_objects, ids):
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        if not mesh.vertices or not mesh.polygons:
            raise ValueError('Part has empty geometry: ' + sid)
        values = [material_value(m) for m in mesh.materials] or [material_value(None)]
        mesh.materials.clear()
        for i, value in enumerate(values):
            mesh.materials.append(make_material(value, sid + '_material_' + str(i)))
        copy = bpy.data.objects.new(sid, mesh)
        copy['semantic_id'] = sid
        copy.matrix_world = evaluated.matrix_world.copy()
        copies.append(copy)
    scene = bpy.data.scenes.new('Trusted inspection')
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = 'METERS'
    for obj in copies:
        scene.collection.objects.link(obj)
    bpy.context.window.scene = scene
    # Keep only trusted, evaluated mesh objects and their simple PBR materials.
    for obj in list(bpy.data.objects):
        if obj not in copies:
            bpy.data.objects.remove(obj, do_unlink=True)
    for other in list(bpy.data.scenes):
        if other != scene:
            bpy.data.scenes.remove(other)
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    return scene


def observe():
    parts = {}
    for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        if obj.type != 'MESH':
            continue
        sid = obj.get('semantic_id')
        if not isinstance(sid, str) or not sid or sid in parts:
            raise ValueError('Missing or duplicate semantic_id in inspected mesh: ' + obj.name)
        mesh = obj.data
        mesh.calc_loop_triangles()
        local = [finite(v.co[:]) for v in mesh.vertices]
        world = [finite((obj.matrix_world @ v.co)[:]) for v in mesh.vertices]
        edges = [list(e.vertices) for e in mesh.edges]
        faces = [list(p.vertices) for p in mesh.polygons]
        normals = [finite(v.normal[:]) for v in mesh.vertices]
        corner_normals = [finite(n.vector[:]) for n in mesh.corner_normals]
        normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
        triangle_normals = [[finite((normal_matrix @ Vector(corner_normals[i])).normalized()[:])
                             for i in t.loops] for t in mesh.loop_triangles]
        materials = [material_value(m) for m in mesh.materials] or [material_value(None)]
        usage = collections.Counter()
        for face in faces:
            for a, b in zip(face, face[1:] + face[:1]):
                usage[tuple(sorted((a, b)))] += 1
        bounds = {'min': [min(v[i] for v in world) for i in range(3)],
                  'max': [max(v[i] for v in world) for i in range(3)]}
        triangles = [list(t.vertices) for t in mesh.loop_triangles]
        tri_mats = [int(t.material_index) for t in mesh.loop_triangles]
        if any(i >= len(materials) for i in tri_mats):
            raise ValueError('Invalid material index in ' + sid)
        transform = [finite(row[:]) for row in obj.matrix_world]
        area = 0.0
        volume = 0.0
        for triangle in triangles:
            a, b, c = (Vector(world[i]) for i in triangle)
            area += (b - a).cross(c - a).length / 2
            volume += a.dot(b.cross(c)) / 6
        parts[sid] = {
            'geometry_hash': digest({'vertices': local, 'edges': edges, 'faces': faces,
                                     'normals': normals, 'corner_normals': corner_normals, 'face_materials': [p.material_index for p in mesh.polygons]}),
            'transform_hash': digest(transform), 'material_hash': digest(materials),
            'world_bounds': bounds, 'vertices': len(local), 'edges': len(edges), 'faces': len(faces),
            'vertex_count': len(local), 'edge_count': len(edges), 'face_count': len(faces),
            'surface_area': finite(area), 'signed_volume': finite(volume),
            'triangle_count': len(triangles), 'nonmanifold_edges': sum(usage[tuple(sorted(e))] != 2 for e in edges),
            'boundary_edges': sum(usage[tuple(sorted(e))] == 1 for e in edges),
            'local_vertices': local, 'world_vertices': world, 'edge_indices': edges,
            'face_indices': faces, 'triangle_indices': triangles, 'triangle_material_indices': tri_mats,
            'normals': normals, 'corner_normals': corner_normals, 'triangle_world_normals': triangle_normals, 'matrix_world': transform, 'materials': materials,
        }
    if not parts:
        raise ValueError('No mesh parts observed')
    return {'schema_version': SCHEMA_VERSION, 'trusted_observation': True,
            'units': {'length': 'meter', 'scale_length': 1.0, 'area': 'square_meter', 'volume': 'cubic_meter'},
            'visibility_policy': 'All semantic geometry is included; source visibility flags are ignored',
            'material_contract': 'Constant base_color, alpha, metallic, roughness; default other Principled inputs',
            'runtime': {'blender_version': bpy.app.version_string, 'python_version': sys.version.split()[0],
                        'autoexec_enabled': bpy.context.preferences.filepaths.use_scripts_auto_execute},
            'parts': parts}


def triangles_for_compare(part):
    out = []
    for indices, mi, normals in zip(part['triangle_indices'], part['triangle_material_indices'], part['triangle_world_normals']):
        points = [part['world_vertices'][i] + normal for i, normal in zip(indices, normals)]
        # A GLB exporter can rotate triangle start indices, but must retain winding.
        rotations = [points[i:] + points[:i] for i in range(3)]
        points = min(rotations, key=lambda p: tuple(round(x, 4) for v in p for x in v[:3]))
        mat = part['materials'][mi]
        out.append([x for v in points for x in v] + mat['base_color'] + [mat['metallic'], mat['roughness']])
    return sorted(out, key=lambda row: tuple(round(row[i], 4) for i in (0, 1, 2, 6, 7, 8, 12, 13, 14)) + tuple(round(x, 4) for x in row[18:]))


def close_nested(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close_nested(x, y) for x, y in zip(a, b))
    return math.isclose(a, b, abs_tol=TOLERANCE, rel_tol=1e-5)


def compare(reference, observed):
    failures = []
    normal_errors = {}
    if reference.get('units') != observed.get('units'):
        failures.append('units')
    if set(reference['parts']) != set(observed['parts']):
        failures.append('semantic_ids')
    for sid in sorted(set(reference['parts']) & set(observed['parts'])):
        old, new = reference['parts'][sid], observed['parts'][sid]
        if not close_nested(old['matrix_world'], new['matrix_world']):
            failures.append(sid + ':transform')
        before, after = triangles_for_compare(old), triangles_for_compare(new)
        geometry_ok = len(before) == len(after)
        max_angle = 0.0
        for a, b in zip(before, after):
            indices = (0, 1, 2, 6, 7, 8, 12, 13, 14) + tuple(range(18, len(a)))
            geometry_ok = geometry_ok and close_nested([a[i] for i in indices], [b[i] for i in indices])
            for start in (3, 9, 15):
                na, nb = Vector(a[start:start + 3]), Vector(b[start:start + 3])
                if na.length > 0 and nb.length > 0:
                    max_angle = max(max_angle, na.angle(nb))
                elif na.length != nb.length:
                    max_angle = math.pi
        normal_errors[sid] = max_angle
        if not geometry_ok:
            failures.append(sid + ':world_geometry_or_material')
        if max_angle > NORMAL_ANGLE_TOLERANCE:
            failures.append(sid + ':corner_normals')
    return {'schema_version': SCHEMA_VERSION, 'passed': not failures,
            'tolerance': TOLERANCE, 'normal_angle_tolerance_radians': NORMAL_ANGLE_TOLERANCE,
            'max_normal_angle_error_radians': normal_errors, 'failures': failures, 'parts': sorted(observed['parts'])}


def render_views(scene, directory, observation):
    all_points = [Vector(v) for p in observation['parts'].values() for v in p['world_vertices']]
    lo = Vector([min(v[i] for v in all_points) for i in range(3)])
    hi = Vector([max(v[i] for v in all_points) for i in range(3)])
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.01)
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.film_transparent = False
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.studiolight_rotate_z = 0.0
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.background_type = 'WORLD'
    scene.world = bpy.data.worlds.new('Trusted neutral world')
    scene.world.color = (0.12, 0.12, 0.12)
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.view_settings.view_transform = 'Standard'
    camera_data = bpy.data.cameras.new('Trusted orthographic camera')
    camera = bpy.data.objects.new('Trusted orthographic camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = radius * 2.4
    camera_data.clip_start = max(radius * 0.001, 0.0001)
    camera_data.clip_end = radius * 20 + 100
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, direction in [('front', (0, -1, 0)), ('right', (1, 0, 0)), ('top', (0, 0, 1)), ('iso', (1, -1, 1))]:
        camera.location = center + Vector(direction).normalized() * (radius * 5 + 1)
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(directory / (name + '.png'))
        bpy.ops.render.render(write_still=True)
        paths[name] = 'views/' + name + '.png'
    bpy.data.objects.remove(camera, do_unlink=True)
    return paths


def export_stl(path, observation):
    # A deliberately plain ASCII STL export of evaluated world-space triangles.
    with path.open('w') as out:
        out.write('solid trusted_model\n')
        for part in observation['parts'].values():
            for tri in part['triangle_indices']:
                a, b, c = [Vector(part['world_vertices'][i]) for i in tri]
                normal = (b - a).cross(c - a).normalized()
                out.write(' facet normal %.9g %.9g %.9g\n  outer loop\n' % tuple(normal))
                for v in (a, b, c):
                    out.write('   vertex %.9g %.9g %.9g\n' % tuple(v))
                out.write('  endloop\n endfacet\n')
        out.write('endsolid trusted_model\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=('source', 'reopen', 'roundtrip'), default='source')
    parser.add_argument('--reference')
    parser.add_argument('--expected-ids')
    parser.add_argument('--skip-renders', action='store_true')
    parser.add_argument('--print-profile', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        if args.mode == 'roundtrip':
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.context.preferences.filepaths.use_scripts_auto_execute = False
            bpy.ops.import_scene.gltf(filepath=str(Path(args.input).resolve()))
            clear_active_content()
            observation = observe()
            write_json(output / 'observation.json', observation)
            if not args.reference:
                raise ValueError('--reference required for roundtrip')
            result = compare(json.loads(Path(args.reference).read_text()), observation)
            write_json(output / 'roundtrip.json', result)
            if not result['passed']:
                raise ValueError('Roundtrip mismatch: ' + ', '.join(result['failures']))
            return
        bpy.ops.wm.open_mainfile(filepath=str(Path(args.input).resolve()), use_scripts=False, load_ui=False)
        scene = snapshot_source(args.expected_ids.split(',') if args.expected_ids else None)
        observation = observe()
        observation['artifacts'] = {'blend': 'scene.blend', 'glb': 'model.glb', 'views': {}}
        if not args.skip_renders:
            observation['artifacts']['views'] = render_views(scene, output / 'views', observation)
        bpy.ops.wm.save_as_mainfile(filepath=str(output / 'scene.blend'), check_existing=False)
        bpy.ops.export_scene.gltf(filepath=str(output / 'model.glb'), export_format='GLB',
                                  export_extras=True, export_cameras=False, export_lights=False,
                                  export_animations=False, export_yup=True)
        if args.print_profile:
            export_stl(output / 'model.stl', observation)
            observation['artifacts']['stl'] = 'model.stl'
        if args.reference:
            result = compare(json.loads(Path(args.reference).read_text()), observation)
            write_json(output / 'reopen.json', result)
            if not result['passed']:
                raise ValueError('Reopened scene mismatch')
        write_json(output / 'observation.json', observation)
    except Exception as exc:
        write_json(output / 'error.json', {'error': type(exc).__name__, 'message': str(exc)})
        raise


if __name__ == '__main__':
    try:
        main()
    finally:
        for name, handlers in _STARTUP_HANDLERS.items():
            target = getattr(bpy.app.handlers, name)
            target.clear()
            target.extend(handlers)
