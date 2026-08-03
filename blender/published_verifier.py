"""Fresh-process verification for a published complete-v1 artifact set.

This module is intentionally read-only with respect to the published artifact
directory.  The trusted outer launcher supplies fixed paths after Blender's
``--`` boundary and places ``--result`` in private scratch space.  Verification
loads the saved scene, then resets Blender before independently importing GLB
and STL so one format cannot lend state to another.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import bpy


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blender.exporters.model import inspect_binary_stl
from blender.qa.geometry import analyze_mesh_object
from shared.build_manifest import BuildManifest, REQUIRED_ARTIFACTS
from shared.character_spec import BuildRequest
from shared.json_contract import canonical_json_bytes
from shared.quality_report import QualityReport


BLENDER_VERSION = "4.5.12 LTS"
VERIFICATION_VERSION = "published-artifact-verifier/v1"
EXPECTED_COLLECTIONS = {"CAMERAS", "CHARACTER", "LIGHTS", "PRINT", "SET"}
EXPECTED_CAMERAS = {"Camera_Back", "Camera_Front", "Camera_Preview", "Camera_Side"}
EXPECTED_LIGHTS = {"Light_Fill", "Light_Key", "Light_Rim"}
MAX_OBJECTS = 256
MAX_MATERIALS = 64
MAX_TRIANGLES = 500_000
MAX_CONTRACT_BYTES = 4 * 1024 * 1024
EXACT_OUTPUT_TREE = set(REQUIRED_ARTIFACTS) | {"manifest.json"}


class PublishedVerificationFailure(RuntimeError):
    """A stable artifact-verification failure that maps to application exit 11."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublishedVerificationFailure(message)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_read(path: Path, maximum: int = MAX_CONTRACT_BYTES) -> bytes:
    with path.open("rb") as stream:
        payload = stream.read(maximum + 1)
    _require(len(payload) <= maximum, "published JSON exceeds its verification limit")
    return payload


def _resolved_file(raw: str, expected_name: str | None = None) -> Path:
    try:
        supplied = Path(raw)
        _require(not supplied.is_symlink(), "verifier input cannot be a symbolic link")
        path = supplied.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PublishedVerificationFailure("required verifier input is unavailable") from exc
    _require(path.is_file() and not path.is_symlink(), "verifier input must be a regular file")
    _require(path.stat().st_size > 0, "verifier input must be nonempty")
    if expected_name is not None:
        _require(path.name == expected_name, "verifier input has an unexpected artifact name")
    return path


def _within_tolerance(expected: Iterable[Any], observed: Iterable[Any]) -> bool:
    expected_values = tuple(float(value) for value in expected)
    observed_values = tuple(float(value) for value in observed)
    if len(expected_values) != 3 or len(observed_values) != 3:
        return False
    return all(
        abs(actual - baseline) <= max(0.2, abs(baseline) * 0.005)
        for baseline, actual in zip(expected_values, observed_values)
    )


def _combined_dimensions_mm(objects: Iterable[bpy.types.Object]) -> list[float]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    minimum = [math.inf, math.inf, math.inf]
    maximum = [-math.inf, -math.inf, -math.inf]
    found = False
    for obj in objects:
        _require(obj.type == "MESH", "dimension inventory contains a non-mesh object")
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            for vertex in mesh.vertices:
                found = True
                coordinate = evaluated.matrix_world @ vertex.co
                for axis in range(3):
                    value = float(coordinate[axis])
                    _require(math.isfinite(value), "geometry contains a non-finite coordinate")
                    minimum[axis] = min(minimum[axis], value)
                    maximum[axis] = max(maximum[axis], value)
        finally:
            evaluated.to_mesh_clear()
    _require(found, "geometry contains no mesh vertices")
    dimensions = [round((maximum[index] - minimum[index]) * 1000.0, 4) for index in range(3)]
    _require(all(value > 0.0 for value in dimensions), "geometry has flat or empty bounds")
    return dimensions


