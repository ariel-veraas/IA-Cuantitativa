"""A real loopback HTTP exchange with a simulated model; no weights or paid API."""
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from iq.app import Application
from iq.config import Config
from iq.providers import post_json
from iq.domain import UserError
from iq.evaluator import validate_answer
from iq.documents import extract


class ModelHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','/forbidden');self.end_headers();return
        self.server.paths.append(self.path)
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.payload=body
        context=json.loads(body['messages'][1]['content'])
        segment=context['document_fragments'][0]
        answer={'status':'does_not_meet','explanation':'Respuesta simulada para verificar el circuito.',
                'evidence':[{'segment_id':segment['id'],'quote':segment['text']}]}
        result={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}],
                'model':'simulated-test-model','usage':{'prompt_tokens':200,'completion_tokens':50}}
        raw=json.dumps(result).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


class LocalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),ModelHandler);self.server.paths=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

    def test_job_calls_loopback_model_and_validates_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp,Config(local_enabled=True,local_url=self.url))
            try:
                doc=app.add_document({'text':'Las urgencias se cobran por separado.'})
                rubric={'name':'Urgencias','criteria':[{'id':'urg','label':'Urgencias incluidas sin cargo','kind':'semantic','weight':100,'required':True}]}
                job=app.submit({'document_id':doc['id'],'rubric':rubric,'mode':'local'})
                for _ in range(100):
                    job=app.store.job(job['id'])
                    if job['status'] in ('completed','failed'):break
                    time.sleep(.02)
                self.assertEqual(job['status'],'completed')
                row=job['result']['rows'][0]
                self.assertEqual(row['status'],'does_not_meet');self.assertEqual(row['method'],'local')
                self.assertTrue(row['review_required']);self.assertEqual(len(row['evidence']),1)
                self.assertEqual(self.server.paths,['/v1/chat/completions'])
                self.assertFalse(self.server.payload['chat_template_kwargs']['enable_thinking'])
                self.assertEqual(job['result']['summary']['decision'],'does_not_meet')
            finally:app.close()

    def test_redirects_are_not_followed(self):
        with self.assertRaises(UserError):post_json(self.url+'/redirect',{})
        self.assertEqual(self.server.paths,[])

    def test_second_application_cannot_recover_live_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=Application(tmp,Config())
            try:
                with self.assertRaises(ValueError):Application(tmp,Config())
            finally:first.close()
            second=Application(tmp,Config());second.close()

    def test_invalid_segment_id_is_pending_not_crash(self):
        doc={**extract('a.txt',b'Texto'),'id':'a'}
        c={'id':'x','label':'x'}
        answer={'status':'meets','explanation':'a','evidence':[{'segment_id':[],'quote':'Texto'}]}
        self.assertEqual(validate_answer(c,doc,doc['segments'],answer,'local')['status'],'needs_review')
