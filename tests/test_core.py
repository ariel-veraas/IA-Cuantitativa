import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

# run.py puts vendor/ on sys.path before the packaged app ever imports pypdf; tests
# import it directly (to build a synthetic PDF fixture) and otherwise silently skip
# the PDF test instead of exercising the exact reader the shipped app uses.
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'vendor'))
from iq.config import Config, loopback_url, ROOT
from iq.documents import extract, retrieve, _bm25_scores
from iq.domain import UserError, validate_rubric, aggregate, estimate_complexity, needs_external_info
from iq.evaluator import check_rule, validate_answer, markdown_report
from iq.providers import LocalProvider, GeminiProvider
from iq import distill
from iq.skills import SkillRegistry
from iq.store import Store
from iq.app import Application


def document(text):return {**extract('prueba.txt',text.encode()),'id':'doc1'}


class RulesTests(unittest.TestCase):
    def test_demo_does_not_pretend_to_be_ai(self):
        d=document((ROOT/'examples/proveedor.txt').read_text('utf-8'))
        r=validate_rubric(json.loads((ROOT/'examples/rubrica.json').read_text('utf-8')))
        rows=[check_rule(c,d) for c in r['criteria'][:3]]
        self.assertTrue(all(x['status']=='meets' for x in rows))
        self.assertIsNone(check_rule(r['criteria'][3],d))
        summary=aggregate(r['criteria'],rows)
        self.assertEqual(summary['score_min'],70)
        self.assertEqual(summary['score_max'],100)
        self.assertEqual(summary['decision'],'needs_review')

    def test_missing_phrase_is_not_negative_proof(self):
        c={'id':'c','label':'Presencia','kind':'phrase','phrase':'ISO 27001'}
        self.assertEqual(check_rule(c,document('Sin información'))['status'],'needs_review')

    def test_phrase_rule_explicitly_is_literal(self):
        c={'id':'c','label':'Mención','kind':'phrase','phrase':'ISO 27001'}
        row=check_rule(c,document('No contamos con ISO 27001.'))
        self.assertEqual(row['status'],'meets')
        self.assertIn('no su significado',row['explanation'])

    def test_phrase_evidence_contains_actual_match_beyond_1500(self):
        c={'id':'c','label':'Mención','kind':'phrase','phrase':'contrato'}
        row=check_rule(c,document('x'*1600+' contrato'))
        self.assertIn('contrato',row['evidence'][0]['quote'])

    def test_numeric_comparison_conflict_and_units(self):
        c={'id':'c','label':'Entrega','kind':'number_max','field':'Plazo de entrega','unit':'días','maximum':'15'}
        self.assertEqual(check_rule(c,document('Plazo de entrega: 16 días'))['status'],'does_not_meet')
        self.assertEqual(check_rule(c,document('Plazo de entrega: 10 días\nPlazo de entrega: 20 días'))['status'],'needs_review')
        self.assertEqual(check_rule(c,document('Plazo de entrega: 10 semanas'))['status'],'needs_review')
        self.assertEqual(check_rule(c,document('Plazo de entrega: 10 días salvo urgencias'))['status'],'needs_review')

    def test_invalid_rubric_rejected(self):
        c={'id':'a','label':'a','kind':'semantic','weight':1}
        for rows in [[c,c],[{**c,'weight':True}],[{**c,'weight':0}],[]]:
            with self.assertRaises(UserError):validate_rubric({'name':'a','criteria':rows})

    def test_missing_mandatory_cannot_pass(self):
        summary=aggregate([{'id':'a','weight':100,'required':True}],[])
        self.assertEqual(summary['decision'],'needs_review')
        self.assertFalse(summary['complete'])


