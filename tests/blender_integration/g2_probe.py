"""Inner G2 probe executed by Blender, never by ordinary test discovery.

The host-side gate starts one factory-startup Blender process for exactly one
request.  This probe invokes the real generator, inspects source and evaluated
Blender meshes, and emits path-free structural evidence only after every local
assertion succeeds.
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

import bpy  # type: ignore  # Blender-only module
import bmesh  # type: ignore  # Blender-only module

from blender.core import structural_report
from blender.generators.registry import generate_character
from shared.character_spec import BuildRequest
from shared.json_contract import canonical_json_bytes, canonical_sha256


GATE_VERSION = "g2-probe/v1"
BLENDER_VERSION = "4.5.12 LTS"
REQUIRED_COLLECTIONS = ("CAMERAS", "CHARACTER", "LIGHTS", "PRINT", "SET")
MAX_SCENE_OBJECTS = 256
MAX_MATERIALS = 64
MAX_EVALUATED_TRIANGLES = 500_000
MIN_EVALUATED_TRIANGLES = 4
MIN_DESIGNED_FEATURE_MM = 2.0
BASE_DIMENSION_TOLERANCE_MM = 0.001
PATH_LIKE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\]|\\\\)")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ROLE_COUNTS = {
    "facet-bot": {
        "antenna": 2,
        "antenna-tip": 2,
        "arm": 2,
        "base": 1,
        "body": 1,
        "chest-badge": 1,
        "eye": 2,
        "foot": 2,
        "hand": 2,
        "head": 1,
        "leg": 2,
    },
    "moss-hopper": {
        "arm": 3,
        "backpack": 1,
        "base": 1,
        "body": 1,
        "eye": 2,
        "foot": 2,
        "hand": 2,
        "head": 1,
        "leg": 2,
        "pointed-ears": 2,
        "tail": 2,
        "tail-tip": 1,
    },
}


class ProbeFailure(AssertionError):
    """A stable, human-readable G2 invariant failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeFailure(message)


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProbeFailure(f"{label} is not numeric") from exc
    _require(math.isfinite(number), f"{label} is not finite")
    return number


def _rounded(value: float, places: int = 6) -> float:
    rounded = round(float(value), places)
    return 0.0 if rounded == 0 else rounded


