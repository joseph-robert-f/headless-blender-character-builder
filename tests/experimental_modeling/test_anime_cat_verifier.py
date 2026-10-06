# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic inspector-payload controls, requiring no Blender or saved artifacts.

These independently constructed primitives exercise the numeric verifier; the
synthetic cat is only a topology/palette stand-in, not visual Blender evidence.
The runner additionally verifies real saved inspections of the reviewed cat.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_anime_cat import _bounds, _components, verify


PALETTES = {
    "cat": ((.93, .70, .43), (1, .94, .78), (.95, .34, .43),
            (.18, .54, .42), (.035, .027, .055), (1, 1, 1)),
    "hat": ((.21, .12, .39), (.94, .45, .26)),
    "glasses": ((.025, .07, .10), (.95, .63, .19), (1, 1, 1)),
}


def _sphere(center, scale):
    vertices = [[center[0], center[1], center[2] + scale[2]],
                [center[0], center[1], center[2] - scale[2]]]
    for latitude in range(1, 5):
        for longitude in range(8):
            theta, phi = latitude * math.pi / 5, longitude * math.pi / 4
            vertices.append([center[0] + scale[0] * math.sin(theta) * math.cos(phi),
                             center[1] + scale[1] * math.sin(theta) * math.sin(phi),
                             center[2] + scale[2] * math.cos(theta)])
    faces = [[0, 2+i, 2+(i+1)%8] for i in range(8)]
    faces += [[1, 26+(i+1)%8, 26+i] for i in range(8)]
    faces += [[2+r*8+i, 2+r*8+(i+1)%8, 10+r*8+(i+1)%8, 10+r*8+i]
              for r in range(3) for i in range(8)]
    return vertices, faces


def _tube(centers, radius, frame=None):
    """Six-sided tube with separate triangulated cap vertices, like inspection."""
    vertices = []
    for i, center in enumerate(centers):
        u, v = frame(i) if frame else ((1, 0, 0), (0, 0, 1))
        for j in range(6):
            angle = j * math.pi / 3
            vertices.append([center[a] + radius * (u[a]*math.cos(angle) + v[a]*math.sin(angle))
                             for a in range(3)])
    faces = [[r*6+i, r*6+(i+1)%6, (r+1)*6+(i+1)%6, (r+1)*6+i]
             for r in range(len(centers)-1) for i in range(6)]
    for ring in (0, (len(centers)-1)*6):
        offset = len(vertices)
        vertices.extend(copy.deepcopy(vertices[ring:ring+6]))
        faces.extend([[offset, offset+i, offset+i+1] for i in range(1, 5)])
    return vertices, faces


def _cylinder(radius, low, high, rings=4, sides=16, ear=False):
    vertices = [[radius*math.cos(i*2*math.pi/sides), -.02+radius*math.sin(i*2*math.pi/sides),
                 low+(high-low)*r/(rings-1)] for r in range(rings) for i in range(sides)]
    faces = [[r*sides+i, r*sides+(i+1)%sides, (r+1)*sides+(i+1)%sides, (r+1)*sides+i]
             for r in range(rings-1) for i in range(sides)]
    for offset in (0, (rings-1)*sides):
        if ear:
            faces.extend([[offset, offset+i, offset+i+1] for i in range(1, 5)])
            faces.append([offset, offset+5, offset+6, offset+7])
        else:
            faces.append(list(range(offset, offset+sides)))
    return vertices, faces


def _part(kind, shells):
    vertices, faces, face_materials = [], [], []
    for (points, polygons), material in shells:
        offset = len(vertices)
        vertices.extend(points)
        faces.extend([[offset+i for i in face] for face in polygons])
        face_materials.extend([material]*len(polygons))
    usage = Counter(tuple(sorted((a, b))) for face in faces
                    for a, b in zip(face, face[1:]+face[:1]))
    triangles, triangle_materials = [], []
    for face, material in zip(faces, face_materials):
        for j in range(1, len(face)-1):
            triangles.append([face[0], face[j], face[j+1]])
            triangle_materials.append(material)
    materials = []
    for i, rgb in enumerate(PALETTES[kind]):
        roughness = .32 if (kind == "cat" and i in (3, 4)) or (kind == "glasses" and i == 0) else .62
        materials.append({"base_color": [*rgb, 1], "roughness": roughness, "metallic": 0})
    return {
        "world_vertices": vertices, "world_bounds": _bounds(vertices),
        "edge_indices": [list(edge) for edge in usage], "face_indices": faces,
        "triangle_indices": triangles, "face_material_indices": face_materials,
        "triangle_material_indices": triangle_materials, "materials": materials,
        **{key: hashlib.sha256((kind+key).encode()).hexdigest()
           for key in ("geometry_hash", "transform_hash", "material_hash")},
        "vertex_count": len(vertices), "vertices": len(vertices),
        "edge_count": len(usage), "edges": len(usage),
        "face_count": len(faces), "faces": len(faces), "triangle_count": len(triangles),
        "boundary_edges": sum(n == 1 for n in usage.values()),
        "nonmanifold_edges": sum(n != 2 for n in usage.values()),
        "surface_area": 1.0, "signed_volume": 1.0,
    }


