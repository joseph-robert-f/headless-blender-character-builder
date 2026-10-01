"""Security and acceptance invariants of the isolated experimental entry point."""
import copy
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from experimental_modeling.contracts import Policy, read_json
from experimental_modeling.acceptance import check
from experimental_modeling.controller import build, regular_tree, safe_path, snapshot, verify_accepted, write_json, digest

POLICY = {"schema_version": 1, "parts": ["body"], "changed_parts": [], "constraints": [], "profile": "scene"}
OBS = {"parts": {"body": {"world_vertices": [[0,0,0], [1,0,0]], "geometry_hash": "a", "transform_hash": "b", "material_hash": "c", "nonmanifold_edges": 0}}}


class ContractTests(unittest.TestCase):
    def test_strict_policy(self):
        self.assertEqual(Policy.parse(POLICY).parts, ("body",))
        for edit in ({"extra": 1}, {"parts": ["../escape"]}, {"parts": ["body", "body"]}, {"changed_parts": ["unknown"]}, {"profile": "character"}, {"schema_version": True}):
            with self.subTest(edit=edit), self.assertRaises(ValueError): Policy.parse(POLICY | edit)

    def test_reject_malformed_constraints(self):
        for constraint in ({"kind":"assert_pass", "part":"body", "data":{}},
                           {"kind":"anchor", "part":"body", "data":{"point":[float('nan'),0,0], "tolerance":.1}},
                           {"kind":"path_length", "part":"body", "data":{"groups":[[0,0],[1]],"min":1,"max":2}}):
            with self.assertRaises(ValueError): Policy.parse(POLICY | {"constraints":[constraint]})

    def test_unchanged_geometry_transform_material(self):
        for key in ("geometry_hash", "transform_hash", "material_hash"):
            edited = copy.deepcopy(OBS); edited['parts']['body'][key] = 'changed'
            self.assertEqual(check(Policy.parse(POLICY), edited, OBS)[0]['component'], key)

    def test_nan_and_missing_parts_fail(self):
        edited = copy.deepcopy(OBS); edited['parts']['body']['world_vertices'][0][0] = float('nan')
        with self.assertRaises(ValueError): check(Policy.parse(POLICY), edited, None)
        self.assertTrue(check(Policy.parse(POLICY), {"parts":{}}, None))

    def test_geometry_measurements(self):
        constraints=[{"kind":"anchor","part":"body","data":{"point":[0,0,0],"tolerance":.0001}},
                     {"kind":"path_length","part":"body","data":{"groups":[[0],[1]],"min":.99,"max":1.01}}]
        self.assertFalse(check(Policy.parse(POLICY | {"constraints":constraints}),OBS,None))
        constraints[1]['data']['min']=2; constraints[1]['data']['max']=3
        self.assertEqual(check(Policy.parse(POLICY | {"constraints":constraints}),OBS,None)[0]['check'],'path_length')


class BoundaryTests(unittest.TestCase):
    def test_untrusted_fails_before_any_source_read_or_spawn(self):
        with patch('experimental_modeling.controller.safe_path', side_effect=AssertionError('read')), patch('subprocess.Popen', side_effect=AssertionError('spawn')):
            with self.assertRaisesRegex(RuntimeError, 'UNTRUSTED_EXECUTION_UNAVAILABLE'):
                build(source=Path('/absent'),params=Path('/absent'),policy_path=Path('/absent'),store=Path('/absent'),revision='r0')

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'source').mkdir(); (root/'source'/'bad.py').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): regular_tree(root/'source')
            (root/'alias').symlink_to(root/'source', target_is_directory=True)
            with self.assertRaises(ValueError): safe_path(root/'alias'/'new')

    def test_source_budget_and_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir(); (source/'builder.py').write_text('pass')
            with self.assertRaises(ValueError): regular_tree(source,1)
            (source/'unknown.exe').write_text('no')
            with self.assertRaises(ValueError): snapshot(source,root/'copy')

    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json'; path.write_text('{"v":NaN}')
            with self.assertRaises(ValueError): read_json(path)

    def test_invalid_policy_does_not_create_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir(); (source/'builder.py').write_text('pass')
            params=root/'params.json'; params.write_text('{}'); policy=root/'policy.json'; policy.write_text('{}')
            with self.assertRaises(ValueError): build(source=source,params=params,policy_path=policy,store=root/'store',revision='r0',trusted_reviewed_source=True)
            self.assertFalse((root/'store').exists())


