# SPDX-License-Identifier: GPL-3.0-or-later
"""Known offline print-fixture author. It cannot choose the acceptance policy."""
import argparse
import json
import sys
from pathlib import Path
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from solids import build

parser = argparse.ArgumentParser()
parser.add_argument('--params', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
params = json.loads(Path(args.params).read_text())
if set(params) != {'revision'} or params['revision'] not in ('r0', 'r1', 'r2'):
    raise ValueError('Use one reviewed print revision')
build(params['revision'])
bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.output).resolve()), check_existing=False)
