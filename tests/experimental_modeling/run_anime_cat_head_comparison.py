# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline, versioned head comparison; geometry evidence never promotes a print."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling.controller import digest, safe_path, snapshot, write_json
from experimental_modeling.sandbox import DockerSandbox

FIXTURE = ROOT/'experimental_modeling/examples/anime_cat'
COMPARISON_ID = 'anime-cat-head-comparison-v1'
OBSERVER_SHA = '9fe6760b6f5fe5596cf1377abdec78adadaabc7b6b3834680d23cc7a4b5dc869'


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def verify_mesh(report):
    mesh = report['mesh']
    revision = report['revision']
    if revision not in ('r0', 'r1', 'r2'):
        raise ValueError('Unknown fixed comparison revision')
    for key in ('non_manifold_edges', 'boundary_edges', 'non_manifold_vertices',
                'loose_vertices', 'inconsistent_winding_edges', 'degenerate_triangles', 'self_intersections'):
        if type(mesh[key]) is not int or mesh[key] != 0:
            raise ValueError('Comparison failed geometry: '+key)
    if (type(mesh['measured_triangles']) is not int
            or not 0 < mesh['measured_triangles'] <= 500000
            or type(mesh['evaluated_triangles']) is not int
            or mesh['evaluated_triangles'] != mesh['measured_triangles']
            or type(mesh['face_connected_shells']) is not int or mesh['face_connected_shells'] != 1
            or mesh['intersection_measurement']['complete'] is not True
            or not finite_number(mesh['signed_volume_mm3']) or mesh['signed_volume_mm3'] <= 0):
        raise ValueError('Complete bounded positive single-shell geometry is required')
    dimensions = mesh['dimensions_mm']
    low, high = mesh['bounds_mm']['min'], mesh['bounds_mm']['max']
    target = 108.54632568359375 if revision == 'r1' else 100.0
    if (len(dimensions) != 3 or any(not finite_number(v) or not 0 < v <= 120 for v in dimensions)
            or len(low) != 3 or len(high) != 3 or any(not finite_number(v) for v in low+high)
            or any(high[i]-low[i] != dimensions[i] for i in range(3))
            or abs(dimensions[2]-target) > 1.5 or abs(low[2]) > .001):
        raise ValueError('Comparison changed the fixed physical scale or ground')
    feature, ear = mesh['feature_probes'], report['ear_partial_probes']
    expected = {f'whisker-{sign}-{index}': 8 for sign in (-1, 1) for index in range(2)}
    if revision == 'r1':expected['hat-brim'] = 1
    if revision == 'r2':expected['glasses-bridge'] = 8
    samples, chords = feature['samples'], ear['chords_mm']
    if (feature['coverage'] != 'partial' or ear['coverage'] != 'partial'
            or type(feature['sample_count']) is not int or feature['sample_count'] != sum(expected.values())
            or len(samples) != len(expected) or {row['feature']: row['chords'] for row in samples} != expected
            or any(type(row['chords']) is not int or not finite_number(row['minimum_chord_mm'])
                   or row['minimum_chord_mm'] < 1.35 for row in samples)
            or not finite_number(feature['minimum_mm'])
            or feature['minimum_mm'] != min(row['minimum_chord_mm'] for row in samples)
            or type(ear['sample_count']) is not int or ear['sample_count'] != 18 or len(chords) != 18
            or any(not finite_number(v) or v < 1.35 for v in chords)
            or not finite_number(ear['minimum_chord_mm']) or ear['minimum_chord_mm'] != min(chords)):
        raise ValueError('Partial designed-feature probes failed the existing minimum')
    if (report['comparison_id'] != COMPARISON_ID or report['unit'] != 'millimeter'
            or report['promotion_eligible'] is not False or report['physical_validation'] != 'pending'
            or report['feature_coverage'] != 'unknown' or report['observer_sha256'] != OBSERVER_SHA):
        raise ValueError('Comparison must retain its identity, observer and pending acceptance')
    return mesh


def verify_pair(source, stl):
    measured, roundtrip = verify_mesh(source), verify_mesh(stl)
    if (source['revision'] != stl['revision'] or source['body_exterior_bit_exact'] is not True
            or (source['revision'] != 'r0' and source['accessory_exterior_bit_exact'] is not True)):
        raise ValueError('A final head or accessory changed its protected exterior')
    if any(measured[key] != roundtrip[key] for key in
           ('exact_surface_sha256', 'bounds_mm', 'measured_triangles')):
        raise ValueError('The complete STL differs from its saved source surface')
    return measured


