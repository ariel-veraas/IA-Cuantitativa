import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from iq.app import Application
from iq.config import Config
from iq.conversation import calculate,select_skill,validate_response
from iq.domain import UserError
from iq.engine import safe_extract
from iq.documents import extract
from iq.providers import LocalProvider
from iq.vault import Vault


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(self.tmp.name,Config())
    def tearDown(self):self.app.close();self.tmp.cleanup()
    def complete(self,data):
        j=self.app.chat(data)
        for _ in range(200):
            j=self.app.store.job(j['id'])
            if j['status'] in ('completed','failed'):break
            time.sleep(.01)
        self.assertEqual(j['status'],'completed',j.get('error'));return j

    def test_greeting_and_calculator_do_not_call_a_model(self):
        with patch('iq.conversation.LocalProvider.generate',side_effect=AssertionError('model called')):
            hello=self.complete({'message':'Hola!'})
            result=self.complete({'message':'Calculá (1250 + 800) * 1.21'})
        self.assertEqual(hello['result']['provider'],'code')
        self.assertIn('2480.5',result['result']['answer'])

    def test_calculator_cannot_execute_python(self):
        self.assertIsNone(calculate('__import__("os").system("id")'))
        with self.assertRaises(UserError):calculate('2**999999')
        with self.assertRaises(UserError):calculate('1/0')
        self.assertEqual(calculate('0.1+0.2'),'0.1+0.2 = 0.3')

    def test_selected_documents_only_enter_context(self):
        selected=self.app.add_document({'text':'Las urgencias cuestan 50 USD.'})
        self.app.add_document({'text':'OTRO_DOCUMENTO_PRIVADO'})
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        def fake(system,user,schema):
            self.assertNotIn('OTRO_DOCUMENTO_PRIVADO',user)
            s=json.loads(user)['document_fragments'][0]
            return {'answer':'Cuestan 50 USD.','needs_help':False,'evidence':[{'segment_id':s['id'],'quote':s['text']}]},{'usage':{}}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake):
            j=self.complete({'message':'¿Cuánto cuestan las urgencias?','document_ids':[selected['id']]})
        self.assertEqual(j['result']['evidence'][0]['document_id'],selected['id'])

    def test_drafting_without_documents_has_empty_evidence_contract(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        def fake(system,user,schema):
            self.assertEqual(schema['properties']['evidence']['maxItems'],0)
            return {'answer':'Hola, ¿podemos reunirnos mañana?','needs_help':False,'evidence':[]},{}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake):j=self.complete({'message':'Redactá un correo.'})
        self.assertFalse(j['result']['needs_help'])

    def test_capability_version_test_activation_and_rollback(self):
        data={'name':'Revisión','description':'Revisar casos','instructions':'Pedí un número de caso.','example':'Falta un dato','expected':'número de caso'}
        one=self.app.capabilities.save(data)
        with self.assertRaises(UserError):self.app.capabilities.activate(one['id'],1)
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        for version in [one,self.app.capabilities.save({**data,'id':one['id'],'instructions':'Pedí el número de caso antes de continuar.'})]:
            with patch('iq.conversation.LocalProvider.generate',return_value=({'answer':'Necesito el número de caso.','needs_help':False,'evidence':[]},{})):
                j=self.complete({'message':version['example'],'skill_id':version['id'],'skill_version':version['version'],'skill_test':True})
            self.assertTrue(j['result']['test_passed']);self.app.capabilities.activate(one['id'],version['version'])
        self.assertEqual(self.app.capabilities.get(one['id'])['version'],2)
        self.app.capabilities.activate(one['id'],1)
        self.assertEqual(self.app.capabilities.get(one['id'])['version'],1)

    def test_document_comparison_is_deterministic(self):
        a=self.app.add_document({'text':'Entrega: 10 días.'});b=self.app.add_document({'text':'Entrega: 20 días.'})
        with patch('iq.conversation.LocalProvider.generate',side_effect=AssertionError('model called')):
            j=self.complete({'message':'Compará los dos documentos','document_ids':[a['id'],b['id']]})
        self.assertIn('-Entrega: 10',j['result']['answer']);self.assertIn('+Entrega: 20',j['result']['answer'])

    def test_cloud_opt_in_cannot_override_disabled_configuration(self):
        with self.assertRaises(UserError):self.app.chat({'message':'Pregunta','allow_cloud':True})

    def test_deleted_conversation_removes_content(self):
        j=self.complete({'message':'Hola'})
        self.app.delete_conversation(j['payload']['conversation_id'])
        with self.assertRaises(UserError):self.app.store.job(j['id'])

    def test_invalid_evidence_does_not_claim_zero_tokens(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        with patch('iq.conversation.LocalProvider.generate',return_value=({'answer':'Texto','needs_help':False,'evidence':[{'segment_id':'inventado','quote':'falso'}]},{'usage':{'completion_tokens':20}})):
            j=self.complete({'message':'Escribí un texto'})
        self.assertTrue(j['result']['needs_help']);self.assertEqual(j['result']['provider'],'local')
        self.assertEqual(j['result']['model']['usage']['completion_tokens'],20)

    def test_missing_evidence_abstains(self):
        with self.assertRaises(UserError):validate_response({'answer':'Sí','needs_help':False,'evidence':[]},[],True)

    def test_backend_ollama_uses_bounded_context_without_thinking(self):
        seen=[]
        def transport(url,payload,**kwargs):
            seen.append((url,payload));return {'done':True,'done_reason':'stop','message':{'content':'{"status":"needs_review","explanation":"Falta información","evidence":[]}'}}
        LocalProvider(Config(local_enabled=True,local_backend='ollama',local_url='http://127.0.0.1:11435'),transport).evaluate('s','u')
        self.assertFalse(seen[0][1]['think']);self.assertEqual(seen[0][1]['options']['num_ctx'],4096)
        self.assertTrue(seen[0][0].endswith('/api/chat'))


class PackagingTests(unittest.TestCase):
    def test_engine_archive_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../outside.txt','bad')
            with self.assertRaises(UserError):safe_extract(p,Path(tmp)/'unpacked')
            self.assertFalse((Path(tmp)/'outside.txt').exists())

    def test_vault_roundtrip_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            v=Vault(tmp);v.set('FAKE-TEST-KEY');self.assertEqual(v.get(),'FAKE-TEST-KEY')
            if os.name!='nt':self.assertEqual(v.path.stat().st_mode&0o777,0o600)
            v.set('');self.assertEqual(v.get(),'')

    def test_csv_preserves_quoted_fields(self):
        d=extract('a.csv',b'Nombre;Monto\n"Servicio; especial";100\n')
        self.assertIn('Servicio; especial',d['units'][1]['text'])

    def test_xlsx_reads_cached_values_and_warns_about_formulas(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Costos" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Total</t></is></c><c r="B1"><f>10+20</f><v>30</v></c></row></sheetData></worksheet>')
        d=extract('libro.xlsx',buf.getvalue())
        self.assertIn('B1: 30',d['units'][0]['text']);self.assertIn('Costos',d['units'][0]['location']);self.assertEqual(len(d['warnings']),2)
