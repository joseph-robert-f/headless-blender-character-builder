"""Conservative measured mesh evidence for geometry-v1.

Topology is measured on the evaluated printable shell.  Wall and feature
evidence are derived from the actual voxel-unioned shell and reduced by two
voxel widths; ambiguous short ray candidates fail closed as unmeasurable.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..generators.types import GenerationResult
from ..core.primitives import MM_PER_METER


ZERO_AREA_MM2 = 1.0e-8
WALL_THRESHOLD_MM = 1.2
STRICT_OPPOSITION_DOT = -0.9659258262890683
RADIAL_DIRECTIONS = 72
FEATURE_ROLES = {
    "antenna",
    "antenna-tip",
    "arm",
    "backpack",
    "chest-badge",
    "eye",
    "foot",
    "hand",
    "leg",
    "long-horns",
    "pointed-ears",
    "round-ears",
    "short-horns",
    "tail",
    "tail-tip",
}


def _rounded(value: float, places: int = 4) -> float:
    result = round(float(value), places)
    return 0.0 if result == 0 else result


def _face_connected_components(bm: bmesh.types.BMesh) -> int:
    """Count shells by shared edges, not merely by touching vertices."""

    unseen = set(bm.faces)
    count = 0
    while unseen:
        count += 1
        pending = [unseen.pop()]
        while pending:
            face = pending.pop()
            for edge in face.edges:
                for neighbor in edge.link_faces:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        pending.append(neighbor)
    return count


def _bounds_mm(bm: bmesh.types.BMesh) -> list[float]:
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    for vertex in bm.verts:
        for axis in range(3):
            minimum[axis] = min(minimum[axis], vertex.co[axis])
            maximum[axis] = max(maximum[axis], vertex.co[axis])
    return [_rounded((maximum[axis] - minimum[axis]) * MM_PER_METER) for axis in range(3)]


def analyze_mesh_object(
    obj: bpy.types.Object,
    *,
    measure_wall: bool = False,
    voxel_size_mm: float = 0.0,
) -> dict[str, Any]:
    """Measure evaluated world-space topology and optional wall evidence."""

    if obj.type != "MESH":
        raise TypeError("geometry QA requires a mesh object")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.transform(evaluated.matrix_world)
        bm.normal_update()
        finite = all(
            math.isfinite(coordinate) for vertex in bm.verts for coordinate in vertex.co
        ) and all(
            math.isfinite(float(value))
            for row in evaluated.matrix_world
            for value in row
        )
        connected_shells = _face_connected_components(bm) if bm.faces else 0
        non_manifold = sum(1 for edge in bm.edges if not edge.is_manifold)
        non_manifold_vertices = sum(1 for vertex in bm.verts if not vertex.is_manifold)
        non_contiguous = sum(1 for edge in bm.edges if not edge.is_contiguous)
        zero_area = sum(
            1
            for face in bm.faces
            if face.calc_area() * MM_PER_METER * MM_PER_METER <= ZERO_AREA_MM2
        )
        signed_volume_m3 = bm.calc_volume(signed=True) if bm.faces else 0.0
        triangle_count = sum(max(0, len(face.verts) - 2) for face in bm.faces)
        return {
            "dimensions_mm": _bounds_mm(bm),
            "vertices": len(bm.verts),
            "edges": len(bm.edges),
            "faces": len(bm.faces),
            "triangles": triangle_count,
            "connected_shells": connected_shells,
            "non_manifold_edges": non_manifold,
            "non_manifold_vertices": non_manifold_vertices,
            "non_contiguous_edges": non_contiguous,
            "zero_area_faces": zero_area,
            "finite_geometry": finite,
            "signed_volume_mm3": _rounded(signed_volume_m3 * 1_000_000_000.0, 3),
            "positive_volume": signed_volume_m3 > 0.0,
            "outward_normals": non_contiguous == 0 and signed_volume_m3 > 0.0,
            # The conservative shell-wide BVH measurement is attached by
            # analyze_generated_scene.  A topology-only reimport must not
            # pretend that it performed this mandatory analysis.
            "minimum_wall_mm": None,
            "wall_sample_count": 0,
        }
    finally:
        bm.free()
        evaluated.to_mesh_clear()


def _face_adjacency(mesh: bpy.types.Mesh) -> tuple[frozenset[int], ...]:
    """Return polygons joined by a source-mesh edge."""

    edge_faces: list[list[int]] = [[] for _edge in mesh.edges]
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            edge_faces[mesh.loops[loop_index].edge_index].append(polygon.index)
    adjacency: list[set[int]] = [set() for _polygon in mesh.polygons]
    for linked in edge_faces:
        if len(linked) == 2:
            first, second = linked
            adjacency[first].add(second)
            adjacency[second].add(first)
    return tuple(frozenset(neighbors) for neighbors in adjacency)


def _wall_evidence(
    mesh: bpy.types.Mesh,
    matrix_world: Any,
    vertices: list[Vector],
    tree: BVHTree,
    voxel_size_mm: float,
    max_distance_m: float,
) -> dict[str, Any]:
    """Measure every final-shell triangle and reject ambiguous thin chords."""

    loop_triangles = tuple(mesh.loop_triangles)
    triangle_to_polygon = tuple(
        triangle.polygon_index for triangle in loop_triangles
    )
    adjacency = _face_adjacency(mesh)
    normal_matrix = matrix_world.to_3x3().inverted_safe().transposed()
    epsilon_m = max(0.005, voxel_size_mm * 0.03) / MM_PER_METER
    conflict_limit_mm = WALL_THRESHOLD_MM + 2.0 * voxel_size_mm
    strict_count = 0
    reciprocal_count = 0
    strict_conflicts = 0
    reciprocal_conflicts = 0
    strict_minimum = math.inf
    reciprocal_minimum = math.inf
    misses = 0

    for triangle in loop_triangles:
        indices = tuple(
            mesh.loops[loop_index].vertex_index
            for loop_index in triangle.loops
        )
        point = sum(
            (vertices[index] for index in indices),
            Vector((0.0, 0.0, 0.0)),
        ) / 3.0
        normal = normal_matrix @ triangle.normal
        if normal.length_squared <= 0.0:
            misses += 1
            continue
        normal.normalize()
        hit, hit_normal, hit_index, distance = tree.ray_cast(
            point - normal * epsilon_m,
            -normal,
            max_distance_m,
        )
        if (
            hit is None
            or hit_normal is None
            or hit_index is None
            or distance is None
        ):
            misses += 1
            continue
        hit_polygon = triangle_to_polygon[hit_index]
        if (
            hit_index == triangle.index
            or hit_polygon == triangle.polygon_index
            or hit_polygon in adjacency[triangle.polygon_index]
        ):
            continue
        normalized_hit = hit_normal.normalized()
        if normal.dot(normalized_hit) > STRICT_OPPOSITION_DOT:
            continue
        thickness_mm = (float(distance) + epsilon_m) * MM_PER_METER
        if not math.isfinite(thickness_mm) or thickness_mm <= 0.0:
            misses += 1
            continue
        strict_count += 1
        strict_minimum = min(strict_minimum, thickness_mm)
        if thickness_mm < conflict_limit_mm:
            strict_conflicts += 1

        back_hit, back_normal, _back_index, back_distance = tree.ray_cast(
            hit - normalized_hit * epsilon_m,
            -normalized_hit,
            max_distance_m,
        )
        if (
            back_hit is None
            or back_normal is None
            or back_distance is None
        ):
            continue
        back_normal.normalize()
        back_thickness_mm = (float(back_distance) + epsilon_m) * MM_PER_METER
        closure_mm = (back_hit - point).length * MM_PER_METER
        if (
            back_normal.dot(normalized_hit) <= STRICT_OPPOSITION_DOT
            and closure_mm <= voxel_size_mm
            and abs(back_thickness_mm - thickness_mm) <= voxel_size_mm
        ):
            reciprocal_count += 1
            reciprocal_minimum = min(reciprocal_minimum, thickness_mm)
            if thickness_mm < conflict_limit_mm:
                reciprocal_conflicts += 1

    measurable = (
        misses == 0
        and strict_count > 0
        and reciprocal_count > 0
        and strict_conflicts == 0
    )
    raw_minimum = (
        min(strict_minimum, reciprocal_minimum) if measurable else None
    )
    lower_bound = (
        max(0.0, raw_minimum - 2.0 * voxel_size_mm)
        if raw_minimum is not None
        else None
    )
    return {
        "minimum_wall_mm": _rounded(lower_bound) if lower_bound is not None else None,
        "wall_sample_count": len(loop_triangles),
        "wall_strict_count": strict_count,
        "wall_reciprocal_count": reciprocal_count,
        "wall_strict_conflict_count": strict_conflicts,
        "wall_reciprocal_conflict_count": reciprocal_conflicts,
        "wall_ray_misses": misses,
        "wall_raw_minimum_mm": (
            _rounded(raw_minimum) if raw_minimum is not None else None
        ),
        "wall_uncertainty_mm": _rounded(2.0 * voxel_size_mm),
    }


def _bidirectional_width_mm(
    tree: BVHTree,
    point: Vector,
    direction: Vector,
    max_distance_m: float,
) -> float | None:
    if direction.length_squared <= 0.0:
        return None
    direction = direction.normalized()
    plus, _plus_normal, _plus_index, plus_distance = tree.ray_cast(
        point, direction, max_distance_m
    )
    minus, _minus_normal, _minus_index, minus_distance = tree.ray_cast(
        point, -direction, max_distance_m
    )
    if (
        plus is None
        or minus is None
        or plus_distance is None
        or minus_distance is None
    ):
        return None
    width_mm = (float(plus_distance) + float(minus_distance)) * MM_PER_METER
    return width_mm if math.isfinite(width_mm) and width_mm > 0.0 else None


def _axis_range(values: Iterable[float]) -> float:
    values = tuple(values)
    return max(values) - min(values)


def _measured_feature_mm(obj: bpy.types.Object) -> float | None:
    """Measure a component's narrowest modeled cross-section from vertices."""

    if obj.type != "MESH" or not obj.data.vertices:
        return None
    vertices = tuple(vertex.co.copy() for vertex in obj.data.vertices)
    primitive = str(obj.get("builder_primitive", ""))
    if primitive in {"cylinder", "frustum"}:
        z_min = min(vertex.z for vertex in vertices)
        z_max = max(vertex.z for vertex in vertices)
        tolerance = max(1.0e-9, (z_max - z_min) * 1.0e-6)
        ring_measurements = []
        for z_value in (z_min, z_max):
            ring = [vertex for vertex in vertices if abs(vertex.z - z_value) <= tolerance]
            if len(ring) >= 3:
                diameter_x = _axis_range(vertex.x for vertex in ring)
                diameter_y = _axis_range(vertex.y for vertex in ring)
                positive = [value for value in (diameter_x, diameter_y) if value > 1.0e-9]
                if positive:
                    ring_measurements.append(min(positive) * MM_PER_METER)
        if ring_measurements:
            return _rounded(min(ring_measurements), 4)
    dimensions = [
        _axis_range(vertex[axis] for vertex in vertices) * MM_PER_METER
        for axis in range(3)
    ]
    positive_dimensions = [value for value in dimensions if value > 1.0e-6]
    return _rounded(min(positive_dimensions), 4) if positive_dimensions else None


