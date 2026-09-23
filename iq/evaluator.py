import json
import re
import time
from decimal import Decimal
from .domain import clean, folded, aggregate, estimate_complexity, UserError
from .documents import retrieve
from .providers import LocalProvider, GeminiProvider, messages
from .config import Config
from . import distill


def pending(c,reason):
    return {'criterion_id':c['id'],'label':c['label'],'status':'needs_review','explanation':reason,
            'evidence':[],'method':'pending','review_required':True}


def evidence_for_unit(document,unit,quote):
    return {'location':unit['location'],'quote':quote,'document_id':document['id']}


def check_rule(c,doc):
    row=pending(c,'No hay evidencia suficiente.')
    row['method']='rule'
    if c['kind']=='phrase':
        # Exactly what this rule promises: literal occurrence, not semantic compliance.
        needle=folded(c['phrase'])
        for unit in doc['units']:
            if needle in folded(unit['text']):
                row.update(status='meets',explanation='Se encontró la frase requerida. Esta regla verifica presencia literal, no su significado.',
                           evidence=[evidence_for_unit(doc,unit,unit['text'])],review_required=False)
                return row
        row['explanation']='La frase no se encontró. La ausencia queda pendiente de revisión, no se interpreta como incumplimiento.'
        return row
    if c['kind']=='number_max':
        matches=[]
        pattern=re.compile(r'^\s*'+re.escape(folded(c['field']))+r'\s*:\s*(\d+(?:[.,]\d+)?)\s*'+re.escape(folded(c['unit']))+r'\s*[.;]?\s*$')
        for unit in doc['units']:
            for line in unit['text'].splitlines():
                match=pattern.fullmatch(folded(line))
                if match:matches.append((Decimal(match[1].replace(',','.')),unit,line))
        values={x[0] for x in matches}
        if len(values)!=1:
            row['explanation']='Se necesita un único valor explícito en formato “campo: número unidad”; no se encontró o hay valores contradictorios.'
            return row
        v,unit,line=matches[0];ok=v<=Decimal(c['maximum'])
        row.update(status='meets' if ok else 'does_not_meet',
            explanation=f'Valor explícito {v} {c["unit"]}; máximo permitido {c["maximum"]}. Comparación calculada por código.',
            evidence=[evidence_for_unit(doc,unit,line)],review_required=False)
        return row
    return None


def validate_answer(c,doc,segments,answer,provider):
    row=pending(c,'La respuesta del modelo no superó la validación.')
    if not isinstance(answer,dict):return row
    status=answer.get('status');exp=answer.get('explanation');ev=answer.get('evidence')
    if status not in ('meets','does_not_meet','needs_review') or not isinstance(exp,str) or not 1<=len(exp)<=2500 or not isinstance(ev,list) or len(ev)>5:
        return row
    checked=[];index={s['id']:s for s in segments}
    for e in ev:
        if not isinstance(e,dict):return row
        if not isinstance(e.get('segment_id'),str):return row
        s=index.get(e.get('segment_id'));quote=e.get('quote')
        if not s or not isinstance(quote,str) or not quote.strip() or len(quote)>1500 or clean(quote) not in clean(s['text']):
            row['explanation']='El modelo citó un fragmento inexistente o una cita que no coincide con el texto. Requiere revisión.'
            return row
        checked.append({'segment_id':s['id'],'location':s['location'],'quote':quote,'document_id':doc['id']})
    if status!='needs_review' and not checked:
        row['explanation']='El modelo emitió una conclusión sin evidencia verificable.';return row
    return {'criterion_id':c['id'],'label':c['label'],'status':status,'explanation':exp,
            'evidence':checked,'method':provider,'review_required':True,
            'validation':'Citas comprobadas contra el texto; la interpretación requiere revisión humana en esta alfa.'}


