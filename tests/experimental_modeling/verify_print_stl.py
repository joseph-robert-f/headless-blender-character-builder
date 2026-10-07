# SPDX-License-Identifier: GPL-3.0-or-later
"""Real Blender probes for binary STL integrity and exact preservation scope."""
import argparse
import importlib.util
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import struct
import sys

import bmesh
import bpy


parser=argparse.ArgumentParser()
parser.add_argument('--observer',required=True)
parser.add_argument('--author-source',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])

def load(name,path):
    loader=SourceFileLoader(name,path)
    spec=importlib.util.spec_from_loader(name,loader)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

observer=load('print_stl_observer',args.observer)
author=load('print_stl_author',args.author_source)
output=Path(args.output);output.mkdir(exist_ok=True)
vertices=[(0,0,0),(1,0,0),(0,1,0),(0,0,1)]
faces=[(0,2,1),(0,1,3),(0,3,2),(1,2,3)]
facets=[struct.pack('<12fH',0,0,0,*(x for i in face for x in vertices[i]),0) for face in faces]
data=b'Integrity regression'.ljust(80,b'\0')+struct.pack('<I',4)+b''.join(facets)
valid=output/'valid.stl';valid.write_bytes(data)
_,points,rows=observer.read_stl(valid)
assert len(points)==4 and len(rows)==4
results={'valid_complete_tetrahedron':True}
malformed={'truncated':data[:-1],'trailing':data+b'x',
           'zero-count':data[:80]+struct.pack('<I',0)+data[84:],
           'budget-count':data[:80]+struct.pack('<I',500001)+data[84:],
           'nonzero-attribute':data[:132]+struct.pack('<H',1)+data[134:],
           'nonfinite-normal':data[:84]+struct.pack('<f',float('nan'))+data[88:],
           'nonfinite-vertex':data[:96]+struct.pack('<f',float('inf'))+data[100:],
           'collapsed-facet':data[:108]+data[96:108]+data[120:]}
for name,raw in malformed.items():
    path=output/(name+'.stl');path.write_bytes(raw)
    try:observer.read_stl(path)
    except ValueError:results[name]=True
    else:raise AssertionError('Malformed STL accepted: '+name)
duplicate=output/'duplicate.stl'
duplicate.write_bytes(data[:80]+struct.pack('<I',5)+data[84:]+facets[0])
_,obj,count=observer.stl_object(duplicate)
with observer.evaluated_surface(obj) as (mesh,bm):
    assert count==len(mesh.loop_triangles)==len(bm.faces)==5
    assert sum(not edge.is_manifold for edge in bm.edges)==3
results['duplicate_facet_retained_and_nonmanifold']=True

def mesh_object(points,rows):
    mesh=bpy.data.meshes.new('Probe mesh');mesh.from_pydata(points,[],rows)
    obj=bpy.data.objects.new('Probe',mesh);bpy.context.collection.objects.link(obj)
    return obj

obj=mesh_object(vertices,faces)
with observer.evaluated_surface(obj) as (_,bm):
    exact=observer.geometry_hash(bm,exact=True);rounded=observer.geometry_hash(bm)
    bm.verts[0].co.x=-0.0
    assert observer.geometry_hash(bm,exact=True)==exact
    bm.verts[0].co.x=0.0
    # One float32 ULP is smaller than the legacy six-decimal fingerprint.
    bm.verts[1].co.x=1.0000001192092896
    assert observer.geometry_hash(bm)==rounded
    assert observer.geometry_hash(bm,exact=True)!=exact
results['signed_zero_normalized_and_one_ulp_detected']=True
obj=mesh_object(vertices,faces)
with observer.evaluated_surface(obj) as (_,bm):
    points=[vertex.co for vertex in bm.verts]
    measured={'evaluated_triangles':4,'measured_triangles':4,
              'intersection_measurement':{'complete':True},
              'surface_sha256':observer.geometry_hash(bm),
              'exact_surface_sha256':observer.geometry_hash(bm,exact=True),
              'bounds_mm':{'min':[min(p[i] for p in points) for i in range(3)],
                           'max':[max(p[i] for p in points) for i in range(3)]}}
reference={'revision':'r0','unit':'millimeter','input_sha256':'a'*64,'meshes':{'PrintCandidate':measured}}
binding=observer.render_binding(obj,reference,'r0','a'*64)
assert binding['exact_surface_sha256']==measured['exact_surface_sha256']
measured['exact_surface_sha256']='b'*64
try:observer.render_binding(obj,reference,'r0','a'*64)
except ValueError:pass
else:raise AssertionError('Wrong exact fingerprint authorized a preview')
results['preview_requires_exact_full_surface_fingerprint']=True
outside=[(42,0,90),(0,42,90),(42,42,90)]
obj=mesh_object(vertices+outside,faces+[(4,5,6)])
with observer.evaluated_surface(obj) as (_,bm):
    before=observer.protected_regions(bm)['r1']
    assert before['triangles']==5
    bm.verts[4].co.x+=.001
    assert observer.protected_regions(bm)['r1']['surface_sha256']!=before['surface_sha256']
results['outside_triangle_retained_despite_box_overlapping_aabb']=True
boundary=[(20,0,90),(19,0,91),(19,1,90)]
obj=mesh_object(vertices+boundary,faces+[(4,5,6)])
with observer.evaluated_surface(obj) as (_,bm):
    assert observer.protected_regions(bm)['r1']['triangles']==5
results['facet_touching_exact_box_boundary_retained']=True

# A two-sided planar component must never disappear during protected assembly.
cube_vertices=[(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),(-1,-1,2),(1,-1,2),(1,1,2),(-1,1,2)]
cube_faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),
            (2,3,7),(2,7,6),(3,0,4),(3,4,7)]
base=mesh_object(cube_vertices,cube_faces)
plane=[(0,0,90),(1,0,90),(0,1,90)]
bad=mesh_object(cube_vertices+plane,cube_faces+[(8,9,10),(8,10,9)])
for obj,reference in ((bad,base),(base,bad)):
    try:author.restore_protected(obj,reference,'r1')
    except ValueError as exc:assert 'operands' in str(exc)
    else:raise AssertionError('Protected assembly discarded an operand component')
results['both_operand_components_checked_before_selection']=True
(output/'stl-probes.json').write_text(json.dumps({'status':'passed','probes':results},indent=2)+'\n')
print(json.dumps({'status':'passed','probes':len(results)}))
