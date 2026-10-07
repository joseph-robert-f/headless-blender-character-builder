# SPDX-License-Identifier: GPL-3.0-or-later
"""Real Blender transaction, exact local delta and observer policy regressions."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

import bmesh
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parent))
import solids
import x1c_solids as author
import inspect_solid as observer

parser=argparse.ArgumentParser()
parser.add_argument('--params',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
assert json.loads(Path(args.params).read_text())=={'revision':'r1'}
original,base=solids.build('r1')


def encoded_rows(obj):
    rows=[]
    for face in obj.data.polygons:
        points=tuple(tuple(float(v) for v in obj.data.vertices[i].co) for i in face.vertices)
        rows.append(min(points[i:]+points[:i] for i in range(3)))
    return Counter(rows)


def state(obj):
    # Full original indexed mesh and profile tags, independent of author helpers.
    sha=hashlib.sha256()
    for vertex in obj.data.vertices:sha.update(struct.pack('<3f',*vertex.co))
    for face in obj.data.polygons:sha.update(struct.pack('<3I',*face.vertices))
    return (len(obj.data.vertices),len(obj.data.polygons),sha.hexdigest(),obj.get('print_profile_id'))


def clone(obj):
    copy=obj.copy();copy.data=obj.data.copy();bpy.context.collection.objects.link(copy)
    return copy


def rejected(obj, *, repair_hat, message):
    before=state(obj)
    try:author.resize(obj,repair_hat=repair_hat)
    except ValueError as exc:assert message in str(exc),str(exc)
    else:raise AssertionError('Unreviewed resize was accepted')
    assert state(obj)==before,'Rejected transaction changed the complete mesh or profile tag'


results={}
obj=clone(original);rejected(obj,repair_hat=False,message='orientation reversals')
bpy.data.objects.remove(obj,do_unlink=True);results['missing_hat_repair_rejects_without_mesh_change']=True
obj=clone(base);rejected(obj,repair_hat=True,message='orientation reversals')
bpy.data.objects.remove(obj,do_unlink=True);results['hat_repair_cannot_select_base_or_missing_quads']=True

# First quad is valid; only the second neighbor's opposite point changes1ULP.
obj=clone(original);point=author.HAT_QUADS[1][3]
matches=[v for v in obj.data.vertices if tuple(v.co)==point];assert len(matches)==1
bits=struct.unpack('<I',struct.pack('<f',point[0]))[0]
matches[0].co.x=struct.unpack('<f',struct.pack('<I',bits+1))[0]
obj.data.update();rejected(obj,repair_hat=True,message='neighbor or orientation changed')
bpy.data.objects.remove(obj,do_unlink=True);results['second_quad_rejection_cannot_commit_first_rotation']=True

obj=clone(original);point=author.HAT_QUADS[0][1]
matches=[v for v in obj.data.vertices if tuple(v.co)==point];assert len(matches)==1
bits=struct.unpack('<I',struct.pack('<f',point[0]))[0]
matches[0].co.x=struct.unpack('<f',struct.pack('<I',bits+1))[0]
obj.data.update();rejected(obj,repair_hat=True,message='orientation reversals')
bpy.data.objects.remove(obj,do_unlink=True);results['changed_precision_sensitive_triangle_cannot_select_other_quad']=True

obj=clone(original);before=encoded_rows(obj)
mapped=Counter(tuple(tuple(struct.unpack('<f',struct.pack('<f',v*1.0854632543541882))[0] for v in point)
                            for point in row) for row in before.elements())
mapped=Counter(min(row[i:]+row[:i] for i in range(3)) for row in mapped.elements())
old_vertices={tuple(vertex.co) for vertex in obj.data.vertices}
author.resize(obj,repair_hat=True);after=encoded_rows(obj)
assert sum((mapped-after).values())==sum((after-mapped).values())==4
assert len(obj.data.polygons)==376362 and len(obj.data.vertices)==188179
assert {tuple(vertex.co) for vertex in obj.data.vertices}=={
    tuple(struct.unpack('<f',struct.pack('<f',v*1.0854632543541882))[0] for v in point) for point in old_vertices}
results['exactly_two_diagonals_four_facets_and_same_full_vertex_set']=True

observer.configure_profile(observer.X1C_PROFILE_ID)
for name in (observer.DEFAULT_PROFILE_ID,'unknown'):
    if name=='unknown':
        try:observer.configure_profile(name)
        except ValueError:pass
        else:raise AssertionError('Unknown observer policy was accepted')
    else:
        observer.configure_profile(name)
        try:observer.validate_inventory()
        except ValueError as exc:assert 'different print profile' in str(exc)
        else:raise AssertionError('Opposite saved profile metadata was accepted')
results['unknown_observer_policy_and_opposite_saved_profile_rejected']=True
for other in list(bpy.context.scene.objects):
    if other is not obj:bpy.data.objects.remove(other,do_unlink=True)
observer.configure_profile(observer.X1C_PROFILE_ID);observer.validate_inventory()
del obj['print_profile_id']
try:observer.validate_inventory()
except ValueError:pass
else:raise AssertionError('Missing new saved profile metadata was accepted')
results['missing_saved_new_profile_metadata_rejected']=True

bm=bmesh.new()
try:
    x=21.709264755249023
    vertices=[bm.verts.new(p) for p in ((x,0,98),(x-.1,0,98.1),(x-.1,.1,98))]
    bm.faces.new(vertices)
    assert observer.protected_regions(bm)['r1']['triangles']==1
    results['exact_scaled_box_boundary_facet_retained']=True
finally:bm.free()
output=Path(args.output);output.mkdir(exist_ok=True)
(output/'resize-probes.json').write_text(json.dumps({'status':'passed','tests':results,'count':len(results),
    'scope':'Real author transaction and local delta probes; full geometry/native acceptance remains separate'},indent=2)+'\n')
print(json.dumps(results))
