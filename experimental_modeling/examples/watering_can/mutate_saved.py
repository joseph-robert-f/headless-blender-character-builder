"""Reviewed local saved-artifact mutations; no authored construction imports."""
import argparse,json,math,sys
from pathlib import Path
import bpy
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--out',required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
root=Path(a.out).resolve();root.mkdir(parents=True,exist_ok=True)
log=[]
for name in ['detach_upper','block_spout','alter_body']:
    bpy.ops.wm.open_mainfile(filepath=str(Path(a.baseline).resolve()),use_scripts=False)
    objects={o.get('semantic_id'):o for o in bpy.context.scene.objects if o.type=='MESH'}
    vessel,spout=objects['vessel'],objects['spout']
    if name=='detach_upper':
        bpy.ops.mesh.primitive_cube_add(size=1,location=(-1.11,0,1.38));cut=bpy.context.object;cut.scale=(.16,.8,.66)
        bpy.context.view_layer.objects.active=vessel
        mod=vessel.modifiers.new('Remove upper neck only','BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=cut
        bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(cut,do_unlink=True)
        detail='Closed Boolean slot X[-1.19,-1.03], Y[-.4,.4], Z[1.05,1.71], cuts upper neck; lower untouched'
    elif name=='block_spout':
        mesh=spout.data;vertices=[tuple(v.co) for v in mesh.vertices];faces=[tuple(f.vertices) for f in mesh.polygons]
        center=lambda i:sum((Vector(vertices[j]) for j in range(i*16,i*16+16)),Vector())/16
        c=(center(18)+center(19))/2;t=(center(19)-center(18)).normalized();u=Vector((0,1,0));w=t.cross(u).normalized();offset=len(vertices)
        for depth in [-.035,.035]:
            for k in range(16):
                theta=2*math.pi*k/16;v=c+t*depth+.155*(math.cos(theta)*u+math.sin(theta)*w);vertices.append(tuple(v))
        faces.extend([tuple(offset+i for i in range(15,-1,-1)),tuple(offset+16+i for i in range(16))])
        faces.extend([(offset+i,offset+(i+1)%16,offset+(i+1)%16+16,offset+i+16) for i in range(16)])
        replacement=bpy.data.meshes.new('Passage plugged');replacement.from_pydata(vertices,[],faces);replacement.update()
        for mat in mesh.materials:replacement.materials.append(mat)
        spout.data=replacement
        detail='Closed .07-thick radius-.155 plug between stations18/19; original 800 vertices preserved'
    else:
        changed=[]
        for v in vessel.data.vertices:
            if v.co.y>.65 and v.co.x>-.2:
                v.co.y+=.08;changed.append(v.index)
        vessel.data.update();detail={'protected_vertex_shift_y':.08,'changed_vertices':changed}
    bpy.ops.wm.save_as_mainfile(filepath=str(root/(name+'.blend')))
    log.append({'name':name,'mutation':detail})
(root/'mutation-intents.json').write_text(json.dumps(log,indent=2)+'\n')
