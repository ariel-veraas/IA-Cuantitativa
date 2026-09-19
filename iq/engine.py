"""An application-owned Ollama process and resumable, verified preparation."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from urllib.error import HTTPError
from .domain import UserError
from .providers import post_json

RELEASE='v0.34.2'
PROFILES={'balanced':{'model':'qwen3:4b','name':'Equilibrado','download_gb':2.6},
          'light':{'model':'qwen3:1.7b','name':'Más liviano','download_gb':1.4}}
BASE='http://127.0.0.1:11435'


def read_json(url,timeout=10):
    opener=build_opener(ProxyHandler({})) if url.startswith(BASE) else build_opener()
    with opener.open(Request(url,headers={'User-Agent':'IA-Cuantitativa/1.0'}),timeout=timeout) as r:
        raw=r.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise UserError('Metadatos de descarga demasiado grandes.')
        return json.loads(raw)


def download(url,path,sha256,expected_size,cancel,progress):
    if not url.startswith('https://github.com/ollama/ollama/releases/download/'+RELEASE+'/'):
        raise UserError('Origen del motor no permitido.')
    if not isinstance(sha256,str) or len(sha256)!=64 or any(c not in '0123456789abcdef' for c in sha256):
        raise UserError('El distribuidor no publicó una huella verificable del motor.')
    part=Path(str(path)+'.part');offset=part.stat().st_size if part.exists() else 0
    headers={'User-Agent':'IA-Cuantitativa/1.0'}
    if offset:headers['Range']=f'bytes={offset}-'
    if offset<expected_size:
        with urlopen(Request(url,headers=headers),timeout=30) as r:
            resumed=r.status==206 and r.headers.get('Content-Range','').startswith(f'bytes {offset}-')
            if not resumed:offset=0
            with part.open('ab' if resumed else 'wb') as f:
                while True:
                    if cancel.is_set():raise UserError('Preparación pausada. Podés continuar cuando quieras.')
                    chunk=r.read(1024*1024)
                    if not chunk:break
                    offset+=len(chunk)
                    if offset>expected_size:raise UserError('El tamaño descargado no coincide con el publicado.')
                    f.write(chunk);progress(offset,expected_size)
    digest=hashlib.sha256()
    with part.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    if part.stat().st_size!=expected_size or digest.hexdigest()!=sha256:
        part.unlink(missing_ok=True);raise UserError('La descarga no superó la comprobación de integridad. Volvé a prepararla.')
    os.replace(part,path)


def safe_extract(archive,directory):
    directory=Path(directory).resolve()
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>12*1024**3:raise UserError('El paquete expandido supera el tamaño permitido.')
        for info in z.infolist():
            target=(directory/info.filename.replace('\\','/')).resolve()
            if not target.is_relative_to(directory) or (info.external_attr>>16)&0o170000==0o120000:
                raise UserError('El paquete contiene una ruta no permitida.')
        z.extractall(directory)


class Engine:
    def __init__(self,directory,on_ready):
        self.directory=Path(directory)/'engine';self.directory.mkdir(parents=True,exist_ok=True)
        self.callback=on_ready;self.process=None;self.thread=None;self.stop=threading.Event();self.guard=threading.Lock()
        self.status={'stage':'not_ready','message':'Prepará el motor local para empezar.','progress':0,'model':'','ready':False}
        self.preference=self.directory/'preference.json';self.log=None
        if self.preference.exists():
            try:
                pref=json.loads(self.preference.read_text('utf-8'));self.prepare(pref['profile'],False)
            except (ValueError,KeyError,UserError):pass

    def snapshot(self):
        with self.guard:result=dict(self.status)
        if self.process and self.process.poll() is not None and result['ready']:
            self.update(stage='error',ready=False,message='El motor se cerró. Tocá Preparar para volver a iniciarlo.')
            return dict(self.status)
        return result

    def update(self,**values):
        with self.guard:self.status.update(values)

    def executable(self):
        private=self.directory/RELEASE/('ollama.exe' if os.name=='nt' else 'ollama')
        if private.is_file():return str(private)
        # Existing executables are only used outside the packaged Windows edition.
        return shutil.which('ollama') if os.name!='nt' else None

    def prepare(self,profile='balanced',allow_download=True):
        if profile not in PROFILES:raise UserError('Perfil desconocido.')
        with self.guard:
            if self.thread and self.thread.is_alive():raise UserError('La preparación ya está en curso.')
            self.stop.clear();self.status.update(stage='starting',message='Revisando el motor local…',ready=False,profile=profile,progress=0)
            self.thread=threading.Thread(target=self._prepare,args=(profile,allow_download),daemon=True);self.thread.start()
        return self.snapshot()

    def _prepare(self,profile,allow_download):
        model=PROFILES[profile]['model'];self.update(model=model)
        try:
            exe=self.executable()
            if not exe:
                if not allow_download:raise UserError('Hace falta completar la instalación del motor.')
                if os.name!='nt' or platform.machine().lower() not in ('amd64','x86_64'):
                    raise UserError('El instalador integrado es para Windows x64. Este entorno de desarrollo necesita Ollama disponible.')
                if shutil.disk_usage(self.directory).free<12*1024**3:raise UserError('Se necesitan al menos 12 GB libres para preparar motor y modelo.')
                self.update(stage='downloading_engine',message='Descargando el motor verificado…')
                release=read_json('https://api.github.com/repos/ollama/ollama/releases/tags/'+RELEASE,30)
                asset=next((a for a in release.get('assets',[]) if a['name']=='ollama-windows-amd64.zip'),None)
                if not asset or not 0<asset['size']<8*1024**3:raise UserError('No se encontró un paquete compatible del motor.')
                archive=self.directory/'runtime.zip'
                download(asset['browser_download_url'],archive,asset.get('digest','').removeprefix('sha256:'),asset['size'],self.stop,
                         lambda n,total:self.update(progress=round(n/total*100,1),completed_bytes=n,total_bytes=total))
                self.update(stage='extracting',message='Instalando el motor…',progress=0)
                stage=self.directory/(RELEASE+'.staging');shutil.rmtree(stage,ignore_errors=True)
                safe_extract(archive,stage)
                if not (stage/'ollama.exe').exists():raise UserError('El paquete no contiene el motor esperado.')
                os.replace(stage,self.directory/RELEASE);archive.unlink();exe=self.executable()
            if self.stop.is_set():raise UserError('Preparación pausada.')
            self._start(exe)
            self.update(stage='checking_model',message='Revisando el modelo instalado…',progress=0)
            tags=read_json(BASE+'/api/tags');present=any(m.get('name')==model for m in tags.get('models',[]))
            if not present:
                if not allow_download:raise UserError('El modelo todavía no terminó de descargarse. Tocá Preparar.')
                self.update(stage='downloading_model',message='Descargando el modelo. Podés pausar y continuar.',progress=0)
                req=Request(BASE+'/api/pull',data=json.dumps({'model':model,'stream':True}).encode(),headers={'Content-Type':'application/json'})
                success=False
                with build_opener(ProxyHandler({})).open(req,timeout=120) as response:
                    for line in response:
                        if self.stop.is_set():raise UserError('Preparación pausada. La descarga puede continuar después.')
                        if len(line)>100000:raise UserError('Respuesta de descarga inválida.')
                        data=json.loads(line)
                        if data.get('error'):raise UserError('No se pudo descargar el modelo: '+str(data['error'])[:300])
                        total=data.get('total',0);done=data.get('completed',0)
                        if total:self.update(progress=round(done/total*100,1),completed_bytes=done,total_bytes=total)
                        if data.get('status')=='success':success=True
                if not success:raise UserError('La descarga se interrumpió. Tocá Preparar para continuar.')
            self.update(stage='warming',message='Cargando el modelo en memoria…',progress=100)
            post_json(BASE+'/api/generate',{'model':model,'prompt':'','stream':False,'keep_alive':'30m',
                      'options':{'num_ctx':4096}},timeout=300)
            if self.stop.is_set():raise UserError('Preparación pausada.')
            meta=read_json(BASE+'/api/ps')
            loaded=next((m for m in meta.get('models',[]) if m.get('name')==model),{})
            self.preference.write_text(json.dumps({'profile':profile}),encoding='utf-8')
            self.callback(BASE,model)
            self.update(stage='ready',message='Listo para trabajar en este equipo.',ready=True,progress=100,
                        size_bytes=loaded.get('size',0),gpu_bytes=loaded.get('size_vram',0))
        except Exception as exc:
            self.update(stage='paused' if self.stop.is_set() else 'error',ready=False,
                        message=str(exc)[:350] if isinstance(exc,UserError) else 'No se pudo preparar el motor. Comprobá conexión, espacio y controladores; podés volver a intentar.')

    def _start(self,exe):
        if self.process and self.process.poll() is None:return
        # Never attach to an unknown process on the application's private port.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',11435))==0:raise UserError('El puerto del motor está ocupado. Cerrá la otra instancia y volvé a intentar.')
        env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_MODELS=str(self.directory/'models'),
            OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_KEEP_ALIVE='30m',OLLAMA_NO_CLOUD='1',
            OLLAMA_CONTEXT_LENGTH='4096')
        self.log=(self.directory/'engine.log').open('ab')
        self.process=subprocess.Popen([exe,'serve'],env=env,stdout=self.log,stderr=self.log,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(120):
            if self.stop.wait(.5):raise UserError('Preparación pausada.')
            if self.process.poll() is not None:raise UserError('El motor no pudo iniciar. Revisá el controlador gráfico o probá otro perfil.')
            try:read_json(BASE+'/api/version',2);return
            except Exception:continue
        raise UserError('El motor tardó demasiado en iniciar.')

    def pause(self):self.stop.set();return self.snapshot()

    def close(self):
        self.stop.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill()
        if self.thread:self.thread.join(timeout=2)
        if self.log:self.log.close()
