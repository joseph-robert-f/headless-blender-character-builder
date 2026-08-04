"""Shared, Blender-independent contracts for the v0.1 builder."""

from .build_manifest import BuildManifest, validate_manifest
from .character_spec import BuildRequest, CharacterSpec, validate_build_request
from .json_contract import ContractValidationError, canonical_json_bytes, canonical_sha256
from .quality_report import (
    QA_STATUS_BUILD_MAPPING,
    QualityReport,
    dimensions_within_reimport_tolerance,
    derive_qa_status,
    value_within_geometry_tolerance,
    validate_quality_report,
)

__all__ = [
    "BuildManifest",
    "BuildRequest",
    "CharacterSpec",
    "ContractValidationError",
    "QA_STATUS_BUILD_MAPPING",
    "QualityReport",
    "canonical_json_bytes",
    "canonical_sha256",
    "dimensions_within_reimport_tolerance",
    "derive_qa_status",
    "validate_build_request",
    "validate_manifest",
    "validate_quality_report",
    "value_within_geometry_tolerance",
]
