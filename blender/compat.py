"""Version-tolerant wrappers around Blender operators that have been renamed.

Blender moved the STL and OBJ exporters to new `wm.*_export` operators in 4.2
and removed the old `export_mesh.stl` in later releases. Users run whatever
Blender their distribution ships, so the runner probes for what exists rather
than pinning to one spelling.
"""

import bpy


def blender_version():
    return tuple(bpy.app.version)


def _has_operator(path):
    module, _, name = path.partition(".")
    return hasattr(getattr(bpy.ops, module, None), name)


def export_stl(filepath, use_selection=True):
    """Export STL in millimetres.

    Geometry is authored at one Blender unit per millimetre, so the export must
    not apply the scene unit scale on top of that: `use_scene_unit=False` with
    `global_scale=1.0` writes the raw coordinates, which slicers then read as
    millimetres.
    """
    if _has_operator("wm.stl_export"):
        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=use_selection,
            apply_modifiers=True,
            global_scale=1.0,
            use_scene_unit=False,
            ascii_format=False,
        )
        return "wm.stl_export"
    if _has_operator("export_mesh.stl"):
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            use_selection=use_selection,
            use_mesh_modifiers=True,
            global_scale=1.0,
            use_scene_unit=False,
            ascii=False,
        )
        return "export_mesh.stl"
    raise RuntimeError("this Blender build exposes no STL export operator")


def import_stl(filepath):
    if _has_operator("wm.stl_import"):
        bpy.ops.wm.stl_import(filepath=filepath, global_scale=1.0, use_scene_unit=False)
        return "wm.stl_import"
    if _has_operator("import_mesh.stl"):
        bpy.ops.import_mesh.stl(filepath=filepath, global_scale=1.0, use_scene_unit=False)
        return "import_mesh.stl"
    raise RuntimeError("this Blender build exposes no STL import operator")


def export_glb(filepath, use_selection=True):
    """Export a binary glTF.

    glTF is defined in metres and its exporter ignores the scene unit scale, so
    the caller is responsible for having scaled the object down by 1/1000
    first. `blender/exporters.py` does that in a temporary, reverted step.
    """
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format="GLB",
        use_selection=use_selection,
        export_apply=True,
        export_yup=True,
    )
    return "export_scene.gltf"


def import_glb(filepath):
    bpy.ops.import_scene.gltf(filepath=filepath)
    return "import_scene.gltf"
