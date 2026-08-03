"""Independent Blender-side verification for one published G3 artifact set.

The outer gate starts Blender with ``model.blend`` as its startup file.  This
probe inspects that freshly loaded scene, then resets to independent empty
factory scenes for GLB and STL imports.  It writes path-free evidence only to
the caller-owned temporary gate directory.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bmesh  # type: ignore
import bpy  # type: ignore

from blender.core.fingerprint import structural_report
from blender.generators.types import GenerationResult
from shared.character_spec import BuildRequest
from shared.json_contract import canonical_json_bytes, canonical_sha256


GATE_VERSION = "g3-artifact-probe/v1"
BLENDER_VERSION = "4.5.12 LTS"
REQUIRED_COLLECTIONS = ("CAMERAS", "CHARACTER", "LIGHTS", "PRINT", "SET")
GENERATION_COLLECTION_ORDER = ("CHARACTER", "PRINT", "SET", "LIGHTS", "CAMERAS")
EXPECTED_CAMERAS = ("Camera_Back", "Camera_Front", "Camera_Preview", "Camera_Side")
EXPECTED_LIGHTS = ("Light_Fill", "Light_Key", "Light_Rim")
MAX_OBJECTS = 256
MAX_MATERIALS = 64
MAX_TRIANGLES = 500_000
RENDER_SIZE = 512
RENDER_SAMPLES = 32
PATH_LIKE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")


class ArtifactProbeFailure(AssertionError):
    """A stable, path-free G3 artifact invariant failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactProbeFailure(message)


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ArtifactProbeFailure(f"{label} is not numeric") from exc
    _require(math.isfinite(number), f"{label} is not finite")
    return number


def _rounded(value: float, places: int = 6) -> float:
    result = round(float(value), places)
    return 0.0 if result == 0 else result


