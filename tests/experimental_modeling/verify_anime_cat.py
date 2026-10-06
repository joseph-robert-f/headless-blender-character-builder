# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent numeric assertions over the reviewed schema-v2 cat observations.

No author/controller imports. This is a regression contract for the reviewed
low-poly fixture, not a general cat recognizer or a watertightness certificate.
Converted tubes retain detached caps: r2 has 23 edge-connected shells, which
form nine pieces when coincident vertices are joined within one micrometer.
The cat and glasses each retain 168 reviewed boundary/nonmanifold edges.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import product
import math
from typing import Any

HASH_KEYS = ("geometry_hash", "transform_hash", "material_hash")
BASE_REQUIRED = {"cat"}
ACCESSORY = "accessory"
HAT_MIN_Z = 2.50
GLASSES_MAX_Z = 2.32
WELD_TOLERANCE = 1e-6

# Reviewed numeric contract, independent of the source builder and object names.
# Counts are vertices, edges, faces, triangles, boundary/nonmanifold edges.
COUNTS = {"cat": (1586, 3192, 1680, 2856, 168),
          "hat": (192, 336, 150, 372, 0),
          "glasses": (770, 1464, 712, 1336, 168)}
BOUNDS = {
    "cat": ((-.923153, -.795042, 0), (1.273213, .539655, 2.904417)),
    "hat": ((-.56, -.58, 2.595), (.56, .54, 3.15)),
    "glasses": ((-.771565, -.893991, 1.788617), (.771565, -.127309, 2.291383)),
}
PALETTES = {
    "cat": ((.93, .70, .43), (1, .94, .78), (.95, .34, .43),
            (.18, .54, .42), (.035, .027, .055), (1, 1, 1)),
    "hat": ((.21, .12, .39), (.94, .45, .26)),
    "glasses": ((.025, .07, .10), (.95, .63, .19), (1, 1, 1)),
}
MATERIAL_FACES = {"cat": (468, 360, 268, 80, 344, 160),
                  "hat": (100, 50), "glasses": (80, 580, 52)}


def fingerprints(observation: dict) -> dict[str, tuple[str, str, str]]:
    return {name: tuple(part[key] for key in HASH_KEYS)
            for name, part in observation["parts"].items()}


def _bounds(vertices: list[list[float]]) -> dict[str, list[float]]:
    assert vertices, "empty mesh"
    assert all(len(v) == 3 and all(type(x) in (int, float) and math.isfinite(x)
                                 for x in v) for v in vertices), "nonfinite/invalid vertex"
    return {"min": [min(v[a] for v in vertices) for a in range(3)],
            "max": [max(v[a] for v in vertices) for a in range(3)]}


def _near_bounds(bounds: dict, expected: tuple, label: str, tolerance: float = .015) -> None:
    assert all(len(bounds[side]) == 3 and all(math.isfinite(x) for x in bounds[side])
               for side in ("min", "max")), f"{label} invalid bounds"
    assert all(abs(actual - wanted) <= tolerance
               for side, values in zip(("min", "max"), expected)
               for actual, wanted in zip(bounds[side], values)), f"{label} bounds differ"


def _components(vertex_count: int, edges: list[list[int]],
                vertices: list[list[float]] | None = None) -> list[list[int]]:
    """Edge components; optionally join coincident positions, never names."""
    adjacency = [set() for _ in range(vertex_count)]
    for edge in edges:
        assert len(edge) == 2 and all(type(i) is int and 0 <= i < vertex_count for i in edge), "invalid edge"
        a, b = edge
        assert a != b, "degenerate edge"
        adjacency[a].add(b)
        adjacency[b].add(a)
    assert all(adjacency), "accessory has isolated vertices"
    if vertices is not None:
        buckets: dict[tuple, list[int]] = defaultdict(list)
        for i, v in enumerate(vertices):
            cell = tuple(math.floor(x / WELD_TOLERANCE) for x in v)
            for delta in product((-1, 0, 1), repeat=3):
                for j in buckets[tuple(a + b for a, b in zip(cell, delta))]:
                    if math.dist(v, vertices[j]) <= WELD_TOLERANCE:
                        adjacency[i].add(j)
                        adjacency[j].add(i)
            buckets[cell].append(i)
    unseen = set(range(vertex_count))
    components = []
    while unseen:
        start = unseen.pop()
        group, frontier = {start}, [start]
        while frontier:
            for neighbor in adjacency[frontier.pop()]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    group.add(neighbor)
                    frontier.append(neighbor)
        components.append(sorted(group))
    return sorted(components, key=lambda group: (-len(group), group[0]))


