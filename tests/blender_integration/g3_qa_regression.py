"""Blender-side regression for a vertex-pinched pair of closed shells."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blender.qa.geometry import analyze_mesh_object


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new("PinchedShellMesh")
    # Each tetrahedron is individually closed and outward wound.  They share
    # only vertex 0, producing two face-connected shells and a bow-tie vertex
    # while every edge still has exactly two incident faces.
    vertices = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (-1.0, 0.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, -1.0),
    )
    faces = (
        (0, 2, 1),
        (0, 1, 3),
        (0, 3, 2),
        (1, 2, 3),
        (0, 4, 5),
        (0, 6, 4),
        (0, 5, 6),
        (4, 6, 5),
    )
    mesh.from_pydata(vertices, (), faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("PinchedShell", mesh)
    bpy.context.scene.collection.objects.link(obj)

    evidence = analyze_mesh_object(obj)
    if evidence["non_manifold_edges"] != 0:
        raise AssertionError("regression fixture must keep every edge manifold")
    if evidence["connected_shells"] != 2:
        raise AssertionError("production QA did not detect two face-connected shells")
    if evidence["non_manifold_vertices"] < 1:
        raise AssertionError("production QA did not detect the bow-tie vertex")
    print("G3_QA_REGRESSION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
