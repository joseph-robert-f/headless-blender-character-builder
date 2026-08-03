"""Private second-process verifier for saved and exported model artifacts."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.character_spec import BuildRequest
from shared.json_contract import canonical_json_bytes, decode_json_document

from blender.core.fingerprint import structural_report
from blender.exporters.model import inspect_binary_stl
from blender.generators.types import GenerationResult
from blender.qa.geometry import analyze_mesh_object


VERIFICATION_VERSION = "artifact-verifier/v1"
EXPECTED_FIELDS = {
    "dimensions_mm",
    "generation_result",
    "request",
    "structural_fingerprint_sha256",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _within_tolerance(expected: Iterable[float], observed: Iterable[float]) -> bool:
    for baseline, actual in zip(expected, observed):
        tolerance = max(0.2, abs(float(baseline)) * 0.005)
        if abs(float(actual) - float(baseline)) > tolerance:
            return False
    return True


def _combined_dimensions_mm(objects: Iterable[bpy.types.Object]) -> list[float]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    found = False
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            for vertex in mesh.vertices:
                found = True
                world = evaluated.matrix_world @ vertex.co
                for axis in range(3):
                    coordinate = float(world[axis])
                    _require(math.isfinite(coordinate), "reimport contains non-finite geometry")
                    minimum[axis] = min(minimum[axis], coordinate)
                    maximum[axis] = max(maximum[axis], coordinate)
        finally:
            evaluated.to_mesh_clear()
    _require(found, "reimport contains no mesh vertices")
    return [round((maximum[axis] - minimum[axis]) * 1000.0, 4) for axis in range(3)]


def _load_expected(path: Path) -> tuple[dict[str, Any], BuildRequest, GenerationResult]:
    payload = decode_json_document(path.read_bytes(), max_bytes=64 * 1024)
    _require(isinstance(payload, dict) and set(payload) == EXPECTED_FIELDS, "invalid verifier expectation fields")
    request = BuildRequest.from_mapping(payload["request"])
    raw_result = payload["generation_result"]
    _require(isinstance(raw_result, dict), "invalid verifier generation result")
    required_result = {
        "collection_names",
        "designed_minimum_feature_mm",
        "display_object_names",
        "generator_id",
        "printable_object_name",
        "request_sha256",
        "spec_sha256",
        "voxel_size_mm",
    }
    _require(set(raw_result) == required_result, "invalid verifier result fields")
    result = GenerationResult(
        generator_id=str(raw_result["generator_id"]),
        display_object_names=tuple(raw_result["display_object_names"]),
        printable_object_name=str(raw_result["printable_object_name"]),
        designed_minimum_feature_mm=float(raw_result["designed_minimum_feature_mm"]),
        voxel_size_mm=float(raw_result["voxel_size_mm"]),
        request_sha256=str(raw_result["request_sha256"]),
        spec_sha256=str(raw_result["spec_sha256"]),
        collection_names=tuple(raw_result["collection_names"]),
    )
    _require(result.request_sha256 == request.request_sha256, "verifier request hash mismatch")
    return payload, request, result


def _verify_saved_blend(
    blend_path: Path,
    expected: dict[str, Any],
    request: BuildRequest,
    result: GenerationResult,
) -> dict[str, Any]:
    operation = bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    _require("FINISHED" in operation, "model.blend fresh reload failed")
    _require(bpy.context.scene.render.filepath.startswith("//"), "saved render path is not relative")
    _require(not bpy.data.libraries, "saved scene contains an external Blender library")
    for image in bpy.data.images:
        _require(
            not image.filepath or image.filepath.startswith("//"),
            "saved scene contains an external image path",
        )
    printable = bpy.data.objects.get(result.printable_object_name)
    _require(printable is not None and printable.type == "MESH", "saved PrintableShell is missing")
    for name in result.display_object_names:
        obj = bpy.data.objects.get(name)
        _require(obj is not None and obj.type == "MESH", f"saved display mesh is missing: {name}")
    topology = analyze_mesh_object(printable)
    _require(topology["connected_shells"] == 1, "saved PrintableShell is disconnected")
    _require(topology["non_manifold_edges"] == 0, "saved PrintableShell is non-manifold")
    _require(topology["non_manifold_vertices"] == 0, "saved PrintableShell has a non-manifold vertex")
    _require(topology["zero_area_faces"] == 0, "saved PrintableShell has zero-area faces")
    _require(topology["finite_geometry"] is True, "saved PrintableShell is non-finite")
    _require(topology["outward_normals"] is True, "saved PrintableShell normals are not outward")
    _require(topology["positive_volume"] is True, "saved PrintableShell volume is not positive")
    _require(
        _within_tolerance(expected["dimensions_mm"], topology["dimensions_mm"]),
        "saved PrintableShell dimensions changed",
    )
    report = structural_report(request, result)
    _require(
        report["fingerprint_sha256"] == expected["structural_fingerprint_sha256"],
        "saved scene structural fingerprint changed",
    )
    return {"dimensions_mm": topology["dimensions_mm"], "topology": topology}


def _verify_glb(glb_path: Path, expected_dimensions: list[float]) -> dict[str, Any]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    operation = bpy.ops.import_scene.gltf(filepath=str(glb_path))
    _require("FINISHED" in operation, "model.glb import failed")
    meshes = tuple(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    _require(bool(meshes), "model.glb contains no meshes")
    _require(
        all(obj.name != "PrintableShell" for obj in meshes),
        "model.glb incorrectly contains PrintableShell",
    )
    _require(not bpy.data.images, "model.glb contains unexpected image textures")
    dimensions = _combined_dimensions_mm(meshes)
    _require(
        _within_tolerance(expected_dimensions, dimensions),
        "model.glb dimensions exceed reimport tolerance",
    )
    return {"dimensions_mm": dimensions, "mesh_object_count": len(meshes)}


def _verify_stl(stl_path: Path, expected_dimensions: list[float]) -> dict[str, Any]:
    raw = inspect_binary_stl(stl_path)
    _require(
        _within_tolerance(expected_dimensions, raw["dimensions_mm"]),
        "raw-mm STL dimensions exceed tolerance",
    )
    bpy.ops.wm.read_factory_settings(use_empty=True)
    operation = bpy.ops.wm.stl_import(
        filepath=str(stl_path),
        global_scale=0.001,
        use_scene_unit=False,
        forward_axis="Y",
        up_axis="Z",
    )
    _require("FINISHED" in operation, "model.stl import failed")
    meshes = tuple(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
    _require(len(meshes) == 1, "model.stl must import as exactly one mesh")
    topology = analyze_mesh_object(meshes[0])
    _require(topology["connected_shells"] == 1, "reimported STL is disconnected")
    _require(topology["non_manifold_edges"] == 0, "reimported STL is non-manifold")
    _require(topology["non_manifold_vertices"] == 0, "reimported STL has a non-manifold vertex")
    _require(topology["zero_area_faces"] == 0, "reimported STL has zero-area faces")
    _require(topology["finite_geometry"] is True, "reimported STL is non-finite")
    _require(topology["outward_normals"] is True, "reimported STL normals are not outward")
    _require(topology["positive_volume"] is True, "reimported STL volume is not positive")
    _require(
        _within_tolerance(expected_dimensions, topology["dimensions_mm"]),
        "reimported STL dimensions exceed tolerance",
    )
    return {
        "dimensions_mm": topology["dimensions_mm"],
        "raw_dimensions_mm": raw["dimensions_mm"],
        "triangle_count": raw["triangle_count"],
        "topology": topology,
    }


def verify_artifacts(
    blend_path: Path,
    glb_path: Path,
    stl_path: Path,
    expected_path: Path,
) -> dict[str, Any]:
    """Fresh-load and independently reimport the three model formats."""

    for path in (blend_path, glb_path, stl_path, expected_path):
        _require(path.is_file() and path.stat().st_size > 0, f"missing verifier input: {path.name}")
    expected, request, result = _load_expected(expected_path)
    dimensions = [float(value) for value in expected["dimensions_mm"]]
    saved = _verify_saved_blend(blend_path, expected, request, result)
    glb = _verify_glb(glb_path, dimensions)
    stl = _verify_stl(stl_path, dimensions)
    return {
        "verification_version": VERIFICATION_VERSION,
        "fresh_reload": True,
        "glb_reimport": True,
        "stl_reimport": True,
        "blend": saved,
        "glb": glb,
        "stl": stl,
    }


def _script_args() -> Sequence[str]:
    try:
        boundary = sys.argv.index("--")
    except ValueError as exc:
        raise RuntimeError("verifier requires the Blender '--' boundary") from exc
    return sys.argv[boundary + 1 :]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify private Blender artifacts")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--stl", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(_script_args())
    result_path = Path(args.result)
    _require(not result_path.exists(), "refusing to overwrite verifier evidence")
    evidence = verify_artifacts(
        Path(args.blend),
        Path(args.glb),
        Path(args.stl),
        Path(args.expected),
    )
    result_path.write_bytes(canonical_json_bytes(evidence) + b"\n")
    print("ARTIFACT_VERIFIER: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