def _cat():
    shells = []
    for material, number in enumerate((6, 9, 3, 2, 2, 4)):
        shells.extend([(_sphere((0, 0, 1), (.3, .2, .4)), material) for _ in range(number)])
    for material in (0, 0, 2, 2):
        shells.append((_cylinder(.3, 1, 2, rings=9, sides=8, ear=True), material))
    for _ in range(6):
        shells.append((_tube([(i*.1, 0, 1) for i in range(7)], .02), 4))
    shells.append((_tube([(i*.1, 0, 1) for i in range(13)], .1), 0))
    part = _part("cat", shells)
    old = part["world_bounds"]
    low, high = (-.923153, -.795042, 0), (1.273213, .539655, 2.904417)
    for vertex in part["world_vertices"]:
        for axis in range(3):
            vertex[axis] = low[axis]+(vertex[axis]-old["min"][axis])/(old["max"][axis]-old["min"][axis])*(high[axis]-low[axis])
    part["world_bounds"] = _bounds(part["world_vertices"])
    return part


def _glasses():
    shells = []
    for side in (-1, 1):
        center = side*.32
        shells.append((_sphere((center, -.81, 2.04), (.27, .065, .215)), 0))
        centers = [(center+.285*math.cos(i*math.pi/18), -.81,
                    2.04+.228*math.sin(i*math.pi/18)) for i in range(37)]
        frame = lambda i: ((math.cos(i*math.pi/18), 0, math.sin(i*math.pi/18)), (0, 1, 0))
        shells.append((_tube(centers, .027, frame), 1))
        centers = [(side*x, y, z) for x, y, z in (
            (.59, -.79, 2.08), (.66, -.69, 2.11), (.72, -.59, 2.125),
            (.744, -.49, 2.13), (.742, -.37, 2.12), (.738, -.25, 2.105), (.73, -.13, 2.09))]
        shells.append((_tube(centers, .028), 1))
        centers = [(center-.12+.085*i/3, -.877-.003*i/3, 2.12+.04*i/3) for i in range(4)]
        shells.append((_tube(centers, .014, lambda i: ((0, 1, 0), (0, 0, 1))), 2))
    centers = [(-.07+.14*i/6, -.82-.025*math.sin(i*math.pi/6),
                2.10+.03*math.sin(i*math.pi/6)) for i in range(7)]
    shells.append((_tube(centers, .026, lambda i: ((.5, .8660254, 0), (0, 0, 1))), 1))
    return _part("glasses", shells)


def _observations():
    cat = _cat()
    hat = _part("hat", [(_cylinder(.56, 2.595, 2.685), 0),
                        (_cylinder(.37, 2.67, 3.15), 0), (_cylinder(.38, 2.70, 2.82), 1)])
    header = {"schema_version": 2, "trusted_observation": True,
              "units": {"length": "meter", "scale_length": 1.0,
                        "area": "square_meter", "volume": "cubic_meter"},
              "runtime": {"autoexec_enabled": False}}
    return [{**copy.deepcopy(header), "parts": parts} for parts in (
        {"cat": copy.deepcopy(cat)}, {"cat": copy.deepcopy(cat), "accessory": hat},
        {"cat": copy.deepcopy(cat), "accessory": _glasses()})]


