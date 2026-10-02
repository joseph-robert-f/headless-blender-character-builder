"""Pure trusted checks over independently inspected, evaluated geometry."""
from __future__ import annotations

import math
from .contracts import Policy, finite


def check(policy: Policy, observation: dict, previous: dict | None) -> list[dict]:
    failures = []
    parts = observation.get("parts", {})
    if set(parts) != set(policy.parts):
        return [{"check": "semantic_parts", "expected": list(policy.parts), "actual": list(parts)}]
    if previous is not None:
        removed = set(previous["parts"]) - set(parts)
        if removed:
            return [{"check": "removed_parts_unsupported", "parts": sorted(removed)}]
        unscoped = (set(parts) - set(previous["parts"])) - set(policy.changed_parts)
        if unscoped:
            return [{"check": "new_parts_outside_scope", "parts": sorted(unscoped)}]
    for name, part in parts.items():
        vertices = part["world_vertices"]
        if not vertices or len(vertices) > 1000000:
            raise ValueError("invalid observed vertices")
        for vertex in vertices:
            if len(vertex) != 3: raise ValueError("invalid observed vertex")
            for x in vertex: finite(x)
        if previous is not None and name not in policy.changed_parts:
            for key in ("geometry_hash", "transform_hash", "material_hash"):
                if part[key] != previous["parts"][name][key]:
                    failures.append({"check": "unchanged", "part": name, "component": key})
    for constraint in policy.constraints:
        name, data, kind = constraint.part, constraint.data, constraint.kind
        part = parts[name]
        vertices = part["world_vertices"]
        value = None
        if kind == "translated":
            if previous is None: raise ValueError("translation requires parent observation")
            prior = previous["parts"][name]
            same = (len(vertices) == len(prior["world_vertices"]) and part["face_indices"] == prior["face_indices"]
                    and part["material_hash"] == prior["material_hash"])
            value = max((math.dist(v, [a + b for a,b in zip(old, data["delta"])])
                         for v, old in zip(vertices, prior["world_vertices"])), default=float("inf"))
            passed = same and value <= data["tolerance"]
        elif kind == "centroid":
            if any(i >= len(vertices) for i in data["indices"]): raise ValueError("centroid references absent geometry")
            center = [sum(vertices[i][axis] for i in data["indices"]) / len(data["indices"]) for axis in range(3)]
            value = math.dist(center, data["point"])
            passed = value <= data["tolerance"]
        elif kind == "anchor":
            value = min(math.dist(v, data["point"]) for v in vertices)
            passed = value <= data["tolerance"]
        elif kind == "extent":
            axis = data["axis"]
            value = max(v[axis] for v in vertices) - min(v[axis] for v in vertices)
            passed = data["min"] <= value <= data["max"]
        elif kind in ("path_length", "distance"):
            if any(i >= len(vertices) for group in data["groups"] for i in group):
                raise ValueError("measurement references absent geometry")
            centers = [[sum(vertices[i][axis] for i in group) / len(group) for axis in range(3)] for group in data["groups"]]
            value = sum(math.dist(a, b) for a, b in zip(centers, centers[1:]))
            passed = data["min"] <= value <= data["max"]
        else:
            value = part["nonmanifold_edges"]
            passed = value == 0
        if not passed:
            failures.append({"check": kind, "part": name, "measured": value, "expected": data})
    return failures
