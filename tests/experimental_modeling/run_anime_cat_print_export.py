# SPDX-License-Identifier: GPL-3.0-or-later
"""Full millimeter STL roundtrip, preservation and rejection evidence in Docker."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experimental_modeling.contracts import read_json
from experimental_modeling.controller import build, digest, regular_tree, safe_path, snapshot, verify_accepted, write_json
from experimental_modeling.print_contract import PrintProfile
from experimental_modeling.print_preservation import assess
from experimental_modeling.sandbox import DockerSandbox
from run_anime_cat_print import run as run_candidates, verify as verify_candidates

FIXTURE = ROOT/'experimental_modeling/examples/anime_cat/print'
ORIGINAL = ROOT/'experimental_modeling/examples/anime_cat'


def history_fingerprints(history):
    """Verify the real accepted controller tree before retaining its hashes."""
    pointer = read_json(history/'last_good.json')
    if pointer['revision'] != 'r2':
        raise ValueError('History regression requires the accepted original glasses revision')
    expected = pointer['result_hash']
    for index in (2,1,0):
        revision = f'r{index}'
        manifest = verify_accepted(history/'accepted'/revision,expected)
        parent = f'r{index-1}' if index else None
        if manifest['revision'] != revision or manifest['parent'] != parent:
            raise ValueError('Accepted original history parent chain disagrees')
        expected = manifest['parent_result_hash']
        if (index == 0 and expected is not None) or (index and (not isinstance(expected,str) or len(expected) != 64)):
            raise ValueError('Accepted original history parent hash disagrees')
    return {str(path.relative_to(history)):digest(path) for path in regular_tree(history)}


def negative_stls(source, output):
    """Mutate all encoded facets; the independent observer measures each result."""
    data = source.read_bytes()
    count = struct.unpack_from('<I',data,80)[0]
    if not 4 <= count <= 500000 or len(data) != 84+50*count:
        raise ValueError('Expected a bounded complete generated binary STL')
    triangles = [tuple(tuple(row[i:i+3]) for i in (3,6,9)) for row in struct.iter_unpack('<12fH',data[84:])]

    def write(name, rows):
        rows = list(rows)
        path = output/(name+'.stl')
        with path.open('xb') as stream:
            stream.write(data[:80]+struct.pack('<I',len(rows)))
            for a,b,c in rows:
                u,v = [b[i]-a[i] for i in range(3)],[c[i]-a[i] for i in range(3)]
                normal = (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
                length = math.sqrt(sum(x*x for x in normal))
                normal = tuple(x/length for x in normal) if length else (0,0,0)
                stream.write(struct.pack('<12fH',*normal,*a,*b,*c,0))
        return path

    def deform(point, kind):
        x,y,z = point
        # Enlarge so existing valid microscopic facets stay measurable. The
        # fixed-height contract must reject scale without weakening area QA.
        if kind == 'wrong-scale': return tuple(v*2 for v in point)
        if kind == 'shifted-body': return (x+.5*max(0,min(1,(52-z)/12)),y,z)
        cx,cy,cz = .72*100/3.15,-.55*100/3.15,1.68*100/3.15
        factor = 1-.75*max(0,1-abs(x-cx)/3)*max(0,1-abs(z-cz)/4)
        return (x,cy+(y-cy)*factor,cz+(z-cz)*factor)

    result = {'open-seam':write('open-seam',triangles[1:])}
    tetra = [(45,-35,50),(47,-35,50),(45,-33,50),(45,-35,52)]
    detached = [tuple(tetra[i] for i in row) for row in ((0,2,1),(0,1,3),(0,3,2),(1,2,3))]
    result['detached-shell'] = write('detached-shell',triangles+detached)
    for name in ('wrong-scale','thin-whisker','shifted-body'):
        result[name] = write(name,(tuple(deform(point,name) for point in row) for row in triangles))
    return result


def run(store, *, sandbox_image, candidates=None, history=None, docker=None):
    store = safe_path(Path(store).absolute())
    if store.exists() and any(store.iterdir()): raise ValueError('Use a fresh empty STL evidence store')
    store.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(store).free < 1024**3: raise ValueError('At least 1 GiB free disk space is required')
    profile = PrintProfile.load(FIXTURE/'provisional_fdm_v1.json')
    sandbox = DockerSandbox(sandbox_image,docker_executable=Path(docker) if docker else None)
    runtime = sandbox.verify_runtime()
    source_hashes = snapshot(FIXTURE/'source',store/'source')
    observer,exporter = store/'inspect_solid.py',store/'export_stl.py'
    shutil.copyfile(FIXTURE/'inspect_solid.py',observer)
    shutil.copyfile(FIXTURE/'export_stl.py',exporter)
    original_hash = digest(ORIGINAL/'source/builder.py')
    if candidates is None:
        candidates = store/'candidates'
        run_candidates(candidates,sandbox_image=sandbox_image,docker=docker)
    candidates = safe_path(Path(candidates).absolute())
    summary = read_json(candidates/'print-candidate-summary.json')
    if summary['status'] != 'closed_candidates' or summary['source_files'] != source_hashes or summary['observer_sha256'] != digest(observer):
        raise ValueError('Candidates must be completely observed with these exact frozen sources and observer')
    if history is None:
        history = store/'original-history'
        for i in range(3):
            revision = f'r{i}'
            result = build(source=ORIGINAL/'source',params=ORIGINAL/'params'/f'{revision}.json',
                           policy_path=ORIGINAL/'policies'/f'{revision}.policy.json',store=history,
                           revision=revision,parent=f'r{i-1}' if i else None,renders=False,
                           intent='Original reviewed fixture history for offline print rejection regression',
                           sandbox_image=sandbox_image,docker_executable=Path(docker) if docker else None)
            if result['status'] != 'accepted': raise ValueError('Original fixture history did not accept')
    history = safe_path(Path(history).absolute())
    before = history_fingerprints(history)
    jobs,records,observations = {},{},[]
    try:
        probe=store/'stl-probes';probe.mkdir()
        probe_script=store/'verify_print_stl.py'
        shutil.copyfile(ROOT/'tests/experimental_modeling/verify_print_stl.py',probe_script)
        jobs['stl_probes']=sandbox.run('roundtrip',['--python','/inputs/inspector','--','--observer','/inputs/input','--author-source','/inputs/reference','--output','/output'],{'inspector':probe_script,'input':observer,'reference':store/'source/solids.py'},probe,store/'stl-probes.log')
        for revision in ('r0','r1','r2'):
            source = read_json(candidates/revision/'inspection/solid-observation.json')
            base = read_json(candidates/revision/'base-inspection/solid-observation.json')
            blend = candidates/revision/'authored/model.blend'
            if source['input_sha256'] != digest(blend) or base['input_sha256'] != source['input_sha256']:
                raise ValueError('Complete source observations no longer bind to the saved blend')
            source['meshes']['PrintBase'] = base['meshes']['PrintBase']
            observations.append(source)
            current = store/revision
            current.mkdir(); exported = current/'export'; exported.mkdir()
            inspected = current/'inspection'; inspected.mkdir()
            rendered = current/'render'; rendered.mkdir()
            jobs[revision] = {}
            jobs[revision]['export'] = sandbox.run('roundtrip',['--python','/inputs/inspector','--','--input','/inputs/input','--observer','/inputs/reference','--output','/output'],{'inspector':exporter,'input':blend,'reference':observer},exported,current/'export.log')
            stl = exported/'model.stl'
            jobs[revision]['inspect'] = sandbox.run('inspect',['--python','/inputs/inspector','--','--stl','--input','/inputs/input','--output','/output','--revision',revision,'--no-renders'],{'inspector':observer,'input':stl},inspected,current/'inspect.log')
            reimported = read_json(inspected/'solid-observation.json')
            exported_report = read_json(exported/'export-observation.json')
            if revision == 'r0': baseline = reimported
            assessment = assess(profile,revision,source,exported_report,reimported,baseline,
                                stl_sha256=digest(stl),source_observation_sha256=digest(candidates/revision/'inspection/solid-observation.json'),
                                observer_sha256=digest(observer),derivation_sha256=digest(store/'source/solids.py'))
            write_json(current/'assessment.json',assessment)
            if assessment['failures']: raise ValueError(f'{revision} STL gates failed: {assessment["failures"]}')
            jobs[revision]['render'] = sandbox.run('reopen',['--python','/inputs/inspector','--','--stl','--input','/inputs/input','--output','/output','--revision',revision,'--target','PrintCandidate','--render-reference','/inputs/reference'],{'inspector':observer,'input':stl,'reference':inspected/'solid-observation.json'},rendered,current/'render.log')
            binding = read_json(rendered/'render-binding.json')
            if binding['input_sha256'] != digest(stl) or binding['observation_sha256'] != digest(inspected/'solid-observation.json') or len(list((rendered/'views').glob('*.png'))) != 4:
                raise ValueError('STL preview does not bind to its complete observation')
            records[revision] = {'stl_sha256':digest(stl),'assessment':assessment,'triangles':reimported['stl_triangle_count'],
                                 'complete_intersection_pairs':reimported['meshes']['PrintCandidate']['intersection_measurement']['pairs_tested']}
        verify_candidates(observations,profile)
        rebuilt = store/'clean-rebuild'; rebuilt.mkdir()
        params = rebuilt/'params.json'; write_json(params,{'revision':'r2'})
        authored = rebuilt/'authored'; authored.mkdir(); exported = rebuilt/'export'; exported.mkdir()
        jobs['clean_rebuild_author'] = sandbox.run('author',['--python','/inputs/source/builder.py','--','--params','/inputs/params','--output','/output/model.blend'],{'source':store/'source','params':params},authored,rebuilt/'author.log')
        jobs['clean_rebuild_export'] = sandbox.run('roundtrip',['--python','/inputs/inspector','--','--input','/inputs/input','--observer','/inputs/reference','--output','/output'],{'inspector':exporter,'input':authored/'model.blend','reference':observer},exported,rebuilt/'export.log')
        if digest(exported/'model.stl') != records['r2']['stl_sha256']:
            raise ValueError('Clean glasses rebuild produced different STL bytes')
        negative = store/'negative'; negative.mkdir()
        negatives = negative_stls(store/'r2/export/model.stl',negative)
        failures = {}
        required = {'open-seam':'boundary_edges','detached-shell':'connected_shells',
                    'wrong-scale':'fixed_scale_height','thin-whisker':'minimum_feature_mm','shifted-body':'protected_regions'}
        for name,stl in negatives.items():
            current=negative/name;current.mkdir()
            jobs[name] = sandbox.run('inspect',['--python','/inputs/inspector','--','--stl','--input','/inputs/input','--output','/output','--revision','r2','--no-renders'],{'inspector':observer,'input':stl},current,negative/(name+'.log'))
            report = read_json(current/'solid-observation.json')
            original_source = observations[-1]
            exported_report = read_json(store/'r2/export/export-observation.json')
            result = assess(profile,'r2',original_source,exported_report,report,baseline,
                            stl_sha256=digest(stl),source_observation_sha256=digest(candidates/'r2/inspection/solid-observation.json'),
                            observer_sha256=digest(observer),derivation_sha256=digest(store/'source/solids.py'))
            write_json(current/'assessment.json',result)
            if result['measurement_gate'] != 'rejected' or required[name] not in result['failures']:
                raise ValueError(f'Negative STL {name} did not fail its independently measured gate')
            failures[name] = result['failures']
            if history_fingerprints(history) != before: raise ValueError('Rejected print evidence changed accepted controller history')
        frozen_files = {str(p.relative_to(store/'source')):digest(p) for p in regular_tree(store/'source')}
        if frozen_files != source_hashes or digest(observer) != digest(FIXTURE/'inspect_solid.py') or digest(exporter) != digest(FIXTURE/'export_stl.py') or digest(ORIGINAL/'source/builder.py') != original_hash:
            raise ValueError('Source, observer, exporter or original fixture changed during the experiment')
        result = {'status':'provisional_STL_geometry_verified','promotion_eligible':False,'physical_validation':'pending',
                  'feature_coverage':'unknown','visual_fidelity':'pending_independent_review','profile_sha256':profile.sha256,
                  'source_files':source_hashes,'observer_sha256':digest(observer),'exporter_sha256':digest(exporter),
                  'original_fixture_sha256':original_hash,'runtime':runtime,'github_sha':os.environ.get('GITHUB_SHA'),
                  'revisions':records,'jobs':jobs,'negative_failures':failures,'clean_rebuild_stl_bytes_equal':True,
                  'existing_history_scope':'Read-only STL assessment leaves the original scene-contract accepted chain unchanged; print controller acceptance and rollback remain unavailable',
                  'history_files_sha256':before,'last_good_and_accepted_history_unchanged':True}
        write_json(store/'print-export-summary.json',result)
        return result
    except Exception as exc:
        write_json(store/'print-export-failure.json',{'status':'failed','promotion_eligible':False,'error':str(exc),'jobs':jobs})
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--store',required=True,type=Path)
    parser.add_argument('--sandbox-image',required=True)
    parser.add_argument('--candidates',type=Path)
    parser.add_argument('--history',type=Path)
    parser.add_argument('--docker')
    result=run(**vars(parser.parse_args()))
    print(json.dumps({key:result[key] for key in ('status','promotion_eligible','physical_validation')}))
