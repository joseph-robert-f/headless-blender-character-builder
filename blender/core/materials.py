"""Deterministic native Blender materials with no external resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import bpy


@dataclass(frozen=True)
class MaterialSet:
    palette: tuple[bpy.types.Material, ...]
    feature: bpy.types.Material
    printable: bpy.types.Material


def _hex_rgb(color: str) -> tuple[float, float, float]:
    if len(color) != 7 or not color.startswith("#"):
        raise ValueError(f"invalid reviewed color: {color!r}")
    return tuple(int(color[index : index + 2], 16) / 255.0 for index in (1, 3, 5))


def _material(
    name: str,
    color: tuple[float, float, float],
    *,
    roughness: float,
) -> bpy.types.Material:
    if name in bpy.data.materials:
        raise ValueError(f"duplicate deterministic material name: {name}")
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    material.diffuse_color = (*color, 1.0)
    material.metallic = 0.0
    material.roughness = roughness
    node = material.node_tree.nodes.get("Principled BSDF")
    if node is not None:
        node.inputs["Base Color"].default_value = (*color, 1.0)
        node.inputs["Metallic"].default_value = 0.0
        node.inputs["Roughness"].default_value = roughness
        node.inputs["Alpha"].default_value = 1.0
    material["builder_native_material"] = True
    return material


def create_material_set(
    palette: Iterable[str], material_preset: str
) -> MaterialSet:
    """Create one closed palette plus fixed diagnostic/print materials."""

    roughness_by_preset = {"matte": 0.78, "satin": 0.48, "glossy": 0.25}
    if material_preset not in roughness_by_preset:
        raise ValueError(f"unsupported material preset: {material_preset!r}")
    roughness = roughness_by_preset[material_preset]
    colors = tuple(palette)
    if not colors:
        raise ValueError("the reviewed palette cannot be empty")
    palette_materials = tuple(
        _material(
            f"MAT_Palette_{index:02d}_{color[1:]}",
            _hex_rgb(color),
            roughness=roughness,
        )
        for index, color in enumerate(colors, start=1)
    )
    feature = _material("MAT_Feature_Charcoal", (0.035, 0.045, 0.055), roughness=0.52)
    printable = _material("MAT_PrintableShell", (0.54, 0.56, 0.60), roughness=0.82)
    return MaterialSet(palette_materials, feature, printable)
