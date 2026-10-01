"""Run the handwritten robot benchmark through the experimental controller.

Explicit trusted development only. No untrusted execution or sandbox claim.
Example: python tests/experimental_modeling/run_benchmark.py --store /tmp/robot-benchmark --trusted-reviewed-source
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experimental_modeling.controller import build
from experimental_modeling.contracts import read_json

SOURCE=ROOT/'experimental_modeling'/'examples'/'robot'


def assert_accepted(result):
    assert result['status']=='accepted',json.dumps({key:result.get(key) for key in ('revision','status','error','failures','jobs')},indent=2)
    assert all(result['jobs'][job]['exit_code']==0 for job in ('author','inspect','roundtrip','reopen'))


def observation(store,revision):
    return read_json(store/'accepted'/revision/'inspection'/'observation.json')


def hashes(observed):
    return {name:tuple(part[key] for key in ('geometry_hash','transform_hash','material_hash')) for name,part in observed['parts'].items()}


def run(store, trusted_reviewed_source=False, sandbox_image=None):
    if not trusted_reviewed_source and sandbox_image is None:
        raise RuntimeError('Native benchmark requires explicit --trusted-reviewed-source; it is NOT SANDBOXED')
    store=Path(store).absolute()
    if store.exists() and any(store.iterdir()): raise ValueError('Use a fresh empty benchmark store')
    primary=store/'primary'; clean=store/'clean-rebuild'
    results=[]
    def revision(name,params,parent,target=primary,renders=False):
        result=build(source=SOURCE/"source",params=SOURCE/(params+'.json'),policy_path=SOURCE/(params+'.policy.json'),store=target,revision=name,parent=parent,renders=renders,trusted_reviewed_source=trusted_reviewed_source,sandbox_image=sandbox_image)
        results.append({'revision':name,'store':str(target),'status':result['status'],'failures':result['failures'],'jobs':result['jobs']})
        return result
    for name,params,parent,renders in [('r0','initial',None,True),('r1','revision_1_mast','r0',False),('r2','revision_2_front_legs','r1',False)]:
        assert_accepted(revision(name,params,parent,renders=renders))
    pointer_before=(primary/'last_good.json').read_bytes()
    bad=revision('bad','bad_edit','r2')
    assert bad['status']=='rejected',json.dumps({key:bad.get(key) for key in ('revision','status','error','failures','jobs')},indent=2)
    assert any(f['check']=='unchanged' and f['part']=='body' for f in bad['failures'])
    assert (primary/'last_good.json').read_bytes()==pointer_before,'Rejected candidate changed last-good pointer'
    assert (primary/'attempts'/'bad'/'result.json').is_file(),'Rejected diagnostics were lost'
    assert not (primary/'accepted'/'bad').exists()
    assert_accepted(revision('r3','repair','r2',renders=True))
    before,after=hashes(observation(primary,'r2')),hashes(observation(primary,'r3'))
    assert {part for part in before if before[part]!=after[part]}=={'cargo_tray'}
    # Compare rejected candidate against repair as well: repair changes only body.
    bad_observed=read_json(primary/'attempts'/'bad'/'inspection'/'observation.json')
    bad_hashes=hashes(bad_observed)
    assert {part for part in after if bad_hashes[part]!=after[part]}=={'body'}
    assert_accepted(revision('rebuild','revision_3_tray',None,target=clean))
    assert hashes(observation(clean,'rebuild'))==after,'Clean rebuild geometry differed'
    for name in ('r0','r3'):
        views=primary/'accepted'/name/'inspection'/'views'
        assert len(list(views.glob('*.png')))>=4,'Four orthographic evidence views required'
    summary={'status':'passed','execution_mode':'docker-isolated' if sandbox_image else 'trusted-reviewed-development','security_boundary':'EXPERIMENTAL_DOCKER' if sandbox_image else 'NOT_SANDBOXED','semantic_parts':sorted(after),'checks':['three bounded revisions','20% front-leg length increase','fixed leg anchors','fixed tray mounting anchors','0.1 tray thickness','bad edit rejected','last-good pointer preserved','narrow repair','clean-rebuild geometry parity','GLB roundtrip and saved Blend reopen','initial and final rendered views'],'results':results}
    (store/'benchmark-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store',required=True,type=Path)
    parser.add_argument('--trusted-reviewed-source',action='store_true')
    parser.add_argument('--sandbox-image')
    args=parser.parse_args()
    print(json.dumps(run(args.store,args.trusted_reviewed_source,args.sandbox_image),indent=2))

if __name__=='__main__':main()
