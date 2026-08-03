"""Print-readiness measurements.

Everything here is measured from the evaluated mesh, in millimetres, and
reported as numbers rather than a verdict alone -- a slicer's opinion is the one
that ultimately matters, and a user who can see "minimum thickness 1.31 mm"
can judge it against their own printer.

What is measured:

* topology: manifold edges, boundary (open) edges, separate shells, degenerate
  faces -- the things that make a slicer produce holes or refuse the file;
* solid thickness, by casting a ray inward from each face and measuring the
  distance to the far surface;
* unsupported overhangs, by face normal angle, against the profile's limit;
* bed contact area, because a tall model on a small footprint falls over;
* volume and a solid-infill material estimate.

These are geometric diagnostics, not a guarantee that a print will succeed.
"""

import math

import bmesh
from mathutils.bvhtree import BVHTree

from . import scene

# Faces smaller than this are treated as degenerate. At millimetre scale this
# is far below anything a printer could reproduce.
DEGENERATE_AREA_MM2 = 1e-6

# Rays start just inside the surface so they do not immediately re-hit the face
# they came from.
RAY_EPSILON_MM = 1e-3

# Hits closer than this are treated as the ray grazing its own face or a
# neighbour across a shared edge, and the ray is pushed past them. Real
# printable thicknesses are two orders of magnitude larger -- the schema's
# smallest permitted min_wall_mm is 0.2 mm.
MIN_CREDIBLE_HIT_MM = 0.01

# How many self-hits to step over before giving up on a face.
MAX_RAY_STEPS = 8

