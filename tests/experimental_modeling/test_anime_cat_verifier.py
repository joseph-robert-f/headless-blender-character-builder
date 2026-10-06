# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-Python negative controls for the saved-observation cat verifier.

Synthetic observations exercise the independent logic; they are not Blender
evidence and cannot substitute for run_anime_cat.py's actual saved inspections.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_anime_cat import BASE_REQUIRED, verify


def _part(vertices, marker):
    return {
        "world_vertices": vertices,
        "face_indices": [[0, 1, 2]],
        "geometry_hash": marker + "g",
        "transform_hash": marker + "t",
        "material_hash": marker + "m",
        "nonmanifold_edges": 0,
        "signed_volume": 1.0,
        "edge_indices": [[i, i + 1] for i in range(len(vertices) - 1)],
    }


def _observations():
    base = {name: _part([[0, 0, 0], [1, 0, 0], [0, 1, 0]], name) for name in BASE_REQUIRED}
    hat = _part(
        [[-0.5, 0, 2.45], [0.5, 0, 2.45], [-0.3, 0, 2.7], [0.3, 0, 2.7]], "hat"
    )
    shells = []
    for center in (-0.34, 0.34):
        shells.append([
            [center + dx, -0.84, z]
            for dx in (-0.20, -0.12, -0.04, 0.04, 0.12, 0.20)
            for z in (1.80, 1.87, 1.94, 2.01, 2.08)
        ])
    shells.extend([
        [[-0.10, -0.85, 1.93], [-0.04, -0.85, 1.94], [0.04, -0.85, 1.94], [0.10, -0.85, 1.93]],
        [[-0.70, -0.80, 1.94], [-0.64, -0.80, 1.94], [-0.60, -0.80, 1.94], [-0.55, -0.80, 1.94]],
        [[0.55, -0.80, 1.94], [0.60, -0.80, 1.94], [0.64, -0.80, 1.94], [0.70, -0.80, 1.94]],
    ])
    glasses_vertices = [vertex for shell in shells for vertex in shell]
    glasses = _part(glasses_vertices, "glasses")
    glasses["edge_indices"] = []
    offset = 0
    for shell in shells:
        glasses["edge_indices"].extend([[offset + i, offset + i + 1] for i in range(len(shell) - 1)])
        offset += len(shell)
    return [
        {"parts": copy.deepcopy(base)},
        {"parts": {**copy.deepcopy(base), "accessory": hat}},
        {"parts": {**copy.deepcopy(base), "accessory": glasses}},
    ]


class AnimeCatVerifierTests(unittest.TestCase):
    def test_valid_spatial_and_hash_contract(self):
        self.assertTrue(verify(_observations())["passed"])

    def test_rejects_protected_face_change(self):
        observations = _observations()
        observations[2]["parts"]["head"]["geometry_hash"] = "changed"
        with self.assertRaisesRegex(AssertionError, "protected cat part head changed"):
            verify(observations)

    def test_rejects_leftover_hat_vertex(self):
        observations = _observations()
        observations[2]["parts"]["accessory"]["world_vertices"].append([0, 0, 2.6])
        with self.assertRaisesRegex(AssertionError, "hat region"):
            verify(observations)


if __name__ == "__main__":
    unittest.main()
