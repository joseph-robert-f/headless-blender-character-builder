"""Handwritten robot fixture checks, including explicitly opted-in native Blender.

RUN_TRUSTED_BLENDER_TESTS=1 python -m unittest discover -s tests/experimental_modeling -p test_robot_blender.py
Native execution is trusted development mode, never a sandbox security test.
"""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'experimental_modeling'/'examples'/'robot'
sys.path.insert(0,str(SOURCE/"source"))
from parts import meshes, LEG_ENDPOINTS


def length(vertices):
    centers=[tuple(sum(vertices[i][axis] for i in group)/len(group) for axis in range(3)) for group in (range(12),range(12,24),range(24,36))]
    return sum(math.dist(a,b) for a,b in zip(centers,centers[1:]))


def params(name): return json.loads((SOURCE/(name+'.json')).read_text())


class RobotGeometryTests(unittest.TestCase):
    def test_nine_parts_and_bounded_revision_changes(self):
        names=['initial','revision_1_mast','revision_2_front_legs','revision_3_tray','bad_edit','repair']
        scenes=[meshes(params(name)) for name in names]
        self.assertEqual(len(scenes[0]),9)
        expected=[{'mast'},{'leg_front_left','leg_front_right'},{'cargo_tray'},{'body'},{'body'}]
        for a,b,changed in zip(scenes,scenes[1:],expected):
            self.assertEqual({key for key in a if a[key]!=b[key]},changed)
        self.assertEqual(scenes[3],scenes[5])

    def test_front_length_and_endpoints_are_actual_geometry(self):
        before=meshes(params('revision_1_mast')); after=meshes(params('revision_2_front_legs'))
        for name,(start,end) in LEG_ENDPOINTS.items():
            vertices,faces=after[name]
            self.assertEqual(vertices[36],start); self.assertEqual(vertices[37],end)
            self.assertTrue(any(36 in face for face in faces)); self.assertTrue(any(37 in face for face in faces))
            ratio=1.2 if 'front' in name else 1.
            self.assertAlmostEqual(length(vertices)/length(before[name][0]),ratio,places=10)

    def test_tray_widens_with_fixed_mounts_and_thickness(self):
        a=meshes(params('revision_2_front_legs'))['cargo_tray'][0]
        b=meshes(params('revision_3_tray'))['cargo_tray'][0]
        self.assertEqual(a[16:],b[16:])
        self.assertAlmostEqual(max(p[0] for p in b)-min(p[0] for p in b),1.9)
        for vertices in (a,b):
            self.assertAlmostEqual(vertices[8][0]-vertices[4][0],.1)
            self.assertAlmostEqual(vertices[8][1]-vertices[4][1],.1)
            self.assertAlmostEqual(vertices[12][2]-vertices[0][2],.1)


@unittest.skipUnless(os.environ.get('RUN_TRUSTED_BLENDER_TESTS')=='1' and shutil.which('blender'), 'explicit native trusted Blender opt-in required')
class RobotNativeBlenderTests(unittest.TestCase):
    def test_saved_blend_geometry_matches_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            inspect=tmp/'read.py'
            inspect.write_text('import bpy,json,sys\nfrom pathlib import Path\nresult={}\nfor o in bpy.context.scene.objects:\n if o.type=="MESH":\n  result[o["semantic_id"]]=[list(o.matrix_world @ v.co) for v in o.data.vertices]\nPath(sys.argv[-1]).write_text(json.dumps(result))\n')
            actual=[]
            for name in ['initial','revision_1_mast','revision_2_front_legs','revision_3_tray','bad_edit','repair']:
                blend=tmp/(name+'.blend'); report=tmp/(name+'.json')
                subprocess.run(['blender','--background','--factory-startup','--python-exit-code','1','--python',str(SOURCE/'source'/'builder.py'),'--','--params',str(SOURCE/(name+'.json')),'--output',str(blend)],check=True,capture_output=True,timeout=60)
                self.assertTrue(blend.is_file())
                subprocess.run(['blender','--background',str(blend),'--python-exit-code','1','--python',str(inspect),'--',str(report)],check=True,capture_output=True,timeout=60)
                data=json.loads(report.read_text()); actual.append(data)
                expected=meshes(params(name))
                self.assertEqual(set(data),set(expected))
                for part,vertices in data.items():
                    self.assertEqual(len(vertices),len(expected[part][0]))
                    for got,want in zip(vertices,expected[part][0]): self.assertLess(math.dist(got,want),1e-6)
            for leg in ('leg_front_left','leg_front_right'):
                self.assertAlmostEqual(length(actual[2][leg])/length(actual[1][leg]),1.2,places=6)
                for index in (36,37): self.assertEqual(actual[2][leg][index],actual[1][leg][index])
            self.assertEqual(actual[3],actual[5])
            self.assertNotEqual(actual[3]['body'],actual[4]['body'])


if __name__=='__main__': unittest.main()
