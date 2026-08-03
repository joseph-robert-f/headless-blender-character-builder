"""Closed registry for reviewed generator implementations."""

from __future__ import annotations

from shared.character_spec import BuildRequest, GENERATOR

from .types import GenerationResult


def preflight_character(request: BuildRequest) -> None:
    """Run generator-specific validation without importing or changing a scene."""

    if not isinstance(request, BuildRequest):
        raise TypeError("request must be a validated BuildRequest")
    if request.generator != GENERATOR:
        raise ValueError(f"unsupported generator: {request.generator!r}")
    from .geometric_character_v1.builder import preflight

    preflight(request)


def generate_character(request: BuildRequest) -> GenerationResult:
    """Generate one deterministic character through an allowlisted generator.

    The registry accepts an already validated ``BuildRequest`` rather than a
    mapping so arbitrary data cannot reach Blender operators by bypassing G1.
    """

    if not isinstance(request, BuildRequest):
        raise TypeError("request must be a validated BuildRequest")
    if request.generator != GENERATOR:
        raise ValueError(f"unsupported generator: {request.generator!r}")

    # Imported lazily so contract-only callers do not need Blender's ``bpy``.
    from .geometric_character_v1 import generate

    return generate(request)


__all__ = ["generate_character", "preflight_character"]
