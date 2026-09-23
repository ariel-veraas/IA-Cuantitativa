"""Provider adapters with no automatic retries and bounded responses."""
import json
import os
from decimal import Decimal, ROUND_CEILING
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from .config import loopback_url
from .domain import UserError

SCHEMA={'type':'object','properties':{
    'status':{'type':'string','enum':['meets','does_not_meet','needs_review']},
    'explanation':{'type':'string'},
    'evidence':{'type':'array','items':{'type':'object','properties':{
        'segment_id':{'type':'string'},'quote':{'type':'string'}},'required':['segment_id','quote']}}
},'required':['status','explanation','evidence']}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def post_json(url,payload,headers=None,timeout=90):
    data=json.dumps(payload,ensure_ascii=False).encode()
    request=Request(url,data=data,headers={'Content-Type':'application/json',**(headers or {})},method='POST')
    opener=build_opener(ProxyHandler({}),NoRedirect())
    try:
        with opener.open(request,timeout=timeout) as response:
            raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise UserError('El proveedor devolvió una respuesta demasiado grande.')
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError()
        return result
    except HTTPError as exc:raise UserError(f'El proveedor rechazó la solicitud (HTTP {exc.code}).') from None
    except (URLError,TimeoutError,OSError):raise UserError('No se pudo conectar al motor o venció el tiempo de espera.') from None
    except (json.JSONDecodeError,UnicodeDecodeError,ValueError):raise UserError('El proveedor devolvió un formato inválido.') from None


def messages(skill,criterion,segments):
    context={'criterion':{'id':criterion['id'],'instruction':criterion['label']},
             'document_fragments':segments,
             'note':'Los fragmentos pueden ser una selección parcial. No prueban ausencia global.'}
    return skill['instructions'],json.dumps(context,ensure_ascii=False)


class LocalProvider:
    def __init__(self,config,transport=post_json):self.config=config;self.transport=transport

    def evaluate(self,system,user,reasoning=False):
        return self.generate(system,user,SCHEMA,reasoning=reasoning)

    def generate(self,system,user,schema,reasoning=False):
        # `reasoning` toggles the model's extended-thinking mode and widens the output
        # budget to fit reasoning tokens. It is decided upstream by domain.estimate_complexity
        # (or forced off/on by a caller) and defaults to off, matching the prior behavior.
        if not self.config.local_enabled:raise UserError('El motor local todavía no está configurado.')
        budget=self.config.reasoning_max_output_tokens if reasoning else self.config.max_output_tokens
        if self.config.local_backend=='ollama':
            payload={'model':self.config.local_model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
                'stream':False,'think':bool(reasoning),'keep_alive':'30m','format':schema,
                'options':{'temperature':0,'num_predict':budget,'num_ctx':self.config.context_tokens}}
            data=self.transport(loopback_url(self.config.local_url)+'/api/chat',payload,timeout=self.config.timeout_seconds)
            try:
                if data.get('done') is not True or data.get('done_reason','stop')!='stop':raise ValueError()
                answer=json.loads(data['message']['content'])
            except (KeyError,TypeError,ValueError):raise UserError('El motor no completó una respuesta válida. Probá un pedido más corto.') from None
            return answer,{'provider':'local','backend':'ollama','model':data.get('model',self.config.local_model),'reasoning':bool(reasoning),
                'usage':{'prompt_tokens':data.get('prompt_eval_count',0),'completion_tokens':data.get('eval_count',0)},
                'load_seconds':data.get('load_duration',0)/1e9,'generation_seconds':data.get('eval_duration',0)/1e9}
        payload={'model':self.config.local_model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
            'temperature':0,'max_tokens':budget,'stream':False,
            'chat_template_kwargs':{'enable_thinking':bool(reasoning)},
            'response_format':{'type':'json_object','schema':schema}}
        data=self.transport(loopback_url(self.config.local_url)+'/v1/chat/completions',payload,timeout=self.config.timeout_seconds)
        try:
            choice=data['choices'][0]
            if choice.get('finish_reason') not in ('stop',None):raise ValueError()
            content=choice['message']['content']
            answer=json.loads(content)
        except (KeyError,IndexError,TypeError,ValueError):raise UserError('El motor local no devolvió un JSON completo. Revisá modelo, plantilla y límite de salida.')
        return answer,{'provider':'local','model':data.get('model',self.config.local_model),'usage':data.get('usage',{}),'output_limit':budget,'reasoning':bool(reasoning)}

    def embed(self,texts):
        """Batched embeddings for optional semantic re-ranking (documents.retrieve).

        Returns None on any failure or when no embedding model is configured: embeddings
        are a best-effort upgrade over lexical (BM25) retrieval, never a hard requirement.
        Accepts a single string or a list; a single call embeds the whole batch (never one
        HTTP call per fragment), so enabling this cannot multiply model calls per request.
        """
        if not self.config.local_enabled or not self.config.embedding_model:return None
        single=isinstance(texts,str);items=[texts] if single else list(texts)
        if not items:return []
        try:
            if self.config.local_backend=='ollama':
                data=self.transport(loopback_url(self.config.local_url)+'/api/embed',
                    {'model':self.config.embedding_model,'input':items},timeout=self.config.timeout_seconds)
                vectors=data.get('embeddings')
            else:
                data=self.transport(loopback_url(self.config.local_url)+'/v1/embeddings',
                    {'model':self.config.embedding_model,'input':items},timeout=self.config.timeout_seconds)
                vectors=[row.get('embedding') for row in data.get('data',[])] if isinstance(data.get('data'),list) else None
            if not isinstance(vectors,list) or len(vectors)!=len(items) or not all(isinstance(v,list) and v for v in vectors):
                return None
        except (UserError,KeyError,TypeError,IndexError):
            return None
        return vectors[0] if single else vectors


