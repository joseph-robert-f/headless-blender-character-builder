"""Factory scene setup and printable-shell construction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

import bmesh
import bpy

from .primitives import MM_PER_METER, mesh_bounds_mm, mm_to_m


COLLECTION_NAMES = ("CHARACTER", "PRINT", "SET", "LIGHTS", "CAMERAS")


@dataclass(frozen=True)
class SceneContext:
    scene: bpy.types.Scene
    collections: Mapping[str, bpy.types.Collection]


def factory_scene() -> SceneContext:
    """Replace user startup state with a bounded, empty builder scene."""

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.name = "BuilderScene"
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.frame_start = 1
    scene.frame_end = 1
    scene.frame_set(1)
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    world = bpy.data.worlds.new("BuilderWorld")
    world.color = (0.035, 0.035, 0.035)
    scene.world = world

    collections = {}
    for name in COLLECTION_NAMES:
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        collections[name] = collection
    return SceneContext(scene=scene, collections=collections)


def _activate_only(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _evaluated_duplicate(
    source: bpy.types.Object,
    collection: bpy.types.Collection,
    depsgraph: bpy.types.Depsgraph,
) -> bpy.types.Object:
    evaluated = source.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=False,
        depsgraph=depsgraph,
    )
    duplicate = bpy.data.objects.new(f"PRINTSRC_{source.name}", mesh)
    duplicate.matrix_world = source.matrix_world.copy()
    collection.objects.link(duplicate)
    return duplicate


def _join_objects(objects: tuple[bpy.types.Object, ...]) -> bpy.types.Object:
    if not objects:
        raise RuntimeError("print shell requires at least one display solid")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    active = objects[0]
    bpy.context.view_layer.objects.active = active
    bpy.ops.object.join()
    active.name = "PrintableShell"
    active.data.name = "MESH_PrintableShell"
    _activate_only(active)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return active


def _recalculate_outward_normals(obj: bpy.types.Object) -> None:
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update(calc_edges=True)


def _ground_printable(obj: bpy.types.Object, target_height_mm: float) -> None:
    """Place the remesh on Z=0 without changing requested base dimensions."""

    minimum, maximum = mesh_bounds_mm((obj,))
    height = maximum.z - minimum.z
    if not math.isfinite(height) or height <= 0:
        raise RuntimeError("voxel remesh produced invalid printable bounds")
    obj.location.z -= minimum.z / MM_PER_METER
    bpy.context.view_layer.update()
    _activate_only(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    minimum, maximum = mesh_bounds_mm((obj,))
    actual_height = maximum.z - minimum.z
    tolerance_mm = max(0.2, float(target_height_mm) * 0.005)
    if abs(actual_height - float(target_height_mm)) > tolerance_mm:
        raise RuntimeError(
            "printable height drift exceeds tolerance: "
            f"target={target_height_mm:.4f} mm actual={actual_height:.4f} mm"
        )


def derive_printable_shell(
    *,
    display_objects: Iterable[bpy.types.Object],
    print_collection: bpy.types.Collection,
    material: bpy.types.Material,
    target_height_mm: float,
    voxel_size_mm: float,
) -> bpy.types.Object:
    """Voxel-union reviewed display solids into exactly one print object."""

    sources = tuple(
        obj
        for obj in display_objects
        if obj.type == "MESH" and bool(obj.get("print_source", False))
    )
    if not sources:
        raise RuntimeError("no reviewed print-source solids were generated")
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    duplicates = tuple(
        _evaluated_duplicate(source, print_collection, depsgraph) for source in sources
    )
    printable = _join_objects(duplicates)
    printable.data.materials.clear()
    printable.data.materials.append(material)
    printable["builder_role"] = "printable"
    printable["print_source_count"] = len(sources)
    printable["voxel_size_mm"] = float(voxel_size_mm)
    printable["target_height_mm"] = float(target_height_mm)

    printable.data.remesh_voxel_size = mm_to_m(voxel_size_mm)
    printable.data.remesh_voxel_adaptivity = 0.0
    if hasattr(printable.data, "use_remesh_fix_poles"):
        printable.data.use_remesh_fix_poles = True
    if hasattr(printable.data, "use_remesh_preserve_volume"):
        printable.data.use_remesh_preserve_volume = True
    if hasattr(printable.data, "use_remesh_preserve_attributes"):
        printable.data.use_remesh_preserve_attributes = False
    _activate_only(printable)
    bpy.ops.object.voxel_remesh()
    if not printable.data.polygons:
        raise RuntimeError("voxel remesh produced an empty printable shell")
    _recalculate_outward_normals(printable)
    _ground_printable(printable, target_height_mm)
    printable.hide_render = True
    printable.display_type = "WIRE"
    printable.show_name = True
    return printable


__all__ = [
    "COLLECTION_NAMES",
    "SceneContext",
    "derive_printable_shell",
    "factory_scene",
]
