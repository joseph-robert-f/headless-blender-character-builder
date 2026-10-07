# SPDX-License-Identifier: GPL-3.0-or-later
"""Real Blender regressions for intersection and geometry inventory coverage."""
import argparse
import copy
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import json
from pathlib import Path
import sys

import bmesh
import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--observer',required=True)
parser.add_argument('--author-source')
parser.add_argument('--output',required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
loader = SourceFileLoader('independent_print_observer',args.observer)
observer = module_from_spec(spec_from_loader(loader.name,loader))
loader.exec_module(observer)
fixtures = [
    ('valid-coplanar-skinny-bridge',[(-4.929965972900391,-16.886795043945312,86.03174591064453),(-3.3132500648498535,-17.291763305664062,86.03174591064453),(-2.3810935020446777,-12.605486869812012,86.03174591064453),(-2.381093740463257,-12.605486869812012,86.03174591064453),(-3.5429484844207764,-12.314457893371582,86.03174591064453)],[(0,1,2),(0,3,4),(0,2,3)],0),
    ('float32-area-valid-facet',[(-4.9299659729,-16.8867950439,86.0317459106),(-2.3810935020,-12.6054868698,86.0317459106),(-2.3810937405,-12.6054868698,86.0317459106)],[(0,1,2)],0),
    ('valid-tiny-facet',[(0,0,0),(.000016,0,0),(.000008,.0000138564,0)],[(0,1,2)],0),
    ('shared-vertex-crossing',[(0,0,0),(2,0,0),(0,2,0),(1,1,-1),(1,1,1)],[(0,1,2),(0,3,4)],1),
    ('contained-coplanar',[(0,0,0),(2,0,0),(0,2,0),(.2,.2,0),(.8,.2,0),(.2,.8,0)],[(0,1,2),(3,4,5)],1),
    ('valid-shared-edge',[(0,0,0),(2,0,0),(0,2,0),(2,-2,0)],[(0,1,2),(1,0,3)],0),
    ('overlapping-shared-edge',[(0,0,0),(2,0,0),(0,2,0),(1,1,0)],[(0,1,2),(0,1,3)],1),
    ('overlapping-shared-vertex',[(0,0,0),(2,0,0),(0,2,0),(1,.2,0),(.2,1,0)],[(0,1,2),(0,3,4)],1),
    ('valid-shared-vertex',[(0,0,0),(2,0,0),(0,2,0),(-2,0,0),(0,-2,0)],[(0,1,2),(0,3,4)],0),
    ('disjoint-parallel',[(0,0,0),(2,0,0),(0,2,0),(0,0,1),(2,0,1),(0,2,1)],[(0,1,2),(3,4,5)],0),
    ('tiny-contained-coplanar',[(0,0,0),(.002,0,0),(0,.002,0),(.0002,.0002,0),(.0008,.0002,0),(.0002,.0008,0)],[(0,1,2),(3,4,5)],1),
]
results = []
for name,vertices,faces,expected in fixtures:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices,[],faces)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        result = observer.intersections(bm)
        if result['count_lower_bound'] != expected or result['complete'] is not True:
            raise ValueError('Intersection regression: '+name)
        results.append({'fixture':name,'expected_intersections':expected,**result})
    finally:
        bm.free()
        bpy.data.meshes.remove(mesh)
mesh = bpy.data.meshes.new('True collinear triangle')
mesh.from_pydata([(0,0,0),(1,0,0),(2,0,0)],[],[(0,1,2)])
bm = bmesh.new()
try:
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    try:
        observer.intersections(bm)
    except ValueError:
        results.append({'fixture':'true-degenerate-triangle','status':'rejected'})
    else:
        raise ValueError('True degenerate triangle was not rejected')
finally:
    bm.free()
    bpy.data.meshes.remove(mesh)
observer.validate_inventory()
obj = bpy.data.objects['Cube']
try:
    observer.observe(obj,'r0')
except ValueError as exc:
    if 'explicit triangles' not in str(exc):
        raise
    results.append({'fixture':'ambiguous-quad-tessellation','status':'rejected'})
else:
    raise ValueError('Non-triangular final surface was not rejected')
modifier = obj.modifiers.new('Render-only subdivision','SUBSURF')
modifier.show_viewport = False
modifier.show_render = True
try:
    try:
        observer.observe(obj,'r0')
    except ValueError:
        results.append({'fixture':'render-only-modifier','status':'rejected'})
    else:
        raise ValueError('Unmeasured render modifier was not rejected')
finally:
    obj.modifiers.remove(modifier)
bm = bmesh.new()
try:
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    bm.to_mesh(obj.data)
finally:
    bm.free()
measured = observer.observe(obj,'r0')
reference = {**observer.profile_binding(),'revision':'r0','unit':'millimeter','input_sha256':'a'*64,
             'meshes':{'PrintCandidate':measured}}
observer.render_binding(obj,reference,'r0','a'*64)
results.append({'fixture':'render-complete-surface-binding','status':'passed'})
for name,key,value in [('surface','surface_sha256','b'*64),
                       ('count','measured_triangles',1),
                       ('bounds','bounds_mm',{'min':[0,0,0],'max':[1,1,1]}),
                       ('incomplete','intersection_measurement',{'complete':False})]:
    changed = copy.deepcopy(reference)
    changed['meshes']['PrintCandidate'][key] = value
    try:
        observer.render_binding(obj,changed,'r0','a'*64)
    except ValueError:
        results.append({'fixture':'render-reject-'+name,'status':'rejected'})
    else:
        raise ValueError('Render accepted a changed '+name+' reference')
try:
    observer.render_binding(obj,reference,'r0','b'*64)
except ValueError:
    results.append({'fixture':'render-reject-input-digest','status':'rejected'})
else:
    raise ValueError('Render accepted a different input candidate')
curve = bpy.data.curves.new('Unmeasured curve','CURVE')
obj = bpy.data.objects.new('Unmeasured curve',curve)
bpy.context.collection.objects.link(obj)
try:
    try:
        observer.validate_inventory()
    except ValueError:
        results.append({'fixture':'unsupported-curve','status':'rejected'})
    else:
        raise ValueError('Unmeasured visible geometry was not rejected')
finally:
    bpy.data.objects.remove(obj,do_unlink=True)
    bpy.data.curves.remove(curve)
if args.author_source:
    # The test may load the fixed author to verify its cleanup rejection.
    # The independent observer itself never imports or repairs author geometry.
    loader = SourceFileLoader('reviewed_print_author',args.author_source)
    author = module_from_spec(spec_from_loader(loader.name,loader))
    loader.exec_module(author)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add(size=10)
    main = bpy.context.object
    bpy.ops.mesh.primitive_cube_add(size=.000002,location=(20,0,0))
    tiny = bpy.context.object
    obj = author.join([main,tiny],'Two components')
    try:
        author.triangulated(obj,weld_mm=True)
    except ValueError as exc:
        if 'preserve every face-connected component' not in str(exc):
            raise
        results.append({'fixture':'cleanup-component-collapse','status':'rejected'})
    else:
        raise ValueError('Cleanup discarded a microscopic component')
output = Path(args.output)
output.mkdir(exist_ok=True)
(output/'intersection-regressions.json').write_text(json.dumps({'status':'passed','fixtures':results},indent=2)+'\n')
print('Intersection and inventory fixtures passed:',len(results))
