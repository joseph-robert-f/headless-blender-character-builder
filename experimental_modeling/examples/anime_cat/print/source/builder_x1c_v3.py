# SPDX-License-Identifier: GPL-3.0-or-later
"""Known offline X1C fixture author, using one frozen factor for every revision."""
import argparse
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parent))
from x1c_bambu_solids import build_x1c_bambu

parser = argparse.ArgumentParser()
parser.add_argument('--params',required=True)
parser.add_argument('--output',required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
params = json.loads(Path(args.params).read_text())
if set(params)!={'revision'} or params['revision'] not in ('r0','r1','r2'):
    raise ValueError('Use one reviewed print revision')
build_x1c_bambu(params['revision'])
bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()),check_existing=False)
