"""Scene setup and object helpers.

Every build starts from factory settings with an empty scene so that no user
preference, add-on, or leftover datablock can change the result.
"""

import bpy
from mathutils import Vector

# One Blender unit is one millimetre throughout this project.
UNIT_SCALE = 0.001


def reset(scene_name="hbcb"):
    """Return Blender to a deterministic empty scene in millimetre units."""
    bpy.ops.wm.read_factory_settings(use_empty=True)

    scene = bpy.context.scene
    scene.name = scene_name
    units = scene.unit_settings
    units.system = "METRIC"
    units.scale_length = UNIT_SCALE
    units.length_unit = "MILLIMETERS"

    # A build must not depend on frame state; everything is a single still.
    scene.frame_start = 1
    scene.frame_end = 1
    scene.frame_set(1)
    return scene


def select_only(obj):
    """Make `obj` the sole selected and active object.

    Operators that act on "the selection" are the norm in Blender, so this is
    called before every export and modifier apply.
    """
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def apply_modifier(obj, name):
    select_only(obj)
    bpy.ops.object.modifier_apply(modifier=name)


def evaluated_mesh(obj):
    """A depsgraph-evaluated copy of `obj`'s mesh, with modifiers applied.

    The caller owns the result and must free it with `bpy.data.meshes.remove`.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    return bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
    )


def world_bounds(obj):
    """Axis-aligned world-space bounds as (min_xyz, max_xyz) in millimetres."""
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def dimensions_mm(obj):
    low, high = world_bounds(obj)
    return [high[index] - low[index] for index in range(3)]


def drop_to_floor(obj):
    """Translate `obj` so its lowest point sits exactly on Z=0.

    Slicers place a model on the bed by its bounding box, so shipping an STL
    that already rests on the origin plane avoids a manual "place on bed" step.
    """
    low, _ = world_bounds(obj)
    obj.location.z -= low[2]
    bpy.context.view_layer.update()
    return obj


def center_on_origin_xy(obj):
    """Centre `obj` horizontally so it lands mid-bed and renders symmetrically."""
    low, high = world_bounds(obj)
    obj.location.x -= (low[0] + high[0]) / 2.0
    obj.location.y -= (low[1] + high[1]) / 2.0
    bpy.context.view_layer.update()
    return obj


def set_world_background(color=(0.20, 0.21, 0.23), strength=1.0):
    """A neutral mid-grey world.

    Mid-grey rather than near-black: dark models on a dark background are
    unreadable in the diagnostic views, and the world also supplies the ambient
    fill that keeps unlit sides from crushing to pure black.
    """
    world = bpy.data.worlds.new("hbcb-world")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (color[0], color[1], color[2], 1.0)
        background.inputs[1].default_value = strength
    bpy.context.scene.world = world
    return world
