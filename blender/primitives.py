"""Primitive builders.

Only closed, solid primitives are exposed. A boolean union is only well defined
over closed volumes, and every part of a character eventually gets unioned into
one printable shell, so there is no place here for planes or open surfaces.

All sizes are millimetres and describe the finished part: `box(size=(10,10,10))`
is 10 mm on each side, not a 10 mm "radius".
"""

import bpy

from .scene import select_only


def _apply_scale(obj):
    """Bake object scale into the mesh.

    Downstream code measures wall thickness with raycasts and reports
    dimensions in millimetres; leaving a non-unit object scale in place would
    make every one of those measurements silently wrong.
    """
    select_only(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def _named(obj, name):
    obj.name = name
    obj.data.name = name
    return obj


def box(name, size, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0)):
    """Axis-aligned box of the given (x, y, z) size, centred on `location`."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.scale = size
    return _apply_scale(_named(obj, name))


def cylinder(name, radius, height, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), segments=32):
    """Z-aligned cylinder, centred on `location`."""
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=segments, radius=radius, depth=height, location=location, rotation=rotation
    )
    return _named(bpy.context.active_object, name)


def cone(
    name,
    radius_bottom,
    radius_top,
    height,
    location=(0.0, 0.0, 0.0),
    rotation=(0.0, 0.0, 0.0),
    segments=32,
):
    """Z-aligned cone or truncated cone, centred on `location`."""
    bpy.ops.mesh.primitive_cone_add(
        vertices=segments,
        radius1=radius_bottom,
        radius2=radius_top,
        depth=height,
        location=location,
        rotation=rotation,
    )
    return _named(bpy.context.active_object, name)


def sphere(name, radius, location=(0.0, 0.0, 0.0), segments=24, faceted=False, scale=None):
    """Sphere, optionally squashed by a per-axis `scale` multiplier.

    `faceted` swaps in an icosphere, which is what the low-poly style wants:
    even triangles and a much lower vertex count than a UV sphere.
    """
    if faceted:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=location)
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=segments, ring_count=max(6, segments // 2), radius=radius, location=location
        )
    obj = bpy.context.active_object
    if scale is not None:
        obj.scale = scale
        _apply_scale(obj)
    return _named(obj, name)


# How far the shaft is extended past each cap sphere's equator, as a fraction
# of the radius. See `capsule` for why this cannot be zero.
_CAP_OVERLAP = 0.35

# Cap spheres are made a hair narrower than the shaft. At equal radii the
# sphere's equator is exactly tangent to the cylinder wall, and unioning two
# tangent surfaces produces a ring of zero-area faces. Shrinking the cap pulls
# it just inside the shaft so the two surfaces meet transversally instead.
_CAP_SHRINK = 0.985


def capsule(name, radius, height, location=(0.0, 0.0, 0.0), segments=24, faceted=False):
    """A cylinder with hemispherical caps, built as three unioned-later parts.

    Returned as a list because the caller drops every part into the same union
    collection; a capsule does not need to be a single mesh before that.

    `height` is the total tip-to-tip length, so the cap centres sit at
    `height/2 - radius` and the tips land exactly on the requested length.

    The shaft deliberately runs *past* each cap's equator rather than meeting it
    edge to edge. Ending the cylinder exactly at the equator puts the cylinder's
    end cap and the sphere's equator ring in the same plane, and the boolean
    solver turns that coplanar pair into a ring of zero-area faces -- which
    Blender's own STL importer then strips, leaving holes in the exported mesh.
    """
    x, y, z = location
    cap_radius = radius * _CAP_SHRINK
    # Offsetting by the cap radius keeps the tips exactly on the requested
    # total length despite the shrink.
    centre_offset = height / 2.0 - cap_radius
    if centre_offset <= 0.0:
        return [sphere(name, radius, location=location, segments=segments, faceted=faceted)]

    shaft_depth = 2.0 * (centre_offset + cap_radius * _CAP_OVERLAP)
    parts = [
        cylinder(
            "%s-shaft" % name,
            radius,
            shaft_depth,
            location=(x, y, z),
            segments=8 if faceted else segments,
        ),
        sphere(
            "%s-cap-top" % name,
            cap_radius,
            location=(x, y, z + centre_offset),
            segments=segments,
            faceted=faceted,
        ),
        sphere(
            "%s-cap-bottom" % name,
            cap_radius,
            location=(x, y, z - centre_offset),
            segments=segments,
            faceted=faceted,
        ),
    ]
    return parts


def rounded_box(name, size, location=(0.0, 0.0, 0.0), radius=1.0, segments=3):
    """A box with bevelled edges, used for the geometric and chibi silhouettes.

    The bevel is applied here rather than to the finished union: bevelling after
    a boolean tends to run along intersection seams and produce the
    near-degenerate faces that print QA then rejects.
    """
    obj = box(name, size, location=location)
    limit = min(size) / 2.0
    width = min(radius, limit * 0.9)
    if width <= 0.0:
        return obj
    modifier = obj.modifiers.new(name="bevel", type="BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    modifier.angle_limit = 0.7854  # 45 degrees; leaves coplanar faces alone.
    modifier.use_clamp_overlap = True
    select_only(obj)
    bpy.ops.object.modifier_apply(modifier="bevel")
    return obj
