"""Independent verification of a finished build.

This runs in a *fresh* Blender process that did not build the model. That is
the whole point: a builder can convince itself its in-memory scene is fine, but
only a second process reading the published files can prove the files are.

Three things are checked:

* every artifact still hashes to what the manifest recorded;
* `model.blend` reopens and contains the model the manifest describes;
* `model.stl` and `model.glb` re-import to the same size and, for the STL, the
  same watertight topology -- which is what actually reaches the slicer.
"""

import json
import os

import bmesh
import bpy

from hbcb import layout
from hbcb import manifest as manifest_module
from hbcb.exit_codes import FILESYSTEM, VERIFY_FAILED, BuildError

from . import compat, scene

# The manifest and a re-import may differ by float rounding in the file format.
# Matches the tolerance stated in the spec docs: the greater of 0.2 mm or 0.5%.
ABSOLUTE_TOLERANCE_MM = 0.2
RELATIVE_TOLERANCE = 0.005


def _tolerance(expected):
    return max(ABSOLUTE_TOLERANCE_MM, abs(expected) * RELATIVE_TOLERANCE)


def _compare_dimensions(label, actual, expected, problems):
    for axis, name in enumerate("xyz"):
        allowed = _tolerance(expected[axis])
        difference = abs(actual[axis] - expected[axis])
        if difference > allowed:
            problems.append(
                "%s: %s axis is %.3f mm, manifest says %.3f mm (off by %.3f mm, "
                "tolerance %.3f mm)"
                % (label, name, actual[axis], expected[axis], difference, allowed)
            )


def _mesh_objects():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _pick_model():
    """The model object in a freshly opened scene."""
    meshes = _mesh_objects()
    if not meshes:
        return None
    named = [obj for obj in meshes if obj.name == "character"]
    if named:
        return named[0]
    # Fall back to whichever mesh has the most geometry.
    return max(meshes, key=lambda obj: len(obj.data.vertices))


def _import_bounds(importer, path, problems, label, scale=1.0):
    """Import a file into an empty scene and return its dimensions in mm."""
    scene.reset("verify-%s" % label)
    before = {obj.name for obj in bpy.context.scene.objects}
    try:
        importer(path)
    except Exception as error:
        problems.append("%s: re-import failed: %s" % (label, error))
        return None, None

    imported = [obj for obj in _mesh_objects() if obj.name not in before]
    if not imported:
        problems.append("%s: re-import produced no mesh" % label)
        return None, None

    target = max(imported, key=lambda obj: len(obj.data.vertices))
    dimensions = [value * scale for value in scene.dimensions_mm(target)]
    return target, dimensions


def _stl_topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    non_manifold = sum(1 for edge in bm.edges if len(edge.link_faces) not in (1, 2))
    triangles = len(bm.faces)
    bm.free()
    return boundary, non_manifold, triangles


def run(output_dir, log=print):
    """Verify the build in `output_dir`. Returns a process exit code."""
    manifest_path = os.path.join(output_dir, layout.MANIFEST)
    if not os.path.isfile(manifest_path):
        raise BuildError(
            FILESYSTEM,
            "no %s in %s; either the build did not finish or this is not a build "
            "directory" % (layout.MANIFEST, output_dir),
        )
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(VERIFY_FAILED, "cannot read the manifest: %s" % error) from error

    problems = []

    log("checking artifact hashes")
    problems.extend(manifest_module.verify_artifacts(output_dir, manifest))

    expected_dimensions = manifest.get("model", {}).get("dimensions_mm")
    if not expected_dimensions:
        problems.append("manifest does not record model dimensions")
        expected_dimensions = None

    blend_path = os.path.join(output_dir, layout.MODEL_BLEND)
    if os.path.isfile(blend_path):
        log("reopening %s in this fresh process" % layout.MODEL_BLEND)
        try:
            bpy.ops.wm.open_mainfile(filepath=blend_path)
        except Exception as error:
            problems.append("%s: failed to reopen: %s" % (layout.MODEL_BLEND, error))
        else:
            model = _pick_model()
            if model is None:
                problems.append("%s: contains no mesh object" % layout.MODEL_BLEND)
            elif expected_dimensions:
                _compare_dimensions(
                    layout.MODEL_BLEND,
                    scene.dimensions_mm(model),
                    expected_dimensions,
                    problems,
                )

    stl_path = os.path.join(output_dir, layout.MODEL_STL)
    if os.path.isfile(stl_path):
        log("re-importing %s" % layout.MODEL_STL)
        target, dimensions = _import_bounds(compat.import_stl, stl_path, problems, layout.MODEL_STL)
        if target is not None:
            if expected_dimensions:
                _compare_dimensions(layout.MODEL_STL, dimensions, expected_dimensions, problems)
            boundary, non_manifold, triangles = _stl_topology(target)
            # This is the file the slicer actually reads, so its topology
            # matters more than the .blend's.
            if boundary:
                problems.append(
                    "%s: %d open boundary edges after re-import; the exported "
                    "mesh is not watertight" % (layout.MODEL_STL, boundary)
                )
            if non_manifold:
                problems.append(
                    "%s: %d non-manifold edges after re-import" % (layout.MODEL_STL, non_manifold)
                )
            log("  %s: %d triangles, watertight" % (layout.MODEL_STL, triangles))

    glb_path = os.path.join(output_dir, layout.MODEL_GLB)
    if os.path.isfile(glb_path):
        log("re-importing %s" % layout.MODEL_GLB)
        # No scale factor: the GLB holds metres, `scene.reset` puts the scene in
        # millimetres, and Blender's glTF importer converts between them using
        # that unit setting. So the re-imported object already measures in
        # millimetres. If a future Blender stops honouring the unit scale this
        # check fails loudly, which is the right way to find out.
        target, dimensions = _import_bounds(compat.import_glb, glb_path, problems, layout.MODEL_GLB)
        if target is not None and expected_dimensions:
            _compare_dimensions(layout.MODEL_GLB, dimensions, expected_dimensions, problems)

    if problems:
        for problem in problems:
            log("  FAIL %s" % problem)
        raise BuildError(
            VERIFY_FAILED,
            "verification found %d problem(s) in %s" % (len(problems), output_dir),
        )

    log(
        "verified: %d artifacts, hashes match, .blend and exports re-open cleanly"
        % len(manifest.get("artifacts", {}))
    )
    return 0
