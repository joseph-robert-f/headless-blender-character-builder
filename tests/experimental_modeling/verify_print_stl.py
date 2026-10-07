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
reference={**observer.profile_binding(),'revision':'r0','unit':'millimeter','input_sha256':'a'*64,'meshes':{'PrintCandidate':measured}}
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

# A closed frustum retains the real cut quad and full cat bounding center.
# The alternate diagonal must preserve vertices, topology and its planar cap.
quad=[(-15.388243675231934,2.8162667751312256,0),
      (-15.388137817382812,2.8163833618164062,0),
      (-15.224020957946777,2.9970552921295166,0),
      (-14.13800048828125,3.9858973026275635,0)]
top=[(-30.03129768371582,-25.507780075073242,92.1265640258789),
     (-30.03129768371582,18.070018768310547,92.1265640258789),
     (40.66703414916992,18.070018768310547,92.1265640258789),
     (40.66703414916992,-25.507780075073242,92.1265640258789)]
frustum_faces=[(0,1,2),(0,2,3),(4,6,5),(4,7,6)]
for i in range(4):
    j=(i+1)%4
    frustum_faces.extend([(j,i,i+4),(j,i+4,j+4)])
frustum=mesh_object(quad+top,frustum_faces)
before_points=sorted(tuple(v.co) for v in frustum.data.vertices)
with observer.evaluated_surface(frustum) as (_,bm):
    old_hash=observer.geometry_hash(bm,exact=True)
assert author.stabilize_cut_diagonals(frustum,'ground')==1
assert sorted(tuple(v.co) for v in frustum.data.vertices)==before_points
assert len(frustum.data.polygons)==12
cap={frozenset(tuple(frustum.data.vertices[i].co) for i in face.vertices)
     for face in frustum.data.polygons if all(frustum.data.vertices[i].co.z==0 for i in face.vertices)}
assert cap=={frozenset((quad[0],quad[1],quad[3])),frozenset((quad[1],quad[2],quad[3]))}
with observer.evaluated_surface(frustum) as (_,bm):
    assert all(edge.is_manifold and edge.is_contiguous for edge in bm.edges)
    assert observer.geometry_hash(bm,exact=True)!=old_hash
    new_hash=observer.geometry_hash(bm,exact=True)
results['ground_rotation_preserves_exact_cap_vertices_and_topology']=True
for scope in ('ground','glasses','unreviewed'):
    try:author.stabilize_cut_diagonals(frustum,scope)
    except ValueError:pass
    else:raise AssertionError('Unmatched cut-diagonal scope was silently accepted')
    with observer.evaluated_surface(frustum) as (_,bm):
        assert observer.geometry_hash(bm,exact=True)==new_hash
results['cut_rotation_rejects_repeated_missing_and_unknown_targets']=True
detached=mesh_object(quad+top+vertices,frustum_faces+[tuple(i+8 for i in face) for face in faces])
with observer.evaluated_surface(detached) as (_,bm):
    disconnected_hash=observer.geometry_hash(bm,exact=True)
try:author.stabilize_cut_diagonals(detached,'ground')
except ValueError as exc:assert 'closed oriented solid' in str(exc)
else:raise AssertionError('Cut rotation accepted a detached component')
with observer.evaluated_surface(detached) as (_,bm):
    assert observer.geometry_hash(bm,exact=True)==disconnected_hash
results['cut_rotation_rejects_detached_component_before_mutation']=True

