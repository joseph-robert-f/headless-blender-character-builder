# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate watering-can positives and saved-artifact negatives; no binary fixtures.

Native mode requires explicit source review. A requested Docker image never falls
back to native. The relation report alone is not aggregate pipeline verification.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling.controller import run_job
from experimental_modeling.requirements import evaluate

FIXTURE = ROOT / 'experimental_modeling/examples/watering_can'
INSPECTOR = ROOT / 'experimental_modeling/inspect_scene.py'
EXPECTED_MUTANTS = {
    # Boolean neck cutting also retessellates 124 protected triangles; strict
    # surface protection intentionally rejects that additional change.
    'detach_upper': {'handle_upper', 'protected_body_region'},
    'block_spout': {'water_passage'},
    'alter_body': {'protected_body_region', 'protected_body_rays'},
}


def read(path):
    return json.loads(path.read_text())


def generate_observations(store, *, trusted_reviewed_source=False, sandbox_image=None):
    """Actual Blender author/observer runs; no imported model-construction functions."""
    if trusted_reviewed_source == bool(sandbox_image):
        raise ValueError('Select exactly one reviewed native or explicit sandbox mode')
    store = Path(store).absolute()
    if store.exists() and any(store.iterdir()):
        raise ValueError('Use a fresh empty store')
    store.mkdir(parents=True, exist_ok=True)
    backend = None
    if sandbox_image:
        from experimental_modeling.sandbox import DockerSandbox
        backend = DockerSandbox(sandbox_image)
    binary = shutil.which('blender') if backend is None else None
    if backend is None and binary is None:
        raise RuntimeError('Blender unavailable; no implicit fallback')
    base = [binary, '--background', '--factory-startup', '--disable-autoexec',
            '--threads', '2', '--python-exit-code', '1'] if binary else None

    def author(revision):
        output = store/revision/'authored'; output.mkdir(parents=True)
        params = FIXTURE/'params'/f'{revision}.json'; log = store/revision/'author.log'
        if backend:
            backend.run('author', ['--python', '/inputs/source/builder.py', '--',
                                  '--params', '/inputs/params', '--output', '/output/scene.blend'],
                        {'source': FIXTURE/'source', 'params': params}, output, log)
        else:
            run_job(base + ['--python', str(FIXTURE/'source/builder.py'), '--', '--params', str(params),
                            '--output', str(output/'scene.blend')], output, log)
        return output/'scene.blend'

    def inspect(name, scene):
        output = store/name/'inspection'; output.mkdir(parents=True)
        log = store/name/'inspect.log'
        if backend:
            backend.run('inspect', ['--python', '/inputs/inspector', '--', '--input', '/inputs/input',
                                   '--output', '/output', '--expected-ids', 'vessel,spout', '--skip-renders'],
                        {'inspector': INSPECTOR, 'input': scene}, output, log)
        else:
            run_job(base + ['--python', str(INSPECTOR), '--', '--input', str(scene), '--output', str(output),
                            '--expected-ids', 'vessel,spout', '--skip-renders'], output, log)
        return read(output/'observation.json')

    observations = {revision: inspect(revision, author(revision)) for revision in ('r0', 'r1', 'r2')}
    artifacts = store/'mutants'; artifacts.mkdir()
    baseline = store/'r2/inspection/scene.blend'; mutation = FIXTURE/'mutate_saved.py'
    if backend:
        backend.run('inspect', ['--python', '/inputs/inspector', '--', '--baseline', '/inputs/input',
                               '--out', '/output'], {'inspector': mutation, 'input': baseline},
                    artifacts, store/'mutate.log')
    else:
        run_job(base + ['--python', str(mutation), '--', '--baseline', str(baseline), '--out', str(artifacts)],
                artifacts, store/'mutate.log')
    for name in EXPECTED_MUTANTS:
        observations[name] = inspect(name, artifacts/f'{name}.blend')
    return observations


def validate_reports(observations, reports):
    """Good cases must pass; the exact intended predicates must reject each mutant."""
    for name in ('r0', 'r1', 'r2'):
        report = reports[name]
        assert report['requirements_satisfied'], (name, report)
        assert all(row['status'] == 'pass' for row in report['requirements'] if row['applicable']), name
        assert 'machine_verified' not in report, 'Relation-only result must not claim pipeline verification'
    for name, expected in EXPECTED_MUTANTS.items():
        report = reports[name]
        assert not report['requirements_satisfied'], name
        assert not any(row['status'] == 'unknown' for row in report['requirements']), (name, report)
        actual = {row['id'] for row in report['requirements'] if row['status'] == 'fail'}
        assert actual == expected, (name, actual, expected)
    initial = {row['id']: row for row in reports['r0']['requirements']}
    for name in ('protected_body_region', 'protected_body_rays'):
        assert initial[name]['status'] == 'unknown' and not initial[name]['applicable']
    baseline = observations['r2']['parts']
    assert observations['block_spout']['parts']['vessel']['geometry_hash'] == baseline['vessel']['geometry_hash']
    assert observations['block_spout']['parts']['spout']['world_vertices'][:800] == baseline['spout']['world_vertices']
    for name in ('detach_upper', 'alter_body'):
        assert observations[name]['parts']['spout']['geometry_hash'] == baseline['spout']['geometry_hash']
    rows = {row['id']: row for row in reports['detach_upper']['requirements']}
    assert rows['handle_lower']['status'] == 'pass', 'Mutation must retain lower attachment'


def run(store, *, trusted_reviewed_source=False, sandbox_image=None):
    store = Path(store).absolute()
    started = time.monotonic()
    observations = generate_observations(store, trusted_reviewed_source=trusted_reviewed_source, sandbox_image=sandbox_image)
    spec = read(FIXTURE/'requirements.json'); reports = {}; timing = {}
    for name, observation in observations.items():
        previous = None if name == 'r0' else observations['r0' if name == 'r1' else 'r1']
        before = time.monotonic(); reports[name] = evaluate(spec, observation, previous)
        timing[name] = round(time.monotonic()-before, 3)
        (store/name/'requirements-report.json').write_text(json.dumps(reports[name], indent=2)+'\n')
    # Retain evidence before assertions so a failed/unknown predicate remains diagnosable.
    summary = {'regression_passed': False, 'execution_mode': 'experimental-docker' if sandbox_image else 'trusted-reviewed-development',
               'security_boundary': 'EXPERIMENTAL_DOCKER' if sandbox_image else 'NOT_SANDBOXED',
               'elapsed_seconds': round(time.monotonic()-started, 3), 'evaluation_seconds': timing,
               'cases': {name: {row['id']: row['status'] for row in report['requirements']} for name, report in reports.items()},
               'scope': 'three positive source states and three saved-artifact mutations; relation predicates only'}
    (store/'relations-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    validate_reports(observations, reports)
    summary['regression_passed'] = True
    (store/'relations-summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--trusted-reviewed-source', action='store_true')
    mode.add_argument('--sandbox-image')
    args = parser.parse_args()
    print(json.dumps(run(args.store, trusted_reviewed_source=args.trusted_reviewed_source,
                         sandbox_image=args.sandbox_image), indent=2))