def _check_part(part: dict, kind: str) -> dict:
    vertices = part["world_vertices"]
    bounds = _bounds(vertices)
    expected = COUNTS[kind]
    for singular, plural, key, count in zip(
        ("vertex", "edge", "face", "triangle"), ("vertices", "edges", "faces", None),
        ("world_vertices", "edge_indices", "face_indices", "triangle_indices"), expected[:4]
    ):
        assert len(part[key]) == part[singular + "_count"] == count, f"{kind} {singular} count differs"
        if plural:
            assert part[plural] == count, f"{kind} {plural} alias differs"
    assert part["boundary_edges"] == part["nonmanifold_edges"] == expected[4], f"{kind} reviewed boundary topology differs"
    assert math.isfinite(part["signed_volume"]) and part["signed_volume"] > 0, f"{kind} nonpositive signed volume"
    assert math.isfinite(part["surface_area"]) and part["surface_area"] > 0, f"{kind} nonpositive surface area"
    _near_bounds(bounds, BOUNDS[kind], kind)
    _near_bounds(part["world_bounds"], (bounds["min"], bounds["max"]),
                 kind + " declared", tolerance=1e-6)
    for key in HASH_KEYS:
        digest = part[key]
        assert isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), f"{kind} invalid {key}"
    for key, size in (("edge_indices", 2), ("face_indices", None), ("triangle_indices", 3)):
        for row in part[key]:
            assert (len(row) == size if size else len(row) >= 3), f"{kind} invalid {key}"
            assert all(type(i) is int and 0 <= i < len(vertices) for i in row), f"{kind} invalid vertex index"
            assert len(set(row)) == len(row), f"{kind} repeated face/edge vertex"
    usage = Counter(tuple(sorted((a, b))) for face in part["face_indices"]
                    for a, b in zip(face, face[1:] + face[:1]))
    edges = [tuple(sorted(edge)) for edge in part["edge_indices"]]
    assert len(set(edges)) == len(edges) and set(edges) == set(usage), f"{kind} edge/face topology differs"
    assert sum(n == 1 for n in usage.values()) == expected[4], f"{kind} measured boundary topology differs"
    assert sum(n != 2 for n in usage.values()) == expected[4], f"{kind} measured nonmanifold topology differs"
    assert sum(len(face) - 2 for face in part["face_indices"]) == expected[3], f"{kind} polygon triangulation count differs"
    materials = part["materials"]
    assert len(materials) == len(PALETTES[kind]), f"{kind} material slots differ"
    for i, (material, rgb) in enumerate(zip(materials, PALETTES[kind])):
        assert len(material["base_color"]) == 4 and all(
            math.isfinite(a) and abs(a - b) <= 1e-6
            for a, b in zip(material["base_color"], (*rgb, 1))), f"{kind} material color differs"
        roughness = .32 if (kind == "cat" and i in (3, 4)) or (kind == "glasses" and i == 0) else .62
        assert math.isfinite(material["roughness"]) and abs(material["roughness"] - roughness) <= 1e-6, f"{kind} material roughness differs"
        assert math.isfinite(material["metallic"]) and abs(material["metallic"]) <= 1e-6, f"{kind} material metallic differs"
    for key, rows in (("face_material_indices", part["face_indices"]),
                      ("triangle_material_indices", part["triangle_indices"])):
        indices = part[key]
        assert len(indices) == len(rows), f"{kind} material assignment count differs"
        assert all(type(i) is int and 0 <= i < len(materials) for i in indices), f"{kind} invalid material index"
        assert set(indices) == set(range(len(materials))), f"{kind} unused material color"
    counts = Counter(part["face_material_indices"])
    assert tuple(counts[i] for i in range(len(materials))) == MATERIAL_FACES[kind], f"{kind} material face usage differs"
    return bounds


