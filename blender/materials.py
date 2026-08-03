"""Palette handling and material creation.

Materials exist for the preview renders and the GLB; STL carries no colour.
Keeping them simple and node-light also keeps the .blend easy to open and edit,
which is half the point of shipping a .blend at all.
"""

import bpy

# Slot meaning is part of the CharacterSpec contract.
SLOT_BODY = 0
SLOT_ACCENT = 1
SLOT_DETAIL = 2


def hex_to_linear_rgba(value):
    """Convert an sRGB hex string to the linear RGBA Blender stores internally.

    Blender's colour inputs are linear; feeding sRGB values straight in makes
    every render noticeably washed out.
    """
    text = value.lstrip("#")
    srgb = [int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4)]
    return tuple(_srgb_to_linear(channel) for channel in srgb) + (1.0,)


def _srgb_to_linear(channel):
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


class Palette:
    """Resolves colour slots, repeating the last entry when a slot is missing."""

    def __init__(self, colors):
        if not colors:
            raise ValueError("a palette needs at least one colour")
        self.colors = list(colors)
        self._materials = {}

    def hex_for(self, slot):
        index = min(slot, len(self.colors) - 1)
        return self.colors[index]

    def material(self, slot, roughness=0.45, metallic=0.0):
        """Return (creating on first use) the material for a palette slot."""
        key = (slot, round(roughness, 3), round(metallic, 3))
        if key in self._materials:
            return self._materials[key]

        color = self.hex_for(slot)
        # The finish is part of the identity: a glossy eye and a matte body can
        # share palette slot 2 but are genuinely different materials, so the
        # name has to distinguish them or Blender appends .001 suffixes.
        material = bpy.data.materials.new(name="hbcb-slot%d-r%02d" % (slot, round(roughness * 100)))
        material.use_nodes = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is not None:
            principled.inputs["Base Color"].default_value = hex_to_linear_rgba(color)
            principled.inputs["Roughness"].default_value = roughness
            principled.inputs["Metallic"].default_value = metallic
        # diffuse_color drives the viewport and Workbench renders, so set it too.
        material.diffuse_color = hex_to_linear_rgba(color)
        self._materials[key] = material
        return material


def assign(obj, material):
    """Give `obj` exactly one material slot.

    Single-slot operands keep the material indices predictable after a boolean
    union, which is what lets the merged model stay multi-coloured.
    """
    obj.data.materials.clear()
    obj.data.materials.append(material)
    return obj
