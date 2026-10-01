"""Run in Blender: --background --python builder.py -- --params p.json --output scene.blend."""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from parts import meshes


def main():
    import bpy
    parser=argparse.ArgumentParser()
    parser.add_argument('--params',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    params=json.loads(Path(args.params).read_text())
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    palette={'body':(.10,.22,.27,1),'mast':(.85,.36,.10,1),'cargo_tray':(.20,.45,.36,1)}
    for semantic_id,(vertices,faces) in meshes(params).items():
        mesh=bpy.data.meshes.new(semantic_id+'_mesh'); mesh.from_pydata(vertices,[],faces); mesh.update()
        obj=bpy.data.objects.new(semantic_id,mesh); bpy.context.collection.objects.link(obj)
        obj['semantic_id']=semantic_id
        material=bpy.data.materials.new(semantic_id+'_material'); material.diffuse_color=palette.get(semantic_id,(.46,.52,.56,1)); obj.data.materials.append(material)
    bpy.context.scene.unit_settings.system='METRIC'
    output=Path(args.output).resolve(); output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))

if __name__=='__main__': main()