def _actual_feature_probe(
    printable_tree: BVHTree,
    obj: bpy.types.Object,
    voxel_size_mm: float,
    max_distance_m: float,
) -> dict[str, Any]:
    """Measure generator-specific semantic cross-sections on PrintableShell.

    Compact primitives use their three principal centre axes.  Swept cylinders
    and frustums additionally sample their centreline no farther than half a
    voxel apart, using 72 radial directions at every position.  Attachment
    joins are not waived here; ambiguous short joins are independently caught
    by the shell-wide wall conflict gate.
    """

    local = tuple(vertex.co.copy() for vertex in obj.data.vertices)
    if not local:
        return {"status": "unmeasurable", "reason": "empty source mesh"}
    minimum = Vector(
        tuple(min(vertex[axis] for vertex in local) for axis in range(3))
    )
    maximum = Vector(
        tuple(max(vertex[axis] for vertex in local) for axis in range(3))
    )
    center = (minimum + maximum) * 0.5
    rotation = obj.matrix_world.to_3x3()
    axes = tuple(
        (rotation @ axis).normalized()
        for axis in (
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 1.0, 0.0)),
            Vector((0.0, 0.0, 1.0)),
        )
    )
    world_center = obj.matrix_world @ center
    center_widths = [
        _bidirectional_width_mm(
            printable_tree, world_center, axis, max_distance_m
        )
        for axis in axes
    ]
    if any(width is None for width in center_widths):
        return {
            "status": "unmeasurable",
            "reason": "a compact principal-axis ray missed PrintableShell",
        }
    widths = [float(width) for width in center_widths if width is not None]
    samples: list[dict[str, Any]] = []
    primitive = str(obj.get("builder_primitive", ""))
    if primitive in {"cylinder", "frustum"}:
        span_mm = (maximum.z - minimum.z) * MM_PER_METER
        margin_mm = min(span_mm * 0.25, max(voxel_size_mm * 0.5, 0.05))
        start = minimum.z + margin_mm / MM_PER_METER
        stop = maximum.z - margin_mm / MM_PER_METER
        maximum_step_mm = max(voxel_size_mm * 0.5, 0.05)
        count = max(
            3,
            int(
                math.ceil(
                    max(0.0, (stop - start) * MM_PER_METER)
                    / maximum_step_mm
                )
            )
            + 1,
        )
        for index in range(count):
            position = start + (stop - start) * index / (count - 1)
            point = obj.matrix_world @ Vector((center.x, center.y, position))
            radial_widths = []
            for angle_index in range(RADIAL_DIRECTIONS):
                angle = math.pi * angle_index / RADIAL_DIRECTIONS
                direction = axes[0] * math.cos(angle) + axes[1] * math.sin(angle)
                width = _bidirectional_width_mm(
                    printable_tree, point, direction, max_distance_m
                )
                if width is None:
                    return {
                        "status": "unmeasurable",
                        "reason": "a swept radial ray missed PrintableShell",
                        "axis_sample_count": len(samples),
                    }
                radial_widths.append(width)
            local_minimum = min(radial_widths)
            widths.append(local_minimum)
            samples.append(
                {
                    "position_mm": position * MM_PER_METER,
                    "minimum_mm": local_minimum,
                    "radial_directions": RADIAL_DIRECTIONS,
                }
            )
    return {
        "status": "measured",
        "primitive": primitive,
        "center_widths_mm": center_widths,
        "axis_sample_count": len(samples),
        "minimum_actual_shell_width_mm": min(widths),
        "minimum_axis_samples": sorted(
            samples, key=lambda sample: sample["minimum_mm"]
        )[:5],
    }


