"""Deterministic structural evidence for generated Blender scenes."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

import bmesh
import bpy
from mathutils import Vector

from shared.character_spec import BuildRequest
from shared.json_contract import canonical_sha256

from ..generators.types import GenerationResult
from .primitives import MM_PER_METER


FINGERPRINT_VERSION = "structural/v1"


def _rounded(value: float, places: int = 4) -> float:
    result = round(float(value), places)
    return 0.0 if result == 0 else result


def _counts(mesh: bpy.types.Mesh) -> dict[str, int]:
    mesh.calc_loop_triangles()
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "triangles": len(mesh.loop_triangles),
    }


def _add_counts(target: dict[str, int], values: Mapping[str, int]) -> None:
    for key in target:
        target[key] += int(values[key])


def _bounds_from_vertices(
    vertices: Iterable[Any], matrix_world: Any
) -> tuple[Vector, Vector]:
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    found = False
    for vertex in vertices:
        found = True
        world = matrix_world @ vertex.co
        minimum.x = min(minimum.x, world.x)
        minimum.y = min(minimum.y, world.y)
        minimum.z = min(minimum.z, world.z)
        maximum.x = max(maximum.x, world.x)
        maximum.y = max(maximum.y, world.y)
        maximum.z = max(maximum.z, world.z)
    if not found:
        raise RuntimeError("mesh has no vertices")
    return minimum, maximum


def _bounds_dict(minimum: Vector, maximum: Vector) -> dict[str, list[float]]:
    minimum_mm = minimum * MM_PER_METER
    maximum_mm = maximum * MM_PER_METER
    dimensions_mm = maximum_mm - minimum_mm
    return {
        "minimum": [_rounded(value) for value in minimum_mm],
        "maximum": [_rounded(value) for value in maximum_mm],
        "dimensions": [_rounded(value) for value in dimensions_mm],
    }


def _matrix_values(obj: bpy.types.Object) -> list[list[float]]:
    return [[_rounded(value, 8) for value in row] for row in obj.matrix_world]


def _mesh_inventory(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> tuple[dict[str, Any], tuple[Vector, Vector]]:
    source_counts = _counts(obj.data)
    evaluated_obj = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_obj.to_mesh()
    try:
        evaluated_counts = _counts(evaluated_mesh)
        minimum, maximum = _bounds_from_vertices(
            evaluated_mesh.vertices, evaluated_obj.matrix_world
        )
    finally:
        evaluated_obj.to_mesh_clear()
    materials = sorted(
        slot.material.name for slot in obj.material_slots if slot.material is not None
    )
    entry = {
        "name": obj.name,
        "type": obj.type,
        "collections": sorted(collection.name for collection in obj.users_collection),
        "builder_role": str(obj.get("builder_role", "")),
        "component_role": str(obj.get("component_role", "")),
        "component_preset": str(obj.get("component_preset", "")),
        "materials": materials,
        "source_mesh_counts": source_counts,
        "evaluated_mesh_counts": evaluated_counts,
        "bounds_mm": _bounds_dict(minimum, maximum),
        "matrix_world": _matrix_values(obj),
    }
    return entry, (minimum, maximum)


def _component_count(bm: bmesh.types.BMesh) -> int:
    remaining = set(bm.faces)
    components = 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for linked in edge.link_faces:
                    if linked in remaining:
                        remaining.remove(linked)
                        stack.append(linked)
    return components


def _printable_topology(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    mesh_counts = _counts(mesh)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()
        connected_shells = _component_count(bm)
        boundary_edges = sum(1 for edge in bm.edges if edge.is_boundary)
        non_manifold_edges = sum(1 for edge in bm.edges if not edge.is_manifold)
        zero_area_faces = sum(1 for face in bm.faces if face.calc_area() <= 1.0e-16)
        finite_coordinates = all(
            math.isfinite(coordinate) for vertex in bm.verts for coordinate in vertex.co
        )
        signed_volume_m3 = bm.calc_volume(signed=True) if bm.faces else 0.0
    finally:
        bm.free()
    return {
        **mesh_counts,
        "connected_shells": connected_shells,
        "boundary_edges": boundary_edges,
        "non_manifold_edges": non_manifold_edges,
        "zero_area_faces": zero_area_faces,
        "finite_coordinates": finite_coordinates,
        "signed_volume_mm3": _rounded(signed_volume_m3 * 1_000_000_000.0, 3),
        "positive_volume": signed_volume_m3 > 0.0,
    }


def structural_report(
    request: BuildRequest, result: GenerationResult
) -> dict[str, Any]:
    """Return a canonical-hashable structural report for the current scene."""

    if not isinstance(request, BuildRequest):
        raise TypeError("request must be a validated BuildRequest")
    if not isinstance(result, GenerationResult):
        raise TypeError("result must be a GenerationResult")
    if result.request_sha256 != request.request_sha256:
        raise ValueError("generation result does not belong to this request")

    display_names = set(result.display_object_names)
    expected_names = display_names | {result.printable_object_name}
    actual_names = {obj.name for obj in bpy.context.scene.objects if obj.type == "MESH"}
    if actual_names != expected_names:
        raise RuntimeError(
            "scene mesh inventory differs from GenerationResult: "
            f"expected={sorted(expected_names)!r} actual={sorted(actual_names)!r}"
        )
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bpy.context.view_layer.update()
    entries = []
    totals_source = {"vertices": 0, "edges": 0, "faces": 0, "triangles": 0}
    totals_evaluated = {"vertices": 0, "edges": 0, "faces": 0, "triangles": 0}
    display_minimum = Vector((math.inf, math.inf, math.inf))
    display_maximum = Vector((-math.inf, -math.inf, -math.inf))
    printable_bounds = None
    for name in sorted(expected_names):
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH":
            raise RuntimeError(f"missing generated mesh object: {name}")
        entry, bounds = _mesh_inventory(obj, depsgraph)
        entries.append(entry)
        _add_counts(totals_source, entry["source_mesh_counts"])
        _add_counts(totals_evaluated, entry["evaluated_mesh_counts"])
        minimum, maximum = bounds
        if name == result.printable_object_name:
            printable_bounds = bounds
        else:
            for index in range(3):
                display_minimum[index] = min(display_minimum[index], minimum[index])
                display_maximum[index] = max(display_maximum[index], maximum[index])
    if printable_bounds is None:
        raise RuntimeError("printable object has no bounds")

    printable = bpy.data.objects[result.printable_object_name]
    payload = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "generator_id": result.generator_id,
        "request_sha256": request.request_sha256,
        "spec_sha256": request.spec_sha256,
        "designed_minimum_feature_mm": _rounded(result.designed_minimum_feature_mm),
        "voxel_size_mm": _rounded(result.voxel_size_mm, 6),
        "bounds_mm": {
            "display": _bounds_dict(display_minimum, display_maximum),
            "printable": _bounds_dict(*printable_bounds),
        },
        "scene": {
            "collections": sorted(
                collection.name for collection in bpy.context.scene.collection.children
            ),
            "object_count": len(bpy.context.scene.objects),
            "mesh_object_count": len(expected_names),
            "material_count": len(bpy.data.materials),
            "material_names": sorted(material.name for material in bpy.data.materials),
            "source_mesh_counts": totals_source,
            "evaluated_mesh_counts": totals_evaluated,
            "objects": entries,
        },
        "printable": {
            "name": printable.name,
            "topology": _printable_topology(printable),
        },
    }
    report = dict(payload)
    report["fingerprint_sha256"] = canonical_sha256(payload)
    return report


__all__ = ["FINGERPRINT_VERSION", "structural_report"]
