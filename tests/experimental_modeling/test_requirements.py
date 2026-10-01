import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from experimental_modeling.requirements import RequirementSet, evaluate, point_triangle_distance
from experimental_modeling.controller import build
from experimental_modeling.review_server import ReviewProject

PART={'world_vertices':[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],'triangle_indices':[[0,1,2],[0,2,3]],
      'edge_indices':[[0,1],[1,2],[2,3],[3,0],[0,2]],'material_hash':'two-material-palette',
      'triangle_material_indices':[0,0],'triangle_world_normals':[[[0,0,1]]*3,[[0,0,1]]*3]}
OBS={'parts':{'body':PART}}
ALL=[[None,None],[None,None],[None,None]]


def spec(kind,params,phase='always',hard=True):
    return {'schema_version':1,'requirements':[{'id':'test-rule','title':'Reviewed requirement','kind':kind,'hard':hard,'phase':phase,'params':params}]}


class RequirementTests(unittest.TestCase):
    def test_strict_version_and_definitions(self):
        for bad in ({'schema_version':2,'requirements':[]},{'schema_version':True,'requirements':[]},spec('python',{}),spec('manual_review',{'instruction':'x'})|{'extra':1}):
            with self.assertRaises(ValueError):RequirementSet.parse(bad)
    def test_connected_path_and_disconnected_negative(self):
        definition=spec('connected_path',{'part':'body','region':ALL,'from':[[None,.1],[None,None],[None,None]],'to':[[.9,None],[None,None],[None,None]]})
        self.assertTrue(evaluate(definition,OBS,None)['requirements_satisfied'])
        changed=copy.deepcopy(OBS);changed['parts']['body']['edge_indices']=[[1,2],[3,0]]
        self.assertEqual(evaluate(definition,changed,None)['requirements'][0]['status'],'fail')
    def test_clearance_crossing_and_clear_positive(self):
        parameters={'parts':['body'],'points':[{'point':[.2,.2,-1]},{'point':[.2,.2,1]}],'samples_per_segment':2,'min_clearance':.1,'epsilon':1e-6}
        self.assertEqual(evaluate(spec('clearance_path',parameters),OBS,None)['requirements'][0]['status'],'fail')
        parameters['points']=[{'point':[2,2,-1]},{'point':[2,2,1]}]
        self.assertTrue(evaluate(spec('clearance_path',parameters),OBS,None)['requirements_satisfied'])
    def test_preserved_region_rejects_winding_assignment_and_normal_mutations(self):
        definition=spec('preserved_region',{'part':'body','region':ALL,'tolerance':1e-6},'revision')
        self.assertTrue(evaluate(definition,OBS,OBS)['requirements_satisfied'])
        for change in ('winding','assignment','normal','position'):
            candidate=copy.deepcopy(OBS);part=candidate['parts']['body']
            if change=='winding':part['triangle_indices'][0]=[0,2,1]
            if change=='assignment':part['triangle_material_indices'][0]=1
            if change=='normal':part['triangle_world_normals'][0][0]=[0,1,0]
            if change=='position':part['world_vertices'][0][2]=.1
            with self.subTest(change=change):self.assertEqual(evaluate(definition,candidate,OBS)['requirements'][0]['status'],'fail')
    def test_missing_coverage_is_unknown_not_pass(self):
        definition=spec('preserved_region',{'part':'missing','region':ALL,'tolerance':1e-6},'revision')
        report=evaluate(definition,OBS,OBS)
        self.assertEqual(report['requirements'][0]['status'],'unknown');self.assertFalse(report['requirements_satisfied'])
        initial=evaluate(definition,OBS,None);self.assertEqual(initial['requirements'][0]['status'],'unknown');self.assertFalse(initial['requirements'][0]['applicable'])
        self.assertNotIn('machine_verified',initial)
    def test_degenerate_triangle_distance_uses_segments_and_points(self):
        self.assertAlmostEqual(point_triangle_distance((.5,1,0),(0,0,0),(1,0,0),(2,0,0)),1)
        self.assertAlmostEqual(point_triangle_distance((0,0,2),(0,0,0),(0,0,0),(0,0,0)),2)

    def test_missing_revision_baseline_is_not_mislabeled_non_applicable(self):
        definition=spec('preserved_region',{'part':'body','region':ALL,'tolerance':1e-6},'revision')
        report=evaluate(definition,OBS,None,is_revision=True)
        self.assertTrue(report['requirements'][0]['applicable'])
        self.assertEqual(report['requirements'][0]['status'],'unknown')
        self.assertFalse(report['requirements_satisfied'])

    def test_preserved_ray_negative(self):
        definition=spec('preserved_rays',{'part':'body','rays':[{'origin':[.2,.2,1],'direction':[0,0,-1],'max_distance':2}],'tolerance':1e-6},'revision')
        self.assertTrue(evaluate(definition,OBS,OBS)['requirements_satisfied'])
        changed=copy.deepcopy(OBS)
        for vertex in changed['parts']['body']['world_vertices']:vertex[2]=.1
        self.assertEqual(evaluate(definition,changed,OBS)['requirements'][0]['status'],'fail')


