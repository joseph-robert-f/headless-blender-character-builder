# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild the independently authored desk-creature probe; outputs stay external."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling.controller import build
from experimental_modeling.contracts import Policy, read_json
from experimental_modeling.acceptance import check
from verify_desk_creature import fingerprints, verify

FIXTURE = ROOT / 'experimental_modeling/examples/desk_creature'


def run(store, trusted_reviewed_source=False, sandbox_image=None):
    if not trusted_reviewed_source and sandbox_image is None:
        raise RuntimeError('Review source and explicitly select native development or an available sandbox; no fallback')
    store = Path(store).absolute()
    if store.exists() and any(store.iterdir()):
        raise ValueError('Use a fresh empty store')
    observations, results = [], []
    intents = ['Create grounded asymmetric tripod desk creature and separate crescent vessel',
               'Lift tail stations by 0.35*sin(pi*t), preserve endpoints/radii and all other parts',
               'Raise only vessel rim from 0.35 to 0.50; preserve footprint, .08 floor/walls and creature']
    for i in range(3):
        name = f'r{i}'
        result = build(source=FIXTURE/'source', params=FIXTURE/'params'/f'{name}.json',
                       policy_path=FIXTURE/'policies'/f'{name}.policy.json', store=store/'primary',
                       revision=name, parent=f'r{i-1}' if i else None, renders=True, intent=intents[i],
                       trusted_reviewed_source=trusted_reviewed_source, sandbox_image=sandbox_image)
        assert result['status'] == 'accepted', result
        results.append({'revision': name, 'status': result['status'], 'jobs': result['jobs']})
        directory = store/'primary/accepted'/name
        observations.append(read_json(directory/'inspection/observation.json'))
        assert len(list((directory/'inspection/views').glob('*.png'))) == 4
        for path in ['roundtrip/roundtrip.json', 'reopened/reopen.json']:
            assert read_json(directory/path)['passed']
    summary = verify(observations)
    result = build(source=FIXTURE/'source', params=FIXTURE/'params/r2.json',
                   policy_path=FIXTURE/'policies/r2.policy.json', store=store/'clean',
                   revision='rebuild', renders=False, trusted_reviewed_source=trusted_reviewed_source,
                   sandbox_image=sandbox_image)
    assert result['status'] == 'accepted', result
    assert fingerprints(read_json(store/'clean/accepted/rebuild/inspection/observation.json')) == fingerprints(observations[-1])
    policy = copy.deepcopy(read_json(FIXTURE/'policies/r2.policy.json'))
    next(c for c in policy['constraints'] if c['kind'] == 'centroid')['data']['point'][0] += .05
    failures = check(Policy.parse(policy), observations[-1], observations[-2])
    assert len(failures) == 1 and failures[0]['check'] == 'centroid', failures
    summary.update({'execution_mode': result['execution_mode'], 'security_boundary': result['security_boundary'],
                    'clean_rebuild_all_24_hashes_equal': True, 'centroid_wrong_target_negative_control': True,
                    'results': results, 'scope': 'one novel construction, two local revisions; not generality or print proof'})
    (store/'desk-creature-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--trusted-reviewed-source', action='store_true')
    parser.add_argument('--sandbox-image')
    args = parser.parse_args()
    print(json.dumps(run(args.store, args.trusted_reviewed_source, args.sandbox_image), indent=2))