def _validate_mesh_inventory(
    objects: Iterable[bpy.types.Object], *, require_materials: bool
) -> int:
    total_triangles = 0
    found = False
    for obj in objects:
        found = True
        _require(obj.type == "MESH" and obj.data is not None, "expected a real mesh object")
        _require(bool(obj.data.vertices) and bool(obj.data.polygons), "mesh object is empty")
        _require(
            all(math.isfinite(float(value)) for row in obj.matrix_world for value in row),
            "mesh transform contains a non-finite value",
        )
        if require_materials:
            _require(
                any(slot.material is not None for slot in obj.material_slots),
                "display mesh has no material",
            )
        evidence = analyze_mesh_object(obj)
        _require(evidence["finite_geometry"] is True, "mesh geometry is non-finite")
        _require(int(evidence["vertices"]) > 0, "mesh contains no vertices")
        _require(int(evidence["faces"]) > 0, "mesh contains no faces")
        _require(int(evidence["triangles"]) > 0, "mesh contains no triangles")
        total_triangles += int(evidence["triangles"])
    _require(found, "mesh inventory is empty")
    _require(4 <= total_triangles <= MAX_TRIANGLES, "mesh triangle budget is invalid")
    return total_triangles


def _require_watertight(topology: Mapping[str, Any], label: str) -> None:
    _require(int(topology["connected_shells"]) == 1, f"{label} is not one connected shell")
    _require(int(topology["non_manifold_edges"]) == 0, f"{label} has non-manifold edges")
    _require(
        int(topology["non_manifold_vertices"]) == 0,
        f"{label} has non-manifold vertices",
    )
    _require(int(topology["zero_area_faces"]) == 0, f"{label} has zero-area faces")
    _require(topology["finite_geometry"] is True, f"{label} has non-finite geometry")
    _require(topology["outward_normals"] is True, f"{label} normals are not outward")
    _require(topology["positive_volume"] is True, f"{label} has no positive volume")


def _require_no_embedded_or_external_content() -> None:
    _require(not bpy.data.libraries, "scene contains an external Blender library")
    _require(not bpy.data.texts, "scene contains a text block")
    _require(not bpy.data.images, "scene or import contains an image")
    for attribute in ("cache_files", "movieclips", "sounds", "volumes"):
        collection = getattr(bpy.data, attribute, ())
        _require(not collection, f"scene contains forbidden {attribute}")


def _require_no_drivers() -> None:
    collections = (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.worlds,
        bpy.data.scenes,
    )
    for collection in collections:
        for datablock in collection:
            animation = getattr(datablock, "animation_data", None)
            _require(
                animation is None or not animation.drivers,
                "scene contains a scripted driver",
            )


def _verify_tree(
    root: Path,
    request: BuildRequest,
    manifest: BuildManifest,
    manifest_payload: bytes,
) -> QualityReport:
    actual_files = set()
    for path in root.rglob("*"):
        _require(not path.is_symlink(), "published artifact tree contains a symbolic link")
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
        elif path.is_dir():
            _require(
                path.relative_to(root).as_posix() == "diagnostics",
                "published artifact tree contains an unexpected directory",
            )
        else:
            raise PublishedVerificationFailure("published artifact tree contains a special file")
    _require(actual_files == EXACT_OUTPUT_TREE, "published artifact tree is not complete-v1")
    _require(
        manifest_payload == manifest.canonical_bytes + b"\n",
        "manifest.json is not canonical",
    )
    _require(manifest.request_sha256 == request.request_sha256, "manifest request hash mismatch")
    _require(manifest.spec_sha256 == request.spec_sha256, "manifest spec hash mismatch")

    for relative_name in REQUIRED_ARTIFACTS:
        path = root / relative_name
        entry = manifest.artifacts[relative_name]
        _require(path.stat().st_size == int(entry["bytes"]), "artifact byte count mismatch")
        _require(_hash_file(path) == entry["sha256"], "artifact SHA-256 mismatch")

    qa_payload = _bounded_read(root / "qa.json")
    qa = QualityReport.from_json(qa_payload)
    _require(qa_payload == qa.canonical_bytes + b"\n", "qa.json is not canonical")
    _require(qa.status == "passed", "published QA status is not passed")
    _require(
        tuple(qa.measurements["dimensions_mm"] or ()) == tuple(manifest.dimensions_mm),
        "manifest and QA dimensions disagree",
    )
    _require(manifest.qa["status"] == qa.status, "manifest and QA status disagree")
    _require(manifest.qa["manifold"] == qa.checks["manifold"], "manifest manifold summary mismatch")
    _require(
        manifest.qa["non_manifold_edges"] == qa.measurements["non_manifold_edges"],
        "manifest topology summary mismatch",
    )
    _require(
        manifest.qa["connected_shells"] == qa.measurements["connected_shells"],
        "manifest shell summary mismatch",
    )
    _require(
        manifest.qa["positive_volume"] == qa.checks["positive_volume"],
        "manifest volume summary mismatch",
    )
    for field in ("fresh_reload", "glb_reimport", "stl_reimport"):
        _require(manifest.qa[field] == qa.checks[field], "manifest reimport summary mismatch")
    return qa


