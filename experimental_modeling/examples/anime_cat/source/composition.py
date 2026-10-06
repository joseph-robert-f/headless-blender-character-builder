# SPDX-License-Identifier: GPL-3.0-or-later
"""Original chibi cat composition and two accessory states.

The body, face, ears, feet, and tail do not depend on the accessory parameter.
The body_shift_x parameter exists solely for the deliberate rejected candidate.
"""

from geometry import combine, ellipsoid, prism_xz, torus_xy, tube


FUR = (.91, .62, .48, 1)
CREAM = (1.0, .85, .70, 1)
PINK = (.96, .42, .53, 1)
BLUSH = (.98, .55, .58, 1)
WHITE = (.97, .98, 1.0, 1)
TEAL = (.10, .62, .64, 1)
INK = (.028, .065, .095, 1)
BROWN = (.27, .12, .13, 1)
BLUE = (.12, .43, .68, 1)
GOLD = (.97, .72, .18, 1)
HAT = (.42, .31, .78, 1)
GLASSES = (.035, .075, .13, 1)


BASE_IDS = (
    "body", "belly", "head", "ears", "inner_ears", "paws",
    "tail", "tail_tip", "eyes", "irises", "pupils", "highlights",
    "muzzle", "nose", "mouth", "whiskers", "cheeks", "collar", "bell",
)


def _pair_spheres(x, y, z, radii):
    return combine(*(ellipsoid((sign * x, y, z), radii)
                     for sign in (-1, 1)))


def _hat():
    # Brim and soft dome touch the crown of the unchanged head.  The hat stays
    # above 2.40 m, while the later glasses stay below 2.15 m.
    return combine(
        ellipsoid((0, -.025, 2.485), (.45, .39, .055)),
        ellipsoid((0, -.025, 2.655), (.35, .31, .21)),
        ellipsoid((-.07, -.055, 2.827), (.15, .14, .075)),
    )


def _sunglasses():
    lenses = _pair_spheres(.335, -.825, 1.925, (.215, .027, .145))
    bridge = tube([(-.123, -.837, 1.985), (0, -.855, 2.015),
                   (.123, -.837, 1.985)], [.025, .026, .025], sides=10)
    temples = combine(
        tube([(-.535, -.82, 1.975), (-.64, -.775, 2.005),
              (-.75, -.77, 2.025)], [.022, .022, .018], sides=8),
        tube([(.535, -.82, 1.975), (.64, -.775, 2.005),
              (.75, -.77, 2.025)], [.022, .022, .018], sides=8),
    )
    return combine(lenses, bridge, temples)


def parts(params):
    accessory = params["accessory"]
    shift = params["body_shift_x"]
    if accessory not in ("none", "hat", "sunglasses"):
        raise ValueError("Unknown accessory state")
    if not isinstance(shift, (float, int)) or isinstance(shift, bool) or not -.1 <= shift <= .1:
        raise ValueError("Invalid body shift")

    result = {
        "body": (ellipsoid((shift, .10, .82), (.64, .48, .76)), FUR),
        "belly": (ellipsoid((0, -.355, .77), (.43, .11, .48)), CREAM),
        "head": (ellipsoid((0, -.015, 1.755), (.82, .65, .69)), FUR),
        "ears": (combine(
            prism_xz(((-.79, 2.20), (-.29, 2.23), (-.69, 2.80)), -.33, .03),
            prism_xz(((.29, 2.23), (.79, 2.20), (.69, 2.80)), -.33, .03),
        ), FUR),
        "inner_ears": (combine(
            prism_xz(((-.724, 2.41), (-.42, 2.42), (-.677, 2.675)), -.352, -.335),
            prism_xz(((.42, 2.42), (.724, 2.41), (.677, 2.675)), -.352, -.335),
        ), PINK),
        "paws": (_pair_spheres(.38, -.36, .30, (.235, .25, .30)), FUR),
        "tail": (tube((
            (.55, .35, .73), (.84, .50, .64), (1.07, .50, .84),
            (1.18, .43, 1.11), (1.09, .35, 1.37), (.93, .32, 1.48),
        ), (.16, .17, .17, .15, .13, .11), sides=14), FUR),
        "tail_tip": (ellipsoid((.93, .32, 1.48), (.13, .13, .13)), CREAM),
        "eyes": (_pair_spheres(.335, -.614, 1.935, (.235, .082, .265)), WHITE),
        "irises": (_pair_spheres(.335, -.692, 1.925, (.148, .042, .188)), TEAL),
        "pupils": (_pair_spheres(.335, -.731, 1.917, (.083, .025, .137)), INK),
        "highlights": (combine(
            _pair_spheres(.28, -.752, 2.005, (.046, .017, .058)),
            _pair_spheres(.387, -.746, 1.86, (.022, .012, .027)),
        ), WHITE),
        "muzzle": (_pair_spheres(.145, -.645, 1.555, (.205, .158, .145)), CREAM),
        "nose": (prism_xz(((0, 1.525), (.105, 1.647), (-.105, 1.647)),
                           -.822, -.785), PINK),
        "mouth": (combine(
            tube(((0, -.835, 1.515), (-.045, -.843, 1.465),
                  (-.12, -.836, 1.457)), (.017, .015, .011), sides=8),
            tube(((0, -.835, 1.515), (.045, -.843, 1.465),
                  (.12, -.836, 1.457)), (.017, .015, .011), sides=8),
        ), BROWN),
        "whiskers": (combine(*(
            tube(((sign * .23, -.775, 1.55 + level * .06),
                  (sign * .52, -.769, 1.55 + level * .075),
                  (sign * .77, -.738, 1.55 + level * .11)),
                 (.009, .008, .006), sides=6)
            for sign in (-1, 1) for level in (-1, 0, 1)
        )), BROWN),
        "cheeks": (_pair_spheres(.585, -.512, 1.58, (.105, .024, .066)), BLUSH),
        "collar": (torus_xy((0, -.015, 1.265), .49, .068), BLUE),
        "bell": (ellipsoid((0, -.535, 1.225), (.11, .105, .115)), GOLD),
    }
    if accessory == "hat":
        result["accessory"] = (_hat(), HAT)
    elif accessory == "sunglasses":
        result["accessory"] = (_sunglasses(), GLASSES)
    return result
