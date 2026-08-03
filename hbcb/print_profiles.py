"""Printer constraint profiles.

A print profile is the bridge between "what the user's printer can physically
do" and both halves of the pipeline: the generator refuses to emit a strut
thinner than `min_feature_mm`, and QA fails a build whose measured walls fall
under `min_wall_mm`. Validating a 0.6 mm draft print against 0.2 mm fine-nozzle
rules would be theatre, so the thresholds travel with the request.

FDM wall minimums below assume the common "walls should be a whole number of
extrusion widths, and three perimeters is a sane floor" rule of thumb. They are
conservative defaults, not a guarantee for any specific printer.
"""

from .exit_codes import INVALID_REQUEST, BuildError

PRESETS = {
    "fdm-0.4-standard": {
        "technology": "fdm",
        "nozzle_mm": 0.4,
        "layer_height_mm": 0.2,
        "min_wall_mm": 1.2,
        "min_feature_mm": 2.0,
        "max_overhang_deg": 45.0,
        "material_density_g_cm3": 1.24,
    },
    "fdm-0.6-draft": {
        "technology": "fdm",
        "nozzle_mm": 0.6,
        "layer_height_mm": 0.3,
        "min_wall_mm": 1.8,
        "min_feature_mm": 3.0,
        "max_overhang_deg": 45.0,
        "material_density_g_cm3": 1.24,
    },
    "fdm-0.2-fine": {
        "technology": "fdm",
        "nozzle_mm": 0.2,
        "layer_height_mm": 0.1,
        "min_wall_mm": 0.8,
        "min_feature_mm": 1.2,
        "max_overhang_deg": 50.0,
        "material_density_g_cm3": 1.24,
    },
    "resin-standard": {
        "technology": "resin",
        "nozzle_mm": None,
        "layer_height_mm": 0.05,
        "min_wall_mm": 0.8,
        "min_feature_mm": 1.0,
        "max_overhang_deg": 60.0,
        "material_density_g_cm3": 1.10,
    },
}

DEFAULT_PRESET = "fdm-0.4-standard"

_OVERRIDABLE = (
    "technology",
    "nozzle_mm",
    "layer_height_mm",
    "min_wall_mm",
    "min_feature_mm",
    "max_overhang_deg",
    "material_density_g_cm3",
)


def resolve(requested):
    """Merge a request's `print_profile` block into a complete profile.

    Explicit fields always win over the preset. `preset: "custom"` starts from
    the standard FDM profile so a caller only has to state what differs.
    """
    requested = dict(requested or {})
    preset_name = requested.pop("preset", DEFAULT_PRESET)
    base_name = DEFAULT_PRESET if preset_name == "custom" else preset_name
    if base_name not in PRESETS:
        raise BuildError(
            INVALID_REQUEST,
            "unknown print profile preset %r (known: %s)"
            % (preset_name, ", ".join(sorted(PRESETS))),
        )

    profile = dict(PRESETS[base_name])
    profile["preset"] = preset_name
    for key in _OVERRIDABLE:
        if key in requested:
            profile[key] = requested[key]

    _check_coherence(profile)
    return profile


def _check_coherence(profile):
    """Reject profiles that are internally contradictory.

    These are cheap mistakes to make by hand (asking for a 0.5 mm wall from a
    0.8 mm nozzle, say) and expensive to discover after a five-hour print.
    """
    if profile["min_feature_mm"] < profile["min_wall_mm"]:
        raise BuildError(
            INVALID_REQUEST,
            "print profile is contradictory: min_feature_mm (%s) is smaller than "
            "min_wall_mm (%s); a freestanding feature cannot be thinner than a wall"
            % (profile["min_feature_mm"], profile["min_wall_mm"]),
        )
    nozzle = profile.get("nozzle_mm")
    if profile["technology"] == "fdm":
        if not nozzle:
            raise BuildError(INVALID_REQUEST, "an FDM print profile requires nozzle_mm")
        if profile["min_wall_mm"] < 2 * nozzle:
            raise BuildError(
                INVALID_REQUEST,
                "print profile is contradictory: min_wall_mm (%s) is less than two "
                "extrusion widths for a %s mm nozzle; such a wall cannot be printed "
                "as a solid perimeter pair" % (profile["min_wall_mm"], nozzle),
            )
        if profile["layer_height_mm"] > 0.8 * nozzle:
            raise BuildError(
                INVALID_REQUEST,
                "print profile is contradictory: layer_height_mm (%s) exceeds 80%% of "
                "the %s mm nozzle diameter and will not bond reliably"
                % (profile["layer_height_mm"], nozzle),
            )


def describe(profile):
    """One-line human summary used in CLI output and QA reports."""
    if profile["technology"] == "fdm":
        head = "FDM, %.2f mm nozzle, %.2f mm layers" % (
            profile["nozzle_mm"],
            profile["layer_height_mm"],
        )
    else:
        head = "resin, %.3f mm layers" % profile["layer_height_mm"]
    return "%s; min wall %.2f mm, min feature %.2f mm, max overhang %.0f deg" % (
        head,
        profile["min_wall_mm"],
        profile["min_feature_mm"],
        profile["max_overhang_deg"],
    )