def _measure_printable_shell(
    printable: bpy.types.Object,
    feature_objects: Iterable[bpy.types.Object],
    voxel_size_mm: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], float | None]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = printable.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        matrix_world = evaluated.matrix_world.copy()
        vertices = [matrix_world @ vertex.co for vertex in mesh.vertices]
        triangles = [
            tuple(mesh.loops[index].vertex_index for index in triangle.loops)
            for triangle in mesh.loop_triangles
        ]
        if not vertices or not triangles:
            return (
                {
                    "minimum_wall_mm": None,
                    "wall_sample_count": 0,
                    "wall_strict_count": 0,
                    "wall_reciprocal_count": 0,
                    "wall_strict_conflict_count": 0,
                    "wall_reciprocal_conflict_count": 0,
                    "wall_ray_misses": 0,
                    "wall_raw_minimum_mm": None,
                    "wall_uncertainty_mm": _rounded(2.0 * voxel_size_mm),
                },
                [],
                None,
            )
        tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
        minimum = Vector(
            tuple(min(vertex[axis] for vertex in vertices) for axis in range(3))
        )
        maximum = Vector(
            tuple(max(vertex[axis] for vertex in vertices) for axis in range(3))
        )
        max_distance_m = max(maximum - minimum) * 2.0
        wall = _wall_evidence(
            mesh,
            matrix_world,
            vertices,
            tree,
            voxel_size_mm,
            max_distance_m,
        )
        measurements: list[dict[str, Any]] = []
        complete = True
        source_minimum = math.inf
        actual_minimum = math.inf
        for obj in feature_objects:
            source_width = _measured_feature_mm(obj)
            actual = _actual_feature_probe(
                tree, obj, voxel_size_mm, max_distance_m
            )
            actual_width = actual.get("minimum_actual_shell_width_mm")
            if (
                source_width is None
                or actual.get("status") != "measured"
                or not isinstance(actual_width, (int, float))
                or not math.isfinite(float(actual_width))
            ):
                complete = False
            else:
                source_minimum = min(source_minimum, source_width)
                actual_minimum = min(actual_minimum, float(actual_width))
            measurements.append(
                {
                    "name": obj.name,
                    "role": str(obj.get("component_role", "")),
                    "source_mm": source_width,
                    "actual_shell": actual,
                }
            )
        lower_bound = None
        if complete and measurements:
            lower_bound = max(
                0.0,
                min(source_minimum, actual_minimum) - 2.0 * voxel_size_mm,
            )
        return wall, measurements, (
            _rounded(lower_bound) if lower_bound is not None else None
        )
    finally:
        evaluated.to_mesh_clear()