class ComplexityTests(unittest.TestCase):
    def test_short_factual_requests_stay_fast(self):
        for msg in ('hola','cuanto es 2+2','cual es el plazo de entrega'):
            self.assertFalse(estimate_complexity(msg,document_count=1),msg)

    def test_analytical_or_multi_document_requests_trigger_reasoning(self):
        self.assertTrue(estimate_complexity('cosa cualquiera',document_count=2))
        self.assertTrue(estimate_complexity('Compara estos documentos y explica las diferencias'))
        self.assertTrue(estimate_complexity('x'*500))
        self.assertTrue(estimate_complexity('pregunta uno? pregunta dos?'))

    def test_needs_external_info_only_for_live_or_current_requests(self):
        self.assertFalse(needs_external_info('Cual es el plazo de entrega segun el contrato?'))
        self.assertFalse(needs_external_info('Resumime este documento'))
        self.assertTrue(needs_external_info('Cual es el precio de mercado actual del dolar?'))
        self.assertTrue(needs_external_info('Buscá en la web la última versión de esta norma'))
        self.assertTrue(needs_external_info('Que noticias hay hoy sobre esto'))


class DocumentTests(unittest.TestCase):
    def test_retrieval_budget_preserves_quotes(self):
        d=document('Otros datos.\n\nSoporte nocturno incluido.\n\nInformación adicional.')
        selected=retrieve(d,'soporte nocturno',35)
        self.assertEqual(selected[0]['text'],'Soporte nocturno incluido.')
        self.assertLessEqual(sum(len(x['text']) for x in selected),35)

    def test_unknown_format_and_empty_rejected(self):
        for name,body in [('bad.exe',b'hello'),('blank.txt',b'   '),('bad.txt',b'\xff')]:
            with self.assertRaises(UserError):extract(name,body)

    def test_bm25_matches_whole_words_not_substrings(self):
        # Regression for the old naive-substring ranking, which let a short query term
        # match inside an unrelated longer word (e.g. "cat" inside "categoria").
        d=document('Aca hay una categoria general.\n\nHabria que concatenar los textos.')
        self.assertEqual(_bm25_scores(d['segments'],{'cat'}),[0.0,0.0])

    def test_bm25_ranks_the_segment_with_all_query_terms_first(self):
        d=document('Clima variable en la zona.\n\nEl soporte tecnico incluye guardia nocturna.\n\nSin relacion alguna.')
        selected=retrieve(d,'soporte guardia nocturna',60)
        self.assertEqual(selected[0]['text'],'El soporte tecnico incluye guardia nocturna.')

    def test_embedding_rerank_finds_semantic_match_with_no_shared_words(self):
        class FakeProvider:
            calls=0
            vectors={'emergencia critica que no puede esperar':[1.0,0.0],
                     'Procedimiento de rutina para mantenimiento habitual.':[0.0,1.0],
                     'Este es un caso urgente que requiere atencion inmediata.':[0.95,0.05],
                     'Otro texto neutro sin relacion alguna.':[0.5,0.5]}
            def embed(self,texts):
                FakeProvider.calls+=1;return [self.vectors[t] for t in texts]
        d=document('Procedimiento de rutina para mantenimiento habitual.\n\n'
                    'Este es un caso urgente que requiere atencion inmediata.\n\nOtro texto neutro sin relacion alguna.')
        provider=FakeProvider()
        selected=retrieve(d,'emergencia critica que no puede esperar',60,provider=provider)
        self.assertEqual(selected[0]['text'],'Este es un caso urgente que requiere atencion inmediata.')
        self.assertEqual(FakeProvider.calls,1)

    def test_embedding_rerank_is_skipped_without_a_provider(self):
        d=document('Uno.\n\nDos.\n\nTres.')
        # No provider passed: behavior must be pure BM25, identical to the default path.
        self.assertEqual(retrieve(d,'dos',60),retrieve(d,'dos',60,provider=None))

    def test_docx_tables_and_body_order(self):
        try:from docx import Document
        except ImportError:self.skipTest('Optional DOCX reader not installed')
        doc=Document();doc.add_paragraph('Antes');table=doc.add_table(rows=1,cols=2)
        table.cell(0,0).text='Campo';table.cell(0,1).text='Valor';doc.add_paragraph('Después')
        stream=io.BytesIO();doc.save(stream)
        result=extract('prueba.docx',stream.getvalue())
        self.assertEqual([u['text'] for u in result['units']],['Antes','Campo | Valor','Después'])
        self.assertTrue(result['warnings'])

    def test_pdf_page_reference_and_scanned_page_warning(self):
        try:from pypdf import PdfWriter
        except ImportError:self.skipTest('Optional PDF reader not installed')
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        w=PdfWriter();p=w.add_blank_page(width=300,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 20 260 Td (Entrega: 10 dias) Tj ET')
        p[NameObject('/Contents')]=w._add_object(content);w.add_blank_page(width=300,height=300)
        stream=io.BytesIO();w.write(stream)
        result=extract('prueba.pdf',stream.getvalue())
        self.assertEqual(result['units'][0]['location'],'Página 1')
        self.assertIn('Entrega',result['units'][0]['text']);self.assertIn('Página 2',result['warnings'][0])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.c={'id':'c','label':'Servicio incluido'};self.doc=document('El soporte remoto está incluido.');self.seg=self.doc['segments']

    def test_fabricated_quote_is_rejected(self):
        answer={'status':'meets','explanation':'Sí','evidence':[{'segment_id':'s1','quote':'Servicio 24 horas'}]}
        row=validate_answer(self.c,self.doc,self.seg,answer,'local')
        self.assertEqual(row['status'],'needs_review')

    def test_unknown_segment_cannot_cite_other_documents(self):
        answer={'status':'meets','explanation':'Sí','evidence':[{'segment_id':'other','quote':self.seg[0]['text']}]}
        self.assertEqual(validate_answer(self.c,self.doc,self.seg,answer,'local')['status'],'needs_review')

    def test_valid_quote_still_requires_human_review(self):
        answer={'status':'meets','explanation':'El soporte está incluido','evidence':[{'segment_id':'s1','quote':self.seg[0]['text']}]}
        row=validate_answer(self.c,self.doc,self.seg,answer,'local')
        self.assertEqual(row['status'],'meets');self.assertTrue(row['review_required'])

    def test_invalid_shape_does_not_crash(self):
        for a in [None,[],{'status':'meets','explanation':'sí','evidence':[42]}, {'status':'meets','explanation':'sí','evidence':[]}]:
            self.assertEqual(validate_answer(self.c,self.doc,self.seg,a,'local')['status'],'needs_review')


class ConfigTests(unittest.TestCase):
    def test_reasoning_budget_defaults_and_bounds(self):
        Config().validate()  # default reasoning_max_output_tokens >= max_output_tokens
        with self.assertRaises(ValueError):Config(reasoning_max_output_tokens=100).validate()  # below max_output_tokens
        with self.assertRaises(ValueError):Config(reasoning_max_output_tokens=5000).validate()  # above hard cap
        Config(max_output_tokens=200,reasoning_max_output_tokens=200).validate()  # equal is allowed

    def test_embedding_model_must_be_short_string(self):
        Config(embedding_model='').validate()
        Config(embedding_model='nomic-embed-text').validate()
        with self.assertRaises(ValueError):Config(embedding_model='x'*161).validate()


class DistillTests(unittest.TestCase):
    segments=[{'id':'s1','text':'Parrafo irrelevante.'},{'id':'s2','text':'El plazo de entrega es de 10 dias.'}]

    def test_no_compression_without_local_engine(self):
        self.assertIsNone(distill.compress(LocalProvider(Config(local_enabled=False)),Config(local_enabled=False),'x',self.segments))

    def test_no_compression_without_segments(self):
        self.assertIsNone(distill.compress(LocalProvider(Config(local_enabled=True)),Config(local_enabled=True),'x',[]))

    def test_keeps_only_the_chosen_existing_segments(self):
        def transport(url,payload,**kw):
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
                {'summary':'Se conoce el plazo.','missing':'Nada mas.','key_segment_ids':['s2','no-existe']})}}]}
        cfg=Config(local_enabled=True)
        result=distill.compress(LocalProvider(cfg,transport),cfg,'Cual es el plazo?',self.segments)
        self.assertEqual([s['id'] for s in result['segments']],['s2'])
        self.assertEqual(result['summary'],'Se conoce el plazo.')

    def test_falls_back_to_none_on_malformed_output(self):
        def transport(url,payload,**kw):
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary':'x'})}}]}
        cfg=Config(local_enabled=True)
        self.assertIsNone(distill.compress(LocalProvider(cfg,transport),cfg,'x',self.segments))

    def test_falls_back_to_none_when_local_call_fails(self):
        cfg=Config(local_enabled=True)
        def transport(url,payload,**kw):raise UserError('sin conexion')
        self.assertIsNone(distill.compress(LocalProvider(cfg,transport),cfg,'x',self.segments))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.db')
        self.cfg=Config(cloud_enabled=True,gemini_model='gemini-2.5-flash',input_usd_per_million=1,
            output_usd_per_million=2,monthly_budget_usd=.01,per_job_budget_usd=.005,pricing_confirmed=True)
    def tearDown(self):self.tmp.cleanup()

    def test_local_cannot_use_external_or_redirecting_address(self):
        for url in ['https://example.org','http://example.org','http://127.0.0.1:80/a','http://user:pass@localhost:80']:
            with self.assertRaises(ValueError):loopback_url(url)

    def test_local_schema_contract(self):
        calls=[]
        def transport(url,payload,**kw):
            calls.append((url,payload));return {'choices':[{'finish_reason':'stop','message':{'content':'{"status":"needs_review","explanation":"Falta información","evidence":[]}'}}]}
        answer,meta=LocalProvider(Config(local_enabled=True),transport).evaluate('sys','user')
        self.assertEqual(answer['status'],'needs_review')
        self.assertFalse(calls[0][1]['chat_template_kwargs']['enable_thinking'])
        self.assertEqual(meta['provider'],'local')

    def test_embed_returns_none_without_configured_model(self):
        self.assertIsNone(LocalProvider(Config(local_enabled=True)).embed('texto'))
        self.assertIsNone(LocalProvider(Config(local_enabled=False,embedding_model='m')).embed('texto'))

    def test_embed_batches_ollama_requests_into_one_call(self):
        calls=[]
        def transport(url,payload,**kw):
            calls.append((url,payload));return {'embeddings':[[1.0,0.0],[0.0,1.0]]}
        provider=LocalProvider(Config(local_enabled=True,local_backend='ollama',embedding_model='embed-model'),transport)
        result=provider.embed(['a','b'])
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][1]['input'],['a','b'])
        self.assertEqual(result,[[1.0,0.0],[0.0,1.0]])

    def test_embed_fails_closed_on_malformed_response(self):
        provider=LocalProvider(Config(local_enabled=True,embedding_model='m'),lambda *a,**k:{'unexpected':True})
        self.assertIsNone(provider.embed(['a']))

    def test_disabled_cloud_never_touches_network(self):
        with self.assertRaises(UserError):GeminiProvider(Config(),self.store,lambda *a: self.fail('network')).evaluate('s','u','j','c')

    def test_cloud_count_reserve_settle(self):
        calls=[]
        def transport(url,payload,*args):
            calls.append((url,payload))
            if url.endswith('countTokens'):return {'totalTokens':100}
            return {'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':50},
                'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"status":"needs_review","explanation":"Falta evidencia","evidence":[]}'}]}}]}
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-only'}):
            a,meta=GeminiProvider(self.cfg,self.store,transport).evaluate('sys','user','job','c')
        self.assertEqual(len(calls),2);self.assertIn('systemInstruction',calls[0][1]['generateContentRequest'])
        self.assertEqual(self.store.usage()['accounted_usd'],.0002)
        self.assertEqual(self.store.usage()['unconfirmed_usd'],0)
        self.assertEqual(meta['usage']['promptTokenCount'],100)

    def test_search_disabled_by_default_even_with_cloud_enabled(self):
        with self.assertRaises(UserError):GeminiProvider(self.cfg,self.store,lambda *a:self.fail('network')).search('q','job','c')

    def test_search_returns_grounded_text_and_sources(self):
        cfg=replace(self.cfg,web_search_enabled=True)
        calls=[]
        def transport(url,payload,*args):
            calls.append((url,payload))
            if url.endswith('countTokens'):return {'totalTokens':50}
            return {'usageMetadata':{'promptTokenCount':50,'candidatesTokenCount':40},
                'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'El dolar cotiza a 1000.'}]},
                    'groundingMetadata':{'groundingChunks':[{'web':{'uri':'https://ejemplo.com/dolar','title':'Cotizacion'}}]}}]}
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-only'}):
            text,sources,meta=GeminiProvider(cfg,self.store,transport).search('cotizacion del dolar','job','conversation-search')
        self.assertIn('1000',text)
        self.assertEqual(sources,[{'title':'Cotizacion','uri':'https://ejemplo.com/dolar'}])
        self.assertEqual(meta['provider'],'gemini-search')
        self.assertNotIn('responseSchema',calls[1][1])
        self.assertEqual(calls[1][1]['tools'],[{'google_search':{}}])

    def test_no_retry_on_unknown_paid_outcome(self):
        def transport(url,payload,*args):
            if url.endswith('countTokens'):return {'totalTokens':100}
            raise UserError('Timeout')
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-only'}):
            with self.assertRaises(UserError):GeminiProvider(self.cfg,self.store,transport).evaluate('s','u','j','c')
        self.assertGreater(self.store.usage()['unconfirmed_usd'],0)
        with self.assertRaises(UserError):self.store.reserve('j','c',1,100000,100000)

    def test_budget_atomic_under_concurrency(self):
        def attempt(i):
            try:self.store.reserve(str(i),'c',6000,10000,10000);return True
            except UserError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:accepted=list(pool.map(attempt,range(8)))
        self.assertEqual(sum(accepted),1)

    def test_actual_usage_over_reservation_blocks_future_calls(self):
        id=self.store.reserve('j','c',10,100,100)
        self.store.settle(id,20,{})
        with self.assertRaises(UserError):self.store.reserve('j2','c',10,100,100)