class EvidenceTests(unittest.TestCase):
    def test_rejected_unsafe_artifact_keeps_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir(); (source/'builder.py').write_text('pass')
            params=root/'params.json'; params.write_text('{}'); policy=root/'policy.json'; policy.write_text(json.dumps(POLICY))
            def bad_job(command,cwd,log,**kwargs):
                (cwd/'unsafe').symlink_to(params)
                return {}
            with patch('experimental_modeling.controller.run_job', side_effect=bad_job):
                result=build(source=source,params=params,policy_path=policy,store=root/'store',revision='r0',trusted_reviewed_source=True,blender=sys.executable)
            self.assertEqual(result['status'],'needs_review')
            self.assertTrue((root/'store/attempts/r0/result.json').is_file())
            self.assertFalse((root/'store/last_good.json').exists())
            self.assertFalse((root/'store/attempts/r0/authored/unsafe').is_symlink())
            self.assertEqual(params.read_text(),'{}')

    def test_parent_manifest_and_artifact_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'artifact').write_text('original')
            write_json(root/'result.json',{'status':'accepted','artifacts':{'artifact':digest(root/'artifact')}})
            expected=digest(root/'result.json')
            verify_accepted(root,expected)
            (root/'artifact').write_text('tamper')
            with self.assertRaisesRegex(ValueError,'artifact integrity'): verify_accepted(root,expected)
            (root/'result.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'manifest integrity'): verify_accepted(root,expected)

    def test_print_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir(); (source/'builder.py').write_text('pass')
            params=root/'params.json'; params.write_text('{}'); policy=root/'policy.json'; policy.write_text(json.dumps(POLICY | {'profile':'print'}))
            with self.assertRaisesRegex(ValueError,'PRINT_ACCEPTANCE_UNAVAILABLE'):
                build(source=source,params=params,policy_path=policy,store=root/'store',revision='r0',trusted_reviewed_source=True)


class TranslationTests(unittest.TestCase):
    def test_translation_rejects_local_deformation_and_material_drift(self):
        prior=copy.deepcopy(OBS); prior['parts']['body']['face_indices']=[]
        moved=copy.deepcopy(prior); moved['parts']['body']['world_vertices']=[[.2,0,0],[1.2,0,0]]
        policy=Policy.parse(POLICY | {'changed_parts':['body'],'constraints':[{'kind':'translated','part':'body','data':{'delta':[.2,0,0],'tolerance':.0001}}]})
        self.assertFalse(check(policy,moved,prior))
        moved['parts']['body']['world_vertices'][1][1]=.1
        self.assertEqual(check(policy,moved,prior)[0]['check'],'translated')
        moved['parts']['body']['world_vertices'][1][1]=0
        moved['parts']['body']['material_hash']='changed'
        self.assertTrue(check(policy,moved,prior))


class CentroidTests(unittest.TestCase):
    def test_centroid_position_is_independent_measurement(self):
        policy=Policy.parse(POLICY | {'constraints':[{'kind':'centroid','part':'body','data':{'indices':[0,1],'point':[.5,0,0],'tolerance':.0001}}]})
        self.assertFalse(check(policy,OBS,None))
        changed=copy.deepcopy(OBS); changed['parts']['body']['world_vertices'][1][1]=.1
        self.assertEqual(check(policy,changed,None)[0]['check'],'centroid')