class FailureEvidenceTests(unittest.TestCase):
    def setup_files(self,root):
        source=root/'source';source.mkdir();(source/'builder.py').write_text('pass')
        params=root/'params.json';params.write_text('{}');policy=root/'policy.json'
        policy.write_text(json.dumps({'schema_version':1,'parts':['body'],'changed_parts':[],'constraints':[],'profile':'scene'}))
        return source,params,policy
    def run_build(self,root,revision='r0',requirements=None):
        source,params,policy=self.setup_files(root)
        return build(source=source,params=params,policy_path=policy,store=root/'store',revision=revision,requirements_path=requirements,trusted_reviewed_source=True,blender=sys.executable)
    def test_malformed_observation_keeps_inspectable_unknown_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def fake_job(command,cwd,log,**kwargs):
                if cwd.name=='authored':(cwd/'scene.blend').write_bytes(b'unit fixture only')
                if cwd.name=='inspection':(cwd/'observation.json').write_text('{invalid')
                return {'exit_code':0}
            with patch('experimental_modeling.controller.run_job',side_effect=fake_job):result=self.run_build(root)
            self.assertEqual(result['status'],'needs_review')
            viewed=ReviewProject(root/'store').revision('r0')
            self.assertFalse(viewed['report']['machine_verified']);self.assertIsNone(viewed['observation'])
            self.assertEqual(next(r for r in viewed['report']['requirements'] if r['id']=='pipeline-inspect')['status'],'unknown')
    def test_unsafe_retained_output_downgrade_keeps_report_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def bad_job(command,cwd,log,**kwargs):(cwd/'unsafe').symlink_to(root/'params.json');return {'exit_code':0}
            with patch('experimental_modeling.controller.run_job',side_effect=bad_job):result=self.run_build(root)
            self.assertEqual(result['status'],'needs_review');self.assertFalse(ReviewProject(root/'store').revision('r0')['report']['machine_verified'])
    def test_first_explicit_rules_lock_cannot_be_weakened_or_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,params,policy=self.setup_files(root)
            rules=root/'rules.json';definition=spec('manual_review',{'instruction':'Human visual review'},hard=True);rules.write_text(json.dumps(definition))
            def attempt(revision,path):
                return build(source=source,params=params,policy_path=policy,store=root/'store',revision=revision,requirements_path=path,trusted_reviewed_source=True,blender=sys.executable)
            with patch('experimental_modeling.controller.run_job',side_effect=RuntimeError('fixture early failure')):
                attempt('default',None);self.assertFalse((root/'store/requirements.json').exists())
                attempt('explicit',rules);attempt('omitted',None)
            self.assertEqual(json.loads((root/'store/attempts/omitted/requirements.json').read_text()),definition)
            rules.write_text(json.dumps({'schema_version':1,'requirements':[]}))
            with self.assertRaisesRegex(ValueError,'locked'):attempt('weakened',rules)
            self.assertFalse((root/'store/attempts/weakened').exists())
            (root/'store/requirements.json').unlink()
            with patch('experimental_modeling.controller.run_job',side_effect=AssertionError('must not execute')):
                with self.assertRaisesRegex(ValueError,'requirements are missing'):attempt('removed',None)
                with self.assertRaisesRegex(ValueError,'requirements are missing'):attempt('reintroduced',rules)
            self.assertFalse((root/'store/requirements.json').exists())
    def test_source_snapshot_failure_still_has_unknown_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,params,policy=self.setup_files(root);(source/'unsupported.exe').write_text('x')
            result=build(source=source,params=params,policy_path=policy,store=root/'store',revision='invalid',trusted_reviewed_source=True,blender=sys.executable)
            self.assertEqual(result['status'],'needs_review');self.assertFalse(ReviewProject(root/'store').revision('invalid')['report']['machine_verified'])
