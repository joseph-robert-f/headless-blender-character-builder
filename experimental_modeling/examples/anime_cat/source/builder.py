# SPDX-License-Identifier: GPL-3.0-or-later
"""Reviewed fixture entry point: --params JSON --output SCENE.BLEND."""

import argparse
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy
from composition import parts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1:]
    args = parser.parse_args(argv)
    params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    if set(params) != {"accessory", "body_shift_x"}:
        raise ValueError("Unexpected fixture parameters")
    if not math.isfinite(params["body_shift_x"]):
        raise ValueError("Non-finite body shift")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    for semantic_id, (geometry, color) in parts(params).items():
        vertices, faces = geometry
        mesh = bpy.data.meshes.new(semantic_id)
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        material = bpy.data.materials.new(semantic_id + "_material")
        material.diffuse_color = color
        material.roughness = .53
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = .53
        mesh.materials.append(material)
        obj = bpy.data.objects.new(semantic_id, mesh)
        obj["semantic_id"] = semantic_id
        bpy.context.collection.objects.link(obj)

    bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()))


if __name__ == "__main__":
    main()
