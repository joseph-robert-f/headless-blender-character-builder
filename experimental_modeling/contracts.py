"""Controller-owned strict contracts. Source code cannot select acceptance policy."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .platform_io import safe_path

ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
MAX_JSON = 4 * 1024 * 1024


def read_json(path: Path) -> Any:
    path = safe_path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError("JSON must be a bounded regular non-symlink file")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("invalid semantic/revision identifier")
    return value


def finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("expected finite number")
    return float(value)


@dataclass(frozen=True)
class Constraint:
    kind: Literal["anchor", "extent", "path_length", "distance", "manifold", "translated", "centroid"]
    part: str
    data: dict[str, Any]

    @classmethod
    def parse(cls, raw: Any, *, policy_version: int = 1) -> "Constraint":
        def number(value):
            try:
                return finite(value)
            except OverflowError as exc:
                if policy_version == 2:
                    raise ValueError("Number exceeds the check limit.") from exc
                raise
        if not isinstance(raw, dict) or set(raw) != {"kind", "part", "data"}:
            raise ValueError("constraint requires kind, part, data")
        kind, part, data = raw["kind"], identifier(raw["part"]), raw["data"]
        if kind not in {"anchor", "extent", "path_length", "distance", "manifold", "translated", "centroid"} or not isinstance(data, dict):
            raise ValueError("unknown constraint")
        fields = {"anchor": {"point", "tolerance"}, "extent": {"axis", "min", "max"},
                  "path_length": {"groups", "min", "max"}, "distance": {"groups", "min", "max"},
                  "manifold": set(), "translated": {"delta", "tolerance"}, "centroid": {"indices", "point", "tolerance"}}[kind]
        if kind == "translated" and policy_version == 2:
            fields = fields | {"normal_tolerance_radians"}
        if set(data) != fields:
            raise ValueError("unexpected constraint fields")
        if kind == "translated":
            if policy_version == 2 and not 0 <= number(data["normal_tolerance_radians"]) <= .01:
                raise ValueError("Normal tolerance must be from 0 to 0.01 radians.")
            if not isinstance(data["delta"], list) or len(data["delta"]) != 3: raise ValueError("translation must be a 3-vector")
            for value in data["delta"]:
                value = number(value)
                if policy_version == 2 and abs(value) > 1e9:
                    raise ValueError("Translation exceeds the check limit.")
            if not 0 <= number(data["tolerance"]) <= 1: raise ValueError("invalid translation tolerance")
        if kind == "centroid":
            indices = data["indices"]
            if not isinstance(indices, list) or not 1 <= len(indices) <= 256 or len(set(indices)) != len(indices):
                raise ValueError("invalid centroid indices")
            if any(type(i) is not int or not 0 <= i <= 1000000 for i in indices): raise ValueError("invalid centroid index")
        if kind in {"anchor", "centroid"}:
            if not isinstance(data["point"], list) or len(data["point"]) != 3:
                raise ValueError("anchor point must be a 3-vector")
            for v in data["point"]: number(v)
            if not 0 <= number(data["tolerance"]) <= 1: raise ValueError("anchor tolerance out of range")
        if kind in {"extent", "path_length", "distance"}:
            if not 0 <= number(data["min"]) <= number(data["max"]): raise ValueError("invalid limits")
        if kind == "extent" and (type(data["axis"]) is not int or data["axis"] not in (0, 1, 2)):
            raise ValueError("axis must be 0..2")
        if kind in {"path_length", "distance"}:
            groups = data["groups"]
            if not isinstance(groups, list) or not 2 <= len(groups) <= 256 or (kind == "distance" and len(groups) != 2):
                raise ValueError("invalid measured groups")
            for group in groups:
                if not isinstance(group, list) or not 1 <= len(group) <= 256 or any(type(i) is not int or not 0 <= i <= 1000000 for i in group):
                    raise ValueError("invalid vertex indices")
                if len(set(group)) != len(group): raise ValueError("duplicate vertex indices")
        return cls(kind, part, data)


@dataclass(frozen=True)
class Policy:
    schema_version: int
    parts: tuple[str, ...]
    changed_parts: tuple[str, ...]
    constraints: tuple[Constraint, ...]
    profile: Literal["scene", "print"]

    @classmethod
    def parse(cls, raw: Any) -> "Policy":
        if not isinstance(raw, dict) or set(raw) != {"schema_version", "parts", "changed_parts", "constraints", "profile"}:
            raise ValueError("policy fields mismatch")
        if type(raw["schema_version"]) is not int or raw["schema_version"] not in (1, 2): raise ValueError("unsupported policy")
        if raw["profile"] not in ("scene", "print"): raise ValueError("unknown profile")
        for key in ("parts", "changed_parts"):
            if not isinstance(raw[key], list) or len(raw[key]) > 128: raise ValueError("invalid parts")
            for part in raw[key]: identifier(part)
            if len(set(raw[key])) != len(raw[key]): raise ValueError("duplicate parts")
        if not raw["parts"] or not set(raw["changed_parts"]) <= set(raw["parts"]): raise ValueError("invalid change scope")
        if not isinstance(raw["constraints"], list) or len(raw["constraints"]) > 1024: raise ValueError("invalid constraints")
        if raw["schema_version"] == 2 and len(raw["constraints"]) > 32:
            raise ValueError("Version 2 permits at most 32 constraints.")
        constraints = tuple(Constraint.parse(c, policy_version=raw["schema_version"]) for c in raw["constraints"])
        if any(c.part not in raw["parts"] for c in constraints): raise ValueError("unknown constraint part")
        return cls(raw["schema_version"], tuple(raw["parts"]), tuple(raw["changed_parts"]), constraints, raw["profile"])
