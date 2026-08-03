"""Versioned, allowlisted procedural character generators."""

from .registry import generate_character
from .types import GenerationResult

__all__ = ["GenerationResult", "generate_character"]
