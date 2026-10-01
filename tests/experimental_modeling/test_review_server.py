"""Local review security/state tests use synthetic controller-owned unit fixtures."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from experimental_modeling.contracts import Policy
from experimental_modeling.controller import digest, write_json
from experimental_modeling.requirements import RequirementSet, canonical_hash
from experimental_modeling.verification import make_report
from experimental_modeling.review_server import ReviewProject, LocalReviewServer, Conflict


def fixture(store, revision='r0', status='accepted', parent=None):
    root=store/'accepted'/revision;root.mkdir(parents=True)
    spec={'schema_version':1,'requirements':[]}
    if not (store/'requirements.json').exists():write_json(store/'requirements.json',spec)
    policy={'schema_version':1,'parts':['body'],'changed_parts':[],'constraints':[],'profile':'scene'}
    obs={'parts':{'body':{'world_vertices':[[0,0,0],[1,0,0],[0,1,0]],'triangle_indices':[[0,1,2]],'edge_indices':[[0,1],[1,2],[2,0]],'geometry_hash':'a','transform_hash':'b','material_hash':'c'}}}
    (root/'inspection').mkdir();write_json(root/'inspection/observation.json',obs)
    write_json(root/'requirements.json',spec);write_json(root/'policy.json',policy)
    result={'schema_version':1,'revision':revision,'parent':parent,'parent_result_hash':digest(store/'accepted'/parent/'result.json') if parent else None,'status':status,'jobs':{job:{'exit_code':0} for job in ('author','inspect','roundtrip','reopen')},'provenance_verified':True,
            'requirements_hash':canonical_hash(spec),'policy_hash':digest(root/'policy.json'),'runtime_hash':'unit-fixture','source_files':{},'failures':[]}
    write_json(root/'verification.json',make_report(result,Policy.parse(policy),obs,json.loads((store/'accepted'/parent/'inspection/observation.json').read_text()) if parent else None,RequirementSet.parse(spec)))
    result['artifacts']={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
    write_json(root/'result.json',result)
    if not (store/'last_good.json').exists():write_json(store/'last_good.json',{'revision':revision,'result_hash':digest(root/'result.json')})
    return root


class LocalReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Path(self.tmp.name);self.root=fixture(self.store)
        self.project=ReviewProject(self.store);self.server=LocalReviewServer(self.project)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,method='GET',body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        h={} if headers is None else dict(headers)
        if body is not None:
            h.setdefault('Content-Type','application/json');h.setdefault('Origin',self.server.origin)
            body=json.dumps(body)
        connection.request(method,path,body=body,headers=h);response=connection.getresponse();data=response.read()
        result=(response.status,dict(response.getheaders()),json.loads(data) if data.startswith(b'{') or data.startswith(b'[') else data)
        connection.close();return result
    def payload(self):
        return {'csrf_token':self.project.token,'expected_result_hash':digest(self.root/'result.json'),'notes':'QA review'}
    def test_local_security_boundaries(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        self.assertEqual(self.request('/api/project',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('/api/project',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/project',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        code,headers,data=self.request('/api/project');self.assertEqual(code,200)
        self.assertEqual(headers['Cache-Control'],'no-store');self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin',headers)
        self.assertEqual(self.request('/artifacts/r0/%2e%2e%2fresult.json')[0],409)
        self.assertEqual(self.request('/api/execute','POST',self.payload())[0],404)
    def test_csrf_origin_and_stale_hash_fail_closed(self):
        p=self.payload();p['csrf_token']='wrong'
        self.assertEqual(self.request('/api/revisions/r0/accept','POST',p)[0],403)
        p=self.payload();p['expected_result_hash']='0'*64
        self.assertEqual(self.request('/api/revisions/r0/accept','POST',p)[0],409)
        self.assertEqual(self.request('/api/revisions/r0/accept','POST',self.payload(),{'Origin':'https://evil.example'})[0],403)
        self.assertFalse(list((self.store/'review/acceptances').iterdir()))
    def test_accept_is_persisted_idempotent_and_not_machine_promotion(self):
        before=(self.store/'last_good.json').read_bytes()
        first=self.request('/api/revisions/r0/accept','POST',self.payload());self.assertEqual(first[0],200);self.assertTrue(first[2]['human_accepted'])
        second=self.request('/api/revisions/r0/accept','POST',self.payload());self.assertEqual(first[2],second[2])
        fresh=ReviewProject(self.store);self.assertTrue(fresh.revision('r0')['state']['human_accepted'])
        self.assertEqual((self.store/'last_good.json').read_bytes(),before)
    def test_failed_revision_cannot_be_human_accepted(self):
        failed=fixture(self.store,'bad','rejected')
        payload=self.payload()|{'expected_result_hash':digest(failed/'result.json')}
        self.assertEqual(self.request('/api/revisions/bad/accept','POST',payload)[0],409)
    def test_queue_preserves_exact_intent_without_execution(self):
        prompt='QA: move only the mast\nKeep the body unchanged <script>never execute</script>'
        p={'csrf_token':self.project.token,'expected_result_hash':digest(self.root/'result.json'),'revision_id':'r0','prompt':prompt}
        a=self.request('/api/requests','POST',p);b=self.request('/api/requests','POST',p)
        self.assertEqual(a[0],200);self.assertEqual(a[2],b[2]);self.assertEqual(a[2]['status'],'queued')
        records=ReviewProject(self.store).requests();self.assertEqual(len(records),1);self.assertEqual(records[0]['prompt'],prompt);self.assertEqual(records[0]['execution'],'not_started')
    def test_integrity_tamper_blocks_display_and_accept(self):
        with (self.root/'inspection/observation.json').open('a') as stream:stream.write(' ')
        self.assertEqual(self.request('/api/revisions/r0')[0],409)
        self.assertNotEqual(self.request('/api/revisions/r0/accept','POST',self.payload())[0],200)
    def test_report_cannot_weaken_its_own_required_rows(self):
        path=self.root/'verification.json';report=json.loads(path.read_text());report['requirements']=[];path.write_text(json.dumps(report))
        result=json.loads((self.root/'result.json').read_text());result['artifacts']['verification.json']=digest(path);(self.root/'result.json').write_text(json.dumps(result))
        (self.store/'last_good.json').write_text(json.dumps({'revision':'r0','result_hash':digest(self.root/'result.json')}))
        with self.assertRaisesRegex(ValueError,'does not match'):self.project.revision('r0')
    def test_metadata_symlink_refused(self):
        target=Path(self.tmp.name)/'elsewhere';target.mkdir();directory=self.store/'review/acceptances';directory.rmdir();directory.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):self.project.accept('r0',self.payload())
        self.assertFalse(list(target.iterdir()))

    def test_direct_endpoint_checks_current_pointer_binding(self):
        with (self.root/'result.json').open('a') as stream:stream.write(' ')
        self.assertEqual(self.request('/api/revisions/r0')[0],409)
        self.assertEqual(self.request('/api/revisions/r0/accept','POST',self.payload())[0],400)

    def test_revision_order_uses_parent_links_not_copied_file_times(self):
        import os
        first=fixture(self.store,'r1',parent='r0')
        second=fixture(self.store,'r2',parent='r1')
        failed=fixture(self.store,'bad-body','rejected',parent='r2')
        (self.store/'last_good.json').write_text(json.dumps({'revision':'r2','result_hash':digest(second/'result.json')}))
        for path,stamp in ((self.root,9000),(first,2000),(second,7000),(failed,1000)):
            os.utime(path/'result.json',(stamp,stamp))
        project=self.project.project()
        self.assertEqual([r['id'] for r in project['revisions']],['r0','r1','r2','bad-body'])
        self.assertEqual(project['latest_revision'],'r2')
