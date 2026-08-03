"""Blender-independent result values returned by trusted generators."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationResult:
    """Immutable inventory emitted after a character scene is generated."""

    generator_id: str
    display_object_names: tuple[str, ...]
    printable_object_name: str
    designed_minimum_feature_mm: float
    voxel_size_mm: float
    request_sha256: str
    spec_sha256: str
    collection_names: tuple[str, ...]
