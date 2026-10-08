# SPDX-License-Identifier: GPL-3.0-or-later
"""Assess complete offline STL measurements, without promoting artifacts."""
from __future__ import annotations
import re

from .print_contract import PrintProfile, X1C_PROFILE_ID, X1C_BAMBU_PROFILE_ID, assess_final_stl

BOXES = {'r1':{'min':[-20,-20,80],'max':[20,20,103]},
         'r2':{'min':[-26,-32,54],'max':[26,2,76]}}
METHOD = 'canonical_oriented_exact_float32_boundary_facets_retained'
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def protected_boxes(profile):
    if profile.profile_id in (X1C_PROFILE_ID, X1C_BAMBU_PROFILE_ID):
        return {'r1':{'min':[-21.709264755249023,-21.709264755249023,86.8370590209961],
                      'max':[21.709264755249023,21.709264755249023,111.8027114868164]},
                'r2':{'min':[-28.222043991088867,-34.734825134277344,58.61501693725586],
                      'max':[28.222043991088867,2.170926570892334,82.49520874023438]}}
    return {key:{side:list(points) for side,points in box.items()} for key,box in BOXES.items()}


def require_profile_binding(profile, *reports):
    if any(report.get('profile_id') != profile.profile_id or
           report.get('profile_sha256') != profile.sha256 for report in reports):
        raise ValueError('Evidence uses a different print profile')


def digest(value):
    if not isinstance(value,str) or not SHA256.fullmatch(value):
        raise ValueError('Invalid complete surface fingerprint')
    return value


def count(value):
    if type(value) is not int or not 4 <= value <= 500000:
        raise ValueError('Invalid complete triangle count')
    return value


def measured_evidence(profile, revision, report, mesh, hashes, checks):
    probes = mesh['feature_probes']
    return {
        'schema_version':1,'profile_sha256':profile.sha256,'revision':revision,
        'measurement_source':'reimported_final_stl','units':'millimeter',
        **hashes,'triangle_count':report['stl_triangle_count'],
        'evaluated_triangle_count':mesh['evaluated_triangles'],'measured_triangle_count':mesh['measured_triangles'],
        'connected_shells':mesh['face_connected_shells'],'boundary_edges':mesh['boundary_edges'],
        'nonmanifold_edges':mesh['non_manifold_edges'],'nonmanifold_vertices':mesh['non_manifold_vertices'],
        'loose_vertices':mesh['loose_vertices'],'noncontiguous_edges':mesh['inconsistent_winding_edges'],
        'degenerate_triangles':mesh['degenerate_triangles'],'signed_volume_mm3':mesh['signed_volume_mm3'],
        'bounds_min_mm':mesh['bounds_mm']['min'],'bounds_max_mm':mesh['bounds_mm']['max'],
        'measured_minimum_feature_mm':probes['minimum_mm'],'feature_sample_count':probes['sample_count'],
        'checks':checks,
    }


def intersection_check(mesh):
    value = mesh['self_intersections']
    if type(value) is not int or not 0 <= value <= 10000000:
        raise ValueError('Invalid self-intersection count')
    return 'passed' if value == 0 and mesh['intersection_measurement']['complete'] is True else 'failed'