def _piece_rows(part: dict, *, weld: bool) -> list[dict]:
    vertices = part["world_vertices"]
    groups = _components(len(vertices), part["edge_indices"], vertices if weld else None)
    owner = {vertex: i for i, group in enumerate(groups) for vertex in group}
    rows = [{"indices": group, "faces": [], "materials": set(),
             "bounds": _bounds([vertices[i] for i in group])} for group in groups]
    for face, material in zip(part["face_indices"], part["face_material_indices"]):
        owners = {owner[i] for i in face}
        assert len(owners) == 1, "face crosses disconnected components"
        row = rows[owners.pop()]
        row["faces"].append(face)
        row["materials"].add(material)
    return rows


def _check_hat(hat: dict) -> None:
    rows = _piece_rows(hat, weld=False)
    assert len(rows) == 3, "hat needs brim, crown, and ribbon components"
    rows.sort(key=lambda row: row["bounds"]["min"][2])
    specifications = (
        (((-.56, -.58, 2.595), (.56, .54, 2.685)), 0),
        (((-.37, -.39, 2.67), (.37, .35, 3.15)), 0),
        (((-.38, -.40, 2.70), (.38, .36, 2.82)), 1),
    )
    for row, (bounds, material) in zip(rows, specifications):
        assert len(row["indices"]) == 64 and len(row["faces"]) == 50, "hat component topology differs"
        assert row["materials"] == {material}, "hat component material differs"
        _near_bounds(row["bounds"], bounds, "hat component")


def _check_glasses(glasses: dict) -> tuple[list[dict], list[dict]]:
    vertices = glasses["world_vertices"]
    raw = _piece_rows(glasses, weld=False)
    assert Counter(len(row["indices"]) for row in raw) == {222: 2, 42: 3, 34: 2, 24: 2, 6: 14}, "glasses raw shell topology differs"
    pieces = _piece_rows(glasses, weld=True)
    assert len(pieces) == 9, "glasses need nine position-welded components"
    lenses = [row for row in pieces if row["materials"] == {0}]
    rims = [row for row in pieces if row["materials"] == {1} and len(row["indices"]) == 234]
    bars = [row for row in pieces if row["materials"] == {1} and len(row["indices"]) == 54]
    glints = [row for row in pieces if row["materials"] == {2}]
    assert (len(lenses), len(rims), len(bars), len(glints)) == (2, 2, 3, 2), "glasses need two lenses, rims, temples, glints, and bridge"
    for collection in (lenses, rims, bars, glints):
        collection.sort(key=lambda row: row["bounds"]["min"][0])
    for side, lens, rim, glint in zip((-1, 1), lenses, rims, glints):
        center = side * .32
        assert len(lens["indices"]) == 34 and len(lens["faces"]) == 40, "lens topology differs"
        _near_bounds(lens["bounds"], ((center-.256785, -.871819, 1.825),
                                    (center+.256785, -.748181, 2.255)), "lens")
        # Every lens vertex must lie on the reviewed ellipsoid, not merely
        # provide the right extrema (boxes and collapsed/bent lenses fail).
        for i in lens["indices"]:
            x, y, z = vertices[i]
            radius = ((x-center)/.27)**2 + ((y+.81)/.065)**2 + ((z-2.04)/.215)**2
            assert abs(radius-1) < .015, "lens is not the reviewed oval surface"
        assert len(rim["faces"]) == 224, "rim topology differs"
        _near_bounds(rim["bounds"], ((center-.309, -.837, 1.789),
                                   (center+.309, -.783, 2.291)), "rim")
        for i in rim["indices"]:
            x, y, z = vertices[i]
            radius = math.hypot((x-center)/.285, (z-2.04)/.228)
            assert .85 < radius < 1.15 and abs(y+.81) <= .028, "rim does not surround the lens"
        assert len(glint["indices"]) == 36 and len(glint["faces"]) == 26, "glint topology differs"
        _near_bounds(glint["bounds"], ((center-.125404, -.893991, 2.109028),
                                     (center-.029596, -.863009, 2.170971)), "glint")
    bar_bounds = (
        ((-.771565, -.801841, 2.056023), (-.564627, -.127309, 2.154501)),
        ((-.082309, -.870941, 2.079119), (.082309, -.795515, 2.153339)),
        ((.564627, -.801841, 2.056023), (.771565, -.127309, 2.154501)),
    )
    for bar, bounds, name in zip(bars, bar_bounds, ("left temple", "bridge", "right temple")):
        assert len(bar["faces"]) == 44, f"{name} topology differs"
        _near_bounds(bar["bounds"], bounds, name)
    return raw, lenses