def evaluate_job(store,job,registry):
    started=time.monotonic();payload=job['payload'];cfg=Config(**payload['config']).validate()
    doc=store.document(payload['document_id']);criteria=payload['rubric']['criteria']
    skill=payload['skill'];result=job['result'];done={r['criterion_id'] for r in result['rows']}
    result['previous_elapsed_seconds']=result.get('elapsed_seconds',0)
    result.update(skill={'id':skill['id'],'version':skill['version'],'sha256':skill['sha256']},
                  document={'id':doc['id'],'name':doc['name'],'sha256':doc['sha256']},warnings=doc['warnings'])
    local_provider=LocalProvider(cfg)
    embed_provider=local_provider if cfg.local_enabled and cfg.embedding_model else None
    for c in criteria:
        if store.job(job['id'])['status']=='cancelled':return
        if c['id'] in done:continue
        t=time.monotonic();row=check_rule(c,doc)
        if row is None:
            row=pending(c,'Este criterio necesita interpretación. Conectá un modelo local o habilitá asistencia externa.')
            selected=retrieve(doc,c['label'],cfg.max_context_chars,provider=embed_provider)
            system,user=messages(skill,c,selected)
            # Same heuristic used for chat (domain.estimate_complexity), applied to the
            # criterion's own wording: short literal-sounding labels stay fast, while
            # labels that read as comparative/interpretive judgments get reasoning on.
            reasoning=estimate_complexity(c['label'])
            context_info={'selected_characters':sum(len(s['text']) for s in selected),
                          'document_characters':doc['characters'],'prompt_characters':len(system)+len(user),
                          'selection':'lexical' if embed_provider is None else 'lexical+embeddings','segments':len(selected),
                          'reasoning':reasoning}
            if payload['mode']=='local':
                try:
                    answer,meta=local_provider.evaluate(system,user,reasoning=reasoning)
                    row=validate_answer(c,doc,selected,answer,'local');row['model']=meta
                except UserError as exc:row=pending(c,str(exc))
            if row['status']=='needs_review' and payload['allow_cloud']:
                if store.job(job['id'])['status']=='cancelled':return
                if store.has_cloud_attempt(job['id'],c['id']):
                    row=pending(c,'Existe un intento externo previo. Revisá el consumo y la evidencia antes de crear otra evaluación.')
                else:
                    try:
                        # Same free local distillation used for chat escalation (see
                        # iq/distill.py): only pay to send the fragments the paid call
                        # actually needs, falling back to the full selection otherwise.
                        brief=distill.compress(local_provider,cfg,c['label'],selected)
                        cloud_selected=brief['segments'] if brief and brief['segments'] else selected
                        cloud_context={'criterion':{'id':c['id'],'instruction':c['label']},'document_fragments':cloud_selected,
                            'note':'Los fragmentos pueden ser una selección parcial. No prueban ausencia global.'}
                        if brief:cloud_context['local_context_brief']={'summary':brief['summary'],'missing':brief['missing']}
                        cloud_user=json.dumps(cloud_context,ensure_ascii=False)
                        answer,meta=GeminiProvider(cfg,store).evaluate(system,cloud_user,job['id'],c['id'])
                        row=validate_answer(c,doc,cloud_selected,answer,'gemini');row['model']=meta
                    except UserError as exc:row=pending(c,str(exc))
            row['context']=context_info
        row['elapsed_seconds']=round(time.monotonic()-t,3)
        result['rows'].append(row)
        result['events'].append({'criterion_id':c['id'],'method':row['method'],'status':row['status']})
        result['summary']=aggregate(criteria,result['rows'])
        result['review_required']=any(r.get('review_required') for r in result['rows']) or bool(doc['warnings'])
        result['elapsed_seconds']=round(result.get('previous_elapsed_seconds',0)+time.monotonic()-started,3)
        store.checkpoint(job['id'],result)
    result['summary']=aggregate(criteria,result['rows'])
    result['review_required']=any(r.get('review_required') for r in result['rows']) or bool(doc['warnings'])
    store.checkpoint(job['id'],result,'completed')


def markdown_report(job):
    p=job['payload'];r=job['result'];s=r.get('summary',{})
    lines=['# Evaluación documental','',f'Rúbrica: {p["rubric"]["name"]}',f'Estado del trabajo: {job["status"]}',
           f'Documento: {r.get("document",{}).get("name",p["document_id"])}',
           f'Puntaje preliminar según criterios: {s.get("score_min",0)} / 100',
           f'Máximo si se resuelven pendientes: {s.get("score_max",100)} / 100','',
           'Las citas se comprueban contra el texto; las interpretaciones del modelo necesitan revisión humana.','']
    for row in r['rows']:
        lines.extend(['## '+row['label'],f'Estado: {row["status"]} · Método: {row["method"]}',row['explanation'],''])
        for ev in row['evidence']:lines.extend([f'Fuente: {ev["location"]}', '> '+ev['quote'].replace('\n','\n> '),''])
    lines.extend(['## Registro de ejecución','',f'Trabajo: {job["id"]}',f'Skill: {p["skill"]["id"]} {p["skill"]["version"]}',
                  f'Tiempo de procesamiento: {r.get("elapsed_seconds",0)} s',
                  f'Huella del documento: {r.get("document",{}).get("sha256","")}'])
    return '\n'.join(lines)