def assess(profile: PrintProfile, revision, source, exported, reimported, baseline,
           *, stl_sha256, source_observation_sha256, observer_sha256, derivation_sha256):
    require_profile_binding(profile,source,exported,reimported,baseline)
    if (revision not in ('r0','r1','r2') or source['revision'] != revision or
            reimported['revision'] != revision or source['unit'] != 'millimeter' or
            exported['unit'] != 'millimeter' or reimported['unit'] != 'millimeter' or
            source['measurement_source'] != 'evaluated_saved_blend' or
            reimported['measurement_source'] != 'reimported_final_stl' or
            exported['input_sha256'] != source['input_sha256'] or
            reimported['input_sha256'] != stl_sha256):
        raise ValueError('Source, export and full STL observation provenance disagree')
    digest(source['input_sha256'])
    digest(exported['input_sha256'])
    if (baseline['revision'] != 'r0' or baseline['unit'] != 'millimeter' or
            baseline['measurement_source'] != 'reimported_final_stl'):
        raise ValueError('Protected baseline must be the independently reimported hat-free r0 STL')
    original = source['meshes']['PrintCandidate']
    result = reimported['meshes']['PrintCandidate']
    export = exported['meshes']['PrintCandidate']
    reference = baseline['meshes']['PrintCandidate']
    for mesh in (original,result,reference):
        digest(mesh['surface_sha256'])
        digest(mesh['exact_surface_sha256'])
    digest(export['surface_sha256'])
    digest(export['exact_surface_sha256'])
    complete = (count(original['evaluated_triangles']) == count(original['measured_triangles']) ==
                count(export['evaluated_triangles']) == count(reimported['stl_triangle_count']) ==
                count(result['evaluated_triangles']) == count(result['measured_triangles']))
    if not (count(baseline['stl_triangle_count']) == count(reference['evaluated_triangles']) ==
            count(reference['measured_triangles'])):
        raise ValueError('Protected baseline omitted final STL facets')
    hashes = {'stl_sha256':stl_sha256,'source_observation_sha256':source_observation_sha256,
              'evaluated_mesh_sha256':export['exact_surface_sha256'],'observer_sha256':observer_sha256,
              'derivation_sha256':derivation_sha256}
    baseline_hashes = dict(hashes,stl_sha256=digest(baseline['input_sha256']),
                           evaluated_mesh_sha256=reference['exact_surface_sha256'])
    baseline_checks = {key:'unknown' for key in ('roundtrip_surface','protected_regions','feature_coverage','visual_fidelity')}
    baseline_checks['self_intersections'] = intersection_check(reference)
    if assess_final_stl(profile,measured_evidence(profile,'r0',baseline,reference,baseline_hashes,baseline_checks))['failures']:
        raise ValueError('Protected baseline fails the complete final STL geometry contract')
    roundtrip = (complete and export['stl_sha256'] == stl_sha256 and
                 original['surface_sha256'] == export['surface_sha256'] == result['surface_sha256'] and
                 original['exact_surface_sha256'] == export['exact_surface_sha256'] == result['exact_surface_sha256'])
    base = exported['meshes']['PrintBase']
    observed_base = source['meshes']['PrintBase']
    preserved_base = (count(base['evaluated_triangles']) == count(observed_base['evaluated_triangles']) ==
                      count(observed_base['measured_triangles']) == reference['measured_triangles'] and
                      digest(base['exact_surface_sha256']) == digest(observed_base['exact_surface_sha256']) == reference['exact_surface_sha256'])
    if revision == 'r0':
        preserved = result['exact_surface_sha256'] == reference['exact_surface_sha256']
    else:
        actual,expected = result['protected_regions'][revision],reference['protected_regions'][revision]
        for row,total in ((actual,result['measured_triangles']),(expected,reference['measured_triangles'])):
            if (set(row) != {'excluded_box_mm','triangles','surface_sha256','method'} or
                    row['excluded_box_mm'] != protected_boxes(profile)[revision] or row['method'] != METHOD or
                    type(row['triangles']) is not int or not 0 < row['triangles'] <= total):
                raise ValueError('Unsupported protected-region scope or incomplete facet fingerprint')
            digest(row['surface_sha256'])
        preserved = actual == expected
    checks = {'self_intersections':intersection_check(result),
              'roundtrip_surface':'passed' if roundtrip else 'failed',
              'protected_regions':'passed' if preserved and preserved_base else 'failed',
              'feature_coverage':'unknown','visual_fidelity':'unknown'}
    evidence = measured_evidence(profile,revision,reimported,result,hashes,checks)
    assessment = assess_final_stl(profile,evidence)
    assessment.update({'full_source_stl_surface_equal':roundtrip,'final_protected_surface_unchanged':preserved,
                       'hidden_base_unchanged':preserved_base,'hat_region_matches_hat_free_base':preserved if revision=='r2' else None,
                       'evidence':evidence})
    return assessment
