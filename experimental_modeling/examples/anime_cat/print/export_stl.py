# SPDX-License-Identifier: GPL-3.0-or-later
"""Export all explicit evaluated facets, in their existing millimeter units."""
import argparse
import hashlib
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
import json
from pathlib import Path
import struct
import sys

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input',required=True)
parser.add_argument('--observer',required=True)
parser.add_argument('--output',required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
loader = SourceFileLoader('independent_print_observer',args.observer)
observer = module_from_spec(spec_from_loader(loader.name,loader))
loader.exec_module(observer)
bpy.ops.wm.open_mainfile(filepath=str(Path(args.input).resolve()))
observer.validate_inventory()
units = bpy.context.scene.unit_settings
if units.system != 'METRIC' or abs(units.scale_length-.001)>1e-10 or units.length_unit != 'MILLIMETERS':
    raise ValueError('Export requires explicit millimeter scene coordinates')
objects = {obj.name:obj for obj in bpy.context.scene.objects if obj.type=='MESH'}
if set(objects) != {'PrintCandidate','PrintBase'}:
    raise ValueError('Export requires the candidate and preserved base')
result = {'unit':'millimeter','input_sha256':hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
          'promotion_eligible':False,'physical_validation':'pending','meshes':{}}
for name in ('PrintCandidate','PrintBase'):
    with observer.evaluated_surface(objects[name]) as (mesh,bm):
        if len(mesh.loop_triangles) != len(bm.faces):
            raise ValueError('Export cannot omit evaluated source triangles')
        row = {'evaluated_triangles':len(mesh.loop_triangles),
               'surface_sha256':observer.geometry_hash(bm),
               'exact_surface_sha256':observer.geometry_hash(bm,exact=True),
               'protected_regions':observer.protected_regions(bm)}
        if name == 'PrintCandidate':
            triangles = []
            for face in bm.faces:
                points = tuple(tuple(float(value) for value in vertex.co) for vertex in face.verts)
                triangles.append(min(points[i:]+points[:i] for i in range(3)))
            output = Path(args.output)
            output.mkdir(exist_ok=True)
            stl = output/'model.stl'
            # STL has no unit metadata. Coordinates already represent mm;
            # do not multiply them by the scene's display unit scale.
            with stl.open('xb') as stream:
                stream.write(b'Anime cat provisional millimeter STL'.ljust(80,b'\0'))
                stream.write(struct.pack('<I',len(triangles)))
                for points in sorted(triangles):
                    normal = observer._normal3(points)
                    stream.write(struct.pack('<12fH',*normal,*(value for point in points for value in point),0))
            row['stl_sha256'] = hashlib.sha256(stl.read_bytes()).hexdigest()
        result['meshes'][name] = row
(Path(args.output)/'export-observation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
