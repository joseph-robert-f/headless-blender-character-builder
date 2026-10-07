# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and independently inspect the separate offline print candidates."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experimental_modeling.contracts import read_json
from experimental_modeling.controller import digest, regular_tree, run_job, safe_path, snapshot, write_json
from experimental_modeling.print_contract import PrintProfile, DEFAULT_PROFILE_ID, X1C_PROFILE_ID, X1C_BAMBU_PROFILE_ID
from experimental_modeling.print_preservation import require_profile_binding
from experimental_modeling.sandbox import DockerSandbox

FIXTURE = ROOT / 'experimental_modeling/examples/anime_cat/print'


def verify(observations, profile):
    """Check observed candidates, without claiming complete print acceptance."""
    if len(observations) != 3:
        raise ValueError('Three observed print revisions are required')
    base_hashes = set()
    for revision, report in zip(('r0','r1','r2'), observations):
        require_profile_binding(profile,report)
        if report['revision'] != revision or report['unit'] != 'millimeter' or report['promotion_eligible'] is not False:
            raise ValueError('Incorrect revision, units, or promotion status')
        for name in ('PrintBase','PrintCandidate'):
            mesh = report['meshes'][name]
            for key in ('non_manifold_edges','non_manifold_vertices','loose_vertices',
                        'inconsistent_winding_edges','degenerate_triangles','self_intersections'):
                if type(mesh[key]) is not int or mesh[key] != 0:
                    raise ValueError(f'{revision} {name}: {key}')
            if type(mesh['face_connected_shells']) is not int or mesh['face_connected_shells'] != 1:
                raise ValueError(f'{revision} {name}: solid must contain one face-connected shell')
            triangles = mesh['evaluated_triangles']
            if type(triangles) is not int or not 0 < triangles <= profile.raw['maximum_triangles'] or type(mesh['measured_triangles']) is not int or triangles != mesh['measured_triangles']:
                raise ValueError('Complete evaluated mesh must fit the measured triangle budget')
            if mesh['intersection_measurement']['complete'] is not True:
                raise ValueError('Complete intersection observation is required')
            volume = mesh['signed_volume_mm3']
            if type(volume) not in (int,float) or not math.isfinite(volume) or volume <= 0:
                raise ValueError('Expected finite positive signed solid volume')
            low, high = mesh['bounds_mm']['min'], mesh['bounds_mm']['max']
            if len(low) != 3 or len(high) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in low+high):
                raise ValueError('Invalid observed bounds')
            dimensions = [high[i]-low[i] for i in range(3)]
            target = profile.raw['revision_heights_mm'][revision if name == 'PrintCandidate' else 'r0']
            if any(not 0 < value <= profile.raw['maximum_dimension_mm'] for value in dimensions) or abs(dimensions[2]-target) > profile.raw['height_tolerance_mm'] or abs(low[2]) > .001:
                raise ValueError('Incorrect dimensions, shared scale, or ground contact')
        for mesh in report['meshes'].values():
            if not isinstance(mesh['surface_sha256'],str) or re.fullmatch(r'[0-9a-f]{64}',mesh['surface_sha256']) is None:
                raise ValueError('Invalid complete surface hash')
        base_hashes.add(report['meshes']['PrintBase']['surface_sha256'])
        probes = report['meshes']['PrintCandidate']['feature_probes']
        expected = {f'whisker-{sign}-{i}':8 for sign in (-1,1) for i in range(2)}
        if revision == 'r1':
            expected['hat-brim'] = 1
        elif revision == 'r2':
            expected['glasses-bridge'] = 8
        samples = probes['samples']
        if len(samples) != len(expected) or {row['feature']:row['chords'] for row in samples} != expected or probes['sample_count'] != sum(expected.values()):
            raise ValueError('Independent feature probes are missing or inconsistent')
        if any(type(row['minimum_chord_mm']) not in (int,float) or not math.isfinite(row['minimum_chord_mm']) for row in samples) or abs(probes['minimum_mm']-min(row['minimum_chord_mm'] for row in samples)) > 1e-6:
            raise ValueError('Feature minimum does not match its observed probes')
        if type(probes['minimum_mm']) not in (int,float) or not math.isfinite(probes['minimum_mm']) or probes['minimum_mm'] < profile.raw['minimum_feature_mm'] or type(probes['sample_count']) is not int or probes['sample_count'] < 32:
            raise ValueError('A designed feature is too thin or lacks observed samples')
    if len(base_hashes) != 1 or observations[0]['meshes']['PrintCandidate']['surface_sha256'] not in base_hashes:
        raise ValueError('The original closed base changed across accessory revisions')
    return {'status': 'closed_candidates', 'shared_base_surface_sha256': base_hashes.pop(),
            'feature_coverage': 'unknown', 'protected_regions': 'unknown',
            'visual_fidelity': 'pending_independent_review', 'promotion_eligible': False,
            'physical_validation': 'pending'}