class AnimeCatVerifierTests(unittest.TestCase):
    def setUp(self):
        self.observations = _observations()
        self.glasses = self.observations[2]["parts"]["accessory"]

    def assertRejected(self, pattern):
        with self.assertRaisesRegex(AssertionError, pattern):
            verify(self.observations)

    def refresh_bounds(self):
        self.glasses["world_bounds"] = _bounds(self.glasses["world_vertices"])

    def test_valid_spatial_hash_palette_and_component_contract(self):
        report = verify(self.observations)
        self.assertTrue(report["passed"])
        self.assertEqual(report["r2_edge_connected_shells"], 23)
        self.assertEqual(report["r2_position_welded_components"], 9)
        self.assertEqual(report["r2_vertices_in_hat_band"], 0)
        self.assertFalse(report["watertight"])

    def test_rejects_protected_geometry_transform_and_material_changes(self):
        for key in ("geometry_hash", "transform_hash", "material_hash"):
            with self.subTest(key=key):
                self.setUp()
                self.observations[2]["parts"]["cat"][key] = "0"*64
                self.assertRejected("protected cat part cat changed")

    def test_rejects_changed_protected_payload_even_with_stale_hash(self):
        self.observations[1]["parts"]["cat"]["world_vertices"][0][0] += .15
        self.assertRejected("protected cat observation changed")

    def test_rejects_extra_semantic_hat_mesh(self):
        self.observations[2]["parts"]["hat"] = self.observations[1]["parts"]["accessory"]
        self.assertRejected("only cat and accessory")

    def test_rejects_accessory_in_original(self):
        self.observations[0]["parts"]["accessory"] = self.glasses
        self.assertRejected("only the protected cat")

    def test_rejects_leftover_hat_vertex(self):
        self.glasses["world_vertices"][0][2] = 2.6
        self.assertRejected("hat region")

    def test_rejects_hat_as_final_accessory(self):
        self.observations[2]["parts"]["accessory"] = copy.deepcopy(self.observations[1]["parts"]["accessory"])
        self.assertRejected("geometry did not change")

    def test_rejects_flat_hat_crown(self):
        hat = self.observations[1]["parts"]["accessory"]
        for vertex in hat["world_vertices"][64:128]:
            vertex[2] = 2.75
        hat["world_bounds"] = _bounds(hat["world_vertices"])
        self.assertRejected("hat bounds differ")

    def test_rejects_wrong_schema_or_units(self):
        self.observations[0]["schema_version"] = 1
        self.assertRejected("schema-v2")
        self.observations[0]["schema_version"] = 2
        self.observations[0]["units"]["scale_length"] = .01
        self.assertRejected("meter observation")

    def test_rejects_untrusted_or_autoexec_observation(self):
        self.observations[1]["trusted_observation"] = False
        self.assertRejected("trusted schema-v2")
        self.observations[1]["trusted_observation"] = True
        self.observations[1]["runtime"]["autoexec_enabled"] = True
        self.assertRejected("autoexec")

    def test_rejects_wrong_material_color_roughness_or_alpha(self):
        for field, value in (("base_color", [1, 0, 0, 1]), ("base_color", [.025, .07, .10, .1]),
                             ("roughness", .9), ("metallic", 1)):
            with self.subTest(field=field, value=value):
                self.setUp()
                self.glasses["materials"][0][field] = value
                self.assertRejected("material (color|roughness|metallic) differs")

    def test_rejects_unused_lens_color(self):
        self.glasses["face_material_indices"] = [1 if i == 0 else i for i in self.glasses["face_material_indices"]]
        self.assertRejected("unused material color")

    def test_rejects_wrong_material_face_usage(self):
        self.glasses["face_material_indices"][0] = 1
        self.assertRejected("material face usage differs")

    def test_rejects_lens_material_swapped_with_frame_preserving_totals(self):
        materials = self.glasses["face_material_indices"]
        first_lens = [i for i, m in enumerate(materials) if m == 0][:40]
        first_frame = [i for i, m in enumerate(materials) if m == 1][:40]
        for i in first_lens:
            materials[i] = 1
        for i in first_frame:
            materials[i] = 0
        self.assertRejected("two lenses, rims")

    def test_rejects_absent_lens(self):
        del self.glasses["world_vertices"][:34]
        self.assertRejected("vertex count differs")

    def test_rejects_collapsed_lens_with_other_bounds_preserved(self):
        for vertex in self.glasses["world_vertices"][:34]:
            vertex[0] = -.32
        self.refresh_bounds()
        self.assertRejected("lens bounds differ")

    def test_rejects_box_shaped_lens_with_same_extrema(self):
        # One non-extreme sphere sample moves inside its bounding box. The
        # component counts, material assignments and global bounds stay fixed.
        vertex = self.glasses["world_vertices"][3]
        vertex[:] = [-.45, -.81, 2.10]
        self.refresh_bounds()
        self.assertRejected("reviewed oval surface")

    def test_rejects_detached_caps_beyond_weld_tolerance(self):
        # First rim has 222 side vertices and two six-vertex cap islands.
        for vertex in self.glasses["world_vertices"][256:262]:
            vertex[1] += .0001
        self.refresh_bounds()
        self.assertRejected("nine position-welded")

    def test_rejects_missing_bridge_geometry(self):
        for vertex in self.glasses["world_vertices"][-54:]:
            vertex[0] += .15
        self.refresh_bounds()
        self.assertRejected("bridge bounds differ")

    def test_rejects_rim_collapsed_inside_unchanged_extrema(self):
        self.glasses["world_vertices"][50] = [-.32, -.81, 2.04]
        self.refresh_bounds()
        self.assertRejected("rim does not surround")

    def test_rejects_forged_bounds_and_counts(self):
        self.glasses["world_bounds"]["min"][0] -= .2
        self.assertRejected("declared bounds differ")
        self.refresh_bounds()
        self.glasses["face_count"] -= 1
        self.assertRejected("face count differs")

    def test_rejects_changed_boundary_topology(self):
        self.glasses["boundary_edges"] = 0
        self.assertRejected("reviewed boundary topology")

    def test_rejects_nonfinite_vertex_or_material(self):
        self.glasses["world_vertices"][0][0] = float("nan")
        self.assertRejected("nonfinite/invalid vertex")
        self.setUp()
        self.glasses["materials"][0]["roughness"] = float("nan")
        self.assertRejected("material roughness")

    def test_rejects_invalid_edge_indices(self):
        self.glasses["edge_indices"][0][0] = -1
        self.assertRejected("invalid vertex index")

    def test_weld_does_not_join_nearby_distinct_geometry(self):
        vertices = [[0, 0, 0], [1, 0, 0], [0, 0, .0001], [1, 0, .0001]]
        self.assertEqual(len(_components(4, [[0, 1], [2, 3]], vertices)), 2)


if __name__ == "__main__":
    unittest.main()