def _json_value(value: Any) -> Any:
    """Normalize mappings, tuples, and Decimals through project canonical JSON."""

    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _assert_path_free(value: Any, label: str = "$") -> None:
    """Reject accidental host/repository paths in durable evidence."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_path_free(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_path_free(item, f"{label}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        _require(not PATH_LIKE.match(value), f"{label} contains an absolute path")
        _require("file://" not in lowered, f"{label} contains a file URI")


def _scene_collections() -> Dict[str, Any]:
    found: Dict[str, Any] = {}

    def visit(collection: Any) -> None:
        for child in collection.children:
            found[child.name] = child
            visit(child)

    visit(bpy.context.scene.collection)
    return found


def _material_names(obj: Any) -> Tuple[str, ...]:
    names: List[str] = []
    for index, slot in enumerate(obj.material_slots):
        _require(slot.material is not None, f"{obj.name}: empty material slot {index}")
        names.append(slot.material.name)
    _require(bool(names), f"{obj.name}: mesh has no assigned material")
    return tuple(names)


def _validate_source_mesh(obj: Any) -> None:
    _require(obj.data is not None, f"{obj.name}: missing source mesh datablock")
    _require(len(obj.data.vertices) > 0, f"{obj.name}: empty source vertices")
    _require(len(obj.data.polygons) > 0, f"{obj.name}: empty source polygons")
    copied = obj.data.copy()
    try:
        corrected = copied.validate(verbose=False, clean_customdata=False)
        _require(not corrected, f"{obj.name}: source mesh required validation repair")
    finally:
        bpy.data.meshes.remove(copied)


def _matrix_is_finite(obj: Any) -> None:
    for row_index, row in enumerate(obj.matrix_world):
        for column_index, value in enumerate(row):
            _finite_number(value, f"{obj.name}.matrix_world[{row_index}][{column_index}]")


def _printable_topology(
    evaluated_mesh: Any, matrix_world: Any, mm_per_unit: float
) -> Dict[str, Any]:
    mesh = bmesh.new()
    try:
        mesh.from_mesh(evaluated_mesh)
        mesh.transform(matrix_world)
        mesh.normal_update()
        _require(bool(mesh.verts), "printable shell has no BMesh vertices")
        _require(bool(mesh.edges), "printable shell has no BMesh edges")
        _require(bool(mesh.faces), "printable shell has no BMesh faces")

        unseen = set(mesh.verts)
        connected_components = 0
        while unseen:
            connected_components += 1
            pending = [unseen.pop()]
            while pending:
                vertex = pending.pop()
                for edge in vertex.link_edges:
                    other = edge.other_vert(vertex)
                    if other in unseen:
                        unseen.remove(other)
                        pending.append(other)
        _require(
            connected_components == 1,
            f"printable shell has {connected_components} connected vertex components",
        )

        unseen_faces = set(mesh.faces)
        face_components = 0
        while unseen_faces:
            face_components += 1
            pending_faces = [unseen_faces.pop()]
            while pending_faces:
                face = pending_faces.pop()
                for edge in face.edges:
                    for linked_face in edge.link_faces:
                        if linked_face in unseen_faces:
                            unseen_faces.remove(linked_face)
                            pending_faces.append(linked_face)
        _require(
            face_components == 1,
            f"printable shell has {face_components} face-connected shells",
        )

        boundary_edges = sum(1 for edge in mesh.edges if edge.is_boundary)
        non_manifold = sum(1 for edge in mesh.edges if not edge.is_manifold)
        non_manifold_vertices = sum(1 for vertex in mesh.verts if not vertex.is_manifold)
        non_contiguous = sum(1 for edge in mesh.edges if not edge.is_contiguous)
        _require(boundary_edges == 0, "printable shell has boundary edges")
        _require(non_manifold == 0, "printable shell has non-manifold edges")
        _require(
            non_manifold_vertices == 0,
            "printable shell has non-manifold vertices",
        )
        _require(non_contiguous == 0, "printable shell has non-contiguous winding")

        area_scale = mm_per_unit * mm_per_unit
        near_zero_faces = sum(
            1 for face in mesh.faces if face.calc_area() * area_scale <= 1e-8
        )
        _require(near_zero_faces == 0, "printable shell has near-zero-area faces")
        signed_volume_mm3 = _finite_number(
            mesh.calc_volume(signed=True) * mm_per_unit * mm_per_unit * mm_per_unit,
            "printable signed volume",
        )
        _require(signed_volume_mm3 > 0, "printable shell has non-positive signed volume")
        return {
            "boundary_edges": boundary_edges,
            "connected_face_components": face_components,
            "connected_vertex_components": connected_components,
            "near_zero_faces": near_zero_faces,
            "non_contiguous_edges": non_contiguous,
            "non_manifold_edges": non_manifold,
            "non_manifold_vertices": non_manifold_vertices,
            "signed_volume_mm3": _rounded(signed_volume_mm3),
        }
    finally:
        mesh.free()


def _mesh_observation(
    obj: Any, depsgraph: Any, mm_per_unit: float, is_printable: bool
) -> Dict[str, Any]:
    _matrix_is_finite(obj)
    _validate_source_mesh(obj)
    materials = _material_names(obj)

    evaluated_object = obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        _require(evaluated_mesh is not None, f"{obj.name}: evaluated mesh is missing")
        corrected = evaluated_mesh.validate(verbose=False, clean_customdata=False)
        _require(not corrected, f"{obj.name}: evaluated mesh required validation repair")
        _require(len(evaluated_mesh.vertices) > 0, f"{obj.name}: empty evaluated vertices")
        _require(len(evaluated_mesh.polygons) > 0, f"{obj.name}: empty evaluated polygons")
        evaluated_mesh.calc_loop_triangles()
        triangle_count = len(evaluated_mesh.loop_triangles)
        _require(triangle_count >= 1, f"{obj.name}: no evaluated triangles")

        minimum = [math.inf, math.inf, math.inf]
        maximum = [-math.inf, -math.inf, -math.inf]
        matrix = evaluated_object.matrix_world
        for vertex in evaluated_mesh.vertices:
            world = matrix @ vertex.co
            for axis in range(3):
                coordinate = _finite_number(world[axis], f"{obj.name}.vertex[{vertex.index}][{axis}]")
                minimum[axis] = min(minimum[axis], coordinate)
                maximum[axis] = max(maximum[axis], coordinate)

        dimensions_mm = [
            _rounded((maximum[axis] - minimum[axis]) * mm_per_unit)
            for axis in range(3)
        ]
        center_mm = [
            _rounded(((maximum[axis] + minimum[axis]) * 0.5) * mm_per_unit)
            for axis in range(3)
        ]
        _require(
            all(dimension > 0 for dimension in dimensions_mm),
            f"{obj.name}: evaluated mesh lacks three-dimensional extent",
        )

        observation = {
            "bounds_center_mm": center_mm,
            "dimensions_mm": dimensions_mm,
            "edge_count": len(evaluated_mesh.edges),
            "material_names": list(materials),
            "name": obj.name,
            "polygon_count": len(evaluated_mesh.polygons),
            "triangle_count": triangle_count,
            "vertex_count": len(evaluated_mesh.vertices),
        }
        if is_printable:
            observation["printable_topology"] = _printable_topology(
                evaluated_mesh, matrix, mm_per_unit
            )
        return observation
    finally:
        evaluated_object.to_mesh_clear()


def _used_materials(mesh_objects: Sequence[Any]) -> Dict[str, Any]:
    materials: Dict[str, Any] = {}
    for obj in mesh_objects:
        for slot in obj.material_slots:
            if slot.material is not None:
                materials[slot.material.name] = slot.material
    return materials


def _fixture_roles(slug: str, objects: Sequence[Any]) -> Dict[str, int]:
    _require(slug in EXPECTED_ROLE_COUNTS, f"no fixture role contract for {slug}")
    counts: Dict[str, int] = {}
    for obj in objects:
        _require(obj.get("builder_role") == "display", f"{obj.name}: invalid builder_role")
        _require(obj.get("print_source") is True, f"{obj.name}: display mesh is not a print source")
        feature = _finite_number(
            obj.get("designed_minimum_feature_mm"),
            f"{obj.name}.designed_minimum_feature_mm",
        )
        _require(feature >= MIN_DESIGNED_FEATURE_MM, f"{obj.name}: designed feature is below 2.0 mm")
        role = obj.get("builder_part")
        _require(isinstance(role, str) and bool(role), f"{obj.name}: missing builder_part")
        counts[role] = counts.get(role, 0) + 1
    _require(counts == EXPECTED_ROLE_COUNTS[slug], f"{slug}: fixture role inventory mismatch")
    return dict(sorted(counts.items()))


def _base_dimension_evidence(
    request: BuildRequest,
    source_objects: Sequence[Any],
    observations: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    base_objects = [obj for obj in source_objects if obj.get("builder_part") == "base"]
    expected = [
        _finite_number(request.spec.base.width_mm, "requested base width"),
        _finite_number(request.spec.base.depth_mm, "requested base depth"),
        _finite_number(request.spec.base.height_mm, "requested base height"),
    ]
    if request.spec.base.preset == "none":
        _require(not base_objects, "base preset none generated a display base")
        _require(expected == [0.0, 0.0, 0.0], "base preset none has nonzero dimensions")
        return {
            "maximum_error_mm": 0.0,
            "observed_dimensions_mm": None,
            "preset": "none",
            "requested_dimensions_mm": expected,
        }

    _require(len(base_objects) == 1, "non-none base preset must generate exactly one base")
    base_object = base_objects[0]
    for field, requested in zip(("width", "depth", "height"), expected):
        declared = _finite_number(
            base_object.get(f"requested_{field}_mm"),
            f"{base_object.name}.requested_{field}_mm",
        )
        _require(
            abs(declared - requested) <= 1e-9,
            f"{base_object.name}: declared requested {field} does not match request",
        )

    observation = next(
        (item for item in observations if item["name"] == base_object.name), None
    )
    _require(observation is not None, "display base has no evaluated observation")
    observed = [
        _finite_number(value, f"{base_object.name}.dimensions_mm[{index}]")
        for index, value in enumerate(observation["dimensions_mm"])
    ]
    errors = [abs(observed[index] - expected[index]) for index in range(3)]
    _require(
        all(error <= BASE_DIMENSION_TOLERANCE_MM for error in errors),
        "display base dimensions differ from the request",
    )
    center = observation["bounds_center_mm"]
    _require(
        abs(float(center[0])) <= BASE_DIMENSION_TOLERANCE_MM
        and abs(float(center[1])) <= BASE_DIMENSION_TOLERANCE_MM
        and abs(float(center[2]) - expected[2] * 0.5)
        <= BASE_DIMENSION_TOLERANCE_MM,
        "display base is not centered on the ground plane",
    )
    return {
        "maximum_error_mm": _rounded(max(errors)),
        "observed_dimensions_mm": observed,
        "preset": request.spec.base.preset,
        "requested_dimensions_mm": expected,
    }


def _assert_materials_are_procedural(materials: Mapping[str, Any]) -> None:
    _require(bool(materials), "scene has no used materials")
    _require(len(materials) <= MAX_MATERIALS, "used material cap exceeded")
    _require(len(bpy.data.materials) <= MAX_MATERIALS, "material datablock cap exceeded")
    for material in materials.values():
        for index, channel in enumerate(material.diffuse_color):
            _finite_number(channel, f"{material.name}.diffuse_color[{index}]")
        if material.use_nodes and material.node_tree is not None:
            for node in material.node_tree.nodes:
                _require(
                    node.bl_idname not in {"ShaderNodeTexEnvironment", "ShaderNodeTexImage"},
                    f"{material.name}: external image texture node is not allowed",
                )

    file_sources = {"FILE", "MOVIE", "SEQUENCE"}
    for image in bpy.data.images:
        _require(image.source not in file_sources, f"external image datablock is not allowed: {image.name}")


def _topology_totals(observations: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    fields = ("edge_count", "polygon_count", "triangle_count", "vertex_count")
    return {field: sum(int(item[field]) for item in observations) for field in fields}


def _geometry_payload(
    observations: Sequence[Mapping[str, Any]], printable_name: str, printable_dimensions: Sequence[float]
) -> Dict[str, Any]:
    """Build a name-, palette-, and material-independent shape signature."""

    height = float(printable_dimensions[2])
    _require(height > 0, "printable height must be positive")
    printable = next(item for item in observations if item["name"] == printable_name)
    printable_center = [float(value) for value in printable["bounds_center_mm"]]

    shapes: List[Dict[str, Any]] = []
    for item in observations:
        dimensions = [
            _rounded(float(value) / height) for value in item["dimensions_mm"]
        ]
        center = [
            _rounded((float(item["bounds_center_mm"][axis]) - printable_center[axis]) / height)
            for axis in range(3)
        ]
        shapes.append(
            {
                "center_over_height": center,
                "dimensions_over_height": dimensions,
                "edge_count": int(item["edge_count"]),
                "is_printable": item["name"] == printable_name,
                "polygon_count": int(item["polygon_count"]),
                "triangle_count": int(item["triangle_count"]),
                "vertex_count": int(item["vertex_count"]),
            }
        )
    shapes.sort(key=lambda item: canonical_json_bytes(item))
    return {
        "normalized_mesh_shapes": shapes,
        "topology_totals": _topology_totals(observations),
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one in-Blender G2 structural probe")
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(argv)


def _script_args() -> Sequence[str]:
    try:
        boundary = sys.argv.index("--")
    except ValueError as exc:
        raise ProbeFailure("Blender invocation is missing the '--' script-argument boundary") from exc
    return sys.argv[boundary + 1 :]


def _scene_identity_snapshot(scene: Any) -> Dict[str, Any]:
    return {
        "child_collections": sorted(
            (collection.name, collection.as_pointer())
            for collection in scene.collection.children
        ),
        "materials": sorted(
            (material.name, material.as_pointer()) for material in bpy.data.materials
        ),
        "objects": sorted(
            (
                obj.name,
                obj.as_pointer(),
                obj.type,
                tuple(tuple(float(value) for value in row) for row in obj.matrix_world),
            )
            for obj in scene.objects
        ),
        "scene": scene.as_pointer(),
        "world": scene.world.as_pointer() if scene.world is not None else 0,
    }


def _semantic_rejection_preflight(request: BuildRequest) -> None:
    impossible_mapping = _json_value(request.to_dict())
    impossible_mapping["spec"]["height_mm"] = 25
    impossible_mapping["spec"]["base"] = {
        "depth_mm": 25,
        "height_mm": 25,
        "preset": "round",
        "width_mm": 25,
    }
    impossible = BuildRequest.from_mapping(impossible_mapping)

    scene = bpy.context.scene
    sentinel_name = "G2_Semantic_Rejection_Sentinel"
    _require(bpy.data.objects.get(sentinel_name) is None, "preflight sentinel already exists")
    sentinel = bpy.data.objects.new(sentinel_name, None)
    sentinel["g2_preflight_sentinel"] = True
    scene.collection.objects.link(sentinel)
    before = _scene_identity_snapshot(scene)
    try:
        generate_character(impossible)
    except ValueError:
        pass
    else:
        raise ProbeFailure("semantically impossible request was not rejected")

    _require(
        bpy.context.scene.as_pointer() == before["scene"],
        "semantic rejection replaced the active scene",
    )
    _require(
        _scene_identity_snapshot(bpy.context.scene) == before,
        "semantic rejection mutated scene data",
    )
    retained = bpy.data.objects.get(sentinel_name)
    _require(retained is not None, "semantic rejection removed the sentinel")
    _require(scene.objects.get(sentinel_name) is retained, "semantic rejection unlinked the sentinel")


def run_probe(request_path: Path) -> Dict[str, Any]:
    _require(
        bpy.app.version_string == BLENDER_VERSION,
        f"probe requires Blender {BLENDER_VERSION}",
    )
    _require(bpy.data.filepath == "", "probe must start without loading a .blend file")
    request = BuildRequest.from_json(request_path.read_bytes())
    _semantic_rejection_preflight(request)
    result = generate_character(request)
    _require(
        bpy.data.objects.get("G2_Semantic_Rejection_Sentinel") is None,
        "valid generation did not factory-reset the preflight sentinel",
    )

    _require(result.generator_id == request.generator, "GenerationResult generator_id mismatch")
    _require(result.request_sha256 == request.request_sha256, "GenerationResult request hash mismatch")
    _require(result.spec_sha256 == request.spec_sha256, "GenerationResult spec hash mismatch")
    _require(
        len(result.collection_names) == len(REQUIRED_COLLECTIONS)
        and set(result.collection_names) == set(REQUIRED_COLLECTIONS),
        "GenerationResult collection inventory mismatch",
    )
    display_names = tuple(result.display_object_names)
    _require(bool(display_names), "GenerationResult has no display objects")
    _require(len(display_names) == len(set(display_names)), "display object names are not unique")
    _require(
        isinstance(result.printable_object_name, str) and bool(result.printable_object_name),
        "GenerationResult printable_object_name is invalid",
    )
    designed_minimum = _finite_number(
        result.designed_minimum_feature_mm, "designed_minimum_feature_mm"
    )
    _require(
        designed_minimum >= MIN_DESIGNED_FEATURE_MM,
        "designed minimum feature is below the 2.0 mm contract",
    )

    scene = bpy.context.scene
    scene_objects = list(scene.objects)
    _require(1 <= len(scene_objects) <= MAX_SCENE_OBJECTS, "scene object cap violated")
    collections = _scene_collections()
    _require(
        set(collections) == set(REQUIRED_COLLECTIONS),
        "scene collection inventory must contain exactly the five required collections",
    )
    _require(
        {collection.name for collection in scene.collection.children}
        == set(REQUIRED_COLLECTIONS),
        "all required collections must be direct scene children",
    )
    _require(
        len(scene.collection.objects) == 0,
        "generated objects may not be linked directly to the scene root",
    )

    source_objects = list(collections["CHARACTER"].all_objects)
    printable_objects = list(collections["PRINT"].all_objects)
    _require(len(printable_objects) == 1, "PRINT must contain exactly one object")
    printable_object = printable_objects[0]
    _require(printable_object.type == "MESH", "printable object is not a mesh")
    _require(
        printable_object.name == result.printable_object_name,
        "PRINT object does not match GenerationResult",
    )
    _require(
        {obj.name for obj in source_objects} == set(display_names),
        "CHARACTER objects do not match GenerationResult display objects",
    )
    _require(
        not ({obj.name for obj in source_objects} & {printable_object.name}),
        "printable object is also linked into CHARACTER",
    )

    _require(
        all(obj.type == "MESH" for obj in source_objects),
        "CHARACTER may contain only declared mesh display objects",
    )
    light_objects = list(collections["LIGHTS"].all_objects)
    camera_objects = list(collections["CAMERAS"].all_objects)
    _require(all(obj.type == "LIGHT" for obj in light_objects), "LIGHTS contains a non-light object")
    _require(all(obj.type == "CAMERA" for obj in camera_objects), "CAMERAS contains a non-camera object")
    if camera_objects:
        _require(scene.camera in camera_objects, "active scene camera is not in CAMERAS")
    else:
        _require(scene.camera is None, "scene camera exists outside CAMERAS")

    fixture_roles = _fixture_roles(request.spec.slug, source_objects)
    _require(printable_object.get("builder_role") == "printable", "printable builder_role is invalid")
    _require(
        printable_object.get("print_source_count") == len(source_objects),
        "printable print_source_count does not match CHARACTER inventory",
    )
    _require(
        abs(_finite_number(printable_object.get("target_height_mm"), "printable target height")
            - _finite_number(request.spec.height_mm, "requested height"))
        <= 1e-9,
        "printable target height property mismatch",
    )

    mesh_objects = sorted(
        (obj for obj in scene_objects if obj.type == "MESH"), key=lambda obj: obj.name
    )
    permitted_meshes = set(source_objects) | set(printable_objects) | set(collections["SET"].all_objects)
    _require(
        all(obj in permitted_meshes for obj in mesh_objects),
        "scene contains a mesh outside CHARACTER, PRINT, or SET",
    )

    scale_length = _finite_number(scene.unit_settings.scale_length, "scene unit scale")
    _require(scale_length > 0, "scene unit scale must be positive")
    mm_per_unit = scale_length * 1000.0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    observations = [
        _mesh_observation(
            obj,
            depsgraph,
            mm_per_unit,
            obj.name == result.printable_object_name,
        )
        for obj in mesh_objects
    ]
    base_dimensions = _base_dimension_evidence(request, source_objects, observations)
    totals = _topology_totals(observations)
    _require(
        MIN_EVALUATED_TRIANGLES <= totals["triangle_count"] <= MAX_EVALUATED_TRIANGLES,
        "evaluated triangle cap violated",
    )

    used_materials = _used_materials(mesh_objects)
    _assert_materials_are_procedural(used_materials)
    printable_observation = next(
        item for item in observations if item["name"] == result.printable_object_name
    )
    printable_dimensions = printable_observation["dimensions_mm"]
    _require(
        min(float(value) for value in printable_dimensions) >= MIN_DESIGNED_FEATURE_MM,
        "printable bounds are flat or below the minimum feature contract",
    )
    requested_height = _finite_number(request.spec.height_mm, "requested height")
    observed_height = float(printable_dimensions[2])
    tolerance = max(0.2, abs(requested_height) * 0.005)
    _require(
        abs(observed_height - requested_height) <= tolerance,
        "printable height is outside max(0.2 mm, 0.5%) tolerance",
    )

    engine_report = _json_value(structural_report(request, result))
    _require(isinstance(engine_report, dict), "structural_report must return a mapping")
    fingerprint = engine_report.get("fingerprint_sha256")
    _require(
        isinstance(fingerprint, str) and SHA256.fullmatch(fingerprint) is not None,
        "structural_report fingerprint_sha256 is missing or invalid",
    )
    fingerprint_payload = dict(engine_report)
    del fingerprint_payload["fingerprint_sha256"]
    _require(
        canonical_sha256(fingerprint_payload) == fingerprint,
        "structural_report fingerprint does not match its canonical payload",
    )
    report_topology = engine_report.get("printable", {}).get("topology", {})
    _require(
        report_topology.get("connected_shells") == 1
        and report_topology.get("boundary_edges") == 0
        and report_topology.get("non_manifold_edges") == 0
        and report_topology.get("zero_area_faces") == 0
        and report_topology.get("finite_coordinates") is True
        and report_topology.get("positive_volume") is True
        and isinstance(report_topology.get("signed_volume_mm3"), (int, float))
        and not isinstance(report_topology.get("signed_volume_mm3"), bool)
        and report_topology.get("signed_volume_mm3") > 0,
        "structural report printable topology does not prove one closed positive shell",
    )

    character_observations = [
        item
        for item in observations
        if item["name"] in (set(display_names) | {result.printable_object_name})
    ]
    geometry_payload = _geometry_payload(
        character_observations, result.printable_object_name, printable_dimensions
    )
    stable = {
        "base_dimensions": base_dimensions,
        "character_topology_totals": _topology_totals(character_observations),
        "engine_report": engine_report,
        "fixture_role_counts": fixture_roles,
        "geometry_signature_sha256": canonical_sha256(geometry_payload),
        "material_assignments": [
            {
                "material_names": item["material_names"],
                "object_name": item["name"],
            }
            for item in observations
        ],
        "mesh_inventory": observations,
        "object_count": len(scene_objects),
        "request_sha256": request.request_sha256,
        "spec_sha256": request.spec_sha256,
        "topology_totals": totals,
        "used_material_count": len(used_materials),
    }
    evidence = {
        "blender_version": bpy.app.version_string,
        "checks": {
            "caps": True,
            "finite_nonempty_actual_meshes": True,
            "height_tolerance_mm": _rounded(tolerance),
            "observed_height_mm": _rounded(observed_height),
            "one_printable_object": True,
            "printable_topology": True,
            "requested_height_mm": _rounded(requested_height),
            "required_collections": list(REQUIRED_COLLECTIONS),
            "semantic_rejection_before_scene_creation": True,
        },
        "example_slug": request.spec.slug,
        "gate_version": GATE_VERSION,
        "stable": stable,
        "status": "passed",
    }
    _assert_path_free(evidence)
    return evidence


def main() -> int:
    args = _parse_args(_script_args())
    evidence = run_probe(Path(args.request))
    result_path = Path(args.result)
    result_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print("G2_INNER_PROBE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
