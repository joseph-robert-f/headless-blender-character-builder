"""Artifact export.

Three formats, three audiences: `.blend` for someone who wants to keep editing,
`.stl` for the slicer, `.glb` for previewing in a browser or engine. All three
come from the same evaluated object so they cannot disagree about the model.
"""

import bpy

from . import compat
from .scene import select_only

# glTF is defined in metres while this project works in millimetres.
GLTF_SCALE = 0.001


def save_blend(path):
    """Write the current scene to `path` without rebinding the live session.

    `copy=True` matters: without it Blender adopts the new path as the session
    file, which changes the meaning of any later relative path.
    """
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=False, copy=True)
    return path


def export_stl(path, obj):
    """Write a binary STL in millimetres, ready to drop into a slicer."""
    select_only(obj)
    compat.export_stl(path, use_selection=True)
    return path


def export_glb(path, obj):
    """Write a binary glTF, temporarily scaled to metres.

    The scale is applied to the object transform and reverted immediately, so
    the scene the `.blend` captures stays in millimetres.
    """
    original = tuple(obj.scale)
    try:
        obj.scale = (GLTF_SCALE, GLTF_SCALE, GLTF_SCALE)
        bpy.context.view_layer.update()
        select_only(obj)
        compat.export_glb(path, use_selection=True)
    finally:
        obj.scale = original
        bpy.context.view_layer.update()
    return path