# Cap on how many faces are ray-cast. Well above what this generator produces;
# it exists so a future dense generator cannot make QA run unbounded.
MAX_THICKNESS_SAMPLES = 40000


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    index = int(round(fraction * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


def _count_shells(bm):
    """Number of face-connected components."""
    seen = set()
    shells = 0
    for face in bm.faces:
        if face.index in seen:
            continue
        shells += 1
        stack = [face]
        seen.add(face.index)
        while stack:
            current = stack.pop()
            for edge in current.edges:
                for neighbour in edge.link_faces:
                    if neighbour.index not in seen:
                        seen.add(neighbour.index)
                        stack.append(neighbour)
    return shells


def _topology(bm):
    non_manifold_edges = 0
    boundary_edges = 0
    for edge in bm.edges:
        face_count = len(edge.link_faces)
        if face_count == 1:
            boundary_edges += 1
        elif face_count != 2:
            non_manifold_edges += 1
    non_manifold_verts = sum(1 for vert in bm.verts if not vert.is_manifold)

    degenerate = 0
    degenerate_area = 0.0
    total_area = 0.0
    for face in bm.faces:
        area = face.calc_area()
        total_area += area
        if area < DEGENERATE_AREA_MM2:
            degenerate += 1
            degenerate_area += area

    return {
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "triangles": sum(max(0, len(face.verts) - 2) for face in bm.faces),
        "boundary_edges": boundary_edges,
        "non_manifold_edges": non_manifold_edges,
        "non_manifold_vertices": non_manifold_verts,
        "degenerate_faces": degenerate,
        "degenerate_area_mm2": round(degenerate_area, 9),
        "connected_shells": _count_shells(bm),
        "surface_area_mm2": round(total_area, 4),
    }


def _cast_through(bvh, origin, direction, limit):
    """Distance to the first surface that is not a numerical self-hit.

    A ray leaving a face centre can immediately re-register that face, or the
    neighbour sharing its edge, at a distance of microns. Stepping past those
    hits is what makes the difference between reporting a 0.002 mm wall and the
    19 mm one that is actually there.
    """
    travelled = 0.0
    point = origin.copy()
    for _ in range(MAX_RAY_STEPS):
        remaining = limit - travelled
        if remaining <= 0.0:
            return None
        location, _, _, distance = bvh.ray_cast(point, direction, remaining)
        if location is None or distance is None:
            return None
        travelled += distance
        if distance >= MIN_CREDIBLE_HIT_MM:
            return travelled
        # Nudge past the grazing hit and keep going.
        point = location + direction * MIN_CREDIBLE_HIT_MM
        travelled += MIN_CREDIBLE_HIT_MM
    return None


def _thickness(bm, max_dimension):
    """Solid thickness at every face, measured by an inward ray.

    For a wall this is the wall thickness; for a strut it is the strut
    diameter. One measurement therefore covers both of the constraints a
    printer cares about.
    """
    bvh = BVHTree.FromBMesh(bm)
    faces = list(bm.faces)
    step = max(1, len(faces) // MAX_THICKNESS_SAMPLES)
    limit = max_dimension * 1.5

    samples = []
    misses = 0
    for face in faces[::step]:
        if face.calc_area() < DEGENERATE_AREA_MM2:
            continue
        normal = face.normal
        if normal.length_squared == 0.0:
            continue
        origin = face.calc_center_median() - normal * RAY_EPSILON_MM
        distance = _cast_through(bvh, origin, -normal, limit)
        if distance is None:
            # An inward ray that escapes means the surface is open there; the
            # topology check reports that far more precisely than a ray can.
            misses += 1
            continue
        samples.append(distance + RAY_EPSILON_MM)

    samples.sort()
    return {
        "samples": len(samples),
        "escaped_rays": misses,
        "min_mm": round(samples[0], 4) if samples else None,
        "p01_mm": round(_percentile(samples, 0.01), 4) if samples else None,
        "p05_mm": round(_percentile(samples, 0.05), 4) if samples else None,
        "median_mm": round(_percentile(samples, 0.50), 4) if samples else None,
    }


def _overhangs(bm, max_overhang_deg, bed_tolerance_mm):
    """Downward-facing area steeper than the profile allows.

    Overhang angle is measured from the horizontal plane: a vertical wall is 0
    degrees, a flat ceiling is 90. Faces sitting on the build plate are
    excluded -- they rest on the bed rather than on air.
    """
    limit = math.radians(max_overhang_deg)
    unsupported_area = 0.0
    bed_area = 0.0
    total_down_area = 0.0
    steepest = 0.0

    for face in bm.faces:
        normal = face.normal
        if normal.z >= 0.0:
            continue
        area = face.calc_area()
        if area < DEGENERATE_AREA_MM2:
            continue
        total_down_area += area
        if face.calc_center_median().z <= bed_tolerance_mm:
            bed_area += area
            continue
        angle = math.asin(min(1.0, -normal.z))
        steepest = max(steepest, angle)
        if angle > limit:
            unsupported_area += area

    return {
        "max_overhang_deg": round(max_overhang_deg, 2),
        "steepest_overhang_deg": round(math.degrees(steepest), 2),
        "unsupported_area_mm2": round(unsupported_area, 4),
        "downward_area_mm2": round(total_down_area, 4),
        "bed_contact_area_mm2": round(bed_area, 4),
    }


def measure(obj, print_profile):
    """Return the full measurement dictionary for `obj`."""
    mesh = scene.evaluated_mesh(obj)
    try:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.transform(obj.matrix_world)
        bm.normal_update()
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        low, high = scene.world_bounds(obj)
        dimensions = [round(high[i] - low[i], 4) for i in range(3)]
        max_dimension = max(dimensions) if dimensions else 1.0

        topology = _topology(bm)
        # Signed volume is positive only when normals face outward, which is
        # exactly the "is this solid inside-out?" question a slicer asks.
        signed_volume = bm.calc_volume(signed=True)
        thickness = _thickness(bm, max_dimension)
        overhangs = _overhangs(
            bm, print_profile["max_overhang_deg"], print_profile["layer_height_mm"] * 1.5
        )

        volume_cm3 = abs(signed_volume) / 1000.0
        density = print_profile["material_density_g_cm3"]

        return {
            "dimensions_mm": dimensions,
            "topology": topology,
            "volume": {
                "signed_volume_mm3": round(signed_volume, 4),
                "positive_volume": signed_volume > 0.0,
                "solid_volume_cm3": round(volume_cm3, 4),
                "estimated_solid_mass_g": round(volume_cm3 * density, 3),
                "material_density_g_cm3": density,
                "note": (
                    "mass assumes 100% infill; a typical 15-20% infill print uses "
                    "considerably less material"
                ),
            },
            "thickness": thickness,
            "overhangs": overhangs,
        }
    finally:
        import bpy

        bpy.data.meshes.remove(mesh)


def evaluate(measurements, print_profile, strict):
    """Turn measurements into named pass/fail checks.

    Every check reports its measured value alongside the threshold, so a
    failure explains itself without the user re-running anything.
    """
    topology = measurements["topology"]
    thickness = measurements["thickness"]
    overhangs = measurements["overhangs"]
    volume = measurements["volume"]

    checks = []

    def check(name, passed, detail, required=True):
        checks.append(
            {"name": name, "passed": bool(passed), "required": required, "detail": detail}
        )

    check(
        "watertight",
        topology["boundary_edges"] == 0,
        "%d open boundary edges (must be 0)" % topology["boundary_edges"],
    )
    check(
        "manifold",
        topology["non_manifold_edges"] == 0 and topology["non_manifold_vertices"] == 0,
        "%d non-manifold edges, %d non-manifold vertices (must be 0)"
        % (topology["non_manifold_edges"], topology["non_manifold_vertices"]),
    )
    check(
        "single_shell",
        topology["connected_shells"] == 1,
        "%d connected shells (must be 1 so the slicer sees one body)"
        % topology["connected_shells"],
    )
    # Advisory, not required. Boolean solvers leave zero-area triangles along
    # intersection seams; they enclose no volume and slicers discard them. The
    # vertex welding that would remove them measurably tears the manifold on
    # this generator's output, which is a real defect rather than a cosmetic
    # one, so the count is reported instead of being fixed.
    check(
        "no_degenerate_faces",
        topology["degenerate_faces"] == 0,
        "%d zero-area faces totalling %.2e mm2; harmless to slicers but worth "
        "knowing about" % (topology["degenerate_faces"], topology["degenerate_area_mm2"]),
        required=False,
    )
    check(
        "positive_volume",
        volume["positive_volume"],
        "signed volume %.3f mm3 must be positive; a negative value means the "
        "normals point inward" % volume["signed_volume_mm3"],
    )

    min_wall = print_profile["min_wall_mm"]
    measured = thickness["p01_mm"]
    # The 1st percentile rather than the raw minimum: a single sliver face on a
    # bevel seam should not condemn a model whose walls are sound everywhere.
    check(
        "minimum_thickness",
        measured is not None and measured >= min_wall,
        "1st-percentile solid thickness %s mm against a %.2f mm minimum "
        "(absolute minimum measured %s mm)"
        % (
            "n/a" if measured is None else "%.3f" % measured,
            min_wall,
            "n/a" if thickness["min_mm"] is None else "%.3f" % thickness["min_mm"],
        ),
    )

    # Overhangs are advisory even under the strict profile: they are printable
    # with supports, so they are a warning about print setup, not a defect in
    # the geometry.
    unsupported = overhangs["unsupported_area_mm2"]
    check(
        "overhangs_within_limit",
        unsupported == 0.0,
        "%.1f mm2 of surface overhangs beyond %.0f degrees and will need "
        "supports" % (unsupported, overhangs["max_overhang_deg"]),
        required=False,
    )
    check(
        "bed_contact",
        overhangs["bed_contact_area_mm2"] > 0.0,
        "%.1f mm2 of flat surface touches the build plate" % overhangs["bed_contact_area_mm2"],
        required=False,
    )

    required_failures = [c["name"] for c in checks if c["required"] and not c["passed"]]
    warnings = [c["name"] for c in checks if not c["required"] and not c["passed"]]

    return {
        "checks": checks,
        "failed": required_failures,
        "warnings": warnings,
        # Under the advisory profile the build still publishes, so a user can
        # look at the model and decide for themselves.
        "passed": not required_failures or not strict,
        "strict": strict,
    }
