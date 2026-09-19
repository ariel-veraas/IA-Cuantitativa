"""Domain checks shared by HTTP, evaluator and tests."""
import re
import unicodedata
from decimal import Decimal


class UserError(ValueError):
    pass


def clean(value):
    return ' '.join(str(value).split())


def folded(value):
    s = unicodedata.normalize('NFKD', clean(value).casefold())
    return ''.join(c for c in s if not unicodedata.combining(c))


def text_field(obj,key,limit=1000,optional=False):
    value=obj.get(key,'')
    if not isinstance(value,str) or (not optional and not value.strip()) or len(value)>limit:
        raise UserError(f'Campo {key} vacío o demasiado largo (máximo {limit}).')
    return value.strip()


def validate_rubric(data):
    if not isinstance(data,dict): raise UserError('La rúbrica debe ser un objeto.')
    name=text_field(data,'name',120)
    rows=data.get('criteria')
    if not isinstance(rows,list) or not 1<=len(rows)<=15:
        raise UserError('Agregá entre 1 y 15 criterios.')
    result=[];seen=set()
    for raw in rows:
        if not isinstance(raw,dict): raise UserError('Criterio inválido.')
        cid=text_field(raw,'id',40)
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',cid) or cid in seen:
            raise UserError('Los identificadores deben ser únicos y sin espacios.')
        seen.add(cid)
        kind=raw.get('kind')
        if kind not in ('phrase','number_max','semantic'):
            raise UserError('Tipo de criterio desconocido.')
        weight=raw.get('weight')
        if type(weight) is not int or not 1<=weight<=100:
            raise UserError('Cada peso debe ser un entero entre 1 y 100.')
        if type(raw.get('required',False)) is not bool:
            raise UserError('required debe ser verdadero o falso.')
        c={'id':cid,'kind':kind,'label':text_field(raw,'label',500),'weight':weight,
           'required':raw.get('required',False)}
        if kind=='phrase':
            c['phrase']=text_field(raw,'phrase',200)
        if kind=='number_max':
            c['field']=text_field(raw,'field',120)
            c['unit']=text_field(raw,'unit',40)
            value=raw.get('maximum')
            try: number=Decimal(str(value))
            except Exception: raise UserError('Máximo numérico inválido.')
            if not number.is_finite() or not 0<=number<=1000000000:
                raise UserError('Máximo numérico fuera de rango.')
            c['maximum']=str(number)
        result.append(c)
    return {'name':name,'criteria':result}


def aggregate(criteria,rows):
    by_id={r['criterion_id']:r for r in rows}
    total=sum(c['weight'] for c in criteria)
    earned=sum(c['weight'] for c in criteria if by_id.get(c['id'],{}).get('status')=='meets')
    pending=sum(c['weight'] for c in criteria if by_id.get(c['id'],{}).get('status') not in ('meets','does_not_meet'))
    mandatory=[by_id.get(c['id'],{}).get('status','needs_review') for c in criteria if c['required']]
    decision='does_not_meet' if 'does_not_meet' in mandatory else ('needs_review' if pending else 'evaluated')
    return {'earned_weight':earned,'total_weight':total,'pending_weight':pending,
            'score_min':round(100*earned/total,2),'score_max':round(100*(earned+pending)/total,2),
            'decision':decision,'complete':len(rows)==len(criteria) and pending==0}
