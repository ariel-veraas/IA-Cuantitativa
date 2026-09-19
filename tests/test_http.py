import json
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from iq.server import create_server
from iq.config import Config


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.server=create_server(0,self.tmp.name,Config())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.token=self.request('/api/session')[1]['token']
    def tearDown(self):
        self.server.shutdown();self.server.app.close();self.server.server_close();self.tmp.cleanup()

    def request(self,path,payload=None,headers=None,auth=True):
        h={'Content-Type':'application/json'}
        if auth and hasattr(self,'token'):h['X-IQ-Session']=self.token
        h.update(headers or {})
        req=Request(self.base+path,data=json.dumps(payload).encode() if payload is not None else None,headers=h)
        try:response=urlopen(req,timeout=5)
        except HTTPError as e:response=e
        with response:
            raw=response.read()
            result=json.loads(raw) if 'application/json' in response.headers.get('Content-Type','') else raw
            return response.status,result

    def test_ui_and_demo_end_to_end(self):
        status,html=self.request('/evaluate');self.assertEqual(status,200);self.assertIn(b'Revis',html)
        _,demo=self.request('/api/demo',{})
        code,job=self.request('/api/jobs',{'document_id':demo['document']['id'],'rubric':demo['rubric']})
        self.assertEqual(code,201)
        for _ in range(50):
            _,state=self.request('/api/state');j=next(x for x in state['jobs'] if x['id']==job['id'])
            if j['status']=='completed':break
            time.sleep(.02)
        self.assertEqual(j['result']['summary']['score_min'],70)
        status,report=self.request(f'/api/jobs/{job["id"]}/export')
        self.assertEqual(status,200);self.assertIn(b'Fuente:',report)

    def test_csrf_origin_and_host_rejected(self):
        self.assertEqual(self.request('/api/demo',{},auth=False)[0],403)
        self.assertEqual(self.request('/api/demo',{},headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/session',headers={'Host':'evil.example'})[0],403)

    def test_cloud_cannot_be_enabled_by_job_payload(self):
        _,d=self.request('/api/demo',{})
        code,_=self.request('/api/jobs',{'document_id':d['document']['id'],'rubric':d['rubric'],'allow_cloud':True})
        self.assertEqual(code,400)

    def test_user_text_is_not_inserted_as_html(self):
        code,d=self.request('/api/documents',{'text':'<script>alert(1)</script> Propuesta'})
        self.assertEqual(code,201)
        code,returned=self.request('/api/documents/'+d['id'])
        self.assertEqual(returned['units'][0]['text'],'<script>alert(1)</script> Propuesta')
        # Browser test separately asserts no execution in DOM.

    def test_local_url_validation(self):
        code,_=self.request('/api/settings/local',{'url':'https://external.example','model':'test','enabled':True})
        self.assertEqual(code,400)


if __name__=='__main__':unittest.main()