def run(store, *, trusted_reviewed_source=False, sandbox_image=None, blender='blender', docker=None, profile_id=DEFAULT_PROFILE_ID):
    if trusted_reviewed_source == bool(sandbox_image):
        raise ValueError('Select exactly one explicit Docker or reviewed native mode')
    if trusted_reviewed_source and sys.platform == 'darwin':
        raise RuntimeError('Use Docker on macOS. This native harness cannot enforce its address-space limit.')
    store = safe_path(Path(store).absolute())
    if store.exists() and any(store.iterdir()):
        raise ValueError('Use a fresh empty print evidence store')
    store.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(store).free < 1024**3:
        raise ValueError('At least 1 GiB free disk space is required for bounded local evidence')
    profile = PrintProfile.load(FIXTURE/PrintProfile.reviewed(profile_id).fixture_name)
    policy_args = ['--profile-id',profile.profile_id]
    source_hashes = snapshot(FIXTURE/'source', store/'source')
    observer = store/'inspect_solid.py'
    shutil.copyfile(FIXTURE/'inspect_solid.py', observer)
    original = ROOT/'experimental_modeling/examples/anime_cat/source/builder.py'
    original_hash = digest(original)
    sandbox = DockerSandbox(sandbox_image, docker_executable=Path(docker) if docker else None) if sandbox_image else None
    runtime = sandbox.verify_runtime() if sandbox else {'security_boundary': 'NOT_SANDBOXED'}
    jobs, observations = {}, []
    try:
        if profile.profile_id==X1C_PROFILE_ID:
            resize_probe=store/'resize-probes';resize_probe.mkdir()
            resize_source=store/'resize-probe-source'
            snapshot(store/'source',resize_source)
            shutil.copyfile(observer,resize_source/'inspect_solid.py')
            shutil.copyfile(ROOT/'tests/experimental_modeling/verify_x1c_resize.py',resize_source/'verify_x1c_resize.py')
            resize_params=store/'resize-probe-params.json';write_json(resize_params,{'revision':'r1'})
            if sandbox:
                jobs['resize_probes']=sandbox.run('author',['--python','/inputs/source/verify_x1c_resize.py','--','--params','/inputs/params','--output','/output'],{'source':resize_source,'params':resize_params},resize_probe,store/'resize-probes.log')
            else:
                jobs['resize_probes']=run_job([blender,'--background','--factory-startup','--disable-autoexec','--threads','2','--python-exit-code','1','--python',str(resize_source/'verify_x1c_resize.py'),'--','--params',str(resize_params),'--output',str(resize_probe)],store,store/'resize-probes.log',budget_root=store)
        if profile.profile_id==X1C_BAMBU_PROFILE_ID:
            floor_probe=store/'floor-probes';floor_probe.mkdir()
            floor_source=store/'floor-probe-source'
            snapshot(store/'source',floor_source)
            shutil.copyfile(ROOT/'tests/experimental_modeling/verify_x1c_bambu_floor.py',floor_source/'verify_x1c_bambu_floor.py')
            floor_params=store/'floor-probe-params.json';write_json(floor_params,{'revision':'r0'})
            if sandbox:
                jobs['floor_probes']=sandbox.run('author',['--python','/inputs/source/verify_x1c_bambu_floor.py','--','--params','/inputs/params','--output','/output'],{'source':floor_source,'params':floor_params},floor_probe,store/'floor-probes.log')
            else:
                jobs['floor_probes']=run_job([blender,'--background','--factory-startup','--disable-autoexec','--threads','2','--python-exit-code','1','--python',str(floor_source/'verify_x1c_bambu_floor.py'),'--','--params',str(floor_params),'--output',str(floor_probe)],store,store/'floor-probes.log',budget_root=store)
        probe = store/'geometry-probes'
        probe.mkdir()
        probe_script = store/'verify_print_intersections.py'
        shutil.copyfile(ROOT/'tests/experimental_modeling/verify_print_intersections.py',probe_script)
        if sandbox:
            jobs['geometry_probes'] = sandbox.run('roundtrip',['--python','/inputs/inspector','--','--observer','/inputs/input','--author-source','/inputs/reference','--output','/output'],{'inspector':probe_script,'input':observer,'reference':store/'source/solids.py'},probe,store/'geometry-probes.log')
        else:
            jobs['geometry_probes'] = run_job([blender,'--background','--factory-startup','--disable-autoexec','--threads','2','--python-exit-code','1','--python',str(probe_script),'--','--observer',str(observer),'--author-source',str(store/'source/solids.py'),'--output',str(probe)],store,store/'geometry-probes.log',budget_root=store)
        for revision in ('r0','r1','r2'):
            root = store/revision
            root.mkdir()
            params = root/'params.json'
            write_json(params, {'revision': revision})
            authored, inspected = root/'authored', root/'inspection'
            authored.mkdir()
            inspected.mkdir()
            base_inspection = root/'base-inspection'
            base_inspection.mkdir()
            rendered = root/'render'
            rendered.mkdir()
            if sandbox:
                author = sandbox.run('author', ['--python','/inputs/source/'+profile.author_entry,'--','--params','/inputs/params','--output','/output/model.blend'],
                                     {'source':store/'source','params':params}, authored,root/'author.log')
                inspect_base = sandbox.run('inspect',['--python','/inputs/inspector','--','--input','/inputs/input','--output','/output','--revision',revision,'--target','PrintBase','--no-renders']+policy_args,{'inspector':observer,'input':authored/'model.blend'},base_inspection,root/'inspect-base.log')
                inspect = sandbox.run('inspect', ['--python','/inputs/inspector','--','--input','/inputs/input','--output','/output','--revision',revision,'--target','PrintCandidate','--no-renders']+policy_args,
                                      {'inspector':observer,'input':authored/'model.blend'},inspected,root/'inspect.log')
                render = sandbox.run('reopen',['--python','/inputs/inspector','--','--input','/inputs/input','--output','/output','--revision',revision,'--target','PrintCandidate','--render-reference','/inputs/reference']+policy_args,{'inspector':observer,'input':authored/'model.blend','reference':inspected/'solid-observation.json'},rendered,root/'render.log')
            else:
                command = [blender,'--background','--factory-startup','--disable-autoexec','--threads','2','--python-exit-code','1']
                author = run_job(command+['--python',str(store/'source'/profile.author_entry),'--','--params',str(params),'--output',str(authored/'model.blend')],root,root/'author.log',budget_root=store)
                inspect_base = run_job(command+['--python',str(observer),'--','--input',str(authored/'model.blend'),'--output',str(base_inspection),'--revision',revision,'--target','PrintBase','--no-renders']+policy_args,root,root/'inspect-base.log',budget_root=store)
                inspect = run_job(command+['--python',str(observer),'--','--input',str(authored/'model.blend'),'--output',str(inspected),'--revision',revision,'--target','PrintCandidate','--no-renders']+policy_args,root,root/'inspect.log',budget_root=store)
                render = run_job(command+['--python',str(observer),'--','--input',str(authored/'model.blend'),'--output',str(rendered),'--revision',revision,'--target','PrintCandidate','--render-reference',str(inspected/'solid-observation.json')]+policy_args,root,root/'render.log',budget_root=store)
            jobs[revision] = {'author':author,'inspect':inspect,'inspect_base':inspect_base,'render':render}
            report = read_json(inspected/'solid-observation.json')
            base_report = read_json(base_inspection/'solid-observation.json')
            require_profile_binding(profile,report,base_report)
            report['meshes']['PrintBase'] = base_report['meshes']['PrintBase']
            if base_report['revision'] != revision or base_report['unit'] != 'millimeter' or base_report['input_sha256'] != report['input_sha256'] or report['input_sha256'] != digest(authored/'model.blend'):
                raise ValueError('Saved candidate changed after inspection')
            binding = read_json(rendered/'render-binding.json')
            require_profile_binding(profile,binding)
            candidate = report['meshes']['PrintCandidate']
            if binding['input_sha256'] != report['input_sha256'] or binding['observation_sha256'] != digest(inspected/'solid-observation.json') or binding['surface_sha256'] != candidate['surface_sha256'] or binding['measured_triangles'] != candidate['measured_triangles']:
                raise ValueError('Preview does not bind to the complete independent observation')
            if len(list((rendered/'views').glob('*.png'))) != 4:
                raise ValueError('Four independent preview views are required')
            observations.append(report)
        result = verify(observations,profile)
        if source_hashes != {str(p.relative_to(store/'source')):digest(p) for p in regular_tree(store/'source')} or digest(observer) != digest(FIXTURE/'inspect_solid.py') or digest(original) != original_hash:
            raise ValueError('Source or independent observer changed during the experiment')
        result.update({'profile_id':profile.profile_id,'profile_sha256':profile.sha256,'source_files':source_hashes,
                       'observer_sha256':digest(observer),'original_fixture_sha256':original_hash,
                       'jobs':jobs,'runtime':runtime,'github_sha':__import__('os').environ.get('GITHUB_SHA'),
                       'revisions':{report['revision']:report['meshes']['PrintCandidate'] for report in observations}})
        write_json(store/'print-candidate-summary.json',result)
        return result
    except Exception as exc:
        write_json(store/'print-candidate-failure.json', {'status':'failed','promotion_eligible':False,'error':str(exc),'jobs':jobs})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--trusted-reviewed-source', action='store_true')
    mode.add_argument('--sandbox-image')
    parser.add_argument('--blender',default='blender')
    parser.add_argument('--docker')
    parser.add_argument('--profile-id',choices=(DEFAULT_PROFILE_ID,X1C_PROFILE_ID,X1C_BAMBU_PROFILE_ID),default=DEFAULT_PROFILE_ID)
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({key:result[key] for key in ('status','promotion_eligible','feature_coverage','physical_validation')}))


if __name__ == '__main__':
    main()
