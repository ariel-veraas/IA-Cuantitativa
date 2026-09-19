import json
import os
import threading
from dataclasses import replace
from pathlib import Path
from .config import ROOT, load_config
from .documents import decode_upload, extract
from .domain import UserError, validate_rubric
from .evaluator import evaluate_job
from .skills import SkillRegistry
from .store import Store
from .lock import DataLock


class Application:
    def __init__(self,data_dir=None,config=None):
        self.config=config or load_config()
        directory=Path(data_dir or os.environ.get('IQ_DATA_DIR',ROOT/'data'))
        self.lock=DataLock(directory)
        try:
            self.store=Store(directory/'iq.sqlite3')
            with self.store.db() as c:
                saved=c.execute("SELECT value FROM flags WHERE key='local_config'").fetchone()
            if saved:self.config=replace(self.config,**json.loads(saved[0])).validate()
        except Exception:
            self.lock.close();raise
        self.skills=SkillRegistry();self.stop_event=threading.Event();self.wake=threading.Event()
        self.worker=threading.Thread(target=self._work,daemon=True,name='iq-worker');self.worker.start()

    def close(self):
        self.stop_event.set();self.wake.set();self.worker.join(timeout=2)

    def _work(self):
        try:self._work_loop()
        finally:self.lock.close()

    def _work_loop(self):
        while not self.stop_event.is_set():
            job=self.store.next_job()
            if not job:
                self.wake.wait(0.5);self.wake.clear();continue
            try:evaluate_job(self.store,job,self.skills)
            except Exception:
                current=self.store.job(job['id'])
                self.store.checkpoint(job['id'],current['result'],'failed','No se completó el trabajo. Se conservaron los pasos terminados.')

    def add_document(self,payload):
        if 'text' in payload:
            text=payload['text']
            if not isinstance(text,str) or len(text)>200000:raise UserError('Texto demasiado largo.')
            doc=extract('documento.txt',text.encode('utf-8'))
        else:doc=decode_upload(payload.get('filename'),payload.get('base64'))
        return self.store.add_document(doc)

    def demo(self):
        doc=extract('proveedor-ejemplo.txt',(ROOT/'examples'/'proveedor.txt').read_bytes())
        doc=self.store.add_document(doc)
        rubric=json.loads((ROOT/'examples'/'rubrica.json').read_text('utf-8'))
        return {'document':doc,'rubric':rubric}

    def submit(self,payload):
        if not isinstance(payload.get('document_id'),str):raise UserError('Seleccioná un documento.')
        doc=self.store.document(payload['document_id'])
        rubric=validate_rubric(payload.get('rubric'))
        mode=payload.get('mode','rules')
        if mode not in ('rules','local'):raise UserError('Modo desconocido.')
        allow=payload.get('allow_cloud',False)
        if type(allow) is not bool:raise UserError('La opción de asistencia externa es inválida.')
        if allow and not self.config.cloud_enabled:raise UserError('Gemini no está habilitado en la configuración.')
        if mode=='local' and not self.config.local_enabled:raise UserError('El motor local no está habilitado. Podés probar las reglas sin modelo.')
        job=self.store.create_job({'document_id':doc['id'],'rubric':rubric,'mode':mode,'allow_cloud':allow,
            'config':self.config.public(),'skill':self.skills.load()})
        self.wake.set();return job

    def state(self):
        return {'version':'0.1.0','config':self.config.public(),'documents':self.store.documents(),
                'jobs':self.store.jobs(),'skills':self.skills.catalog(),'usage':self.store.usage(),
                'gemini_key_present':bool(os.environ.get('GEMINI_API_KEY'))}

    def configure_local(self,data):
        changes={'local_url':data.get('url'),'local_model':data.get('model'),'local_enabled':data.get('enabled')}
        config=replace(self.config,**changes).validate()
        with self.store.db() as c:c.execute("INSERT OR REPLACE INTO flags VALUES ('local_config',?)",(json.dumps(changes),))
        self.config=config
        return config.public()