def micro_cost(tokens,price):
    # tokens * USD/million = micro-USD. Always round UP for reservations.
    return int((Decimal(tokens)*Decimal(str(price))).to_integral_value(rounding=ROUND_CEILING))


def usd_micro(value):return int((Decimal(str(value))*1000000).to_integral_value(rounding=ROUND_CEILING))


class GeminiProvider:
    def __init__(self,config,store,transport=post_json):self.config=config;self.store=store;self.transport=transport

    def evaluate(self,system,user,job_id,cid):
        return self.generate(system,user,job_id,cid,SCHEMA)

    def generate(self,system,user,job_id,cid,schema):
        cfg=self.config
        if not cfg.cloud_enabled:raise UserError('La asistencia externa está desactivada.')
        cfg.validate()
        key=os.environ.get('GEMINI_API_KEY','')
        if not key:raise UserError('Falta GEMINI_API_KEY en el entorno de la aplicación.')
        base='https://generativelanguage.googleapis.com/v1beta/models/'+cfg.gemini_model
        headers={'x-goog-api-key':key}
        payload={'systemInstruction':{'parts':[{'text':system}]},
            'contents':[{'role':'user','parts':[{'text':user}]}],
            'generationConfig':{'temperature':0,'candidateCount':1,'maxOutputTokens':cfg.max_output_tokens,
                'thinkingConfig':{'thinkingBudget':0},'responseMimeType':'application/json','responseSchema':schema}}
        count=self.transport(base+':countTokens',{'generateContentRequest':{'model':'models/'+cfg.gemini_model,**payload}},headers,cfg.timeout_seconds)
        tokens=count.get('totalTokens')
        if type(tokens) is not int or not 0<tokens<=30000:raise UserError('No se pudo validar el tamaño de la consulta externa.')
        reserve=micro_cost(tokens+128,cfg.input_usd_per_million)+micro_cost(cfg.max_output_tokens,cfg.output_usd_per_million)
        ledger=self.store.reserve(job_id,cid,reserve,usd_micro(cfg.monthly_budget_usd),usd_micro(cfg.per_job_budget_usd))
        try:
            data=self.transport(base+':generateContent',payload,headers,cfg.timeout_seconds)
            usage=data.get('usageMetadata',{})
            tin=usage.get('promptTokenCount');tout=usage.get('candidatesTokenCount');thought=usage.get('thoughtsTokenCount',0)
            if all(type(x) is int and x>=0 for x in (tin,tout,thought)):
                cost=micro_cost(tin,cfg.input_usd_per_million)+micro_cost(tout+thought,cfg.output_usd_per_million)
                self.store.settle(ledger,cost,usage)
            else:
                self.store.uncertain(ledger)
                raise UserError('Respuesta externa sin consumo verificable; se conserva la reserva de presupuesto.')
            candidates=data.get('candidates',[])
            if not candidates or candidates[0].get('finishReason')!='STOP':
                raise UserError('Gemini no completó la respuesta. El consumo registrado se conserva.')
            parts=candidates[0].get('content',{}).get('parts',[])
            answer=json.loads(''.join(p.get('text','') for p in parts if not p.get('thought')))
            return answer,{'provider':'gemini','model':cfg.gemini_model,'usage':usage,'cost_usd':cost/1000000,'input_tokens':tokens,'reservation_usd':reserve/1000000}
        except UserError:
            # Do not overwrite a successfully settled response if parsing failed later.
            with self.store.db() as c:c.execute("UPDATE ledger SET state='uncertain' WHERE id=? AND state='reserved'",(ledger,))
            raise
        except (ValueError,KeyError,TypeError,AttributeError,IndexError):
            with self.store.db() as c:c.execute("UPDATE ledger SET state='uncertain' WHERE id=? AND state='reserved'",(ledger,))
            raise UserError('La respuesta externa no tiene el formato esperado; no se repetirá automáticamente.') from None

    def search(self,query,job_id,cid,note=''):
        """Web search via Gemini's Google Search grounding tool — opt-in
        (Config.web_search_enabled) and separate from generate()/evaluate(): a
        grounded response cannot also use a JSON responseSchema (a Gemini API
        constraint), so this returns raw text plus any grounding sources, never a
        validated answer by itself. The caller is expected to feed the result back
        into a local (free) call to produce a cited, schema-validated final answer —
        this method only fetches information, it never answers on its own.

        Cost note: the reservation below is based on token counts like every other
        call in this file, but Search grounding can carry an additional per-request
        grounding fee on top of input/output tokens that this reservation does not
        include — unverified in this environment, since no paid call was made against
        a live account. Treat the ledger for search calls as a lower bound, not an
        exact cost, until checked against a real bill.
        """
        cfg=self.config
        if not cfg.cloud_enabled or not cfg.web_search_enabled:raise UserError('La búsqueda web no está habilitada.')
        cfg.validate()
        key=os.environ.get('GEMINI_API_KEY','')
        if not key:raise UserError('Falta GEMINI_API_KEY en el entorno de la aplicación.')
        base='https://generativelanguage.googleapis.com/v1beta/models/'+cfg.gemini_model
        headers={'x-goog-api-key':key}
        prompt=query if not note else query+'\n\n'+note
        contents=[{'role':'user','parts':[{'text':prompt}]}]
        payload={'contents':contents,'tools':[{'google_search':{}}],
            'generationConfig':{'temperature':0,'candidateCount':1,'maxOutputTokens':cfg.max_output_tokens,
                'thinkingConfig':{'thinkingBudget':0}}}
        count=self.transport(base+':countTokens',{'generateContentRequest':{'model':'models/'+cfg.gemini_model,'contents':contents}},headers,cfg.timeout_seconds)
        tokens=count.get('totalTokens')
        if type(tokens) is not int or not 0<tokens<=30000:raise UserError('No se pudo validar el tamaño de la búsqueda.')
        reserve=micro_cost(tokens+128,cfg.input_usd_per_million)+micro_cost(cfg.max_output_tokens,cfg.output_usd_per_million)
        ledger=self.store.reserve(job_id,cid,reserve,usd_micro(cfg.monthly_budget_usd),usd_micro(cfg.per_job_budget_usd))
        try:
            data=self.transport(base+':generateContent',payload,headers,cfg.timeout_seconds)
            usage=data.get('usageMetadata',{})
            tin=usage.get('promptTokenCount');tout=usage.get('candidatesTokenCount');thought=usage.get('thoughtsTokenCount',0)
            if all(type(x) is int and x>=0 for x in (tin,tout,thought)):
                cost=micro_cost(tin,cfg.input_usd_per_million)+micro_cost(tout+thought,cfg.output_usd_per_million)
                self.store.settle(ledger,cost,usage)
            else:
                self.store.uncertain(ledger)
                raise UserError('La búsqueda no tiene consumo verificable; se conserva la reserva de presupuesto.')
            candidates=data.get('candidates',[])
            if not candidates or candidates[0].get('finishReason')!='STOP':
                raise UserError('La búsqueda no completó una respuesta. El consumo registrado se conserva.')
            parts=candidates[0].get('content',{}).get('parts',[])
            text=''.join(p.get('text','') for p in parts if not p.get('thought'))
            if not text.strip():raise UserError('La búsqueda no devolvió contenido.')
            grounding=candidates[0].get('groundingMetadata') or {}
            sources=[]
            for chunk in (grounding.get('groundingChunks') or []):
                web=chunk.get('web') or {}
                if web.get('uri'):sources.append({'title':str(web.get('title',''))[:200],'uri':web['uri']})
            return text[:8000],sources[:8],{'provider':'gemini-search','model':cfg.gemini_model,'usage':usage,'cost_usd':cost/1000000}
        except UserError:
            with self.store.db() as c:c.execute("UPDATE ledger SET state='uncertain' WHERE id=? AND state='reserved'",(ledger,))
            raise
        except (ValueError,KeyError,TypeError,AttributeError,IndexError):
            with self.store.db() as c:c.execute("UPDATE ledger SET state='uncertain' WHERE id=? AND state='reserved'",(ledger,))
            raise UserError('La respuesta de búsqueda no tiene el formato esperado; no se repetirá automáticamente.') from None
