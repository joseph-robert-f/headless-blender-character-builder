"""BuildRequest v1 and CharacterSpec v1 validation models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional, Tuple, Union

from .json_contract import (
    MAX_BUILD_REQUEST_BYTES,
    ContractValidationError,
    bounded_decimal_value,
    canonical_json_bytes,
    canonical_sha256,
    decode_json_document,
    reject_extra_fields,
    require_fields,
    require_object,
)


REQUEST_VERSION = "build/v1"
SPEC_VERSION = "character/v1"
GENERATOR = "geometric-character@1.0.0"
OUTPUT_PROFILE = "complete-v1"
RENDER_PROFILE = "diagnostic-v1"
QUALITY_PROFILE = "geometry-v1"

STYLES = ("geometric", "low_poly", "chibi")
POSES = ("standing", "wave", "heroic")
MATERIAL_PRESETS = ("matte", "satin", "glossy")
EYE_PRESETS = ("round", "visor", "sleepy")
COMPONENT_PRESETS = (
    "antenna-pair",
    "backpack",
    "chest-badge",
    "long-horns",
    "pointed-ears",
    "round-ears",
    "short-horns",
    "stub-tail",
    "swept-tail",
)
BASE_PRESETS = ("none", "round", "square", "hexagonal")

NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9 '-]{0,62}[A-Za-z0-9])?$")
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLOR_PATTERN = re.compile(r"^#[0-9A-F]{6}$")


def _decimal(
    value: Any, path: str, minimum: Decimal, maximum: Decimal
) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ContractValidationError("expected_number", "value must be a number", path)
    number = bounded_decimal_value(value, path)
    if number < minimum or number > maximum:
        raise ContractValidationError(
            "number_out_of_range",
            f"number must be between {minimum} and {maximum}",
            path,
        )
    return number


def _enum(value: Any, path: str, choices: Tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ContractValidationError(
            "invalid_enum", "value must be one of: " + ", ".join(choices), path
        )
    return value


def _safe_slug_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = slug[:48].rstrip("-")
    if not slug:
        raise ContractValidationError("invalid_slug", "name cannot produce a safe slug", "$.spec.name")
    return slug


@dataclass(frozen=True)
class Proportions:
    head_scale: Decimal
    body_scale: Decimal
    limb_scale: Decimal

    @classmethod
    def from_mapping(cls, raw: Any, path: str = "$.spec.proportions") -> "Proportions":
        value = require_object(raw, path)
        allowed = ("head_scale", "body_scale", "limb_scale")
        reject_extra_fields(value, allowed, path)
        require_fields(value, ("head_scale", "limb_scale"), path)
        return cls(
            head_scale=_decimal(value["head_scale"], path + ".head_scale", Decimal("0.7"), Decimal("1.6")),
            body_scale=_decimal(value.get("body_scale", Decimal("1")), path + ".body_scale", Decimal("0.7"), Decimal("1.4")),
            limb_scale=_decimal(value["limb_scale"], path + ".limb_scale", Decimal("0.7"), Decimal("1.3")),
        )

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "body_scale": self.body_scale,
            "head_scale": self.head_scale,
            "limb_scale": self.limb_scale,
        }


@dataclass(frozen=True)
class BaseSpec:
    preset: str
    width_mm: Decimal
    depth_mm: Decimal
    height_mm: Decimal

    @classmethod
    def from_mapping(cls, raw: Any, path: str = "$.spec.base") -> "BaseSpec":
        value = require_object(raw, path)
        allowed = ("preset", "width_mm", "depth_mm", "height_mm")
        reject_extra_fields(value, allowed, path)
        require_fields(value, allowed, path)
        preset = _enum(value["preset"], path + ".preset", BASE_PRESETS)
        if preset == "none":
            minimum = maximum = Decimal("0")
            height_min = Decimal("0")
            height_max = Decimal("0")
        else:
            minimum, maximum = Decimal("20"), Decimal("160")
            height_min, height_max = Decimal("2"), Decimal("25")
        return cls(
            preset=preset,
            width_mm=_decimal(value["width_mm"], path + ".width_mm", minimum, maximum),
            depth_mm=_decimal(value["depth_mm"], path + ".depth_mm", minimum, maximum),
            height_mm=_decimal(value["height_mm"], path + ".height_mm", height_min, height_max),
        )

    @classmethod
    def default(cls) -> "BaseSpec":
        return cls("round", Decimal("48"), Decimal("48"), Decimal("5"))

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "depth_mm": self.depth_mm,
            "height_mm": self.height_mm,
            "preset": self.preset,
            "width_mm": self.width_mm,
        }


@dataclass(frozen=True)
class CharacterSpec:
    spec_version: str
    name: str
    slug: str
    style: str
    height_mm: Decimal
    pose: str
    palette: Tuple[str, ...]
    proportions: Proportions
    material_preset: str
    eye_preset: str
    components: Tuple[str, ...]
    base: BaseSpec

    @classmethod
    def from_mapping(cls, raw: Any, path: str = "$.spec") -> "CharacterSpec":
        value = require_object(raw, path)
        allowed = (
            "spec_version",
            "name",
            "slug",
            "style",
            "height_mm",
            "pose",
            "palette",
            "proportions",
            "material_preset",
            "eye_preset",
            "components",
            "base",
        )
        required = (
            "spec_version",
            "name",
            "style",
            "height_mm",
            "pose",
            "palette",
            "proportions",
        )
        reject_extra_fields(value, allowed, path)
        require_fields(value, required, path)

        if value["spec_version"] != SPEC_VERSION:
            raise ContractValidationError(
                "unsupported_version", f"spec_version must be {SPEC_VERSION!r}", path + ".spec_version"
            )
        name = value["name"]
        if not isinstance(name, str) or len(name) > 64 or not NAME_PATTERN.fullmatch(name):
            raise ContractValidationError(
                "invalid_name",
                "name must be 1-64 ASCII letters, digits, spaces, apostrophes, or hyphens",
                path + ".name",
            )
        slug = value["slug"] if "slug" in value else _safe_slug_from_name(name)
        if not isinstance(slug, str) or len(slug) > 48 or not SLUG_PATTERN.fullmatch(slug):
            raise ContractValidationError(
                "invalid_slug", "slug must be a 1-48 character lowercase safe slug", path + ".slug"
            )

        palette_raw = value["palette"]
        if not isinstance(palette_raw, list) or not 1 <= len(palette_raw) <= 8:
            raise ContractValidationError(
                "invalid_palette", "palette must contain 1-8 colors", path + ".palette"
            )
        palette = []
        for index, color in enumerate(palette_raw):
            if not isinstance(color, str) or not COLOR_PATTERN.fullmatch(color):
                raise ContractValidationError(
                    "invalid_color",
                    "palette colors must use uppercase #RRGGBB",
                    f"{path}.palette[{index}]",
                )
            if color in palette:
                raise ContractValidationError(
                    "duplicate_item", "palette colors must be unique", f"{path}.palette[{index}]"
                )
            palette.append(color)

        components_raw = value.get("components", [])
        if not isinstance(components_raw, list) or len(components_raw) > 16:
            raise ContractValidationError(
                "invalid_components", "components must be an array of at most 16 presets", path + ".components"
            )
        components = []
        for index, component in enumerate(components_raw):
            component = _enum(component, f"{path}.components[{index}]", COMPONENT_PRESETS)
            if component in components:
                raise ContractValidationError(
                    "duplicate_item", "component presets must be unique", f"{path}.components[{index}]"
                )
            components.append(component)

        base = BaseSpec.from_mapping(value["base"], path + ".base") if "base" in value else BaseSpec.default()
        return cls(
            spec_version=SPEC_VERSION,
            name=name,
            slug=slug,
            style=_enum(value["style"], path + ".style", STYLES),
            height_mm=_decimal(value["height_mm"], path + ".height_mm", Decimal("25"), Decimal("250")),
            pose=_enum(value["pose"], path + ".pose", POSES),
            palette=tuple(palette),
            proportions=Proportions.from_mapping(value["proportions"], path + ".proportions"),
            material_preset=_enum(value.get("material_preset", "matte"), path + ".material_preset", MATERIAL_PRESETS),
            eye_preset=_enum(value.get("eye_preset", "round"), path + ".eye_preset", EYE_PRESETS),
            components=tuple(sorted(components)),
            base=base,
        )

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "base": self.base.to_dict(),
            "components": list(self.components),
            "eye_preset": self.eye_preset,
            "height_mm": self.height_mm,
            "material_preset": self.material_preset,
            "name": self.name,
            "palette": list(self.palette),
            "pose": self.pose,
            "proportions": self.proportions.to_dict(),
            "slug": self.slug,
            "spec_version": self.spec_version,
            "style": self.style,
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True)
class BuildRequest:
    request_version: str
    generator: str
    spec: CharacterSpec
    output_profile: str
    render_profile: str
    quality_profile: str

    @classmethod
    def from_mapping(cls, raw: Any) -> "BuildRequest":
        path = "$"
        value = require_object(raw, path)
        allowed = (
            "request_version",
            "generator",
            "spec",
            "output_profile",
            "render_profile",
            "quality_profile",
        )
        reject_extra_fields(value, allowed, path)
        require_fields(value, allowed, path)
        constants = {
            "request_version": REQUEST_VERSION,
            "generator": GENERATOR,
            "output_profile": OUTPUT_PROFILE,
            "render_profile": RENDER_PROFILE,
            "quality_profile": QUALITY_PROFILE,
        }
        for field, expected in constants.items():
            if value[field] != expected:
                raise ContractValidationError(
                    "unsupported_contract_value",
                    f"{field} must be {expected!r}",
                    "$." + field,
                )
        return cls(
            request_version=REQUEST_VERSION,
            generator=GENERATOR,
            spec=CharacterSpec.from_mapping(value["spec"]),
            output_profile=OUTPUT_PROFILE,
            render_profile=RENDER_PROFILE,
            quality_profile=QUALITY_PROFILE,
        )

    @classmethod
    def from_json(
        cls, payload: Union[str, bytes, bytearray, memoryview]
    ) -> "BuildRequest":
        raw = decode_json_document(payload, max_bytes=MAX_BUILD_REQUEST_BYTES)
        return cls.from_mapping(raw)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "generator": self.generator,
            "output_profile": self.output_profile,
            "quality_profile": self.quality_profile,
            "render_profile": self.render_profile,
            "request_version": self.request_version,
            "spec": self.spec.to_dict(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def spec_sha256(self) -> str:
        return self.spec.sha256


def validate_build_request(
    payload: Union[BuildRequest, Mapping[str, Any], str, bytes, bytearray, memoryview]
) -> BuildRequest:
    if isinstance(payload, BuildRequest):
        return BuildRequest.from_mapping(payload.to_dict())
    if isinstance(payload, Mapping):
        return BuildRequest.from_mapping(payload)
    return BuildRequest.from_json(payload)
