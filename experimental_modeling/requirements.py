"""Versioned, controller-owned geometric requirements over inspected mesh data.

These bounded predicates prove only their stated coverage. No author callbacks,
expressions, imports or truth assertions are accepted in a requirement document.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from .contracts import finite, identifier

MAX_TRIANGLES = 30000
MAX_VERTICES = 100000
MAX_WORK = 8000000
KINDS = {"connected_path", "clearance_path", "preserved_region", "preserved_rays", "manual_review"}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("unexpected requirement fields")


def vector(value):
    if not isinstance(value, list) or len(value) != 3: raise ValueError("expected 3-vector")
    result=tuple(finite(x) for x in value)
    if any(abs(x)>1e9 for x in result):raise ValueError("coordinate exceeds bounded verifier coverage")
    return result


def region(value):
    if not isinstance(value, list) or len(value) != 3: raise ValueError("region requires three axis ranges")
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2: raise ValueError("invalid region range")
        lo, hi = pair
        if lo is not None: finite(lo)
        if hi is not None: finite(hi)
        if lo is not None and hi is not None and lo > hi: raise ValueError("reversed region")


def indices(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 512 or any(type(i) is not int or not 0 <= i < MAX_VERTICES for i in value):
        raise ValueError("invalid selected vertex indices")
    if len(set(value)) != len(value): raise ValueError("duplicate selected indices")


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    kind: str
    hard: bool
    phase: str
    params: dict[str, Any]

    @classmethod
    def parse(cls, raw):
        exact(raw, ("id", "title", "kind", "hard", "phase", "params"))
        identifier(raw["id"])
        if not isinstance(raw["title"], str) or not 1 <= len(raw["title"]) <= 200: raise ValueError("invalid requirement title")
        if type(raw["hard"]) is not bool or raw["phase"] not in ("always", "revision") or (not isinstance(raw["kind"],str) or raw["kind"] not in KINDS):
            raise ValueError("unsupported requirement definition")
        kind, p = raw["kind"], raw["params"]
        if kind == "connected_path":
            exact(p, ("part", "region", "from", "to")); identifier(p["part"])
            for key in ("region", "from", "to"): region(p[key])
        elif kind == "clearance_path":
            exact(p, ("parts", "points", "samples_per_segment", "min_clearance", "epsilon"))
            if not isinstance(p["parts"], list) or not 1 <= len(p["parts"]) <= 16 or len(set(p["parts"])) != len(p["parts"]): raise ValueError("invalid target parts")
            for part in p["parts"]: identifier(part)
            if not isinstance(p["points"], list) or not 2 <= len(p["points"]) <= 64: raise ValueError("invalid path points")
            for point in p["points"]:
                if isinstance(point, dict) and set(point) == {"point"}: vector(point["point"])
                else:
                    exact(point, ("part", "indices", "offset")); identifier(point["part"]); indices(point["indices"]); vector(point["offset"])
            if type(p["samples_per_segment"]) is not int or not 1 <= p["samples_per_segment"] <= 20: raise ValueError("invalid sample count")
            if not 0 <= finite(p["min_clearance"]) <= 100 or not 0 < finite(p["epsilon"]) <= .001: raise ValueError("invalid clearance/tolerance")
        elif kind == "preserved_region":
            exact(p, ("part", "region", "tolerance")); identifier(p["part"]); region(p["region"])
            if not 0 < finite(p["tolerance"]) <= .01: raise ValueError("invalid preservation tolerance")
            if raw["phase"] != "revision": raise ValueError("preservation requires revision phase")
        elif kind == "preserved_rays":
            exact(p, ("part", "rays", "tolerance")); identifier(p["part"])
            if not isinstance(p["rays"], list) or not 1 <= len(p["rays"]) <= 128: raise ValueError("invalid rays")
            for ray in p["rays"]:
                exact(ray, ("origin", "direction", "max_distance")); vector(ray["origin"])
                if norm(vector(ray["direction"])) < 1e-12 or not 0 < finite(ray["max_distance"]) <= 10000: raise ValueError("invalid ray")
            if not 0 < finite(p["tolerance"]) <= .01 or raw["phase"] != "revision": raise ValueError("invalid preservation definition")
        else:
            exact(p, ("instruction",))
            if not isinstance(p["instruction"], str) or not 1 <= len(p["instruction"]) <= 1000: raise ValueError("invalid review instruction")
        return cls(**raw)


@dataclass(frozen=True)
class RequirementSet:
    requirements: tuple[Requirement, ...]
    raw: dict[str, Any]

    @classmethod
    def parse(cls, raw):
        exact(raw, ("schema_version", "requirements"))
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 1: raise ValueError("unsupported requirements version")
        if not isinstance(raw["requirements"], list) or len(raw["requirements"]) > 128: raise ValueError("invalid requirements list")
        items = tuple(Requirement.parse(r) for r in raw["requirements"])
        if len({r.id for r in items}) != len(items): raise ValueError("duplicate requirement ID")
        return cls(items, raw)


def add(a,b): return tuple(x+y for x,y in zip(a,b))
def sub(a,b): return tuple(x-y for x,y in zip(a,b))
def mul(a,s): return tuple(x*s for x in a)
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def norm(a): return math.sqrt(dot(a,a))


def inside(point, bounds):
    return all((lo is None or x >= lo) and (hi is None or x <= hi) for x,(lo,hi) in zip(point,bounds))


def mesh(observation, name):
    part = observation["parts"][name]
    vertices = [vector(v) for v in part["world_vertices"]]
    triangles = part["triangle_indices"]
    edges = part["edge_indices"]
    if not 1 <= len(vertices) <= MAX_VERTICES or not 1 <= len(triangles) <= MAX_TRIANGLES: raise ValueError("mesh exceeds bounded verifier coverage")
    for triangle in triangles:
        if len(triangle) != 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in triangle): raise ValueError("invalid triangles")
    for edge in edges:
        if len(edge) != 2 or any(type(i) is not int or not 0 <= i < len(vertices) for i in edge): raise ValueError("invalid edges")
    return part, vertices, triangles, edges


def ray_distance(origin, direction, a, b, c, epsilon=1e-9):
    """Two-sided Möller–Trumbore. Returns positive distance, not an author claim."""
    ab, ac = sub(b,a), sub(c,a)
    h = cross(direction, ac); determinant = dot(ab,h)
    if abs(determinant) < epsilon: return None
    inv = 1 / determinant; s = sub(origin,a); u = inv*dot(s,h)
    if u < -epsilon or u > 1+epsilon: return None
    q=cross(s,ab); v=inv*dot(direction,q)
    if v < -epsilon or u+v > 1+epsilon: return None
    distance=inv*dot(ac,q)
    return distance if distance >= -epsilon else None


def point_segment_distance(p,a,b):
    edge=sub(b,a);length2=dot(edge,edge)
    if length2<=1e-30:return norm(sub(p,a))
    fraction=max(0.0,min(1.0,dot(sub(p,a),edge)/length2))
    return norm(sub(p,add(a,mul(edge,fraction))))


def point_triangle_distance(p,a,b,c):
    # Closest point regions from Real-Time Collision Detection (standard formula).
    ab,ac,ap=sub(b,a),sub(c,a),sub(p,a)
    area=cross(ab,ac)
    if dot(area,area)<=1e-24:
        return min(point_segment_distance(p,a,b),point_segment_distance(p,b,c),point_segment_distance(p,c,a))
    d1,d2=dot(ab,ap),dot(ac,ap)
    if d1<=0 and d2<=0:return norm(ap)
    bp=sub(p,b);d3,d4=dot(ab,bp),dot(ac,bp)
    if d3>=0 and d4<=d3:return norm(bp)
    vc=d1*d4-d3*d2
    if vc<=0 and d1>=0 and d3<=0:return norm(sub(p,add(a,mul(ab,d1/(d1-d3)))))
    cp=sub(p,c);d5,d6=dot(ab,cp),dot(ac,cp)
    if d6>=0 and d5<=d6:return norm(cp)
    vb=d5*d2-d1*d6
    if vb<=0 and d2>=0 and d6<=0:return norm(sub(p,add(a,mul(ac,d2/(d2-d6)))))
    va=d3*d6-d5*d4
    if va<=0 and d4-d3>=0 and d5-d6>=0:return norm(sub(p,add(b,mul(sub(c,b),(d4-d3)/((d4-d3)+(d5-d6))))))
    denominator=va+vb+vc
    if abs(denominator)<1e-30:return min(point_segment_distance(p,a,b),point_segment_distance(p,b,c),point_segment_distance(p,c,a))
    return norm(sub(p,add(a,add(mul(ab,vb/denominator),mul(ac,vc/denominator)))))


def triangles_for(observation, names):
    triangles=[]
    for name in names:
        _,vertices,faces,_=mesh(observation,name)
        triangles.extend(tuple(vertices[i] for i in face) for face in faces)
    if len(triangles)>MAX_TRIANGLES: raise ValueError("combined mesh exceeds coverage")
    return triangles


def point_value(point, observation):
    if "point" in point:return vector(point["point"])
    _,vertices,_,_=mesh(observation,point["part"])
    selected=[vertices[i] for i in point["indices"]]
    return add(tuple(sum(v[j] for v in selected)/len(selected) for j in range(3)), vector(point["offset"]))


def connected_path(p, observation, previous):
    _,vertices,_,edges=mesh(observation,p["part"])
    selected={i for i,v in enumerate(vertices) if inside(v,p["region"])}
    starts={i for i in selected if inside(vertices[i],p["from"])}
    goals={i for i in selected if inside(vertices[i],p["to"])}
    if not starts or not goals:return False,{"selected_vertices":len(selected),"start_vertices":len(starts),"goal_vertices":len(goals),"connected":False}
    adjacency={i:[] for i in selected}
    for a,b in edges:
        if a in selected and b in selected:adjacency[a].append(b);adjacency[b].append(a)
    seen=set(starts);todo=deque(starts)
    while todo:
        i=todo.popleft()
        for j in adjacency[i]:
            if j not in seen:seen.add(j);todo.append(j)
    joined=bool(seen & goals)
    return joined,{"selected_vertices":len(selected),"start_vertices":len(starts),"goal_vertices":len(goals),"reachable_vertices":len(seen),"connected":joined}


def clearance_path(p, observation, previous):
    triangles=triangles_for(observation,p["parts"])
    points=[point_value(point,observation) for point in p["points"]]
    samples=p["samples_per_segment"]
    if len(triangles)*(len(points)-1)*(samples+2)>MAX_WORK:raise ValueError("clearance work exceeds coverage budget")
    minimum=None; blocked=[];total=0
    for segment,(a,b) in enumerate(zip(points,points[1:])):
        length=norm(sub(b,a))
        if length <= 2*p["epsilon"]:raise ValueError("path segment too short")
        direction=mul(sub(b,a),1/length)
        for x,y,z in triangles:
            distance=ray_distance(a,direction,x,y,z)
            if distance is not None and p["epsilon"] < distance < length-p["epsilon"]:
                blocked.append(segment);break
        for i in range(samples+1):
            sample=add(a,mul(sub(b,a),i/samples))
            distance=min(point_triangle_distance(sample,*triangle) for triangle in triangles)
            minimum=distance if minimum is None else min(minimum,distance);total+=1
    return not blocked and minimum>=p["min_clearance"],{"blocked_segments":blocked,"segments":len(points)-1,"sample_count":total,"minimum_sampled_clearance":minimum}


def preserved_region(p, observation, previous):
    current,vertices,triangles,_=mesh(observation,p["part"])
    old,prior,old_triangles,_=mesh(previous,p["part"])
    a=sorted((tuple(v),i) for i,v in enumerate(prior) if inside(v,p["region"]))
    b=sorted((tuple(v),i) for i,v in enumerate(vertices) if inside(v,p["region"]))
    if not a or not b:raise ValueError("protected region selects no geometry")
    counts_equal=len(a)==len(b)
    maximum=max((math.dist(x[0],y[0]) for x,y in zip(a,b)), default=0)
    def topology(part, faces, points):
        mapping={index:rank for rank,(_,index) in enumerate(points)}
        assignments=part["triangle_material_indices"];normals=part["triangle_world_normals"]
        if len(assignments)!=len(faces) or len(normals)!=len(faces):raise ValueError("incomplete protected surface evidence")
        surfaces=[]
        for number,face in enumerate(faces):
            if not all(i in mapping for i in face):continue
            ranks=tuple(mapping[i] for i in face)
            corners=tuple(tuple(round(finite(c),6) for c in vector(n)) for n in normals[number])
            if len(corners)!=3:raise ValueError("invalid corner normal evidence")
            # Cyclic rotation is equivalent; reversing winding is not.
            oriented=min((ranks[shift:]+ranks[:shift],corners[shift:]+corners[:shift]) for shift in range(3))
            surfaces.append((oriented,assignments[number]))
        return Counter(surfaces)
    faces_equal=counts_equal and topology(old,old_triangles,a)==topology(current,triangles,b)
    materials_equal=current["material_hash"]==old["material_hash"]
    return counts_equal and maximum<=p["tolerance"] and faces_equal and materials_equal, {"reference_vertices":len(a),"candidate_vertices":len(b),"max_vertex_displacement":maximum,"contained_triangle_topology_equal":faces_equal,"part_materials_equal":materials_equal}


def preserved_rays(p, observation, previous):
    old=triangles_for(previous,[p["part"]]);new=triangles_for(observation,[p["part"]])
    if (len(old)+len(new))*len(p["rays"])>MAX_WORK:raise ValueError("ray work exceeds coverage budget")
    missing=[];maximum=0
    for index,ray in enumerate(p["rays"]):
        origin=vector(ray["origin"]);direction=vector(ray["direction"]);direction=mul(direction,1/norm(direction))
        hits=[]
        for mesh_triangles in (old,new):
            distances=[distance for triangle in mesh_triangles if (distance:=ray_distance(origin,direction,*triangle)) is not None and 0<=distance<=ray["max_distance"]]
            hits.append(min(distances) if distances else None)
        if None in hits:missing.append(index)
        else:maximum=max(maximum,abs(hits[0]-hits[1]))
    return not missing and maximum<=p["tolerance"],{"rays":len(p["rays"]),"missing_hit_rays":missing,"maximum_first_hit_displacement":maximum}


COVERAGE={
    "connected_path":"Mesh-edge connectivity within the declared world-space region; not load-bearing strength or watertight union.",
    "clearance_path":"Continuous centerline segment/triangle crossing plus sampled radial clearance; not exhaustive fluid flow, cross-section or manufacturing proof.",
    "preserved_region":"Selected world-vertex multiset, oriented wholly contained triangles, per-triangle material assignments, corner normals rounded to 1e-6 and part materials; boundary-crossing faces are excluded.",
    "preserved_rays":"First surface-hit distances for the specified rays only; not exhaustive surface equivalence.",
    "manual_review":"Human visual judgment; no automated measurement is claimed.",
}


def evaluate(spec: RequirementSet | dict, observation: dict | None, previous: dict | None, *, is_revision: bool | None = None) -> dict:
    if isinstance(spec,dict):spec=RequirementSet.parse(spec)
    if is_revision is None:is_revision=previous is not None
    rows=[]
    for requirement in spec.requirements:
        row={"id":requirement.id,"title":requirement.title,"kind":requirement.kind,"hard":requirement.hard,
             "applicable":not(requirement.phase=="revision" and not is_revision),"status":"unknown",
             "measured":None,"expected":requirement.params,"evidence":{"stage":"geometry_relation" if requirement.phase=="always" else "preservation_comparison"},"coverage":COVERAGE[requirement.kind]}
        try:
            if not row["applicable"]:row["evidence"]["reason"]="No parent exists; revision-only requirement is not applicable to initial construction"
            elif observation is None:row["evidence"]["reason"]="Independent observation unavailable"
            elif requirement.phase=="revision" and previous is None:row["evidence"]["reason"]="Required accepted baseline observation unavailable"
            elif requirement.kind=="manual_review":row["evidence"]["reason"]="Requires human visual review"
            else:
                passed,measured={"connected_path":connected_path,"clearance_path":clearance_path,"preserved_region":preserved_region,"preserved_rays":preserved_rays}[requirement.kind](requirement.params,observation,previous)
                row["status"]="pass" if passed else "fail";row["measured"]=measured
        except (ValueError,KeyError,IndexError,TypeError,ZeroDivisionError) as exc:
            row["evidence"]["reason"]="Measurement not verified: "+str(exc)[:300]
        rows.append(row)
    return {"schema_version":1,"requirements_hash":canonical_hash(spec.raw),"requirements":rows,
            "summary":{status:sum(r["status"]==status for r in rows) for status in ("pass","fail","unknown")},
            "requirements_satisfied":all(r["status"]=="pass" for r in rows if r["hard"] and r["applicable"])}