# Closed, coherently wound joined prisms expose two scope mistakes: both
# targets on one side, and an out-of-window fourth vertex on the other facet.
# Reject transactionally, even when an earlier target could rotate successfully.
rejection_meshes = [('same_side_two_right',
  [[8.88880443572998, -23.361297607421875, 59.054161071777344],
   [8.904789924621582, -23.501811981201172, 59.143253326416016],
   [8.903944969177246, -23.501750946044922, 59.14345932006836],
   [8.904609680175781, -23.501798629760742, 59.1432991027832],
   [8.88880443572998, -22.361297607421875, 60.054161071777344],
   [8.904789924621582, -22.501811981201172, 60.143253326416016],
   [8.903944969177246, -22.501750946044922, 60.14345932006836],
   [8.904609680175781, -22.501798629760742, 60.1432991027832],
   [8.938804626464844, -23.361297607421875, 59.054161071777344],
   [8.954790115356445, -23.501811981201172, 59.143253326416016],
   [8.95394515991211, -23.501750946044922, 59.14345932006836],
   [8.954609870910645, -23.501798629760742, 59.1432991027832],
   [8.938804626464844, -22.361297607421875, 60.054161071777344],
   [8.954790115356445, -22.501811981201172, 60.143253326416016],
   [8.95394515991211, -22.501750946044922, 60.14345932006836],
   [8.954609870910645, -22.501798629760742, 60.1432991027832]],
  [[0, 1, 2],
   [2, 1, 3],
   [6, 5, 4],
   [7, 5, 6],
   [3, 1, 5],
   [3, 5, 7],
   [2, 3, 7],
   [2, 7, 6],
   [0, 2, 6],
   [0, 6, 4],
   [8, 9, 10],
   [10, 9, 11],
   [14, 13, 12],
   [15, 13, 14],
   [9, 8, 12],
   [9, 12, 13],
   [11, 9, 13],
   [11, 13, 15],
   [10, 11, 15],
   [10, 15, 14],
   [1, 0, 8],
   [1, 8, 10],
   [0, 4, 12],
   [0, 12, 8],
   [4, 5, 14],
   [4, 14, 12],
   [5, 1, 10],
   [5, 10, 14]],
  'Reviewed cut-diagonal side count changed'),
 ('out_of_window_fourth_vertex',
  [[-8.88880443572998, -23.361297607421875, 59.054161071777344],
   [-8.903924942016602, -23.501752853393555, 59.14345932006836],
   [-8.904789924621582, -23.501813888549805, 59.14324951171875],
   [-8.9046049118042, -23.501800537109375, 59.14329528808594],
   [-8.88880443572998, -22.361297607421875, 60.054161071777344],
   [-8.903924942016602, -22.501752853393555, 60.14345932006836],
   [-8.904789924621582, -22.501813888549805, 60.14324951171875],
   [-8.9046049118042, -22.501800537109375, 60.14329528808594],
   [8.789999961853027, -23.361297607421875, 59.054161071777344],
   [8.904789924621582, -23.501811981201172, 59.143253326416016],
   [8.903944969177246, -23.501750946044922, 59.14345932006836],
   [8.904609680175781, -23.501798629760742, 59.1432991027832],
   [8.789999961853027, -22.361297607421875, 60.054161071777344],
   [8.904789924621582, -22.501811981201172, 60.143253326416016],
   [8.903944969177246, -22.501750946044922, 60.14345932006836],
   [8.904609680175781, -22.501798629760742, 60.1432991027832]],
  [[0, 1, 2],
   [2, 1, 3],
   [6, 5, 4],
   [7, 5, 6],
   [3, 1, 5],
   [3, 5, 7],
   [2, 3, 7],
   [2, 7, 6],
   [0, 2, 6],
   [0, 6, 4],
   [8, 9, 10],
   [10, 9, 11],
   [14, 13, 12],
   [15, 13, 14],
   [9, 8, 12],
   [9, 12, 13],
   [11, 9, 13],
   [11, 13, 15],
   [10, 11, 15],
   [10, 15, 14],
   [1, 0, 8],
   [1, 8, 10],
   [0, 4, 12],
   [0, 12, 8],
   [4, 5, 14],
   [4, 14, 12],
   [5, 1, 10],
   [5, 10, 14]],
  'Reviewed cut-diagonal quadrilateral exceeds its local window')]
for name,points,rows,diagnostic in rejection_meshes:
    obj=mesh_object(points,rows)
    with observer.evaluated_surface(obj) as (_,bm):
        assert author.face_components(bm)==1 and bm.calc_volume(signed=True)>0
        assert all(edge.is_manifold and edge.is_contiguous for edge in bm.edges)
        assert all(vertex.is_manifold for vertex in bm.verts)
        before=observer.geometry_hash(bm,exact=True)
    try:author.stabilize_cut_diagonals(obj,'glasses')
    except ValueError as exc:assert str(exc)==diagnostic, str(exc)
    else:raise AssertionError('Unreviewed local cut quad accepted: '+name)
    with observer.evaluated_surface(obj) as (_,bm):
        assert observer.geometry_hash(bm,exact=True)==before
    results['cut_rotation_rejects_'+name+'_without_mutation']=True

(output/'stl-probes.json').write_text(json.dumps({'status':'passed','probes':results},indent=2)+'\n')
print(json.dumps({'status':'passed','probes':len(results)}))
