from __future__ import annotations

import unittest

from tests.blender_integration.g3_gate import _stable_glb_structure


class G3RepeatPolicyTests(unittest.TestCase):
    def _inspection(self) -> dict[str, int]:
        return {
            "accessor_count": 50,
            "bytes": 117_892,
            "material_count": 3,
            "mesh_count": 18,
            "position_vertex_count": 3_110,
            "primitive_count": 18,
        }

    def test_encoded_length_and_accessor_dedup_are_not_structural_fields(self) -> None:
        first = self._inspection()
        second = {
            **first,
            "accessor_count": first["accessor_count"] - 1,
            "bytes": first["bytes"] + 4,
        }
        self.assertEqual(_stable_glb_structure(first), _stable_glb_structure(second))

    def test_export_structure_changes_remain_release_blocking(self) -> None:
        first = self._inspection()
        second = {**first, "position_vertex_count": first["position_vertex_count"] + 1}
        self.assertNotEqual(_stable_glb_structure(first), _stable_glb_structure(second))


if __name__ == "__main__":
    unittest.main()