def _verify_blend(
    blend_path: Path,
    request: BuildRequest,
    manifest: BuildManifest,
    qa: QualityReport,
) -> Mapping[str, Any]:
    operation = bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    _require("FINISHED" in operation, "model.blend did not load")
    _require(Path(bpy.data.filepath).resolve() == blend_path, "unexpected blend file is loaded")
    _require(bpy.context.scene.name == "BuilderScene", "saved scene has an unexpected name")
    _require(bpy.context.scene.render.filepath == "//preview.png", "saved render path is not fixed and relative")
    _require(bpy.context.scene.unit_settings.system == "METRIC", "saved scene is not metric")
    _require_no_embedded_or_external_content()
    _require_no_drivers()

    scene_root = bpy.context.scene.collection
    _require(
        {collection.name for collection in scene_root.children} == EXPECTED_COLLECTIONS,
        "saved scene collection inventory differs from complete-v1",
    )
    _require(
        all(not collection.children for collection in scene_root.children),
        "saved scene contains nested collections",
    )
    character = bpy.data.collections.get("CHARACTER")
    printable_collection = bpy.data.collections.get("PRINT")
    cameras_collection = bpy.data.collections.get("CAMERAS")
    lights_collection = bpy.data.collections.get("LIGHTS")
    set_collection = bpy.data.collections.get("SET")
    _require(all(item is not None for item in (character, printable_collection, cameras_collection, lights_collection, set_collection)), "saved scene is missing a required collection")
    assert character is not None
    assert printable_collection is not None
    assert cameras_collection is not None
    assert lights_collection is not None
    assert set_collection is not None

    display_meshes = tuple(character.objects)
    _require(display_meshes and all(obj.type == "MESH" for obj in display_meshes), "CHARACTER must contain only display meshes")
    _require(not set_collection.objects, "SET collection must be empty in v0.1")
    _require(
        {obj.name for obj in cameras_collection.objects} == EXPECTED_CAMERAS
        and all(obj.type == "CAMERA" for obj in cameras_collection.objects),
        "saved camera inventory differs from diagnostic-v1",
    )
    _require(
        {obj.name for obj in lights_collection.objects} == EXPECTED_LIGHTS
        and all(obj.type == "LIGHT" for obj in lights_collection.objects),
        "saved light inventory differs from diagnostic-v1",
    )
    _require(len(printable_collection.objects) == 1, "PRINT must contain exactly one object")
    printable = printable_collection.objects[0]
    _require(
        printable.name == "PrintableShell"
        and printable.type == "MESH"
        and printable.get("builder_role") == "printable",
        "PRINT does not contain the expected PrintableShell",
    )
    _require(printable.hide_render is True, "PrintableShell must be hidden from display renders")

    scene_meshes = {obj.name for obj in bpy.context.scene.objects if obj.type == "MESH"}
    expected_meshes = {obj.name for obj in display_meshes} | {"PrintableShell"}
    _require(scene_meshes == expected_meshes, "saved scene has an unexpected mesh inventory")
    _require(1 <= len(bpy.context.scene.objects) <= MAX_OBJECTS, "saved object budget is invalid")
    _require(1 <= len(bpy.data.materials) <= MAX_MATERIALS, "saved material budget is invalid")
    display_triangles = _validate_mesh_inventory(display_meshes, require_materials=True)
    display_dimensions = _combined_dimensions_mm(display_meshes)

    printable_topology = analyze_mesh_object(printable)
    _require_watertight(printable_topology, "saved PrintableShell")
    expected_printable = qa.measurements["dimensions_mm"]
    expected_display = qa.measurements["glb_dimensions_mm"]
    _require(expected_printable is not None and expected_display is not None, "QA dimensions are unresolved")
    _require(
        _within_tolerance(expected_printable, printable_topology["dimensions_mm"]),
        "saved PrintableShell dimensions changed",
    )
    _require(
        _within_tolerance(manifest.dimensions_mm, printable_topology["dimensions_mm"]),
        "saved PrintableShell differs from manifest dimensions",
    )
    _require(
        _within_tolerance(expected_display, display_dimensions),
        "saved display dimensions differ from QA",
    )
    requested_height = (Decimal(request.spec.height_mm),)
    _require(
        abs(float(printable_topology["dimensions_mm"][2]) - float(requested_height[0]))
        <= max(0.2, float(requested_height[0]) * 0.005),
        "saved PrintableShell height differs from request",
    )
    return {
        "dimensions_mm": printable_topology["dimensions_mm"],
        "display_dimensions_mm": display_dimensions,
        "display_mesh_count": len(display_meshes),
        "display_triangle_count": display_triangles,
        "printable_triangle_count": int(printable_topology["triangles"]),
    }


