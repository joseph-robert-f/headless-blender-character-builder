# SPDX-License-Identifier: GPL-3.0-or-later
"""Real complete-mesh delta and failed two-mesh transaction regressions."""
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
import x1c_bambu_solids as author
from x1c_solids import build_x1c

parser=argparse.ArgumentParser()
parser.add_argument('--params',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
assert json.loads(Path(args.params).read_text())=={'revision':'r0'}
original,base=build_x1c('r0')


def state(obj):
    sha=hashlib.sha256()
    for v in obj.data.vertices:sha.update(struct.pack('<3f',*v.co))
    for f in obj.data.polygons:sha.update(struct.pack('<3I',*f.vertices))
    return (len(obj.data.vertices),len(obj.data.polygons),sha.hexdigest(),obj.get('print_profile_id'),obj.get('print_derivation_version'))


def rows(obj):
    result=[]
    for f in obj.data.polygons:
        p=tuple(tuple(float(x) for x in obj.data.vertices[i].co) for i in f.vertices)
        result.append(min(p[i:]+p[:i] for i in range(3)))
    return Counter(result)


def clone(obj):
    copy=obj.copy();copy.data=obj.data.copy();bpy.context.collection.objects.link(copy)
    return copy


def reject(obj, message):
    before=state(obj);data=obj.data
    try:author.rotate_floor(obj)
    except ValueError as exc:assert message in str(exc),str(exc)
    else:raise AssertionError('Unreviewed floor source was accepted')
    assert state(obj)==before and obj.data is data,'Rejected floor transaction changed mesh or tags'


def discard(obj):
    mesh=obj.data
    bpy.data.objects.remove(obj,do_unlink=True)
    if mesh.users==0:bpy.data.meshes.remove(mesh)


results={}
wrong=clone(original);wrong['print_profile_id']='anime-cat-x1c-pla-04-bare100-v3'
reject(wrong,'reviewed completed v2');discard(wrong);results['wrong_profile_rejects_without_change']=True
changed=clone(original)
point=(-16.70351219177246,3.056802749633789,0.0)
matches=[v for v in changed.data.vertices if tuple(v.co)==point];assert len(matches)==1
bits=struct.unpack('<I',struct.pack('<f',point[0]))[0]
matches[0].co.x=struct.unpack('<f',struct.pack('<I',bits+1))[0];changed.data.update()
reject(changed,'oriented floor pair');discard(changed);results['one_ULP_source_change_rejected_without_change']=True
for kind in ('reversed','absent'):
    invalid=clone(original);bm=bmesh.new()
    try:
        bm.from_mesh(invalid.data)
        face=next(f for f in bm.faces if {tuple(v.co) for v in f.verts}==set(author.OLD[0]))
        if kind=='reversed':face.normal_flip()
        else:bmesh.ops.delete(bm,geom=[face],context='FACES_ONLY')
        bm.to_mesh(invalid.data);invalid.data.update()
    finally:bm.free()
    reject(invalid,'closed triangulated solid');discard(invalid)
    results[kind+'_floor_face_rejected_without_change']=True

candidate=clone(original);reference=clone(base)
matches=[v for v in reference.data.vertices if tuple(v.co)==point];assert len(matches)==1
matches[0].co.x=struct.unpack('<f',struct.pack('<I',bits+1))[0];reference.data.update()
before=(state(candidate),state(reference));data=(candidate.data,reference.data);mesh_count=len(bpy.data.meshes)
real_builder=author.build_x1c
try:
    author.build_x1c=lambda revision:(candidate,reference)
    try:author.build_x1c_bambu('r0')
    except ValueError as exc:assert 'oriented floor pair' in str(exc)
    else:raise AssertionError('Changed second reference was accepted')
finally:author.build_x1c=real_builder
assert (state(candidate),state(reference))==before and (candidate.data,reference.data)==data
assert len(bpy.data.meshes)==mesh_count,'Rejected second mesh leaked a prepared replacement'
discard(candidate);discard(reference)
results['second_mesh_failure_cannot_commit_first_mesh_or_profile']=True

success=clone(original);before=rows(success)
vertices={tuple(v.co) for v in success.data.vertices}
old=(((-16.88590431213379,2.855515718460083,0.0),(-16.70351219177246,3.056802749633789,0.0),(-16.703372955322266,3.0569541454315186,0.0)),
     ((-16.88590431213379,2.855515718460083,0.0),(-16.703372955322266,3.0569541454315186,0.0),(-16.84747314453125,-11.167367935180664,0.0)))
new=((old[0][0],old[0][1],old[1][2]),(old[0][1],old[0][2],old[1][2]))
canonical=lambda p:min(p[i:]+p[:i] for i in range(3))
author.rotate_floor(success);after=rows(success)
assert before-after==Counter(map(canonical,old)) and after-before==Counter(map(canonical,new))
assert sum(before.values())==sum(after.values())==383540
assert {tuple(v.co) for v in success.data.vertices}==vertices
assert success['print_profile_id']=='anime-cat-x1c-pla-04-bare100-v3'
assert state(original)[3]=='anime-cat-x1c-pla-04-bare100-v2'
reject(success,'reviewed completed v2')
success['print_profile_id']='anime-cat-x1c-pla-04-bare100-v2'
reject(success,'oriented floor pair')
results['retagged_already_rotated_source_rejected_without_change']=True
results['exactly_two_floor_facets_same_complete_vertex_set_and_old_source_unchanged']=True

output=Path(args.output);output.mkdir(exist_ok=True)
(output/'floor-probes.json').write_text(json.dumps({'status':'passed','count':len(results),'tests':results,
    'scope':'Actual v2 mesh and v3 local author transaction regressions; complete source/STL/native/physical acceptance remains separate.'},indent=2)+'\n')
print(json.dumps(results))
