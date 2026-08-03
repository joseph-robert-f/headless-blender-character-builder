"""Reusable fixtures for G6 API and worker tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable
from uuid import UUID

from shared.character_spec import BuildRequest
from shared.json_contract import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[2]


def facet_request_bytes() -> bytes:
    return (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()


def moss_request_bytes() -> bytes:
    return (ROOT / "examples" / "requests" / "moss-hopper.json").read_bytes()


def write_valid_builder_output(root: Path, request_payload: bytes) -> None:
    request = BuildRequest.from_json(request_payload)
    root.mkdir(parents=True, exist_ok=False)
    (root / "diagnostics").mkdir()
    payloads = {
        "model.blend": b"BLENDER-fixture\n",
        "model.glb": b"glTF-fixture\n",
        "model.stl": b"STL-fixture\n",
        "preview.png": b"\x89PNG\r\n\x1a\npreview",
        "diagnostics/front.png": b"\x89PNG\r\n\x1a\nfront",
        "diagnostics/side.png": b"\x89PNG\r\n\x1a\nside",
        "diagnostics/back.png": b"\x89PNG\r\n\x1a\nback",
        "qa.json": b'{"qa_version":"qa/v1","status":"passed"}\n',
    }
    for name, payload in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    manifest = {
        "manifest_version": "manifest/v1",
        "request_sha256": request.request_sha256,
        "spec_sha256": request.spec_sha256,
        "input_sha256": {},
        "generator_version": "1.0.0",
        "execution": {
            "mode": "native",
            "project_revision": "a" * 64,
            "blender_version": "4.5.12 LTS",
            "blender_binary_sha256": "b" * 64,
            "worker_image_reference": None,
            "worker_image_digest": None,
            "worker_image_id": None,
        },
        "dimensions_mm": [64, 51, int(request.spec.height_mm)],
        "artifacts": {
            name: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
            for name, payload in payloads.items()
        },
        "qa": {
            "status": "passed",
            "manifold": True,
            "non_manifold_edges": 0,
            "minimum_wall_mm": 1.2,
            "minimum_feature_mm": 2.0,
            "connected_shells": 1,
            "positive_volume": True,
            "fresh_reload": True,
            "glb_reimport": True,
            "stl_reimport": True,
        },
    }
    (root / "manifest.json").write_bytes(canonical_json_bytes(manifest) + b"\n")


def corrupt_file(root: Path, relative_path: str) -> None:
    path = root / relative_path
    payload = path.read_bytes()
    path.write_bytes(payload + b"corrupt")
