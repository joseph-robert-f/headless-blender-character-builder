"""Actual controller integration with locked reusable rules, ready for local review."""
import argparse
import json
from pathlib import Path
import sys
import shutil

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experimental_modeling.controller import build
from experimental_modeling.review_server import ReviewProject

FIXTURE=ROOT/'experimental_modeling/examples/watering_can'


def run(store, trusted_reviewed_source=False, sandbox_image=None):
    store=Path(store).absolute()
    if store.exists():raise ValueError('Use a new integration output directory')
    inputs=store/'inputs';inputs.mkdir(parents=True)
    results=[]
    for i in range(3):
        policy={'schema_version':1,'parts':['vessel','spout'],'changed_parts':[] if i==0 else ['spout'] if i==1 else ['vessel'],
                'constraints':[{'kind':'manifold','part':part,'data':{}} for part in ('vessel','spout')],'profile':'scene'}
        policy_path=inputs/f'r{i}.policy.json';policy_path.write_text(json.dumps(policy))
        result=build(source=FIXTURE/'source',params=FIXTURE/'params'/f'r{i}.json',policy_path=policy_path,
                     requirements_path=FIXTURE/'requirements.json' if i==0 else None,store=store/'project',revision=f'r{i}',parent=f'r{i-1}' if i else None,
                     trusted_reviewed_source=trusted_reviewed_source,sandbox_image=sandbox_image,renders=i in (0,2),intent=['Create watering can','Lift spout while preserving vessel','Thicken handle while protecting vessel interior'][i])
        if result['status']!='accepted':raise AssertionError(json.dumps(result,indent=2))
        response=ReviewProject(store/'project').revision(f'r{i}')
        assert response['report']['machine_verified'] and not response['state']['human_accepted']
        relation_rows=[row for row in response['report']['requirements'] if row['id'] in {'handle_upper','handle_lower','water_passage','protected_body_region','protected_body_rays'}]
        assert len(relation_rows)==5
        assert all(row['status']=='pass' for row in relation_rows if row['applicable'])
        results.append({'revision':f'r{i}','requirements':relation_rows,'machine_verified':True,'human_accepted':False})
    # An actual source edit violates a protected body while preserving the
    # author's successful observation/export stages and old whole-part scope.
    bad_source=store/'bad-source'
    shutil.copytree(FIXTURE/'source',bad_source,ignore=shutil.ignore_patterns('__pycache__'))
    with (bad_source/'builder.py').open('a') as stream:
        stream.write("\n# Deliberate test-only protected-body regression.\nfor vertex in vessel.data.vertices:\n    if vertex.co.y > .65 and vertex.co.x > -.2: vertex.co.y += .08\nvessel.data.update()\nbpy.ops.wm.save_as_mainfile(filepath=str(Path(a.output).resolve()))\n")
    pointer=(store/'project/last_good.json').read_bytes()
    bad=build(source=bad_source,params=FIXTURE/'params/r2.json',policy_path=inputs/'r2.policy.json',store=store/'project',
              revision='bad-body',parent='r2',trusted_reviewed_source=trusted_reviewed_source,sandbox_image=sandbox_image,renders=False,
              intent='Deliberate test regression: change protected body despite successful observation')
    assert bad['status']=='rejected',bad
    assert bad['jobs']['inspect']['exit_code']==0 and bad['jobs']['roundtrip']['exit_code']==0
    failed={row['requirement_id'] for row in bad['failures'] if row.get('check')=='requirement'}
    assert {'protected_body_region','protected_body_rays'} <= failed
    assert (store/'project/last_good.json').read_bytes()==pointer
    rejected=ReviewProject(store/'project').revision('bad-body')
    assert not rejected['report']['machine_verified'] and not rejected['state']['human_accepted']
    summary={'status':'passed','locked_rules_survive_omitted_cli_argument':True,
             'successful_observation_does_not_override_failed_preservation':True,'rejected_requirements':sorted(failed),'results':results}
    (store/'review-project-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--store',type=Path,required=True);parser.add_argument('--trusted-reviewed-source',action='store_true');parser.add_argument('--sandbox-image')
    args=parser.parse_args();print(json.dumps(run(args.store,args.trusted_reviewed_source,args.sandbox_image),indent=2))
