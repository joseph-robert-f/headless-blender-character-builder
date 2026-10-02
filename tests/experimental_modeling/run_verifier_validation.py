# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate schema-2 translated checks with isolated real-Blender artifacts.

No native mode and no automatic fallback. Use a new output/store and an existing
immutable Docker image. This handwritten verifier fixture is not model-author
success evidence. An implementation or mocked unit test is not an executed gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling.acceptance import check
from experimental_modeling.contracts import Policy
from experimental_modeling.controller import build, verify_accepted
from experimental_modeling.sandbox import DockerSandbox

FIXTURE = Path(__file__).parent / 'fixtures/verifier_validation'
sys.path.insert(0, str(FIXTURE))
from oracle import assert_tetra_case, indexed_translation, inspect_tetra

LAMP = ROOT / 'experimental_modeling/examples/external_lamp'
PROBE = FIXTURE / 'probe_artifact.py'
SOURCE_HASHES = {
    'builder.py': '8d31b470a31f6a18e90fbcdefe3ecb49c08f1cfc111fffc5d02f1f87a1932cc6',
    'geometry.py': 'be64750eba590d2235fc90d26c811cc6232606999c4a53de3e0c27d99b43f1b6',
}
ORIGINAL_GEOMETRY_HASH = '4104a88f029ea1ced220f0aa1ba3633957e7ed7e9d6210e7bfd1a8ede857cfcb'
POSITION_TOLERANCE_M = 1e-6
# Reviewed provisional threshold, NOT a new production default. Only an actual
# successful Blender run supplies calibration evidence for its recorded runtime.
NORMAL_TOLERANCE_RADIANS = .001
TETRA_STATES = (
    ('tetra-r0', 0., 'none', 'initial', None, 'accepted'),
    ('tetra-r1', .03, 'none', 'permuted', 'tetra-r0', 'accepted'),
    ('tetra-material-bad', .06, 'material', 'permuted', 'tetra-r1', 'rejected'),
    ('tetra-normal-bad', .06, 'normal', 'permuted', 'tetra-r1', 'rejected'),
    ('tetra-repair', .06, 'none', 'repair', 'tetra-r1', 'accepted'),
)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hashes(folder):
    return {str(path.relative_to(folder)): sha(path) for path in sorted(folder.rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts}


def validate_inputs():
    """Static input validation; does not import/execute author or Blender code."""
    for name, expected in SOURCE_HASHES.items():
        assert sha(LAMP / 'proposal/source' / name) == expected, 'Recorded lamp source changed'
    text = (LAMP / 'proposal/source/geometry.py').read_text()
    marker = "    obj = finish(obj, 'light', surface)\n    # Preserve oriented connectivity with a deterministic face-list order.\n"
    assert text.count(marker) == 1
    original = text.split(marker)[0] + "    return finish(obj, 'light', surface)\n"
    assert hashlib.sha256(original.encode()).hexdigest() == ORIGINAL_GEOMETRY_HASH
    return original


def prepare_lamp_source(destination):
    """Recreate historical source ONLY in fresh output, never rewrite examples."""
    original = validate_inputs()
    shutil.copytree(LAMP / 'proposal/source', destination, ignore=shutil.ignore_patterns('__pycache__'))
    (destination / 'geometry.py').write_text(original)
    assert sha(destination / 'geometry.py') == ORIGINAL_GEOMETRY_HASH
    assert sha(destination / 'builder.py') == SOURCE_HASHES['builder.py']
    return file_hashes(destination)


def tetra_policy(translated):
    constraints = [{'kind': 'manifold', 'part': 'tetra', 'data': {}}]
    if translated:
        constraints.append({'kind': 'translated', 'part': 'tetra', 'data': {
            'delta': [0., 0., .03], 'tolerance': POSITION_TOLERANCE_M,
            'normal_tolerance_radians': NORMAL_TOLERANCE_RADIANS}})
    return {'schema_version': 2, 'profile': 'scene', 'parts': ['tetra'],
            'changed_parts': ['tetra'], 'constraints': constraints}


def lamp_policy(translated):
    original = LAMP / ('revisions/height/policy.json' if translated else 'policy-initial.json')
    policy = read(original)
    policy['schema_version'] = 2
    for constraint in policy['constraints']:
        if constraint['kind'] == 'translated':
            constraint['data']['normal_tolerance_radians'] = NORMAL_TOLERANCE_RADIANS
    return policy


def result_directory(store, result):
    return store / ('accepted' if result['status'] == 'accepted' else 'attempts') / result['revision']


def run(store, *, sandbox_image, docker_executable=None, docker_socket=Path('/var/run/docker.sock')):
    if not sandbox_image:
        raise ValueError('An explicit immutable sandbox image is required; native execution is unavailable')
    validate_inputs()
    store = Path(store).absolute()
    if store.exists() and any(store.iterdir()):
        raise ValueError('Use a fresh empty verifier-validation store; no migration or old baseline reuse')
    store.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    original_hashes = file_hashes(LAMP)
    summary = {'status': 'not_completed', 'scope': 'handwritten schema-2 verifier validation, not author capability',
               'execution_mode': 'docker-isolated', 'security_boundary': 'EXPERIMENTAL_DOCKER',
               'native_fallback': False, 'policy_schema_version': 2, 'observation_schema_version': 2,
               'normal_tolerance': {'configured_radians': NORMAL_TOLERANCE_RADIANS,
                                    'calibration_status': 'unmeasured_provisional',
                                    'max_positive_deviation_radians': None},
               'validation_files': {'runner': sha(Path(__file__)),
                                    'probe': sha(PROBE), 'oracle': sha(FIXTURE / 'oracle.py'),
                                    'author': sha(FIXTURE / 'source/builder.py')},
               'results': [], 'independent_artifact_probes': {}, 'positive_comparisons': {}}
    summary_path = store / 'verifier-validation-summary.json'
    def save():
        summary['elapsed_seconds'] = round(time.monotonic() - started, 3)
        write(summary_path, summary)
    save()
    try:
        backend = DockerSandbox(sandbox_image, socket=docker_socket, docker_executable=docker_executable)
        summary['runtime'] = backend.verify_runtime()  # Mandatory fail-closed, no native fallback.
        save()
        inputs = store / 'inputs'; inputs.mkdir()
        probes = store / 'independent-probes'; probes.mkdir()
        tetra_store, lamp_store = store / 'tetra', store / 'lamp-original-order'
        observations, raw_probes = {}, {}
        normal_measurements = []

        def probe(revision, label, artifact, format):
            assert artifact.is_file(), ('Missing actual artifact', artifact)
            output = probes / revision / label
            output.mkdir(parents=True)
            job = backend.run('inspect', ['--python', '/inputs/inspector', '--',
                '--input', '/inputs/input', '--format', format, '--output', '/output/probe.json'],
                {'inspector': PROBE, 'input': artifact}, output,
                probes / revision / (label + '.log'))
            assert job['exit_code'] == 0
            result = read(output / 'probe.json')
            assert result['autoexec_enabled'] is False
            summary['independent_artifact_probes'].setdefault(revision, {})[label] = {
                'artifact': str(artifact.relative_to(store)), 'artifact_sha256': sha(artifact),
                'probe': str((output / 'probe.json').relative_to(store)), 'job': job}
            raw_probes.setdefault(revision, {})[label] = result
            save()
            return result

        def execute(name, target, source, params, policy, parent, status, *, requirements=None, tetra_case=None):
            param_path, policy_path = inputs / (name + '-params.json'), inputs / (name + '-policy.json')
            write(param_path, params); write(policy_path, policy)
            Policy.parse(policy)
            result = build(source=source, params=param_path, policy_path=policy_path,
                store=target, revision=name, parent=parent, renders=False,
                sandbox_image=sandbox_image, docker_executable=docker_executable,
                docker_socket=docker_socket, requirements_path=requirements,
                intent='Test-only independent translated verifier validation')
            row = {key: result.get(key) for key in ('revision', 'parent', 'status', 'error', 'failures', 'jobs')}
            row['expected_status'] = status
            summary['results'].append(row); save()
            directory = result_directory(target, result)
            # Probe actual artifacts before trusting aggregate status. Preserve
            # raw evidence even when the controller and oracle disagree.
            for label, path, format in (('authored-blend', 'authored/scene.blend', 'blend'),
                                         ('saved-blend', 'inspection/scene.blend', 'blend'),
                                         ('exported-glb', 'inspection/model.glb', 'glb')):
                if (directory / path).is_file():
                    probe(name, label, directory / path, format)
            if tetra_case is not None:
                height, defect = tetra_case
                oracle_errors = []
                for label, measured in raw_probes.get(name, {}).items():
                    evidence = summary['independent_artifact_probes'][name][label]
                    try:
                        report = inspect_tetra(measured, height, tolerance=POSITION_TOLERANCE_M,
                                               normal_tolerance=NORMAL_TOLERANCE_RADIANS)
                        evidence['oracle'] = report
                        assert_tetra_case(report, defect, normal_tolerance=NORMAL_TOLERANCE_RADIANS)
                        if defect == 'none':
                            normal_measurements.append(report['max_normal_angle_deviation_radians'])
                    except AssertionError as exc:
                        evidence['oracle_error'] = str(exc)[:3000]
                        oracle_errors.append(label + ': ' + str(exc)[:1000])
                    save()
                assert not oracle_errors, '; '.join(oracle_errors)
            observations[name] = read(directory / 'inspection/observation.json')
            assert observations[name]['schema_version'] == 2
            assert result['status'] == status, json.dumps(row, indent=2)
            assert not result.get('error'), row
            assert all(result['jobs'][stage]['exit_code'] == 0
                       for stage in ('author', 'inspect', 'roundtrip', 'reopen')), row
            assert set(raw_probes[name]) == {'authored-blend', 'saved-blend', 'exported-glb'}
            verification = read(directory / 'verification.json')
            assert verification['machine_verified'] == (status == 'accepted')
            if status == 'accepted':
                pointer = read(target / 'last_good.json')
                assert pointer['revision'] == name
                verify_accepted(directory, pointer['result_hash'])
            else:
                assert not (target / 'accepted' / name).exists()
                assert len(result['failures']) == 1, row
                failure = result['failures'][0]
                assert failure.get('check') == 'translated' and failure.get('part') == 'tetra', row
                assert tetra_case is not None
                defective_component = {'material': 'face_material_assignments_equal',
                                       'normal': 'corner_normals_equal'}[tetra_case[1]]
                components = ('vertex_count_equal', 'indexed_translation_equal', 'oriented_polygons_equal',
                              'face_material_assignments_equal', 'ordered_material_palette_equal',
                              'indexed_edges_equal', 'corner_normals_equal')
                assert {key for key in components if failure['measured'][key] is not True} == {defective_component}, row
            row['verified_artifact_count'] = 3
            save()
            return result

        preserved_pointer = None
        for name, height, defect, serialization, parent, status in TETRA_STATES:
            if name == 'tetra-material-bad':
                preserved_pointer = (tetra_store / 'last_good.json').read_bytes()
            execute(name, tetra_store, FIXTURE / 'source',
                    {'height_m': height, 'defect': defect, 'serialization': serialization},
                    tetra_policy(parent is not None), parent, status, tetra_case=(height, defect))
            if status == 'rejected':
                assert (tetra_store / 'last_good.json').read_bytes() == preserved_pointer, 'Rejected candidate moved last_good'
            if status == 'accepted' and parent:
                comparison = indexed_translation(raw_probes[parent]['saved-blend']['parts']['tetra'],
                    raw_probes[name]['saved-blend']['parts']['tetra'], [0., 0., .03],
                    tolerance=POSITION_TOLERANCE_M, normal_tolerance=NORMAL_TOLERANCE_RADIANS)
                assert comparison['raw_face_order_changed'], 'Positive must exercise face/corner serialization invariance'
                summary['positive_comparisons'][name] = comparison
                normal_measurements.append(comparison['max_normal_angle_deviation_radians'])
            save()
        summary['negative_controls_preserved_last_good'] = True

        lamp_source = inputs / 'original-lamp-source'
        summary['original_lamp_source_hashes'] = prepare_lamp_source(lamp_source)
        summary['original_lamp_historical_geometry_hash'] = ORIGINAL_GEOMETRY_HASH
        for name, height, parent in (('lamp-r0', .26, None), ('lamp-r1', .29, 'lamp-r0')):
            execute(name, lamp_store, lamp_source,
                    {'height_m': height, 'base_width_m': .16, 'base_depth_m': .12},
                    lamp_policy(parent is not None), parent, 'accepted', requirements=LAMP / 'requirements.json')
        lamp_comparisons = {}
        for label in ('authored-blend', 'saved-blend'):
            for part in ('shade', 'light'):
                comparison = indexed_translation(raw_probes['lamp-r0'][label]['parts'][part],
                    raw_probes['lamp-r1'][label]['parts'][part], [0., 0., .03],
                    tolerance=POSITION_TOLERANCE_M, normal_tolerance=NORMAL_TOLERANCE_RADIANS)
                lamp_comparisons[label + '/' + part] = comparison
                normal_measurements.append(comparison['max_normal_angle_deviation_radians'])
        assert lamp_comparisons['saved-blend/light']['raw_face_order_changed'], (
            'Historical lamp raw-order difference was not reproduced; do not claim regression coverage')
        # Characterize the frozen v1 semantics on the same actual observations;
        # only the v2 controller can promote this fresh v2 baseline/refinement.
        legacy_failures = check(Policy.parse(read(LAMP / 'revisions/height/policy.json')),
                                observations['lamp-r1'], observations['lamp-r0'])
        assert any(row.get('check') == 'translated' and row.get('part') == 'light' for row in legacy_failures)
        summary['original_lamp_regression'] = {'independent_comparisons': lamp_comparisons,
                                               'frozen_v1_failures': legacy_failures,
                                               'v2_status': 'accepted'}
        summary['normal_tolerance'].update({
            'calibration_status': 'measured_fixture_positives_for_recorded_runtime',
            'max_positive_deviation_radians': max(normal_measurements),
            'measurement_count': len(normal_measurements),
            'scope': 'tetra artifact normals and unchanged translated lamp faces; not a universal tolerance'})
        assert max(normal_measurements) <= NORMAL_TOLERANCE_RADIANS
        assert file_hashes(LAMP) == original_hashes, 'Recorded lamp files were modified'
        summary['recorded_lamp_unchanged'] = True
        summary['status'] = 'passed'
        save()
        return summary
    except Exception as exc:
        summary['status'] = 'failed'
        summary['error'] = type(exc).__name__ + ': ' + str(exc)[:4000]
        summary['recorded_lamp_unchanged'] = file_hashes(LAMP) == original_hashes
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', '--output', dest='store', type=Path, required=True)
    parser.add_argument('--sandbox-image', required=True)
    parser.add_argument('--docker', type=Path)
    parser.add_argument('--docker-socket', type=Path, default=Path('/var/run/docker.sock'))
    args = parser.parse_args()
    print(json.dumps(run(args.store, sandbox_image=args.sandbox_image,
                         docker_executable=args.docker, docker_socket=args.docker_socket), indent=2))


if __name__ == '__main__':
    main()
