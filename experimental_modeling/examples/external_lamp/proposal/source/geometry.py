"""Mesh construction for a sculptural desk lamp."""
import math
import bpy
import bmesh
from mathutils import Vector


def material(name, color, metallic=0.0, roughness=0.4):
    value = bpy.data.materials.new(name)
    value.use_nodes = True
    shader = value.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1.0)
    shader.inputs['Metallic'].default_value = metallic
    shader.inputs['Roughness'].default_value = roughness
    value.diffuse_color = (*color, 1.0)
    return value


def finish(obj, semantic_id, surface):
    obj.name = semantic_id
    obj['semantic_id'] = semantic_id
    obj.data.materials.append(surface)
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()
    return obj


def mesh_object(name, vertices, faces):
    mesh = bpy.data.meshes.new(name + '-mesh')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def base(width, depth, surface):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.009))
    obj = bpy.context.object
    obj.dimensions = (width, depth, 0.018)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new('Rounded edges', 'BEVEL')
    bevel.width = 0.006
    bevel.segments = 4
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return finish(obj, 'base', surface)


def stem(height, surface):
    points = [Vector((0, 0.036, 0.014)), Vector((0, 0.062, height*0.69)),
              Vector((0, 0.005, height + 0.005)), Vector((0, -0.030, height-0.008))]
    vertices, faces = [], []
    steps, sides, radius = 40, 16, 0.005
    for i in range(steps + 1):
        t = i / steps
        a = 1 - t
        center = a**3*points[0] + 3*a*a*t*points[1] + 3*a*t*t*points[2] + t**3*points[3]
        tangent = (3*a*a*(points[1]-points[0]) + 6*a*t*(points[2]-points[1]) + 3*t*t*(points[3]-points[2])).normalized()
        u = Vector((1, 0, 0))
        v = tangent.cross(u).normalized()
        for j in range(sides):
            angle = 2*math.pi*j/sides
            vertices.append(tuple(center + radius*(math.cos(angle)*u + math.sin(angle)*v)))
    for i in range(steps):
        for j in range(sides):
            k = (j+1) % sides
            faces.append((i*sides+j, i*sides+k, (i+1)*sides+k, (i+1)*sides+j))
    faces.append(tuple(reversed(range(sides))))
    faces.append(tuple(steps*sides+j for j in range(sides)))
    return finish(mesh_object('stem', vertices, faces), 'stem', surface)


def shade(height, surface):
    # Closed shell around two open apertures, with a curved bell profile.
    profile = [(0.053, height-0.045), (0.046, height-0.035),
               (0.030, height-0.020), (0.014, height-0.006), (0.012, height),
               (0.009, height), (0.011, height-0.006),
               (0.027, height-0.020), (0.043, height-0.035), (0.050, height-0.045)]
    vertices, faces, sides = [], [], 64
    for radius, z in profile:
        for j in range(sides):
            angle = 2*math.pi*j/sides
            vertices.append((radius*math.cos(angle), -0.030+radius*math.sin(angle), z))
    for i in range(len(profile)):
        ni = (i+1) % len(profile)
        for j in range(sides):
            nj = (j+1) % sides
            faces.append((i*sides+j, i*sides+nj, ni*sides+nj, ni*sides+j))
    return finish(mesh_object('shade', vertices, faces), 'shade', surface)


def light(height, surface):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1,
                                       location=(0, -0.030, height-0.031))
    obj = bpy.context.object
    obj.scale = (0.015, 0.015, 0.010)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj = finish(obj, 'light', surface)
    # Preserve oriented connectivity with a deterministic face-list order.
    # Translation checks compare that order, not only the face multiset.
    vertices = [tuple(vertex.co) for vertex in obj.data.vertices]
    faces = []
    for polygon in obj.data.polygons:
        indices = tuple(polygon.vertices)
        start = indices.index(min(indices))
        faces.append(indices[start:] + indices[:start])
    faces.sort()
    previous = obj.data
    ordered = bpy.data.meshes.new('light-ordered-mesh')
    ordered.from_pydata(vertices, [], faces)
    ordered.materials.append(surface)
    ordered.update()
    obj.data = ordered
    bpy.data.meshes.remove(previous)
    return obj