class WorkflowTests(unittest.TestCase):
    def test_completed_job_persists_and_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp,Config())
            try:
                demo=app.demo();job=app.submit({'document_id':demo['document']['id'],'rubric':demo['rubric']})
                for _ in range(100):
                    j=app.store.job(job['id'])
                    if j['status']=='completed':break
                    time.sleep(.02)
                self.assertEqual(j['status'],'completed');self.assertEqual(j['result']['summary']['score_min'],70)
                self.assertEqual(len(j['result']['rows']),4);self.assertEqual(app.store.usage()['calls'],0)
                self.assertIn('Plazo de entrega: 10 días',markdown_report(j))
            finally:app.close()
            store=Store(Path(tmp)/'iq.sqlite3')
            self.assertEqual(store.job(job['id'])['status'],'completed')

    def test_restart_marks_inflight_and_preserves_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db';store=Store(path)
            job=store.create_job({'example':True});store.next_job()
            store.checkpoint(job['id'],{'rows':[{'criterion_id':'a'}],'events':[]})
            store.reserve(job['id'],'b',100,1000,1000)
            recovered=Store(path);j=recovered.job(job['id'])
            self.assertEqual(j['status'],'interrupted');self.assertEqual(len(j['result']['rows']),1)
            self.assertEqual(recovered.usage()['unconfirmed_usd'],.0001)

    def test_cancelled_job_cannot_be_overwritten_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(Path(tmp)/'db');j=s.create_job({});s.cancel(j['id']);s.checkpoint(j['id'],{'rows':[]},'completed')
            self.assertEqual(s.job(j['id'])['status'],'cancelled')


if __name__=='__main__':unittest.main()
