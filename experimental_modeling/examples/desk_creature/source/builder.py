# SPDX-License-Identifier: GPL-3.0-or-later
"""Reviewed author reads passed params and writes passed .blend; no external I/O."""
import argparse
import json
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from composition import meshes
import bpy
import bmesh
p=argparse.ArgumentParser(); p.add_argument('--params',required=True); p.add_argument('--output',required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]); params=json.loads(Path(a.params).read_text())
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
colors={'body':(.10,.48,.35,1),'tail':(.95,.38,.08,1),'crescent':(.49,.29,.70,1)}
def label(o,name):
    o.name=name; o['semantic_id']=name
    m=bpy.data.materials.new(name); m.diffuse_color=colors.get(name,(.045,.07,.08,1) if name.startswith('eye') else (.16,.31,.25,1)); o.data.materials.append(m)
for name,(vertices,faces) in meshes(params).items():
    m=bpy.data.meshes.new(name); m.from_pydata(vertices,[],faces); m.update()
    bm=bmesh.new(); bm.from_mesh(m); bmesh.ops.recalc_face_normals(bm,faces=bm.faces); bm.to_mesh(m); bm.free()
    o=bpy.data.objects.new(name,m); bpy.context.collection.objects.link(o); label(o,name)
for name,location,scale in [('body',(0,0,1.13),(.8,.64,.62)),('eye_left',(-.29,-.59,1.39),(.18,.095,.23)),('eye_right',(.27,-.60,1.35),(.115,.09,.15))]:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=location)
    o=bpy.context.object; o.scale=scale; label(o,name)
bpy.context.scene.unit_settings.system='METRIC'; bpy.context.scene.unit_settings.scale_length=1
bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.output).resolve()))
