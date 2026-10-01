"""Build one visual lamp scene from explicit dimensions in meters."""
import argparse
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geometry import base, stem, shade, light, material

parser = argparse.ArgumentParser()
parser.add_argument('--params', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
params = json.loads(Path(args.params).read_text())
if set(params) != {'height_m', 'base_width_m', 'base_depth_m'}:
    raise ValueError('Use only the specified lamp dimensions.')
height, width, depth = (float(params[key]) for key in ('height_m', 'base_width_m', 'base_depth_m'))
if not (0.20 <= height <= 0.40 and 0.10 <= width <= 0.22 and 0.08 <= depth <= 0.18):
    raise ValueError('The lamp dimensions exceed the design limits.')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1.0
base(width, depth, material('Deep teal', (0.025, 0.24, 0.23), roughness=0.32))
stem(height, material('Brushed brass', (0.64, 0.39, 0.12), metallic=0.75, roughness=0.3))
shade(height, material('Warm cream', (0.86, 0.78, 0.59), roughness=0.4))
light(height, material('Frosted glass appearance', (0.98, 0.92, 0.72), roughness=0.2))
bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output)))
