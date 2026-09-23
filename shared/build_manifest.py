"""Success manifest v1 validation model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Tuple, Union

from .json_contract import (
    ContractValidationError,
    bounded_decimal_value,
    canonical_json_bytes,
    decode_json_document,
    reject_extra_fields,
    require_fields,
    require_object,
)


MANIFEST_VERSION = "manifest/v1"
GENERATOR_VERSION = "1.0.0"
MAX_PUBLISHED_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
REQUIRED_ARTIFACTS = (
    "model.blend",
    "model.glb",
    "model.stl",
    "preview.png",
    "diagnostics/front.png",
    "diagnostics/side.png",
    "diagnostics/back.png",
    "qa.json",
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PROJECT_REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
BLENDER_VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z .+-]{0,63}$")
IMAGE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,254}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _hash(value: Any, path: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ContractValidationError("invalid_sha256", "value must be a lowercase SHA-256 hex digest", path)
    return value


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ContractValidationError("expected_integer", "value must be an integer", path)
    number = bounded_decimal_value(value, path)
    if number != number.to_integral_value():
        raise ContractValidationError("expected_integer", "value must be an integer", path)
    integer = int(number)
    if not minimum <= integer <= maximum:
        raise ContractValidationError(
            "integer_out_of_range", f"integer must be between {minimum} and {maximum}", path
        )
    return integer


def _decimal(value: Any, path: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ContractValidationError("expected_number", "value must be a number", path)
    result = bounded_decimal_value(value, path)
    if result < minimum or result > maximum:
        raise ContractValidationError(
            "number_out_of_range", f"finite number must be between {minimum} and {maximum}", path
        )
    return result


def _true(value: Any, path: str) -> bool:
    if value is not True:
        raise ContractValidationError("mandatory_qa_failed", "success manifest requires true", path)
    return True


def _dimensions(value: Any) -> Tuple[Decimal, Decimal, Decimal]:
    if not isinstance(value, list) or len(value) != 3:
        raise ContractValidationError("invalid_dimensions", "dimensions_mm must contain exactly three values", "$.dimensions_mm")
    return tuple(
        _decimal(item, f"$.dimensions_mm[{index}]", Decimal("0.001"), Decimal("1000"))
        for index, item in enumerate(value)
    )  # type: ignore[return-value]


@dataclass(frozen=True)
class BuildManifest:
    manifest_version: str
    request_sha256: str
    spec_sha256: str
    input_sha256: Mapping[str, str]
    generator_version: str
    execution: Mapping[str, Any]
    dimensions_mm: Tuple[Decimal, Decimal, Decimal]
    artifacts: Mapping[str, Mapping[str, Any]]
    qa: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Any) -> "BuildManifest":
        value = require_object(raw, "$")
        fields = (
            "manifest_version",
            "request_sha256",
            "spec_sha256",
            "input_sha256",
            "generator_version",
            "execution",
            "dimensions_mm",
            "artifacts",
            "qa",
        )
        reject_extra_fields(value, fields, "$")
        require_fields(value, fields, "$")
        if value["manifest_version"] != MANIFEST_VERSION:
            raise ContractValidationError(
                "unsupported_version", f"manifest_version must be {MANIFEST_VERSION!r}", "$.manifest_version"
            )
        request_hash = _hash(value["request_sha256"], "$.request_sha256")
        spec_hash = _hash(value["spec_sha256"], "$.spec_sha256")

        inputs = require_object(value["input_sha256"], "$.input_sha256")
        if inputs:
            raise ContractValidationError(
                "remote_input_forbidden", "v0.1 accepts no external input assets", "$.input_sha256"
            )
        if value["generator_version"] != GENERATOR_VERSION:
            raise ContractValidationError(
                "unsupported_generator_version",
                f"generator_version must be {GENERATOR_VERSION!r}",
                "$.generator_version",
            )

        execution_raw = require_object(value["execution"], "$.execution")
        execution_fields = (
            "mode",
            "project_revision",
            "blender_version",
            "blender_binary_sha256",
            "worker_image_reference",
            "worker_image_digest",
            "worker_image_id",
        )
        reject_extra_fields(execution_raw, execution_fields, "$.execution")
        require_fields(execution_raw, execution_fields, "$.execution")
        mode = execution_raw["mode"]
        if mode not in ("native", "container"):
            raise ContractValidationError("invalid_enum", "mode must be native or container", "$.execution.mode")
        project_revision = execution_raw["project_revision"]
        if not isinstance(project_revision, str) or not PROJECT_REVISION_PATTERN.fullmatch(project_revision):
            raise ContractValidationError(
                "invalid_revision", "project_revision must be a 40- or 64-character lowercase digest", "$.execution.project_revision"
            )
        blender_version = execution_raw["blender_version"]
        if not isinstance(blender_version, str) or not BLENDER_VERSION_PATTERN.fullmatch(blender_version):
            raise ContractValidationError("invalid_blender_version", "invalid Blender version", "$.execution.blender_version")
        binary_hash = _hash(execution_raw["blender_binary_sha256"], "$.execution.blender_binary_sha256")

        reference = execution_raw["worker_image_reference"]
        digest = execution_raw["worker_image_digest"]
        image_id = execution_raw["worker_image_id"]
        if mode == "native":
            if reference is not None or digest is not None or image_id is not None:
                raise ContractValidationError(
                    "native_image_metadata", "native execution requires all image fields to be null", "$.execution"
                )
        else:
            if not isinstance(reference, str) or not IMAGE_REFERENCE_PATTERN.fullmatch(reference):
                raise ContractValidationError(
                    "invalid_image_reference", "container execution requires a bounded OCI image reference", "$.execution.worker_image_reference"
                )
            for field, candidate in (("worker_image_digest", digest), ("worker_image_id", image_id)):
                if candidate is not None and (
                    not isinstance(candidate, str) or not IMAGE_DIGEST_PATTERN.fullmatch(candidate)
                ):
                    raise ContractValidationError(
                        "invalid_image_digest", "image digest/id must be null or sha256:<digest>", "$.execution." + field
                    )
        execution = {
            "blender_binary_sha256": binary_hash,
            "blender_version": blender_version,
            "mode": mode,
            "project_revision": project_revision,
            "worker_image_digest": digest,
            "worker_image_id": image_id,
            "worker_image_reference": reference,
        }

        artifacts_raw = require_object(value["artifacts"], "$.artifacts")
        reject_extra_fields(artifacts_raw, REQUIRED_ARTIFACTS, "$.artifacts")
        require_fields(artifacts_raw, REQUIRED_ARTIFACTS, "$.artifacts")
        artifacts = {}
        total_bytes = 0
        for name in REQUIRED_ARTIFACTS:
            entry_raw = require_object(artifacts_raw[name], "$.artifacts." + name)
            reject_extra_fields(entry_raw, ("sha256", "bytes"), "$.artifacts." + name)
            require_fields(entry_raw, ("sha256", "bytes"), "$.artifacts." + name)
            size = _integer(entry_raw["bytes"], "$.artifacts." + name + ".bytes", 1, MAX_PUBLISHED_ARTIFACT_BYTES)
            total_bytes += size
            artifacts[name] = {
                "bytes": size,
                "sha256": _hash(entry_raw["sha256"], "$.artifacts." + name + ".sha256"),
            }
        if total_bytes > MAX_PUBLISHED_ARTIFACT_BYTES:
            raise ContractValidationError(
                "artifact_budget_exceeded", "published artifacts exceed the 2 GiB v0.1 budget", "$.artifacts"
            )

        qa_raw = require_object(value["qa"], "$.qa")
        qa_fields = (
            "status",
            "manifold",
            "non_manifold_edges",
            "minimum_wall_mm",
            "minimum_feature_mm",
            "connected_shells",
            "positive_volume",
            "fresh_reload",
            "glb_reimport",
            "stl_reimport",
        )
        reject_extra_fields(qa_raw, qa_fields, "$.qa")
        require_fields(qa_raw, qa_fields, "$.qa")
        if qa_raw["status"] != "passed":
            raise ContractValidationError(
                "success_manifest_requires_pass", "success manifest QA status must be passed", "$.qa.status"
            )
        if _integer(qa_raw["non_manifold_edges"], "$.qa.non_manifold_edges", 0, 100_000_000) != 0:
            raise ContractValidationError("mandatory_qa_failed", "non_manifold_edges must be zero", "$.qa.non_manifold_edges")
        if _integer(qa_raw["connected_shells"], "$.qa.connected_shells", 0, 10_000) != 1:
            raise ContractValidationError("mandatory_qa_failed", "connected_shells must be one", "$.qa.connected_shells")
        minimum_wall = _decimal(qa_raw["minimum_wall_mm"], "$.qa.minimum_wall_mm", Decimal("1.2"), Decimal("1000"))
        minimum_feature = _decimal(qa_raw["minimum_feature_mm"], "$.qa.minimum_feature_mm", Decimal("2.0"), Decimal("1000"))
        qa = {
            "connected_shells": 1,
            "fresh_reload": _true(qa_raw["fresh_reload"], "$.qa.fresh_reload"),
            "glb_reimport": _true(qa_raw["glb_reimport"], "$.qa.glb_reimport"),
            "manifold": _true(qa_raw["manifold"], "$.qa.manifold"),
            "minimum_feature_mm": minimum_feature,
            "minimum_wall_mm": minimum_wall,
            "non_manifold_edges": 0,
            "positive_volume": _true(qa_raw["positive_volume"], "$.qa.positive_volume"),
            "status": "passed",
            "stl_reimport": _true(qa_raw["stl_reimport"], "$.qa.stl_reimport"),
        }

        immutable_artifacts = MappingProxyType(
            {name: MappingProxyType(dict(entry)) for name, entry in artifacts.items()}
        )
        manifest = cls(
            MANIFEST_VERSION,
            request_hash,
            spec_hash,
            MappingProxyType({}),
            GENERATOR_VERSION,
            MappingProxyType(execution),
            _dimensions(value["dimensions_mm"]),
            immutable_artifacts,
            MappingProxyType(qa),
        )
        # Publication contains nine files. The manifest omits its own hash,
        # but its canonical bytes and final newline still consume the budget.
        if total_bytes + len(manifest.canonical_bytes) + 1 > MAX_PUBLISHED_ARTIFACT_BYTES:
            raise ContractValidationError(
                "artifact_budget_exceeded",
                "published artifacts including manifest.json exceed the 2 GiB v0.1 budget",
                "$.artifacts",
            )
        return manifest

    @classmethod
    def from_json(
        cls, payload: Union[str, bytes, bytearray, memoryview]
    ) -> "BuildManifest":
        return cls.from_mapping(decode_json_document(payload))

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "artifacts": {name: dict(entry) for name, entry in self.artifacts.items()},
            "dimensions_mm": list(self.dimensions_mm),
            "execution": dict(self.execution),
            "generator_version": self.generator_version,
            "input_sha256": dict(self.input_sha256),
            "manifest_version": self.manifest_version,
            "qa": dict(self.qa),
            "request_sha256": self.request_sha256,
            "spec_sha256": self.spec_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def validate_manifest(
    payload: Union[BuildManifest, Mapping[str, Any], str, bytes, bytearray, memoryview]
) -> BuildManifest:
    if isinstance(payload, BuildManifest):
        return BuildManifest.from_mapping(payload.to_dict())
    if isinstance(payload, Mapping):
        return BuildManifest.from_mapping(payload)
    return BuildManifest.from_json(payload)
