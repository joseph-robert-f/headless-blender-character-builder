"""Build orchestration inside Blender.

One function, `run`, takes a resolved request and an output directory and
produces the complete artifact set. Everything is staged in a hidden directory
first and moved into place only after QA passes, so an interrupted or failed
build never leaves behind something that looks like a finished result.
"""

import datetime
import os
import shutil
import time

import bpy

from hbcb import canonical, layout
from hbcb import manifest as manifest_module
from hbcb.exit_codes import BLENDER_FAILED, FILESYSTEM, VERIFY_FAILED, BuildError

from . import exporters, generator, qa, render, scene


def _prepare_directories(output_dir):
    staging = os.path.join(output_dir, layout.STAGING_DIR)
    try:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        os.makedirs(os.path.join(staging, layout.DIAGNOSTICS_DIR), exist_ok=True)
    except OSError as error:
        raise BuildError(FILESYSTEM, "cannot prepare staging directory: %s" % error) from error
    return staging


def _publish(staging, output_dir, relative_paths):
    """Move staged artifacts into the output directory."""
    try:
        os.makedirs(os.path.join(output_dir, layout.DIAGNOSTICS_DIR), exist_ok=True)
        for relative in relative_paths:
            source = os.path.join(staging, relative)
            destination = os.path.join(output_dir, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            os.replace(source, destination)
        shutil.rmtree(staging, ignore_errors=True)
    except OSError as error:
        raise BuildError(FILESYSTEM, "cannot publish artifacts: %s" % error) from error


def _summarise_qa(measurements, verdict):
    """The compact QA view embedded in the manifest.

    The full measurement set lives in qa.json; repeating all of it in the
    manifest would bury the provenance the manifest exists to carry.
    """
    topology = measurements["topology"]
    return {
        "passed": verdict["passed"],
        "strict": verdict["strict"],
        "failed_checks": verdict["failed"],
        "warnings": verdict["warnings"],
        "watertight": topology["boundary_edges"] == 0,
        "manifold": topology["non_manifold_edges"] == 0 and topology["non_manifold_vertices"] == 0,
        "connected_shells": topology["connected_shells"],
        "positive_volume": measurements["volume"]["positive_volume"],
        "minimum_thickness_mm": measurements["thickness"]["p01_mm"],
        "solid_volume_cm3": measurements["volume"]["solid_volume_cm3"],
        "estimated_solid_mass_g": measurements["volume"]["estimated_solid_mass_g"],
        "unsupported_overhang_area_mm2": measurements["overhangs"]["unsupported_area_mm2"],
        "bed_contact_area_mm2": measurements["overhangs"]["bed_contact_area_mm2"],
    }


def run(request, output_dir, mode="native", log=print):
    """Build `request` into `output_dir` and return the manifest.

    Raises BuildError with the appropriate exit code on any failure.
    """
    started = time.time()
    created_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as error:
        raise BuildError(FILESYSTEM, "cannot create output directory: %s" % error) from error

    staging = _prepare_directories(output_dir)
    expected = layout.expected(request.output_profile, request.render_profile)

    log("generating geometry (%s, %.0f mm)" % (request.spec["style"], request.spec["height_mm"]))
    try:
        scene.reset(request.slug)
        model, report = generator.generate(request.spec, request.print_profile)
    except BuildError:
        raise
    except Exception as error:
        raise BuildError(BLENDER_FAILED, "geometry generation failed: %s" % error) from error

    for adjustment in report.adjustments:
        log("  adjusted: %s" % adjustment)

    log("measuring print readiness")
    try:
        measurements = qa.measure(model, request.print_profile)
        verdict = qa.evaluate(measurements, request.print_profile, request.strict_qa)
    except Exception as error:
        raise BuildError(BLENDER_FAILED, "geometry QA failed: %s" % error) from error

    log("exporting artifacts")
    try:
        exporters.export_stl(os.path.join(staging, layout.MODEL_STL), model)
        if layout.MODEL_GLB in expected:
            exporters.export_glb(os.path.join(staging, layout.MODEL_GLB), model)
        # The .blend is saved after the exports so the saved scene includes the
        # lighting and camera only when renders were actually produced.
        if layout.PREVIEW in expected:
            log("rendering preview and diagnostic views")
            render.render_views(
                model,
                staging,
                os.path.join(staging, layout.PREVIEW),
                {
                    view: os.path.join(staging, layout.diagnostic(view))
                    for view in layout.DIAGNOSTIC_VIEWS
                },
            )
        exporters.save_blend(os.path.join(staging, layout.MODEL_BLEND))
    except BuildError:
        raise
    except Exception as error:
        raise BuildError(BLENDER_FAILED, "artifact export failed: %s" % error) from error

    qa_document = {
        "qa_version": "qa/v1",
        "print_profile": request.print_profile,
        "measurements": measurements,
        "verdict": verdict,
        "adjustments": report.adjustments,
    }
    canonical.write_json(os.path.join(staging, layout.QA), qa_document)

    missing = [
        relative
        for relative in expected
        if relative != layout.MANIFEST and not os.path.isfile(os.path.join(staging, relative))
    ]
    if missing:
        raise BuildError(BLENDER_FAILED, "build did not produce: %s" % ", ".join(missing))

    mesh = model.data
    model_summary = {
        "name": request.spec["name"],
        "slug": request.slug,
        "dimensions_mm": measurements["dimensions_mm"],
        "requested_height_mm": request.spec["height_mm"],
        "vertices": len(mesh.vertices),
        "triangles": measurements["topology"]["triangles"],
        "materials": [material.name for material in mesh.materials if material is not None],
        "parts_before_union": len(report.parts),
    }

    artifacts = manifest_module.hash_artifacts(
        staging, [path for path in expected if path != layout.MANIFEST]
    )
    execution = manifest_module.execution_context(
        mode=mode,
        blender_version=bpy.app.version_string,
        duration_seconds=time.time() - started,
        created_at=created_at,
    )
    status = "succeeded" if verdict["passed"] else "needs_review"
    document = manifest_module.build(
        request=request,
        execution=execution,
        model=model_summary,
        qa_summary=_summarise_qa(measurements, verdict),
        artifacts=artifacts,
        adjustments=report.adjustments,
        status=status,
    )

    if not verdict["passed"]:
        # Leave the staged evidence in place: a failed print check is exactly
        # when someone wants to look at the renders and the QA numbers.
        canonical.write_json(os.path.join(staging, layout.MANIFEST), document)
        _publish(staging, output_dir, expected)
        raise BuildError(
            VERIFY_FAILED,
            "required print checks failed: %s\n  see %s"
            % (", ".join(verdict["failed"]), os.path.join(output_dir, layout.QA)),
        )

    canonical.write_json(os.path.join(staging, layout.MANIFEST), document)
    _publish(staging, output_dir, expected)
    log("published %d artifacts to %s" % (len(expected), output_dir))
    return document
