"""Bounded indexed translation checks for policy version 2."""
from collections import Counter
from fractions import Fraction
import math

from .contracts import finite

MAX_VERTICES = 100000
MAX_FACES = 30000
MAX_CORNERS = 120000
MAX_VALENCE = 256
MAX_EDGES = 120000


def vector(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("Expected three coordinates.")
    values = tuple(finite(x) for x in value)
    if any(abs(x) > 1e9 for x in values):
        raise ValueError("Coordinates exceed the check limit.")
    return values


def material(value):
    if not isinstance(value, dict) or set(value) != {"base_color", "metallic", "roughness"}:
        raise ValueError("Material data is incomplete.")
    color = value["base_color"]
    if not isinstance(color, list) or len(color) != 4:
        raise ValueError("Expected four color values.")
    return tuple(finite(x) for x in color) + (finite(value["metallic"]), finite(value["roughness"]))


def surface(observation, name):
    if not isinstance(observation, dict) or type(observation.get("schema_version")) is not int or observation["schema_version"] != 2:
        raise ValueError("Version-2 observation is required.")
    p = observation["parts"][name]
    vertices = p["world_vertices"]
    faces, edges = p["face_indices"], p["edge_indices"]
    assignments, normals = p["face_material_indices"], p["face_world_corner_normals"]
    palette = p["materials"]
    if not isinstance(vertices, list) or not 1 <= len(vertices) <= MAX_VERTICES:
        raise ValueError("Vertex count exceeds the check limit.")
    if not isinstance(faces, list) or not 1 <= len(faces) <= MAX_FACES:
        raise ValueError("Face count exceeds the check limit.")
    if not isinstance(edges, list) or len(edges) > MAX_EDGES:
        raise ValueError("Edge count exceeds the check limit.")
    if not isinstance(palette, list) or not 1 <= len(palette) <= 128:
        raise ValueError("Material count exceeds the check limit.")
    if not isinstance(assignments, list) or not isinstance(normals, list) or len(assignments) != len(faces) or len(normals) != len(faces):
        raise ValueError("Face data is incomplete.")
    vertices = [vector(v) for v in vertices]
    palette = tuple(material(m) for m in palette)
    def valid_index(i):
        return type(i) is int and 0 <= i < len(vertices)
    edge_counts = Counter()
    for edge in edges:
        if not isinstance(edge, list) or len(edge) != 2 or not all(valid_index(i) for i in edge) or edge[0] == edge[1]:
            raise ValueError("Edge indices are invalid.")
        edge_counts[tuple(sorted(edge))] += 1
    polygons = {}
    total = 0
    for face, assignment, corners in zip(faces, assignments, normals):
        if not isinstance(face, list) or not 3 <= len(face) <= MAX_VALENCE or not all(valid_index(i) for i in face) or len(set(face)) != len(face):
            raise ValueError("Face indices are invalid.")
        for a, b in zip(face, face[1:] + face[:1]):
            if tuple(sorted((a, b))) not in edge_counts:
                raise ValueError("A polygon boundary has no edge evidence.")
        total += len(face)
        if total > MAX_CORNERS:
            raise ValueError("Face corners exceed the check limit.")
        if type(assignment) is not int or not 0 <= assignment < len(palette):
            raise ValueError("Face material index is invalid.")
        if not isinstance(corners, list) or len(corners) != len(face):
            raise ValueError("Face normal data is incomplete.")
        normalized = []
        for raw in corners:
            n = vector(raw)
            length = math.hypot(*n)
            if not math.isclose(length, 1.0, rel_tol=0.0, abs_tol=1e-5):
                raise ValueError("A corner normal is not a unit vector.")
            normalized.append(tuple(x / length for x in n))
        # Distinct vertex IDs make the smallest ID a unique starting corner.
        start = face.index(min(face))
        key = tuple(face[start:] + face[:start])
        if key in polygons:
            raise ValueError("Duplicate oriented faces are outside version-2 coverage.")
        polygons[key] = (assignment, tuple(normalized[start:] + normalized[:start]))
    return vertices, edge_counts, polygons, palette


def angle(a, b):
    cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    return math.atan2(math.hypot(*cross), sum(x*y for x,y in zip(a,b)))


def measure(data, observation, previous, name, *, prepared=None):
    if previous is None:
        raise ValueError("An accepted version-2 baseline is required.")
    current_surface, old_surface = prepared if prepared is not None else (surface(observation, name), surface(previous, name))
    if old_surface is None:
        raise ValueError("An accepted version-2 baseline is required.")
    vertices, edges, faces, palette = current_surface
    prior, old_edges, old_faces, old_palette = old_surface
    counts = len(vertices) == len(prior)
    # Compare exact rational values of the stored binary64 inputs. In particular,
    # rounded math.dist at the boundary cannot turn an outside point into a pass.
    delta = tuple(Fraction(float(x)) for x in data["delta"])
    limit = Fraction(float(data["tolerance"])) ** 2
    largest = Fraction(0)
    for current, old in zip(vertices, prior):
        squared = sum((Fraction(x)-Fraction(y)-d)**2 for x,y,d in zip(current,old,delta))
        largest = max(largest, squared)
    topology = faces.keys() == old_faces.keys()
    assignments = topology and all(faces[key][0] == old_faces[key][0] for key in faces)
    maximum_angle = 0.0
    if topology:
        for key in faces:
            for current, old in zip(faces[key][1], old_faces[key][1]):
                maximum_angle = max(maximum_angle, angle(current, old))
    normals = topology and maximum_angle <= data["normal_tolerance_radians"]
    measured = {"vertex_count_equal":counts, "max_vertex_error_m":math.sqrt(float(largest)),
                "indexed_translation_equal":counts and largest <= limit,
                "distance_limit_exceeded":largest > limit,
                "oriented_polygons_equal":topology, "face_material_assignments_equal":assignments,
                "ordered_material_palette_equal":palette == old_palette,
                "indexed_edges_equal":edges == old_edges,
                "corner_normals_equal":normals,
                "max_normal_angle_error_radians":maximum_angle if topology else None}
    passed = all(measured[k] for k in ("indexed_translation_equal", "oriented_polygons_equal",
                 "face_material_assignments_equal", "ordered_material_palette_equal", "indexed_edges_equal", "corner_normals_equal"))
    return passed, measured
