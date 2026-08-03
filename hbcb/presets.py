"""Named character presets.

The fastest path to a printable file should not require authoring JSON. These
presets are complete, valid `BuildRequest` documents that `hbcb build --preset
<name>` submits directly, and that `hbcb preset show <name>` prints so a user
can save one and start editing rather than starting from a blank file.

All three are original geometric designs composed from Blender primitives.
"""

import copy

_PRESETS = {
    "facet-bot": {
        "summary": "Faceted desk-toy robot. The default example; blocky and forgiving to print.",
        "request": {
            "request_version": "build/v1",
            "generator": "geometric-character@1.0.0",
            "spec": {
                "spec_version": "character/v1",
                "name": "facet-bot",
                "style": "geometric",
                "height_mm": 95,
                "pose": "standing",
                "palette": ["#E87532", "#FFF3D6", "#2E3138"],
                "proportions": {"head_scale": 1.2, "limb_scale": 0.95},
                "features": {"eyes": "dot", "ears": "antenna"},
                "base": {"enabled": True, "shape": "round", "height_mm": 4, "margin_mm": 3},
            },
        },
    },
    "cocoa-cub": {
        "summary": "Chibi cub with round ears and a stub tail. Thick limbs, no supports needed.",
        "request": {
            "request_version": "build/v1",
            "generator": "geometric-character@1.0.0",
            "spec": {
                "spec_version": "character/v1",
                "name": "cocoa-cub",
                "style": "chibi",
                "height_mm": 70,
                "pose": "standing",
                "palette": ["#7A4B2A", "#E9C9A8", "#2A1B12"],
                "proportions": {"head_scale": 1.8, "torso_width": 1.25, "leg_length": 0.7},
                "features": {"eyes": "dot", "ears": "round", "tail": "stub"},
                "base": {"enabled": True, "shape": "round", "height_mm": 3, "margin_mm": 2},
            },
        },
    },
    "crystal-scout": {
        "summary": "Low-poly scout with antenna and backpack. Wide stance, taller and slimmer.",
        "request": {
            "request_version": "build/v1",
            "generator": "geometric-character@1.0.0",
            "spec": {
                "spec_version": "character/v1",
                "name": "crystal-scout",
                "style": "low_poly",
                "height_mm": 120,
                "pose": "wide_stance",
                "palette": ["#3E7CB1", "#D8E2E9", "#1B2A33"],
                "proportions": {"head_scale": 0.9, "torso_width": 0.85, "leg_length": 1.25},
                "features": {"eyes": "visor", "ears": "antenna", "backpack": True},
                "base": {"enabled": True, "shape": "square", "height_mm": 4, "margin_mm": 4},
            },
        },
    },
}


def names():
    return sorted(_PRESETS)


def summary(name):
    return _PRESETS[name]["summary"]


def get(name):
    """Return a fresh copy of a preset request, safe for the caller to mutate."""
    if name not in _PRESETS:
        raise KeyError(name)
    return copy.deepcopy(_PRESETS[name]["request"])


def listing():
    """(name, summary) pairs for CLI help output."""
    return [(name, _PRESETS[name]["summary"]) for name in names()]