def _verify_glb(glb_path: Path, qa: QualityReport) -> Mapping[str, Any]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    operation = bpy.ops.import_scene.gltf(filepath=str(glb_path))
    _require("FINISHED" in operation, "model.glb did not import")
    _require_no_embedded_or_external_content()
    _require_no_drivers()
    objects = tuple(bpy.context.scene.objects)
    meshes = tuple(obj for obj in objects if obj.type == "MESH")
    _require(meshes and len(meshes) == len(objects), "GLB must contain only nonempty display meshes")
    _require(all(obj.name != "PrintableShell" for obj in meshes), "GLB contains PrintableShell")
    _require(1 <= len(meshes) <= MAX_OBJECTS, "GLB object budget is invalid")
    _require(1 <= len(bpy.data.materials) <= MAX_MATERIALS, "GLB material budget is invalid")
    triangles = _validate_mesh_inventory(meshes, require_materials=True)
    dimensions = _combined_dimensions_mm(meshes)
    expected = qa.measurements["glb_dimensions_mm"]
    _require(expected is not None and _within_tolerance(expected, dimensions), "GLB dimensions differ from QA")
    return {
        "dimensions_mm": dimensions,
        "mesh_count": len(meshes),
        "triangle_count": triangles,
    }


def _verify_stl(stl_path: Path, qa: QualityReport) -> Mapping[str, Any]:
    raw = inspect_binary_stl(stl_path)
    expected = qa.measurements["stl_dimensions_mm"]
    _require(expected is not None, "QA STL dimensions are unresolved")
    _require(_within_tolerance(expected, raw["dimensions_mm"]), "binary STL dimensions differ from QA")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    operation = bpy.ops.wm.stl_import(
        filepath=str(stl_path),
        global_scale=0.001,
        use_scene_unit=False,
        forward_axis="Y",
        up_axis="Z",
    )
    _require("FINISHED" in operation, "model.stl did not import")
    _require_no_embedded_or_external_content()
    _require_no_drivers()
    objects = tuple(bpy.context.scene.objects)
    meshes = tuple(obj for obj in objects if obj.type == "MESH")
    _require(len(objects) == 1 and len(meshes) == 1, "STL must import as exactly one mesh")
    topology = analyze_mesh_object(meshes[0])
    _require_watertight(topology, "reimported STL")
    _require(_within_tolerance(expected, topology["dimensions_mm"]), "reimported STL dimensions differ from QA")
    _require(
        _within_tolerance(raw["dimensions_mm"], topology["dimensions_mm"]),
        "binary and reimported STL dimensions disagree",
    )
    return {
        "dimensions_mm": topology["dimensions_mm"],
        "triangle_count": int(topology["triangles"]),
    }


