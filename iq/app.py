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
from .capabilities import Capabilities
from .conversation import evaluate_conversation, select_skill
from .engine import Engine
from .vault import Vault


class Application:
    def __init__(self,data_dir=None,config=None):
        self.config=config or load_config()
        directory=Path(data_dir or os.environ.get('IQ_DATA_DIR',ROOT/'data'))
        self.directory=directory
        self.lock=DataLock(directory)
        try:
            self.store=Store(directory/'iq.sqlite3')
            with self.store.db() as c:
                saved=c.execute("SELECT value FROM flags WHERE key='local_config'").fetchone()
            if saved:self.config=replace(self.config,**json.loads(saved[0])).validate()
            with self.store.db() as c:saved=c.execute("SELECT value FROM flags WHERE key='cloud_config'").fetchone()
            if saved:self.config=replace(self.config,**json.loads(saved[0])).validate()
        except Exception:
            self.lock.close();raise
        self.vault=Vault(directory)
        saved_key=self.vault.get()
        if saved_key:os.environ['GEMINI_API_KEY']=saved_key
        self.skills=SkillRegistry();self.capabilities=Capabilities(self.store)
        self.stop_event=threading.Event();self.wake=threading.Event()
        self.engine=Engine(directory,self._engine_ready)
        self.worker=threading.Thread(target=self._work,daemon=True,name='iq-worker');self.worker.start()

    def close(self):
        self.stop_event.set();self.wake.set();self.engine.close();self.worker.join(timeout=2)

    def _work(self):
        try:self._work_loop()
        finally:self.lock.close()

    def _work_loop(self):
        while not self.stop_event.is_set():
            job=self.store.next_job()
            if not job:
                self.wake.wait(0.5);self.wake.clear();continue
            try:
                if job['payload'].get('kind')=='conversation':evaluate_conversation(self.store,job,self.capabilities)
                else:evaluate_job(self.store,job,self.skills)
            except Exception:
                current=self.store.job(job['id'])
                self.store.checkpoint(job['id'],current['result'],'failed','No se completó el trabajo. Se conservaron los pasos terminados.')

    def add_document(self,payload):
        if 'text' in payload:
            text=payload['text']
            if not isinstance(text,str) or len(text)>200000:raise UserError('Texto demasiado largo.')
            name=payload.get('name','documento')
            if not isinstance(name,str) or len(name)>150:raise UserError('Nombre de documento inválido.')
            doc=extract((name.strip() or 'documento')+'.txt',text.encode('utf-8'))
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
        return {'version':'1.0.0','config':self.config.public(),'documents':self.store.documents(),
                'jobs':self.store.jobs(),'skills':self.skills.catalog(),'usage':self.store.usage(),
                'gemini_key_present':bool(os.environ.get('GEMINI_API_KEY')),'engine':self.engine.snapshot(),
                'capabilities':self.capabilities.catalog(True),'conversations':self.capabilities.conversations()}

    def configure_local(self,data):
        changes={'local_url':data.get('url'),'local_model':data.get('model'),'local_enabled':data.get('enabled'),
                 'local_backend':data.get('backend',self.config.local_backend)}
        config=replace(self.config,**changes).validate()
        with self.store.db() as c:c.execute("INSERT OR REPLACE INTO flags VALUES ('local_config',?)",(json.dumps(changes),))
        self.config=config
        return config.public()

    def _engine_ready(self,url,model):
        self.configure_local({'url':url,'model':model,'enabled':True,'backend':'ollama'})

    def chat(self,data):
        message=data.get('message','')
        if not isinstance(message,str) or not 1<=len(message.strip())<=6000:raise UserError('Escribí un mensaje de hasta 6.000 caracteres.')
        ids=data.get('document_ids',[])
        if not isinstance(ids,list) or len(ids)>4 or any(not isinstance(x,str) for x in ids):raise UserError('Elegí hasta cuatro archivos.')
        ids=list(dict.fromkeys(ids))
        for id in ids:self.store.document(id)
        requested=data.get('skill_id','auto')
        if not isinstance(requested,str):raise UserError('Capacidad inválida.')
        test=data.get('skill_test',False)
        if type(test) is not bool:raise UserError('Prueba inválida.')
        version=data.get('skill_version')
        if version is not None and (type(version) is not int or version<1):raise UserError('Versión inválida.')
        skill=self.capabilities.get(select_skill(message,ids,requested),version,for_test=test)
        if test:
            if skill.get('builtin'):raise UserError('Esta capacidad ya está incluida.')
            message=skill['example']
        conversation_id=data.get('conversation_id')
        if conversation_id:
            if not isinstance(conversation_id,str):raise UserError('Conversación inválida.')
            history=self.capabilities.conversation(conversation_id)[-8:]
        else:conversation_id=self.capabilities.new_conversation(message);history=[]
        allow=data.get('allow_cloud',False)
        if type(allow) is not bool or (allow and not self.config.cloud_enabled):raise UserError('La asistencia externa no está habilitada.')
        if test:allow=False
        job=self.store.create_job({'kind':'conversation','message':message,'conversation_id':conversation_id,
            'document_ids':ids,'requested_skill':requested,'skill':skill,'history':history,'skill_test':test,
            'allow_cloud':allow,'config':self.config.public()})
        self.capabilities.append(conversation_id,job['id'],'user',message)
        if test:self.capabilities.attach_test(skill['id'],skill['version'],job['id'])
        self.wake.set();return job

    def configure_cloud(self,data):
        allowed=('cloud_enabled','gemini_model','input_usd_per_million','output_usd_per_million',
                 'monthly_budget_usd','per_job_budget_usd','pricing_confirmed')
        changes={k:data.get(k,getattr(self.config,k)) for k in allowed}
        config=replace(self.config,**changes).validate()
        key=data.get('key')
        if key is not None:
            if not isinstance(key,str) or len(key)>300 or any(c.isspace() for c in key):raise UserError('La clave no es válida.')
            self.vault.set(key)
            if key:os.environ['GEMINI_API_KEY']=key
            else:os.environ.pop('GEMINI_API_KEY',None)
        if config.cloud_enabled and not os.environ.get('GEMINI_API_KEY'):raise UserError('Ingresá una clave para habilitar Gemini.')
        with self.store.db() as c:c.execute("INSERT OR REPLACE INTO flags VALUES ('cloud_config',?)",(json.dumps(changes),))
        self.config=config;return config.public()

    def delete_document(self,id):
        self.store.document(id)
        with self.store.db() as c:
            if c.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued')").fetchone():raise UserError('Esperá a que terminen los trabajos antes de borrar archivos.')
            c.execute('DELETE FROM documents WHERE id=?',(id,))
        return {'deleted':True,'note':'Los informes y conversaciones anteriores conservan sus citas. Borrá también esas conversaciones si querés retirar su contenido.'}

    def delete_conversation(self,id):
        self.capabilities.conversation(id)
        with self.store.db() as c:
            jobs=[r[0] for r in c.execute('SELECT DISTINCT job_id FROM messages WHERE conversation_id=?',(id,))]
            for job in jobs:
                row=c.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()
                if row and row[0] in ('queued','running'):raise UserError('Cancelá o esperá los trabajos activos antes de borrar la conversación.')
            c.execute('DELETE FROM messages WHERE conversation_id=?',(id,));c.execute('DELETE FROM conversations WHERE id=?',(id,))
            for job in jobs:c.execute('DELETE FROM jobs WHERE id=?',(job,))
        return {'deleted':True}
