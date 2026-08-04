"""Save and export only the v0.1 fixed artifact profiles."""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Iterable

import bpy


def _select_only(objects: Iterable[bpy.types.Object]) -> tuple[bpy.types.Object, ...]:
    selected = tuple(objects)
    if not selected:
        raise RuntimeError("export selection cannot be empty")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in selected:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
    bpy.context.view_layer.objects.active = selected[0]
    return selected


def _require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Blender did not produce required artifact: {path.name}")


def save_model(path: Path) -> None:
    """Save one compressed .blend with only relative internal output paths."""

    scene = bpy.context.scene
    scene.render.filepath = "//preview.png"
    scene.render.filepath = bpy.path.relpath(scene.render.filepath)
    bpy.context.preferences.filepaths.save_version = 0
    result = bpy.ops.wm.save_as_mainfile(
        filepath=str(path),
        check_existing=False,
        compress=True,
        relative_remap=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError("Blender could not save model.blend")
    _require_file(path)


def export_glb(path: Path, display_objects: Iterable[bpy.types.Object]) -> None:
    """Export presentation meshes as a materialized, texture-free binary glTF."""

    selected = _select_only(display_objects)
    if any(obj.type != "MESH" for obj in selected):
        raise RuntimeError("GLB selection must contain only display meshes")
    result = bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_animations=False,
        export_yup=True,
        export_materials="EXPORT",
        export_texcoords=False,
        export_normals=True,
        export_cameras=False,
        export_lights=False,
        export_extras=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError("Blender could not export model.glb")
    _require_file(path)


def export_stl(path: Path, printable: bpy.types.Object) -> None:
    """Export the single printable shell with raw numeric coordinates in mm."""

    if printable.type != "MESH" or printable.name != "PrintableShell":
        raise RuntimeError("STL export requires PrintableShell")
    _select_only((printable,))
    result = bpy.ops.wm.stl_export(
        filepath=str(path),
        export_selected_objects=True,
        apply_modifiers=True,
        ascii_format=False,
        global_scale=1000.0,
        use_scene_unit=False,
        forward_axis="Y",
        up_axis="Z",
    )
    if "FINISHED" not in result:
        raise RuntimeError("Blender could not export model.stl")
    _require_file(path)


def inspect_binary_stl(path: Path) -> dict[str, object]:
    """Independently inspect binary STL numeric bounds and framing."""

    size = path.stat().st_size
    if size < 84:
        raise RuntimeError("STL is shorter than a binary header")
    with path.open("rb") as stream:
        header = stream.read(80)
        count_bytes = stream.read(4)
        if len(count_bytes) != 4:
            raise RuntimeError("STL triangle count is truncated")
        triangle_count = struct.unpack("<I", count_bytes)[0]
        expected_size = 84 + triangle_count * 50
        if size != expected_size or triangle_count < 4:
            raise RuntimeError("STL framing or triangle count is invalid")
        minimum = [math.inf, math.inf, math.inf]
        maximum = [-math.inf, -math.inf, -math.inf]
        for _index in range(triangle_count):
            record = stream.read(50)
            if len(record) != 50:
                raise RuntimeError("STL triangle record is truncated")
            values = struct.unpack("<12fH", record)
            for vertex_offset in (3, 6, 9):
                for axis in range(3):
                    coordinate = float(values[vertex_offset + axis])
                    if not math.isfinite(coordinate):
                        raise RuntimeError("STL contains non-finite coordinates")
                    minimum[axis] = min(minimum[axis], coordinate)
                    maximum[axis] = max(maximum[axis], coordinate)
    dimensions = [maximum[index] - minimum[index] for index in range(3)]
    if min(dimensions) <= 0:
        raise RuntimeError("STL has flat or empty numeric bounds")
    return {
        "binary": True,
        "header_hex": header.hex(),
        "triangle_count": triangle_count,
        "minimum_mm": minimum,
        "maximum_mm": maximum,
        "dimensions_mm": dimensions,
    }