def verify(observations: list[dict[str, Any]]) -> dict:
    assert len(observations) == 3, "expected r0, r1, r2 observations"
    for observation in observations:
        assert observation["schema_version"] == 2 and observation["trusted_observation"] is True, "trusted schema-v2 observation required"
        assert observation["units"] == {"length": "meter", "scale_length": 1.0,
                                        "area": "square_meter", "volume": "cubic_meter"}, "meter observation required"
        assert observation["runtime"]["autoexec_enabled"] is False, "inspection autoexec must be disabled"
    r0, r1, r2 = (observation["parts"] for observation in observations)
    assert set(r0) == BASE_REQUIRED, "r0 must contain only the protected cat"
    assert set(r1) == set(r2) == BASE_REQUIRED | {ACCESSORY}, "revisions may contain only cat and accessory"
    for revision, parts in (("r1", r1), ("r2", r2)):
        assert fingerprints({"parts": {"cat": parts["cat"]}}) == fingerprints(observations[0]), f"protected cat part cat changed in {revision}"
        # Equality of inspector hashes is necessary. Compare their observable
        # payload too, so an accidentally stale hash cannot conceal a change.
        assert parts["cat"] == r0["cat"], f"protected cat observation changed in {revision}"
    for parts in (r0, r1, r2):
        _check_part(parts["cat"], "cat")
    hat, glasses = r1[ACCESSORY], r2[ACCESSORY]
    hat_bounds, glasses_bounds = _bounds(hat["world_vertices"]), _bounds(glasses["world_vertices"])
    assert hat["geometry_hash"] != glasses["geometry_hash"], "accessory geometry did not change"
    assert hat_bounds["min"][2] >= HAT_MIN_Z, "hat descends below reviewed hat region"
    assert glasses_bounds["max"][2] <= GLASSES_MAX_Z, "r2 still has geometry in the hat region"
    assert glasses_bounds["max"][2] < hat_bounds["min"][2], "r2 overlaps former hat height band"
    _check_part(hat, "hat")
    _check_part(glasses, "glasses")
    _check_hat(hat)
    raw, lenses = _check_glasses(glasses)
    return {
        "passed": True, "observation_schema_version": 2,
        "protected_base_parts": ["cat"],
        "protected_geometry_transform_material_hashes_equal": True,
        "protected_observation_payloads_equal": True,
        "r0_accessory_absent": True, "r1_hat_only": True,
        "r2_hat_geometry_absent": True, "r2_sunglasses_present": True,
        "r1_hat_bounds_m": hat_bounds, "r2_sunglasses_bounds_m": glasses_bounds,
        "r1_hat_vertices": len(hat["world_vertices"]),
        "r2_sunglasses_vertices": len(glasses["world_vertices"]),
        "r2_vertices_in_hat_band": sum(v[2] >= HAT_MIN_Z for v in glasses["world_vertices"]),
        "r2_edge_connected_shells": len(raw), "r2_position_welded_components": 9,
        "r2_component_weld_tolerance_m": WELD_TOLERANCE,
        "r2_lens_bounds_m": [row["bounds"] for row in lenses],
        "schema_v2_material_colors_and_face_usage_verified": True,
        "reviewed_boundary_edges": {"cat": 168, "hat": 0, "sunglasses": 168},
        "watertight": False,
        "coverage": "All semantic meshes, accessory vertices, component shapes and used materials; render quality reviewed separately",
    }