def _assert_path_free(value: Any, label: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_path_free(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_path_free(item, f"{label}[{index}]")
    elif isinstance(value, str):
        _require(not PATH_LIKE.match(value), f"{label} contains a local path")
        _require("file://" not in value.lower(), f"{label} contains a file URI")
        for local_root in (str(ROOT), str(Path.home()), "/private/tmp", "/tmp/"):
            _require(local_root not in value, f"{label} embeds a local path")


def _scene_collections() -> Dict[str, Any]:
    found: Dict[str, Any] = {}

    def visit(collection: Any) -> None:
        for child in collection.children:
            found[child.name] = child
            visit(child)

    visit(bpy.context.scene.collection)
    return found


def _world_bounds(
    objects: Iterable[Any], depsgraph: Any, mm_per_unit: float
) -> Tuple[List[float], List[float]]:
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    found = False
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            for vertex in mesh.vertices:
                found = True
                coordinate = evaluated.matrix_world @ vertex.co
                for axis in range(3):
                    number = _finite(coordinate[axis], f"{obj.name}.bound[{axis}]")
                    minimum[axis] = min(minimum[axis], number)
                    maximum[axis] = max(maximum[axis], number)
        finally:
            evaluated.to_mesh_clear()
    _require(found, "bounds require at least one mesh vertex")
    return (
        [_rounded(value * mm_per_unit) for value in minimum],
        [_rounded(value * mm_per_unit) for value in maximum],
    )


def _dimensions(bounds: Tuple[Sequence[float], Sequence[float]]) -> List[float]:
    minimum, maximum = bounds
    result = [_rounded(float(maximum[i]) - float(minimum[i])) for i in range(3)]
    _require(all(value > 0 for value in result), "geometry lacks three-dimensional bounds")
    return result


def _mesh_bounds(mesh: Any, matrix_world: Any, mm_per_unit: float, label: str) -> Tuple[List[float], List[float]]:
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    _require(bool(mesh.vertices), f"{label}: bounds require mesh vertices")
    for vertex in mesh.vertices:
        coordinate = matrix_world @ vertex.co
        for axis in range(3):
            number = _finite(coordinate[axis], f"{label}.bound[{axis}]")
            minimum[axis] = min(minimum[axis], number)
            maximum[axis] = max(maximum[axis], number)
    return (
        [_rounded(value * mm_per_unit) for value in minimum],
        [_rounded(value * mm_per_unit) for value in maximum],
    )


def _matrix_is_finite(obj: Any) -> None:
    for row_index, row in enumerate(obj.matrix_world):
        for column_index, value in enumerate(row):
            _finite(value, f"{obj.name}.matrix[{row_index}][{column_index}]")


def _mesh_observations(
    objects: Iterable[Any], mm_per_unit: float, *, require_materials: bool = True
) -> List[Dict[str, Any]]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    observations: List[Dict[str, Any]] = []
    for obj in sorted((item for item in objects if item.type == "MESH"), key=lambda item: item.name):
        _matrix_is_finite(obj)
        _require(obj.data is not None, f"{obj.name}: missing source mesh")
        _require(len(obj.data.vertices) > 0, f"{obj.name}: source mesh has no vertices")
        _require(len(obj.data.polygons) > 0, f"{obj.name}: source mesh has no faces")
        source_copy = obj.data.copy()
        try:
            _require(
                not source_copy.validate(verbose=False, clean_customdata=False),
                f"{obj.name}: source mesh required repair",
            )
        finally:
            bpy.data.meshes.remove(source_copy)

        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            _require(mesh is not None, f"{obj.name}: evaluated mesh is missing")
            _require(
                not mesh.validate(verbose=False, clean_customdata=False),
                f"{obj.name}: evaluated mesh required repair",
            )
            _require(len(mesh.vertices) > 0, f"{obj.name}: evaluated mesh has no vertices")
            _require(len(mesh.polygons) > 0, f"{obj.name}: evaluated mesh has no faces")
            mesh.calc_loop_triangles()
            _require(bool(mesh.loop_triangles), f"{obj.name}: evaluated mesh has no triangles")
            # Do not call evaluated.to_mesh() a second time while ``mesh`` is
            # live.  Blender invalidates the first temporary mesh when the
            # nested call is cleared.
            bounds = _mesh_bounds(mesh, evaluated.matrix_world, mm_per_unit, obj.name)
            material_names = sorted(
                slot.material.name for slot in obj.material_slots if slot.material is not None
            )
            if require_materials:
                _require(bool(material_names), f"{obj.name}: mesh has no assigned material")
            observations.append(
                {
                    "bounds_mm": {
                        "dimensions": _dimensions(bounds),
                        "maximum": bounds[1],
                        "minimum": bounds[0],
                    },
                    "evaluated": {
                        "edges": len(mesh.edges),
                        "faces": len(mesh.polygons),
                        "triangles": len(mesh.loop_triangles),
                        "vertices": len(mesh.vertices),
                    },
                    "materials": material_names,
                    "name": obj.name,
                    "source": {
                        "edges": len(obj.data.edges),
                        "faces": len(obj.data.polygons),
                        "vertices": len(obj.data.vertices),
                    },
                }
            )
        finally:
            evaluated.to_mesh_clear()
    _require(bool(observations), "scene contains no actual mesh objects")
    return observations


def _topology(obj: Any, mm_per_unit: float) -> Dict[str, Any]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh()
    mesh = bmesh.new()
    try:
        mesh.from_mesh(evaluated_mesh)
        mesh.transform(evaluated.matrix_world)
        mesh.normal_update()
        _require(bool(mesh.verts) and bool(mesh.faces), "shell topology is empty")
        _require(
            all(math.isfinite(coordinate) for vertex in mesh.verts for coordinate in vertex.co),
            "shell topology contains non-finite coordinates",
        )

        unseen_vertices = set(mesh.verts)
        vertex_components = 0
        while unseen_vertices:
            vertex_components += 1
            pending = [unseen_vertices.pop()]
            while pending:
                vertex = pending.pop()
                for edge in vertex.link_edges:
                    other = edge.other_vert(vertex)
                    if other in unseen_vertices:
                        unseen_vertices.remove(other)
                        pending.append(other)

        unseen_faces = set(mesh.faces)
        face_components = 0
        while unseen_faces:
            face_components += 1
            pending_faces = [unseen_faces.pop()]
            while pending_faces:
                face = pending_faces.pop()
                for edge in face.edges:
                    for linked in edge.link_faces:
                        if linked in unseen_faces:
                            unseen_faces.remove(linked)
                            pending_faces.append(linked)

        boundary_edges = sum(1 for edge in mesh.edges if edge.is_boundary)
        non_manifold_edges = sum(1 for edge in mesh.edges if not edge.is_manifold)
        non_contiguous_edges = sum(1 for edge in mesh.edges if not edge.is_contiguous)
        non_manifold_vertices = sum(1 for vertex in mesh.verts if not vertex.is_manifold)
        area_scale = mm_per_unit * mm_per_unit
        near_zero_faces = sum(
            1 for face in mesh.faces if face.calc_area() * area_scale <= 1e-8
        )
        volume = _finite(
            mesh.calc_volume(signed=True) * mm_per_unit * mm_per_unit * mm_per_unit,
            "signed shell volume",
        )
        return {
            "boundary_edges": boundary_edges,
            "face_components": face_components,
            "near_zero_faces": near_zero_faces,
            "non_contiguous_edges": non_contiguous_edges,
            "non_manifold_edges": non_manifold_edges,
            "non_manifold_vertices": non_manifold_vertices,
            "signed_volume_mm3": _rounded(volume),
            "vertex_components": vertex_components,
        }
    finally:
        mesh.free()
        evaluated.to_mesh_clear()


def _assert_closed_positive_shell(topology: Mapping[str, Any], label: str) -> None:
    expected_zero = (
        "boundary_edges",
        "near_zero_faces",
        "non_contiguous_edges",
        "non_manifold_edges",
        "non_manifold_vertices",
    )
    _require(topology["face_components"] == 1, f"{label}: multiple face components")
    _require(topology["vertex_components"] == 1, f"{label}: multiple vertex components")
    for field in expected_zero:
        _require(topology[field] == 0, f"{label}: {field} is nonzero")
    _require(topology["signed_volume_mm3"] > 0, f"{label}: volume is not positive")


def _total_triangles(observations: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(item["evaluated"]["triangles"]) for item in observations)


def _material_count(objects: Iterable[Any]) -> int:
    materials = {
        slot.material.name
        for obj in objects
        if obj.type == "MESH"
        for slot in obj.material_slots
        if slot.material is not None
    }
    return len(materials)


def _assert_no_external_resources() -> None:
    _require(len(bpy.data.libraries) == 0, "scene contains linked libraries")
    for image in bpy.data.images:
        _require(
            image.source not in {"FILE", "MOVIE", "SEQUENCE"},
            "scene contains an external image resource",
        )
    for material in bpy.data.materials:
        if material.use_nodes and material.node_tree is not None:
            for node in material.node_tree.nodes:
                _require(
                    node.bl_idname not in {"ShaderNodeTexEnvironment", "ShaderNodeTexImage"},
                    "scene contains an image texture node",
                )
    for collection_name in ("cache_files", "movieclips", "sounds", "volumes"):
        collection = getattr(bpy.data, collection_name, ())
        for datablock in collection:
            filepath = str(getattr(datablock, "filepath", ""))
            _require(not filepath, f"scene contains external {collection_name}")


def _within_tolerance(expected: Sequence[float], observed: Sequence[float]) -> bool:
    for expected_value, observed_value in zip(expected, observed):
        tolerance = max(0.2, abs(float(expected_value)) * 0.005)
        if abs(float(observed_value) - float(expected_value)) > tolerance:
            return False
    return True


def _height_matches(requested: float, dimensions: Sequence[float]) -> bool:
    tolerance = max(0.2, abs(requested) * 0.005)
    return abs(float(dimensions[2]) - requested) <= tolerance


def _verify_loaded_blend(
    request: BuildRequest, blend_path: Path
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    _require(bpy.app.version_string == BLENDER_VERSION, "gate requires exact Blender 4.5.12 LTS")
    _require(Path(bpy.data.filepath).resolve() == blend_path.resolve(), "model.blend was not freshly loaded")
    scene = bpy.context.scene
    collections = _scene_collections()
    _require(set(collections) == set(REQUIRED_COLLECTIONS), "saved scene collection set is invalid")
    character = list(collections["CHARACTER"].all_objects)
    printable = list(collections["PRINT"].all_objects)
    cameras = list(collections["CAMERAS"].all_objects)
    lights = list(collections["LIGHTS"].all_objects)
    _require(character and all(obj.type == "MESH" for obj in character), "CHARACTER is invalid")
    _require(len(printable) == 1 and printable[0].type == "MESH", "PRINT is not one mesh")
    _require(tuple(sorted(obj.name for obj in cameras)) == EXPECTED_CAMERAS, "camera inventory mismatch")
    _require(tuple(sorted(obj.name for obj in lights)) == EXPECTED_LIGHTS, "light inventory mismatch")
    _require(scene.camera in cameras, "active camera is outside CAMERAS")
    _require(scene.render.engine == "BLENDER_EEVEE_NEXT", "saved render engine is not Eevee Next")
    _require(
        scene.render.resolution_x == RENDER_SIZE
        and scene.render.resolution_y == RENDER_SIZE
        and scene.render.resolution_percentage == 100,
        "saved render dimensions are invalid",
    )
    _require(scene.render.image_settings.file_format == "PNG", "saved output format is not PNG")
    _require(scene.render.image_settings.color_mode == "RGBA", "saved PNG mode is not RGBA")
    _require(scene.render.image_settings.color_depth == "8", "saved PNG depth is not 8-bit")
    _require(scene.render.filepath.startswith("//"), "saved render path is not relative")
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        _require(scene.eevee.taa_render_samples == RENDER_SAMPLES, "saved render sample cap mismatch")

    scene_objects = list(scene.objects)
    _require(1 <= len(scene_objects) <= MAX_OBJECTS, "saved scene object cap violated")
    _require(1 <= len(bpy.data.materials) <= MAX_MATERIALS, "saved material cap violated")
    mm_per_unit = _finite(scene.unit_settings.scale_length, "saved unit scale") * 1000.0
    observations = _mesh_observations(scene_objects, mm_per_unit)
    _require(4 <= _total_triangles(observations) <= MAX_TRIANGLES, "saved triangle cap violated")
    _assert_no_external_resources()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    display_bounds = _world_bounds(character, depsgraph, mm_per_unit)
    print_bounds = _world_bounds(printable, depsgraph, mm_per_unit)
    display_dimensions = _dimensions(display_bounds)
    print_dimensions = _dimensions(print_bounds)
    requested_height = _finite(request.spec.height_mm, "requested height")
    _require(_height_matches(requested_height, display_dimensions), "display height mismatch")
    _require(_height_matches(requested_height, print_dimensions), "printable height mismatch")
    topology = _topology(printable[0], mm_per_unit)
    _assert_closed_positive_shell(topology, "saved printable")
    designed_features = [
        _finite(obj.get("designed_minimum_feature_mm"), f"{obj.name}.designed feature")
        for obj in character
        if obj.get("designed_minimum_feature_mm") is not None
    ]
    _require(bool(designed_features), "saved scene lacks designed feature metadata")
    generation_result = GenerationResult(
        generator_id=request.generator,
        display_object_names=tuple(sorted(obj.name for obj in character)),
        printable_object_name=printable[0].name,
        designed_minimum_feature_mm=min(designed_features),
        voxel_size_mm=_finite(printable[0].get("voxel_size_mm"), "saved printable voxel size"),
        request_sha256=request.request_sha256,
        spec_sha256=request.spec_sha256,
        collection_names=GENERATION_COLLECTION_ORDER,
    )
    fingerprint = structural_report(request, generation_result)
    verifier_expected = {
        "dimensions_mm": [_rounded(value, 4) for value in print_dimensions],
        "generation_result": {
            "collection_names": list(generation_result.collection_names),
            "designed_minimum_feature_mm": generation_result.designed_minimum_feature_mm,
            "display_object_names": list(generation_result.display_object_names),
            "generator_id": generation_result.generator_id,
            "printable_object_name": generation_result.printable_object_name,
            "request_sha256": generation_result.request_sha256,
            "spec_sha256": generation_result.spec_sha256,
            "voxel_size_mm": generation_result.voxel_size_mm,
        },
        "request": json.loads(canonical_json_bytes(request.to_dict()).decode("utf-8")),
        "structural_fingerprint_sha256": fingerprint["fingerprint_sha256"],
    }
    observation = {
        "display_bounds_mm": {
            "dimensions": display_dimensions,
            "maximum": display_bounds[1],
            "minimum": display_bounds[0],
        },
        "material_count": _material_count(scene_objects),
        "mesh_inventory": observations,
        "object_count": len(scene_objects),
        "printable_bounds_mm": {
            "dimensions": print_dimensions,
            "maximum": print_bounds[1],
            "minimum": print_bounds[0],
        },
        "printable_topology": topology,
        "triangle_count": _total_triangles(observations),
    }
    return observation, verifier_expected


def _verify_glb(request: BuildRequest, glb_path: Path, blend: Mapping[str, Any]) -> Dict[str, Any]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(filepath=str(glb_path))
    _require("FINISHED" in result, "GLB import did not finish")
    objects = list(bpy.context.scene.objects)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    _require(meshes and len(meshes) == len(objects), "GLB contains non-mesh scene objects")
    _require(1 <= len(objects) <= MAX_OBJECTS, "GLB object cap violated")
    _require(1 <= len(bpy.data.materials) <= MAX_MATERIALS, "GLB material cap violated")
    observations = _mesh_observations(meshes, 1000.0)
    triangles = _total_triangles(observations)
    _require(4 <= triangles <= MAX_TRIANGLES, "GLB triangle cap violated")
    _assert_no_external_resources()
    bounds = _world_bounds(meshes, bpy.context.evaluated_depsgraph_get(), 1000.0)
    dimensions = _dimensions(bounds)
    expected = blend["display_bounds_mm"]["dimensions"]
    _require(_within_tolerance(expected, dimensions), "GLB bounds differ from display bounds")
    _require(_height_matches(float(request.spec.height_mm), dimensions), "GLB height mismatch")
    return {
        "bounds_mm": {"dimensions": dimensions, "maximum": bounds[1], "minimum": bounds[0]},
        "material_count": _material_count(meshes),
        "mesh_inventory": observations,
        "object_count": len(objects),
        "triangle_count": triangles,
    }


def _verify_stl(request: BuildRequest, stl_path: Path, blend: Mapping[str, Any]) -> Dict[str, Any]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.wm.stl_import(
        filepath=str(stl_path),
        global_scale=0.001,
        use_scene_unit=False,
        forward_axis="Y",
        up_axis="Z",
    )
    _require("FINISHED" in result, "STL import did not finish")
    objects = list(bpy.context.scene.objects)
    meshes = [obj for obj in objects if obj.type == "MESH"]
    _require(len(objects) == 1 and len(meshes) == 1, "STL did not import as exactly one mesh")
    # STL has no material representation; its geometry is verified separately.
    observations = _mesh_observations(meshes, 1000.0, require_materials=False)
    triangles = _total_triangles(observations)
    _require(4 <= triangles <= MAX_TRIANGLES, "STL triangle cap violated")
    _assert_no_external_resources()
    bounds = _world_bounds(meshes, bpy.context.evaluated_depsgraph_get(), 1000.0)
    dimensions = _dimensions(bounds)
    expected = blend["printable_bounds_mm"]["dimensions"]
    _require(_within_tolerance(expected, dimensions), "STL bounds differ from printable bounds")
    _require(_height_matches(float(request.spec.height_mm), dimensions), "STL height mismatch")
    topology = _topology(meshes[0], 1000.0)
    _assert_closed_positive_shell(topology, "reimported STL")
    return {
        "bounds_mm": {"dimensions": dimensions, "maximum": bounds[1], "minimum": bounds[0]},
        "mesh_inventory": observations,
        "object_count": len(objects),
        "topology": topology,
        "triangle_count": triangles,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independently verify one G3 artifact set")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--stl", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(argv)


def _script_args() -> Sequence[str]:
    try:
        boundary = sys.argv.index("--")
    except ValueError as exc:
        raise ArtifactProbeFailure("missing '--' script argument boundary") from exc
    return sys.argv[boundary + 1 :]


def main() -> int:
    args = _parse_args(_script_args())
    result_path = Path(args.result)
    _require(not result_path.exists(), "refusing to overwrite probe evidence")
    request = BuildRequest.from_json(Path(args.request).read_bytes())
    blend, verifier_expected = _verify_loaded_blend(request, Path(args.blend))
    glb = _verify_glb(request, Path(args.glb), blend)
    stl = _verify_stl(request, Path(args.stl), blend)
    stable = {"blend": blend, "glb": glb, "stl": stl}
    evidence = {
        "blender_version": bpy.app.version_string,
        "checks": {
            "fresh_blend_reload": True,
            "glb_clean_reimport": True,
            "no_external_resources": True,
            "stl_clean_reimport": True,
        },
        "example_slug": request.spec.slug,
        "gate_version": GATE_VERSION,
        "stable": stable,
        "stable_sha256": canonical_sha256(stable),
        "status": "passed",
        "verifier_expected": verifier_expected,
    }
    _assert_path_free(evidence)
    result_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print("G3_ARTIFACT_PROBE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
