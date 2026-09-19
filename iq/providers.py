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

    def evaluate(self,system,user):
        if not self.config.local_enabled:raise UserError('El motor local todavía no está configurado.')
        payload={'model':self.config.local_model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
            'temperature':0,'max_tokens':self.config.max_output_tokens,'stream':False,
            'chat_template_kwargs':{'enable_thinking':False},
            'response_format':{'type':'json_object','schema':SCHEMA}}
        data=self.transport(loopback_url(self.config.local_url)+'/v1/chat/completions',payload,timeout=self.config.timeout_seconds)
        try:
            choice=data['choices'][0]
            if choice.get('finish_reason') not in ('stop',None):raise ValueError()
            content=choice['message']['content']
            answer=json.loads(content)
        except (KeyError,IndexError,TypeError,ValueError):raise UserError('El motor local no devolvió un JSON completo. Revisá modelo, plantilla y límite de salida.')
        return answer,{'provider':'local','model':data.get('model',self.config.local_model),'usage':data.get('usage',{}),'output_limit':self.config.max_output_tokens}


def micro_cost(tokens,price):
    # tokens * USD/million = micro-USD. Always round UP for reservations.
    return int((Decimal(tokens)*Decimal(str(price))).to_integral_value(rounding=ROUND_CEILING))


def usd_micro(value):return int((Decimal(str(value))*1000000).to_integral_value(rounding=ROUND_CEILING))


class GeminiProvider:
    def __init__(self,config,store,transport=post_json):self.config=config;self.store=store;self.transport=transport

    def evaluate(self,system,user,job_id,cid):
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
                'thinkingConfig':{'thinkingBudget':0},'responseMimeType':'application/json','responseSchema':SCHEMA}}
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