def verify(
    blend_path: Path,
    glb_path: Path,
    stl_path: Path,
    request_path: Path,
    manifest_path: Path,
) -> Mapping[str, Any]:
    _require(bpy.app.version_string == BLENDER_VERSION, "verifier Blender version mismatch")
    root = manifest_path.parent
    _require(root.is_dir() and not root.is_symlink(), "published artifact root is invalid")
    _require(blend_path == root / "model.blend", "blend path is outside the published artifact set")
    _require(glb_path == root / "model.glb", "GLB path is outside the published artifact set")
    _require(stl_path == root / "model.stl", "STL path is outside the published artifact set")

    request = BuildRequest.from_json(_bounded_read(request_path, 64 * 1024))
    manifest_payload = _bounded_read(manifest_path)
    manifest = BuildManifest.from_json(manifest_payload)
    _require(
        manifest.execution["blender_version"] == bpy.app.version_string,
        "manifest Blender version differs from verifier runtime",
    )
    _require(
        manifest.execution["blender_binary_sha256"] == _hash_file(Path(bpy.app.binary_path)),
        "manifest Blender binary hash differs from verifier runtime",
    )
    qa = _verify_tree(root, request, manifest, manifest_payload)
    blend = _verify_blend(blend_path, request, manifest, qa)
    glb = _verify_glb(glb_path, qa)
    stl = _verify_stl(stl_path, qa)
    return {
        "checks": {
            "artifact_hashes": True,
            "blend_fresh_reload": True,
            "glb_clean_reimport": True,
            "no_embedded_or_external_content": True,
            "stl_clean_reimport": True,
        },
        "dimensions_mm": {
            "blend_printable": blend["dimensions_mm"],
            "glb_display": glb["dimensions_mm"],
            "stl_printable": stl["dimensions_mm"],
        },
        "request_sha256": request.request_sha256,
        "spec_sha256": request.spec_sha256,
        "status": "passed",
        "verification_version": VERIFICATION_VERSION,
    }


def _atomic_write(path: Path, payload: bytes) -> None:
    _require(not path.exists(), "verifier result already exists")
    _require(path.parent.is_dir(), "verifier result parent does not exist")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _script_args() -> Sequence[str]:
    try:
        boundary = sys.argv.index("--")
    except ValueError as exc:
        raise PublishedVerificationFailure("missing Blender '--' script-argument boundary") from exc
    return sys.argv[boundary + 1 :]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify one published complete-v1 artifact set")
    parser.add_argument("--blend", required=True)
    parser.add_argument("--glb", required=True)
    parser.add_argument("--stl", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(_script_args())
    blend_path = _resolved_file(args.blend, "model.blend")
    glb_path = _resolved_file(args.glb, "model.glb")
    stl_path = _resolved_file(args.stl, "model.stl")
    request_path = _resolved_file(args.request)
    manifest_path = _resolved_file(args.manifest, "manifest.json")
    result_path = Path(args.result).resolve(strict=False)
    evidence = verify(blend_path, glb_path, stl_path, request_path, manifest_path)
    _atomic_write(result_path, canonical_json_bytes(evidence) + b"\n")
    print("PUBLISHED_ARTIFACT_VERIFIER: PASS")
    return 0


def _entrypoint() -> None:
    try:
        exit_code = main()
    except PublishedVerificationFailure as exc:
        print(f"PUBLISHED_ARTIFACT_VERIFIER: FAIL: {exc}", file=sys.stderr)
        exit_code = 11
    except Exception as exc:
        print(
            f"PUBLISHED_ARTIFACT_VERIFIER: FAIL: unexpected {type(exc).__name__}",
            file=sys.stderr,
        )
        exit_code = 11
    if exit_code:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)


if __name__ == "__main__":
    _entrypoint()
