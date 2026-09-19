"""Measure total HTTP response time against an already running local model."""
import argparse
import json
import math
import statistics
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from .config import load_config, loopback_url
from .diagnostics import hardware
from .domain import UserError
from .providers import LocalProvider, messages, post_json
from .skills import SkillRegistry
from .documents import extract
from .evaluator import validate_answer


def main():
    parser=argparse.ArgumentParser(description='Benchmark local: sin claves ni llamadas a Gemini.')
    parser.add_argument('--url',help='Dirección del servidor llama.cpp en este equipo')
    parser.add_argument('--model',help='Alias del modelo')
    parser.add_argument('--repetitions',type=int,default=5)
    parser.add_argument('--output',help='Ruta del informe JSON; por defecto, salida de consola')
    args=parser.parse_args()
    if not 1<=args.repetitions<=20:parser.error('Usá entre 1 y 20 repeticiones.')
    cfg=load_config()
    cfg=replace(cfg,local_enabled=True,cloud_enabled=False,
                local_url=args.url or cfg.local_url,local_model=args.model or cfg.local_model).validate()
    doc={**extract('benchmark.txt','Las urgencias fuera de horario tienen un cargo adicional.'.encode()),'id':'benchmark'}
    criterion={'id':'urgencias','label':'El servicio cubre urgencias sin cargo adicional.'}
    system,user=messages(SkillRegistry().load(),criterion,doc['segments'])
    report={'at':datetime.now(timezone.utc).isoformat(),'hardware':hardware(),'model_alias':cfg.local_model,
            'measurement':'Tiempo total HTTP, no tiempo hasta el primer token. El servidor ya debe estar iniciado.',
            'warmup':{},'samples':[],'summary':{}}
    error=None
    try:
        hello={'model':cfg.local_model,'messages':[{'role':'user','content':'Decí solamente: hola'}],
               'max_tokens':16,'temperature':0,'stream':False,'chat_template_kwargs':{'enable_thinking':False}}
        t=time.perf_counter();response=post_json(loopback_url(cfg.local_url)+'/v1/chat/completions',hello,timeout=cfg.timeout_seconds)
        if not response.get('choices'):raise UserError('El motor no devolvió una respuesta al saludo.')
        report['warmup']={'seconds':round(time.perf_counter()-t,4),'usage':response.get('usage',{}),
                          'note':'Primera llamada de esta ejecución; no garantiza modelo frío.'}
        for i in range(args.repetitions):
            t=time.perf_counter();answer,meta=LocalProvider(cfg).evaluate(system,user)
            seconds=time.perf_counter()-t
            row=validate_answer(criterion,doc,doc['segments'],answer,'local')
            report['samples'].append({'sample':i+1,'seconds':round(seconds,4),'status':row['status'],
                    'expected_status':'does_not_meet','matches_expected':row['status']=='does_not_meet',
                    'valid_citations':bool(row['evidence']),'usage':meta['usage']})
        values=sorted(s['seconds'] for s in report['samples'])
        report['summary']={'median_seconds':statistics.median(values),'p95_seconds':values[math.ceil(.95*len(values))-1],
                           'sample_count':len(values),'note':'Una tarea sintética; insuficiente para estimar calidad general.'}
    except (UserError,ValueError) as exc:error=str(exc);report['error']=error
    raw=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:Path(args.output).write_text(raw+'\n',encoding='utf-8')
    else:print(raw)
    return 1 if error else 0


if __name__=='__main__':raise SystemExit(main())
