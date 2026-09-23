"""Compress context before an expensive external call, using the free local model.

This only ever narrows what gets sent to a paid provider — it never adds a fragment
that was not already offered to the local model, and any failure or suspicious output
falls back to the caller using the original, uncompressed selection. The goal is the
one the user asked for explicitly: when the local "brain" can't resolve something and
has to hand it off, hand off a minimal, well-formed context instead of everything it
had, so the external call does not pay for tokens it does not need.
"""
import json
from .domain import UserError

SCHEMA={'type':'object','properties':{
    'summary':{'type':'string'},
    'missing':{'type':'string'},
    'key_segment_ids':{'type':'array','items':{'type':'string'},'maxItems':6}
},'required':['summary','missing','key_segment_ids']}

SYSTEM=('Tu única tarea es preparar un contexto mínimo para pedir ayuda externa paga; no respondas el pedido. '
    'En summary anotá en pocas líneas qué ya se sabe con certeza a partir de los fragmentos, si algo. '
    'En missing decí específicamente qué información falta o por qué no se pudo resolver localmente. '
    'En key_segment_ids elegí como máximo 6 identificadores de fragmentos realmente imprescindibles '
    '(ninguno si ninguno hace falta). No inventes identificadores que no existan entre los provistos.')


def compress(local_provider, cfg, task, segments):
    """segments: list of dicts with at least 'id' and 'text'.

    Returns {'summary','missing','segments'} (a subset of the input segments, possibly
    empty) on success, or None when compression is unavailable or its output does not
    check out — callers should send the original, uncompressed segments in that case.
    """
    if not cfg.local_enabled or not segments:
        return None
    payload={'task':task,'document_fragments':[{'id':s['id'],'text':s['text']} for s in segments]}
    try:
        answer,_=local_provider.generate(SYSTEM,json.dumps(payload,ensure_ascii=False),SCHEMA,reasoning=False)
    except UserError:
        return None
    if not isinstance(answer,dict):
        return None
    summary=answer.get('summary');missing=answer.get('missing');ids=answer.get('key_segment_ids')
    if not isinstance(summary,str) or not isinstance(missing,str) or not isinstance(ids,list):
        return None
    index={s['id']:s for s in segments}
    kept=[index[i] for i in ids if isinstance(i,str) and i in index]
    return {'summary':summary[:2000],'missing':missing[:2000],'segments':kept}
