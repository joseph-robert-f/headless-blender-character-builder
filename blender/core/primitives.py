"""Small deterministic mesh primitives expressed in millimeters."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import bpy
from mathutils import Vector


MM_PER_METER = 1000.0


def mm_to_m(value_mm: float) -> float:
    return float(value_mm) / MM_PER_METER


def point_mm(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("a point must have exactly three coordinates")
    return tuple(mm_to_m(value) for value in values)  # type: ignore[return-value]


def _activate_only(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _finish_object(
    obj: bpy.types.Object,
    *,
    name: str,
    collection: bpy.types.Collection,
    material: bpy.types.Material | None,
    print_source: bool,
    minimum_feature_mm: float,
) -> bpy.types.Object:
    if name in bpy.data.objects and bpy.data.objects[name] is not obj:
        raise ValueError(f"duplicate deterministic object name: {name}")
    obj.name = name
    if obj.data is not None:
        obj.data.name = f"MESH_{name}"
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for linked in tuple(obj.users_collection):
        if linked != collection:
            linked.objects.unlink(obj)
    if material is not None:
        obj.data.materials.clear()
        obj.data.materials.append(material)
    obj["builder_role"] = "display"
    obj["print_source"] = bool(print_source)
    obj["designed_minimum_feature_mm"] = float(minimum_feature_mm)
    return obj


def _apply_scale(obj: bpy.types.Object) -> None:
    _activate_only(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def ellipsoid(
    *,
    name: str,
    collection: bpy.types.Collection,
    center_mm: Sequence[float],
    dimensions_mm: Sequence[float],
    material: bpy.types.Material | None,
    segments: int = 24,
    rings: int = 16,
    print_source: bool = True,
    minimum_feature_mm: float = 2.0,
) -> bpy.types.Object:
    dimensions = tuple(float(value) for value in dimensions_mm)
    if len(dimensions) != 3 or min(dimensions) <= 0:
        raise ValueError("ellipsoid dimensions must be three positive values")
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=max(12, min(int(segments), 48)),
        ring_count=max(8, min(int(rings), 32)),
        radius=0.5,
        location=point_mm(center_mm),
    )
    obj = bpy.context.object
    bpy.context.view_layer.update()
    current = obj.dimensions.copy()
    desired = Vector(tuple(mm_to_m(value) for value in dimensions))
    obj.scale = tuple(desired[index] / current[index] for index in range(3))
    _apply_scale(obj)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=minimum_feature_mm,
    )


def ico_ellipsoid(
    *,
    name: str,
    collection: bpy.types.Collection,
    center_mm: Sequence[float],
    dimensions_mm: Sequence[float],
    material: bpy.types.Material | None,
    subdivisions: int = 2,
    print_source: bool = True,
    minimum_feature_mm: float = 2.0,
) -> bpy.types.Object:
    dimensions = tuple(float(value) for value in dimensions_mm)
    if len(dimensions) != 3 or min(dimensions) <= 0:
        raise ValueError("ico ellipsoid dimensions must be three positive values")
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=max(1, min(int(subdivisions), 3)),
        radius=0.5,
        location=point_mm(center_mm),
    )
    obj = bpy.context.object
    bpy.context.view_layer.update()
    current = obj.dimensions.copy()
    desired = Vector(tuple(mm_to_m(value) for value in dimensions))
    obj.scale = tuple(desired[index] / current[index] for index in range(3))
    _apply_scale(obj)
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=minimum_feature_mm,
    )


def rounded_box(
    *,
    name: str,
    collection: bpy.types.Collection,
    center_mm: Sequence[float],
    dimensions_mm: Sequence[float],
    bevel_mm: float,
    material: bpy.types.Material | None,
    rotation_euler: Sequence[float] = (0.0, 0.0, 0.0),
    print_source: bool = True,
    minimum_feature_mm: float = 2.0,
) -> bpy.types.Object:
    dimensions = tuple(float(value) for value in dimensions_mm)
    if len(dimensions) != 3 or min(dimensions) <= 0:
        raise ValueError("box dimensions must be three positive values")
    maximum_bevel = min(dimensions) * 0.49
    bevel_mm = max(0.0, min(float(bevel_mm), maximum_bevel))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=point_mm(center_mm))
    obj = bpy.context.object
    obj.scale = tuple(mm_to_m(value) for value in dimensions)
    obj.rotation_euler = tuple(float(value) for value in rotation_euler)
    _apply_scale(obj)
    if bevel_mm > 0:
        modifier = obj.modifiers.new(name="BuilderBevel", type="BEVEL")
        modifier.width = mm_to_m(bevel_mm)
        modifier.segments = 2
        modifier.limit_method = "ANGLE"
        _activate_only(obj)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=minimum_feature_mm,
    )


def cylinder(
    *,
    name: str,
    collection: bpy.types.Collection,
    center_mm: Sequence[float],
    radius_mm: float,
    depth_mm: float,
    material: bpy.types.Material | None,
    vertices: int = 24,
    rotation_euler: Sequence[float] = (0.0, 0.0, 0.0),
    print_source: bool = True,
    minimum_feature_mm: float | None = None,
) -> bpy.types.Object:
    if radius_mm <= 0 or depth_mm <= 0:
        raise ValueError("cylinder radius and depth must be positive")
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=max(6, min(int(vertices), 64)),
        radius=mm_to_m(radius_mm),
        depth=mm_to_m(depth_mm),
        end_fill_type="NGON",
        location=point_mm(center_mm),
        rotation=tuple(float(value) for value in rotation_euler),
    )
    obj = bpy.context.object
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=(
            float(minimum_feature_mm)
            if minimum_feature_mm is not None
            else min(radius_mm * 2.0, depth_mm)
        ),
    )


def cylinder_dimensions(
    *,
    name: str,
    collection: bpy.types.Collection,
    center_mm: Sequence[float],
    dimensions_mm: Sequence[float],
    material: bpy.types.Material | None,
    vertices: int = 32,
    rotation_z: float = 0.0,
    print_source: bool = True,
    minimum_feature_mm: float = 2.0,
) -> bpy.types.Object:
    """Create a cylinder scaled to exact requested X/Y/Z bounds."""

    dimensions = tuple(float(value) for value in dimensions_mm)
    if len(dimensions) != 3 or min(dimensions) <= 0:
        raise ValueError("cylinder dimensions must be three positive values")
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=max(6, min(int(vertices), 64)),
        radius=0.5,
        depth=1.0,
        end_fill_type="NGON",
        location=point_mm(center_mm),
        rotation=(0.0, 0.0, float(rotation_z)),
    )
    obj = bpy.context.object
    # Bake polygon orientation first so X/Y dimension fitting operates in
    # world-aligned axes and a non-square hex base keeps exact bounds.
    _activate_only(obj)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    bpy.context.view_layer.update()
    current = obj.dimensions.copy()
    desired = Vector(tuple(mm_to_m(value) for value in dimensions))
    obj.scale = tuple(desired[index] / current[index] for index in range(3))
    _apply_scale(obj)
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=minimum_feature_mm,
    )


def cylinder_between(
    *,
    name: str,
    collection: bpy.types.Collection,
    start_mm: Sequence[float],
    end_mm: Sequence[float],
    radius_mm: float,
    material: bpy.types.Material | None,
    vertices: int = 20,
    overlap_mm: float = 0.0,
    print_source: bool = True,
    minimum_feature_mm: float | None = None,
) -> bpy.types.Object:
    start = Vector(tuple(float(value) for value in start_mm))
    end = Vector(tuple(float(value) for value in end_mm))
    delta = end - start
    length_mm = delta.length
    if length_mm <= 0:
        raise ValueError("cylinder endpoints must be distinct")
    direction = delta.normalized()
    half_overlap = max(0.0, float(overlap_mm)) * 0.5
    expanded_start = start - direction * half_overlap
    expanded_end = end + direction * half_overlap
    midpoint = (expanded_start + expanded_end) * 0.5
    depth_mm = (expanded_end - expanded_start).length
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=max(6, min(int(vertices), 64)),
        radius=mm_to_m(radius_mm),
        depth=mm_to_m(depth_mm),
        end_fill_type="NGON",
        location=point_mm(midpoint),
    )
    obj = bpy.context.object
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(direction)
    _apply_scale(obj)
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=(
            float(minimum_feature_mm)
            if minimum_feature_mm is not None
            else radius_mm * 2.0
        ),
    )


def cone_between(
    *,
    name: str,
    collection: bpy.types.Collection,
    start_mm: Sequence[float],
    end_mm: Sequence[float],
    radius_start_mm: float,
    radius_end_mm: float,
    material: bpy.types.Material | None,
    vertices: int = 20,
    overlap_mm: float = 0.0,
    print_source: bool = True,
    minimum_feature_mm: float | None = None,
) -> bpy.types.Object:
    if radius_start_mm <= 0 or radius_end_mm <= 0:
        raise ValueError("cone end radii must be positive")
    start = Vector(tuple(float(value) for value in start_mm))
    end = Vector(tuple(float(value) for value in end_mm))
    delta = end - start
    length_mm = delta.length
    if length_mm <= 0:
        raise ValueError("cone endpoints must be distinct")
    direction = delta.normalized()
    half_overlap = max(0.0, float(overlap_mm)) * 0.5
    expanded_start = start - direction * half_overlap
    expanded_end = end + direction * half_overlap
    midpoint = (expanded_start + expanded_end) * 0.5
    depth_mm = (expanded_end - expanded_start).length
    bpy.ops.mesh.primitive_cone_add(
        vertices=max(6, min(int(vertices), 64)),
        radius1=mm_to_m(radius_start_mm),
        radius2=mm_to_m(radius_end_mm),
        depth=mm_to_m(depth_mm),
        end_fill_type="NGON",
        location=point_mm(midpoint),
    )
    obj = bpy.context.object
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(direction)
    _apply_scale(obj)
    return _finish_object(
        obj,
        name=name,
        collection=collection,
        material=material,
        print_source=print_source,
        minimum_feature_mm=(
            float(minimum_feature_mm)
            if minimum_feature_mm is not None
            else min(radius_start_mm, radius_end_mm) * 2.0
        ),
    )


def mesh_bounds_mm(objects: Iterable[bpy.types.Object]) -> tuple[Vector, Vector]:
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    found = False
    for obj in objects:
        if obj.type != "MESH":
            continue
        found = True
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            minimum.x = min(minimum.x, world.x)
            minimum.y = min(minimum.y, world.y)
            minimum.z = min(minimum.z, world.z)
            maximum.x = max(maximum.x, world.x)
            maximum.y = max(maximum.y, world.y)
            maximum.z = max(maximum.z, world.z)
    if not found:
        raise ValueError("no mesh objects were supplied")
    return minimum * MM_PER_METER, maximum * MM_PER_METER
