# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent assertions over trusted Blender inspection JSON, with no author imports.

The intentionally separated height bands provide a geometry-level absence
check: the entire r1 hat is above the face, and every r2 accessory vertex is
below that band. Since all other semantic meshes match r0 byte-for-byte in
geometry, transform and material hashes, a hat cannot remain in a base mesh.
"""
from __future__ import annotations

from typing import Any

HASH_KEYS = ("geometry_hash", "transform_hash", "material_hash")
BASE_REQUIRED = {
    "body", "belly", "head", "ears", "inner_ears", "paws", "tail", "tail_tip",
    "eyes", "irises", "pupils", "highlights", "muzzle", "nose", "mouth",
    "whiskers", "cheeks", "collar", "bell",
}
ACCESSORY = "accessory"
HAT_MIN_Z = 2.40
GLASSES_MAX_Z = 2.15
GLASSES_MAX_Y = -0.70
GLASSES_LEFT_X = -0.20
GLASSES_RIGHT_X = 0.20
GLASSES_BRIDGE_X = 0.10


def fingerprints(observation: dict) -> dict[str, tuple[str, str, str]]:
    """Hashes produced by the independent scene inspector, for every semantic mesh."""
    return {
        name: tuple(part[key] for key in HASH_KEYS)
        for name, part in observation["parts"].items()
    }


def _bounds(vertices: list[list[float]]) -> dict[str, list[float]]:
    assert vertices, "empty mesh"
    return {
        "min": [min(v[axis] for v in vertices) for axis in range(3)],
        "max": [max(v[axis] for v in vertices) for axis in range(3)],
    }


def _components(vertex_count: int, edges: list[list[int]]) -> list[list[int]]:
    """Compute connected vertex sets from inspector edges, not author names."""
    adjacency = [set() for _ in range(vertex_count)]
    for edge in edges:
        assert len(edge) == 2 and all(type(i) is int and 0 <= i < vertex_count for i in edge)
        a, b = edge
        adjacency[a].add(b)
        adjacency[b].add(a)
    assert all(adjacency), "accessory has isolated vertices"
    unseen = set(range(vertex_count))
    components = []
    while unseen:
        start = unseen.pop()
        group = {start}
        frontier = [start]
        while frontier:
            for neighbor in adjacency[frontier.pop()]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    group.add(neighbor)
                    frontier.append(neighbor)
        components.append(sorted(group))
    return sorted(components, key=len, reverse=True)


def verify(observations: list[dict[str, Any]]) -> dict:
    assert len(observations) == 3, "expected r0, r1, r2 observations"
    r0, r1, r2 = (observation["parts"] for observation in observations)
    base = set(r0)
    assert base == BASE_REQUIRED, f"cat base parts differ: missing={BASE_REQUIRED-base}, extra={base-BASE_REQUIRED}"
    assert ACCESSORY not in base, "r0 already has accessory geometry"
    assert set(r1) == base | {ACCESSORY}, "r1 should add only the hat accessory"
    assert set(r2) == set(r1), "r2 should replace only the accessory geometry"
    for name in base:
        reference = tuple(r0[name][key] for key in HASH_KEYS)
        for revision, parts in (("r1", r1), ("r2", r2)):
            actual = tuple(parts[name][key] for key in HASH_KEYS)
            assert actual == reference, f"protected cat part {name} changed in {revision}"

    for revision, parts in (("r0", r0), ("r1", r1), ("r2", r2)):
        for name, part in parts.items():
            assert part["world_vertices"] and part["face_indices"], (revision, name, "empty geometry")
            assert part["nonmanifold_edges"] == 0, (revision, name, "open or nonmanifold mesh")
            assert part["signed_volume"] > 0, (revision, name, "nonpositive signed volume")

    hat = r1[ACCESSORY]
    glasses = r2[ACCESSORY]
    hat_vertices = hat["world_vertices"]
    glasses_vertices = glasses["world_vertices"]
    hat_bounds = _bounds(hat_vertices)
    glasses_bounds = _bounds(glasses_vertices)
    assert hat["geometry_hash"] != glasses["geometry_hash"], "accessory geometry did not change"
    assert hat_bounds["min"][2] >= HAT_MIN_Z, "r1 accessory descends into the face region"
    assert hat_bounds["max"][2] - hat_bounds["min"][2] >= 0.12, "r1 hat has no crown height"
    assert hat_bounds["max"][0] - hat_bounds["min"][0] >= 0.65, "r1 hat has no brim width"
    assert glasses_bounds["max"][2] <= GLASSES_MAX_Z, "r2 still has geometry in the hat region"
    assert glasses_bounds["max"][2] < hat_bounds["min"][2], "r2 overlaps the former hat height band"
    assert glasses_bounds["max"][1] < GLASSES_MAX_Y, "r2 eyewear is not entirely in front of the face"
    assert glasses_bounds["min"][0] < GLASSES_LEFT_X, "r2 has no left lens region"
    assert glasses_bounds["max"][0] > GLASSES_RIGHT_X, "r2 has no right lens region"
    assert any(-GLASSES_BRIDGE_X <= vertex[0] <= GLASSES_BRIDGE_X for vertex in glasses_vertices), "r2 has no bridge region"

    # All accessory vertices, not just a bounding-box corner or object origin,
    # must satisfy the height and forward-face constraints above. A leftover
    # hat object cannot hide under a different semantic ID because the part set
    # is exact and every protected base fingerprint is unchanged.
    assert all(vertex[2] <= GLASSES_MAX_Z and vertex[1] < GLASSES_MAX_Y for vertex in glasses_vertices)
    left_count = sum(vertex[0] < GLASSES_LEFT_X for vertex in glasses_vertices)
    right_count = sum(vertex[0] > GLASSES_RIGHT_X for vertex in glasses_vertices)
    assert left_count >= 8 and right_count >= 8, "r2 needs real geometry over both eyes"

    components = _components(len(glasses_vertices), glasses["edge_indices"])
    assert len(components) == 5, "r2 needs two lenses, bridge, and two temples"
    lens_components = sorted(
        components[:2], key=lambda group: sum(glasses_vertices[i][0] for i in group) / len(group)
    )
    lens_bounds = [_bounds([glasses_vertices[i] for i in group]) for group in lens_components]
    for group, bounds in zip(lens_components, lens_bounds):
        assert len(group) >= 20, "sunglass lens has too little geometry"
        assert bounds["max"][0] - bounds["min"][0] >= 0.35, "lens lacks oval width"
        assert bounds["max"][2] - bounds["min"][2] >= 0.24, "lens lacks oval height"
        assert bounds["max"][1] - bounds["min"][1] <= 0.09, "lens is too thick"
    left_center = (lens_bounds[0]["min"][0] + lens_bounds[0]["max"][0]) / 2
    right_center = (lens_bounds[1]["min"][0] + lens_bounds[1]["max"][0]) / 2
    assert -0.50 <= left_center <= -0.20 and 0.20 <= right_center <= 0.50, "lenses are not over both eyes"
    remaining_bounds = [_bounds([glasses_vertices[i] for i in group]) for group in components[2:]]
    assert any(b["min"][0] < -0.05 and b["max"][0] > 0.05 for b in remaining_bounds), "no bridge shell"
    assert any(b["max"][0] < -0.30 for b in remaining_bounds), "no left temple shell"
    assert any(b["min"][0] > 0.30 for b in remaining_bounds), "no right temple shell"

    return {
        "passed": True,
        "protected_base_parts": sorted(base),
        "protected_geometry_transform_material_hashes_equal": True,
        "r0_accessory_absent": True,
        "r1_hat_only": True,
        "r2_hat_geometry_absent": True,
        "r2_sunglasses_present": True,
        "r1_hat_bounds_m": hat_bounds,
        "r2_sunglasses_bounds_m": glasses_bounds,
        "r1_hat_vertices": len(hat_vertices),
        "r2_sunglasses_vertices": len(glasses_vertices),
        "r2_left_region_vertices": left_count,
        "r2_right_region_vertices": right_count,
        "r2_edge_connected_shells": len(components),
        "r2_lens_bounds_m": lens_bounds,
        "coverage": "All inspected semantic meshes and accessory vertices; render quality reviewed separately",
    }