def _scene_triangle_count(objects: Iterable[bpy.types.Object]) -> int:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    total = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    return total


def analyze_generated_scene(result: GenerationResult) -> dict[str, Any]:
    """Measure the live generated scene before it is saved or exported."""

    printable = bpy.data.objects.get(result.printable_object_name)
    if printable is None or printable.type != "MESH":
        raise RuntimeError("PrintableShell is missing before QA")
    display = []
    for name in result.display_object_names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise RuntimeError(f"display mesh is missing before QA: {name}")
        display.append(obj)
    printable_evidence = analyze_mesh_object(printable)
    feature_objects = []
    for obj in display:
        role = str(obj.get("component_role", ""))
        if role not in FEATURE_ROLES:
            continue
        feature_objects.append(obj)
    wall_evidence, feature_measurements, minimum_feature = _measure_printable_shell(
        printable,
        feature_objects,
        result.voxel_size_mm,
    )
    printable_evidence.update(wall_evidence)
    all_scene_objects = tuple(bpy.context.scene.objects)
    used_materials = {
        slot.material.name
        for obj in all_scene_objects
        if obj.type == "MESH"
        for slot in obj.material_slots
        if slot.material is not None
    }
    return {
        "printable": printable_evidence,
        "minimum_feature_mm": minimum_feature,
        "feature_measurements": feature_measurements,
        "triangle_count": _scene_triangle_count(all_scene_objects),
        "object_count": len(all_scene_objects),
        "material_count": len(used_materials),
    }


__all__ = ["analyze_generated_scene", "analyze_mesh_object"]
