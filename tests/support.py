"""Small standard-library fixtures shared by contract tests."""

from __future__ import annotations

from typing import Any, Dict


def passed_qa_report() -> Dict[str, Any]:
    return {
        "qa_version": "qa/v1",
        "status": "passed",
        "measurements": {
            "requested_height_mm": 95,
            "dimensions_mm": [64, 51, 95],
            "glb_dimensions_mm": [64.1, 51, 95.1],
            "stl_dimensions_mm": [64, 50.9, 95],
            "triangle_count": 24000,
            "object_count": 18,
            "material_count": 3,
            "non_manifold_edges": 0,
            "zero_area_faces": 0,
            "minimum_wall_mm": 1.34,
            "minimum_feature_mm": 2.15,
            "connected_shells": 1,
        },
        "checks": {
            "manifold": True,
            "finite_geometry": True,
            "outward_normals": True,
            "positive_volume": True,
            "height_within_tolerance": True,
            "fresh_reload": True,
            "glb_reimport": True,
            "stl_reimport": True,
        },
        "notes": [],
    }


def valid_manifest() -> Dict[str, Any]:
    digest = "a" * 64
    artifacts = {
        name: {"sha256": digest, "bytes": 1024}
        for name in (
            "model.blend",
            "model.glb",
            "model.stl",
            "preview.png",
            "diagnostics/front.png",
            "diagnostics/side.png",
            "diagnostics/back.png",
            "qa.json",
        )
    }
    return {
        "manifest_version": "manifest/v1",
        "request_sha256": "b" * 64,
        "spec_sha256": "c" * 64,
        "input_sha256": {},
        "generator_version": "1.0.0",
        "execution": {
            "mode": "native",
            "project_revision": "d" * 40,
            "blender_version": "4.5.12 LTS",
            "blender_binary_sha256": "e" * 64,
            "worker_image_reference": None,
            "worker_image_digest": None,
            "worker_image_id": None,
        },
        "dimensions_mm": [64, 51, 95],
        "artifacts": artifacts,
        "qa": {
            "status": "passed",
            "manifold": True,
            "non_manifold_edges": 0,
            "minimum_wall_mm": 1.34,
            "minimum_feature_mm": 2.15,
            "connected_shells": 1,
            "positive_volume": True,
            "fresh_reload": True,
            "glb_reimport": True,
            "stl_reimport": True,
        },
    }
