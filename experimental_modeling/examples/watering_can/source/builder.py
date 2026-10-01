"""Reviewed author: local imports, passed parameter read, passed blend write only."""
import argparse,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy,bmesh
from geometry import body,handle,spout
p=argparse.ArgumentParser();p.add_argument('--params',required=True);p.add_argument('--output',required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);params=json.loads(Path(a.params).read_text())
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
def mesh(name,data):
    v,f=data;m=bpy.data.meshes.new(name);m.from_pydata(v,[],f);m.update()
    bm=bmesh.new();bm.from_mesh(m);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);bm.to_mesh(m);bm.free()
    o=bpy.data.objects.new(name,m);bpy.context.collection.objects.link(o);return o
def boolean(target,tool,operation):
    bpy.context.view_layer.objects.active=target
    mod=target.modifiers.new('Exact construction','BOOLEAN');mod.operation=operation;mod.solver='EXACT';mod.object=tool
    bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(tool,do_unlink=True)
vessel=mesh('vessel',body());grip=mesh('handle_tool',handle(params['handle_radius']));boolean(vessel,grip,'UNION')
# Drill the vessel outlet horizontally; spout starts inside cavity and overlaps wall.
bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=.135,depth=.8,end_fill_type='NGON',location=(.9,0,.55),rotation=(0,1.5707963267948966,0))
boolean(vessel,bpy.context.object,'DIFFERENCE')
nozzle=mesh('spout',spout(params['spout_lift']))
for obj,color in [(vessel,(.045,.40,.40,1)),(nozzle,(.88,.39,.10,1))]:
    obj['semantic_id']=obj.name
    mat=bpy.data.materials.new(obj.name);mat.diffuse_color=color;mat.roughness=.42;obj.data.materials.append(mat)
bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1
bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.output).resolve()))