def run(store, candidates, image, docker=None):
    store, candidates = safe_path(Path(store).absolute()), safe_path(Path(candidates).absolute())
    if store.exists() and any(store.iterdir()):
        raise ValueError('Use a new empty comparison store')
    store.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(store).free < 2*1024**3:
        raise ValueError('At least 2 GiB of free evidence space is required')
    source = store/'source';source.mkdir()
    (source/'print').mkdir()
    source_files = {}
    for relative in ('print/source', 'head_comparison_v1'):
        for name, sha in snapshot(FIXTURE/relative, source/relative).items():
            source_files[relative+'/'+name] = sha
    observer = source/'print/inspect_solid.py'
    shutil.copyfile(FIXTURE/'print/inspect_solid.py', observer)
    if digest(observer) != OBSERVER_SHA:
        raise ValueError('The frozen complete geometry observer changed')
    shutil.copyfile(candidates/'r0/authored/model.blend', source/'baseline.blend')
    sandbox = DockerSandbox(image, docker_executable=Path(docker) if docker else None)
    runtime = sandbox.verify_runtime()
    summaries, jobs, base_hashes = {}, {}, set()
    for revision in ('r0', 'r1', 'r2'):
        root = store/revision;root.mkdir()
        params = root/'params.json';write_json(params, {'revision': revision})
        authored = root/'authored';authored.mkdir()
        job = sandbox.run('author', ['--python', '/inputs/source/head_comparison_v1/builder.py', '--',
            '--params', '/inputs/params', '--output', '/output/model.blend', '--baseline', '/inputs/source/baseline.blend'],
            {'source': source, 'params': params}, authored, root/'author.log')
        jobs[revision] = {'author': job}
        for kind, filename in (('source', 'model.blend'), ('stl', 'model.stl')):
            inspected = root/(kind+'-inspection');inspected.mkdir()
            args = ['--python', '/inputs/inspector', '--', '--input', '/inputs/input',
                    '--observer', '/inputs/reference', '--output', '/output', '--revision', revision]
            if kind == 'stl':args.append('--stl')
            jobs[revision][kind] = sandbox.run('roundtrip', args,
                {'inspector': source/'head_comparison_v1/inspect.py', 'input': authored/filename,
                 'reference': observer}, inspected, root/(kind+'-inspect.log'))
        observation = json.loads((root/'source-inspection/observation.json').read_text())
        stl = json.loads((root/'stl-inspection/observation.json').read_text())
        measured = verify_pair(observation, stl)
        if observation['input_sha256'] != digest(authored/'model.blend') or stl['input_sha256'] != digest(authored/'model.stl'):
            raise ValueError('Observation is not bound to the exact artifact bytes')
        base_hashes.add(observation['base_exact_surface_sha256'])
        for variant in ('baseline', 'comparison'):
            render_input = root/(variant+'-render-input');render_input.mkdir()
            shutil.copyfile(source/'head_comparison_v1/inspect.py', render_input/'inspect.py')
            shutil.copyfile(observer, render_input/'inspect_solid.py')
            reference = root/(variant+'-render-reference.json')
            if variant == 'baseline':
                original = candidates/revision/'authored/model.blend'
                old = json.loads((candidates/revision/'inspection/solid-observation.json').read_text())
                if old['profile_id'] != 'anime-cat-x1c-pla-04-bare100-v3' or old['input_sha256'] != digest(original):
                    raise ValueError('Baseline preview must use the observed original v3 bytes')
                write_json(reference, {'input_sha256': old['input_sha256'], 'mesh': old['meshes']['PrintCandidate']})
            else:
                original = authored/'model.blend';write_json(reference, observation)
            shutil.copyfile(original, render_input/'model.blend')
            rendered = root/(variant+'-render');rendered.mkdir()
            args = ['--python', '/inputs/source/inspect.py', '--', '--input', '/inputs/source/model.blend',
                    '--observer', '/inputs/source/inspect_solid.py', '--output', '/output',
                    '--revision', revision, '--render-reference', '/inputs/params']
            if variant == 'baseline':args.append('--baseline')
            # Reopen in a fresh unchanged-budget sandbox. The source/params
            # mount pair permits the frozen observer and its report together.
            jobs[revision][variant+'-render'] = sandbox.run('author', args,
                {'source': render_input, 'params': reference}, rendered, root/(variant+'-render.log'))
            binding = json.loads((rendered/'render-binding.json').read_text())
            if binding['input_sha256'] != digest(original):raise ValueError('Preview source binding changed')
        summaries[revision] = {'source': observation, 'stl': stl,
                               'stl_sha256': digest(authored/'model.stl')}
        write_json(store/('checkpoint-'+revision+'.json'), {'comparison_id': COMPARISON_ID, 'complete_revisions': list(summaries),
                                           'promotion_eligible': False, 'physical_validation': 'pending', 'jobs': jobs})
        print(revision+' complete source/STL/gray A/B PASS', flush=True)
    if len(base_hashes) != 1 or summaries['r0']['source']['mesh']['exact_surface_sha256'] not in base_hashes:
        raise ValueError('Accessory revisions must share the exact new bare comparison base')
    for relative, sha in source_files.items():
        if digest(source/relative) != sha:raise ValueError('Reviewed comparison source changed during execution')
    result = {'comparison_id': COMPARISON_ID, 'status': 'geometry_comparison_only', 'revisions': summaries,
              'runtime': runtime, 'source_files': source_files, 'observer_sha256': OBSERVER_SHA, 'jobs': jobs,
              'promotion_eligible': False, 'physical_validation': 'pending', 'visual_acceptance': 'owner_pending',
              'native_consumed_buffer_fidelity': 'unknown', 'feature_coverage': 'unknown', 'support_clearance': 'unknown'}
    write_json(store/'summary.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', required=True)
    parser.add_argument('--candidates', required=True)
    parser.add_argument('--sandbox-image', required=True)
    parser.add_argument('--docker')
    args = parser.parse_args()
    run(args.store, args.candidates, args.sandbox_image, args.docker)
