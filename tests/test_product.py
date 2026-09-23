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
from iq import distill
from iq import capabilities as capabilities_module
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
        def fake(system,user,schema,**kwargs):
            self.assertNotIn('OTRO_DOCUMENTO_PRIVADO',user)
            s=json.loads(user)['document_fragments'][0]
            return {'answer':'Cuestan 50 USD.','needs_help':False,'evidence':[{'segment_id':s['id'],'quote':s['text']}]},{'usage':{}}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake):
            j=self.complete({'message':'¿Cuánto cuestan las urgencias?','document_ids':[selected['id']]})
        self.assertEqual(j['result']['evidence'][0]['document_id'],selected['id'])

    def test_drafting_without_documents_has_empty_evidence_contract(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        def fake(system,user,schema,**kwargs):
            self.assertEqual(schema['properties']['evidence']['maxItems'],0)
            # Regression for a real failure seen with Qwen3 1.7B: without this line in
            # the system prompt, a weaker model reads an empty document_fragments list
            # as "missing evidence" and abstains even for capabilities that never
            # needed documents in the first place (e.g. drafting, or a plain
            # instruction like "end the message with Gracias").
            self.assertIn('eso no significa que falte información',system)
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

    def test_capability_requires_documents_contract_is_enforced(self):
        data={'name':'Revisión con archivo','description':'Necesita un documento','instructions':'Citá el documento.',
              'example':'Revisá el archivo adjunto','expected':'archivo','requires_documents':True}
        cap=self.app.capabilities.save(data)
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        with patch('iq.conversation.LocalProvider.generate',return_value=({'answer':'El archivo fue revisado.','needs_help':False,'evidence':[]},{})):
            j=self.complete({'message':cap['example'],'skill_id':cap['id'],'skill_version':cap['version'],'skill_test':True})
        self.assertTrue(j['result']['test_passed']);self.app.capabilities.activate(cap['id'],cap['version'])
        with self.assertRaises(UserError):
            self.app.chat({'message':'Probá sin adjuntar nada','skill_id':cap['id']})
        doc=self.app.add_document({'text':'Contenido del archivo.'})
        with patch('iq.conversation.LocalProvider.generate',return_value=({'answer':'ok','needs_help':False,'evidence':[]},{})):
            j2=self.complete({'message':'Probá con un archivo adjunto','skill_id':cap['id'],'document_ids':[doc['id']]})
        self.assertEqual(j2['result']['provider'],'local')

    def test_reconsiders_locally_with_wider_context_before_giving_up(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        # 20 similarly-irrelevant paragraphs, long enough that the default 10,000-char
        # budget cannot fit all of them but the widened retry budget (<=20,000) can —
        # so a second, wider local look genuinely has more material to work with.
        paragraphs=[('Parrafo relleno numero %d de contenido generico sin relacion. '%i)*15 for i in range(20)]
        doc=self.app.add_document({'text':'\n\n'.join(paragraphs)})
        calls=[]
        def fake(system,user,schema,**kwargs):
            calls.append(len(json.loads(user)['document_fragments']))
            return {'answer':'no hay datos suficientes','needs_help':True,'evidence':[]},{}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake):
            j=self.complete({'message':'dato importante que no esta en ningun parrafo','document_ids':[doc['id']]})
        self.assertEqual(len(calls),2)
        self.assertGreater(calls[1],calls[0])
        self.assertTrue(j['result']['reconsidered'])

    def test_no_reconsideration_when_nothing_more_is_available(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        doc=self.app.add_document({'text':'Un solo parrafo corto.'})
        calls=[]
        def fake(system,user,schema,**kwargs):
            calls.append(1)
            return {'answer':'no se','needs_help':True,'evidence':[]},{}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake):
            j=self.complete({'message':'pregunta cualquiera','document_ids':[doc['id']]})
        self.assertEqual(len(calls),1)
        self.assertFalse(j['result']['reconsidered'])

    def test_web_search_disabled_by_default_even_for_current_info_questions(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        self.app.configure_cloud({'cloud_enabled':True,'gemini_model':'gemini-2.5-flash-lite',
            'input_usd_per_million':1,'output_usd_per_million':1,'monthly_budget_usd':10,'per_job_budget_usd':5,
            'pricing_confirmed':True,'key':'test-only-key'})
        with patch('iq.conversation.LocalProvider.generate',
                   return_value=({'answer':'no se','needs_help':True,'evidence':[]},{})), \
             patch('iq.conversation.GeminiProvider.search',side_effect=AssertionError('search called')), \
             patch('iq.conversation.GeminiProvider.generate',
                   return_value=({'answer':'Escalado sin busqueda web','needs_help':False,'evidence':[]},{'usage':{}})):
            j=self.complete({'message':'Cual es el precio de mercado actual del dolar?','allow_cloud':True})
        self.assertFalse(j['result']['needs_help'])
        self.assertEqual(j['result']['answer'],'Escalado sin busqueda web')

    def test_web_search_result_is_reconsidered_locally_before_answering(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        self.app.configure_cloud({'cloud_enabled':True,'web_search_enabled':True,'gemini_model':'gemini-2.5-flash-lite',
            'input_usd_per_million':1,'output_usd_per_million':1,'monthly_budget_usd':10,'per_job_budget_usd':5,
            'pricing_confirmed':True,'key':'test-only-key'})
        calls=[]
        def fake_local(system,user,schema,**kwargs):
            calls.append(system)
            if 'web_search_result' in user:
                ctx=json.loads(user)
                self.assertIn('1000 pesos',ctx['web_search_result'])
                return {'answer':'Segun la busqueda web, cotiza a 1000 pesos.','needs_help':False,'evidence':[]},{}
            return {'answer':'no se','needs_help':True,'evidence':[]},{}
        def fake_search(query,job_id,cid,note=''):
            return 'El dolar cotiza a 1000 pesos hoy.',[{'title':'Fuente','uri':'https://ejemplo.com'}],{'provider':'gemini-search'}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake_local), \
             patch('iq.conversation.GeminiProvider.search',side_effect=fake_search):
            j=self.complete({'message':'Cual es el precio de mercado actual del dolar?','allow_cloud':True})
        self.assertFalse(j['result']['needs_help'])
        self.assertTrue(j['result']['web_search_used'])
        self.assertEqual(j['result']['search_sources'],[{'title':'Fuente','uri':'https://ejemplo.com'}])
        self.assertIn('1000 pesos',j['result']['answer'])

    def test_cloud_escalation_sends_compressed_context_not_everything(self):
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        self.app.configure_cloud({'cloud_enabled':True,'gemini_model':'gemini-2.5-flash-lite',
            'input_usd_per_million':1,'output_usd_per_million':1,'monthly_budget_usd':10,'per_job_budget_usd':5,
            'pricing_confirmed':True,'key':'test-only-key'})
        doc=self.app.add_document({'text':'Parrafo irrelevante uno que no aporta nada.\n\n'
            'El plazo de entrega es de 10 dias.\n\nParrafo irrelevante dos, tampoco aporta nada util aca.'})

        def fake_local(system,user,schema,**kwargs):
            if system==distill.SYSTEM:
                ctx=json.loads(user)
                keep=[f['id'] for f in ctx['document_fragments'] if 'plazo' in f['text'].lower()]
                return {'summary':'Se sabe el plazo.','missing':'Nada mas.','key_segment_ids':keep},{}
            return {'answer':'no se','needs_help':True,'evidence':[]},{}

        captured={}
        def fake_gemini(system,user,job_id,cid,schema):
            captured['user']=user
            ctx=json.loads(user)
            first=ctx['document_fragments'][0]
            return {'answer':'10 dias','needs_help':False,'evidence':[{'segment_id':first['id'],'quote':first['text']}]},{'usage':{}}

        with patch('iq.conversation.LocalProvider.generate',side_effect=fake_local), \
             patch('iq.conversation.GeminiProvider.generate',side_effect=fake_gemini):
            j=self.complete({'message':'Cual es el plazo de entrega?','document_ids':[doc['id']],'allow_cloud':True})
        self.assertEqual(j['result']['provider'],'gemini');self.assertFalse(j['result']['needs_help'])
        ctx=json.loads(captured['user'])
        self.assertEqual(len(ctx['document_fragments']),1)
        self.assertIn('plazo',ctx['document_fragments'][0]['text'].lower())
        self.assertIn('local_context_brief',ctx)

    def test_capability_example_validation(self):
        data={'name':'Revisión','description':'x','instructions':'x','example':'x','expected':'x'}
        cap=self.app.capabilities.save(data)
        with self.assertRaises(UserError):self.app.capabilities.add_example(cap['id'],'pedido','respuesta','maybe')
        with self.assertRaises(UserError):self.app.capabilities.add_example(cap['id'],'pedido','respuesta','bad')
        ok=self.app.capabilities.add_example(cap['id'],'pedido','respuesta','bad','la respuesta correcta era otra')
        self.assertIn('id',ok)
        self.app.capabilities.add_example(cap['id'],'otro pedido','otra respuesta','good')
        self.assertEqual(len(self.app.capabilities.examples(cap['id'])),2)

    def test_improvement_requires_enough_examples_with_a_correction(self):
        data={'name':'Revisión','description':'x','instructions':'x','example':'x','expected':'x'}
        cap=self.app.capabilities.save(data)
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        with self.assertRaises(UserError):self.app.improve_capability({'capability_id':cap['id']})
        self.app.capabilities.add_example(cap['id'],'a','x','good')
        self.app.capabilities.add_example(cap['id'],'b','x','good')
        self.app.capabilities.add_example(cap['id'],'c','x','good')
        with self.assertRaises(UserError):self.app.improve_capability({'capability_id':cap['id']})  # no correction logged

    def test_capability_improves_from_logged_corrections_and_still_needs_a_pass(self):
        data={'name':'Firma de correos','description':'Redacta el cierre de un correo',
              'instructions':'Cerrá el correo con "Saludos".','example':'Escribime el cierre de un correo','expected':'Saludos'}
        cap=self.app.capabilities.save(data)
        self.app.configure_local({'url':'http://127.0.0.1:8080','model':'test','enabled':True})
        with patch('iq.conversation.LocalProvider.generate',
                   return_value=({'answer':'Saludos','needs_help':False,'evidence':[]},{})):
            j=self.complete({'message':cap['example'],'skill_id':cap['id'],'skill_version':cap['version'],'skill_test':True})
        self.assertTrue(j['result']['test_passed']);self.app.capabilities.activate(cap['id'],cap['version'])
        self.app.capabilities.add_example(cap['id'],'Escribime el cierre','Chau','bad','Tiene que terminar con "Saludos cordiales"')
        self.app.capabilities.add_example(cap['id'],'Otro cierre','Nos vemos','bad','Tiene que terminar con "Saludos cordiales"')
        self.app.capabilities.add_example(cap['id'],'Cierre formal','Saludos','good')
        def fake_improve(system,user,schema,**kwargs):
            self.assertEqual(system,capabilities_module.IMPROVE_SYSTEM)
            ctx=json.loads(user)
            self.assertEqual(len(ctx['ejemplos']),3)
            return {'instructions':'Cerrá siempre el correo con "Saludos cordiales".','summary':'Se corrigió el cierre exacto pedido.'},{}
        with patch('iq.conversation.LocalProvider.generate',side_effect=fake_improve):
            improved=self.app.improve_capability({'capability_id':cap['id']})
        self.assertEqual(improved['version'],cap['version']+1)
        self.assertIn('Saludos cordiales',improved['instructions'])
        self.assertFalse(improved['active'])
        with self.assertRaises(UserError):self.app.capabilities.activate(cap['id'],improved['version'])  # not tested yet

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
