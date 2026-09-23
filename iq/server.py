"""Loopback-only desktop server. Not a shared production host."""
import argparse
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .app import Application
from .config import ROOT
from .domain import UserError
from .evaluator import markdown_report
from .conversation import conversation_report

MAX_BODY=12*1024*1024


def integration_view(job):
    res=job['result'] if isinstance(job.get('result'),dict) else {}
    return {'status':job['status'],'job_id':job['id'],
            'conversation_id':job.get('payload',{}).get('conversation_id'),
            'answer':res.get('answer',''),'needs_help':res.get('needs_help'),
            'provider':res.get('provider'),'escalated':res.get('provider') in ('gemini','gemini-search'),
            'reasoning':res.get('reasoning',False),'web_search_used':res.get('web_search_used',False),
            'evidence':res.get('evidence',[]),'warnings':res.get('warnings',[]),
            'error':job.get('error','')}


class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'

    def log_message(self,*args):pass

    def setup(self):
        super().setup();self.connection.settimeout(15)

    def send(self,status,data,content_type='application/json; charset=utf-8',attachment=None):
        if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        elif isinstance(data,str):data=data.encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if attachment:self.send_header('Content-Disposition',f'attachment; filename="{attachment}"')
        self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass

    def permitted(self):
        port=self.server.server_port
        allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
        if self.headers.get('Host') not in allowed:
            self.send(403,{'error':'Host no permitido.'});return False
        origin=self.headers.get('Origin')
        if origin and origin not in {f'http://{x}' for x in allowed}:
            self.send(403,{'error':'Origen no permitido.'});return False
        return True

    def authorized(self):
        if not secrets.compare_digest(self.headers.get('X-IQ-Session',''),self.server.session):
            self.send(403,{'error':'La sesión venció. Recargá la página.'});return False
        return True

    def integration_authorized(self):
        if not self.server.app.integration_key_matches(self.headers.get('X-IQ-Api-Key','')):
            self.send(403,{'error':'Clave de integración inválida o no generada. Generala desde Configuración → Integraciones.'});return False
        return True

    def do_GET(self):
        if not self.permitted():return
        url=urlsplit(self.path);path=url.path;app=self.server.app
        assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        assets.update({'/evaluate':('evaluate.html','text/html; charset=utf-8'),'/workspace.js':('workspace.js','text/javascript; charset=utf-8'),'/workspace.css':('workspace.css','text/css; charset=utf-8')})
        if path in assets:
            file,mime=assets[path];return self.send(200,(ROOT/'iq'/'static'/file).read_bytes(),mime)
        if path=='/api/session':return self.send(200,{'token':self.server.session})
        if path=='/api/health':return self.send(200,{'application':'ia-cuantitativa','version':'1.0.0'})
        if path.startswith('/api/integration/status/'):
            if not self.integration_authorized():return
            try:return self.send(200,integration_view(app.store.job(path.split('/')[-1])))
            except UserError as exc:return self.send(404,{'error':str(exc)})
        if not self.authorized():return
        try:
            if path=='/api/state':return self.send(200,app.state())
            if path=='/api/integration/key':return self.send(200,app.integration_key())
            if path=='/api/hardware':
                from .diagnostics import hardware
                return self.send(200,hardware())
            if path=='/api/backup':
                import tempfile,sqlite3,zipfile,io
                with tempfile.TemporaryDirectory() as directory:
                    target=ROOT.__class__(directory)/'iq.sqlite3'
                    with app.store.db() as source:
                        destination=sqlite3.connect(target)
                        try:source.backup(destination)
                        finally:destination.close()
                    content=io.BytesIO()
                    with zipfile.ZipFile(content,'w',compression=zipfile.ZIP_DEFLATED) as z:z.write(target,'iq.sqlite3')
                return self.send(200,content.getvalue(),'application/zip',attachment='ia-cuantitativa-respaldo.zip')
            if path.startswith('/api/conversations/'):
                return self.send(200,app.capabilities.conversation(path.split('/')[-1]))
            if path.startswith('/api/capabilities/') and path.endswith('/examples'):
                return self.send(200,app.capabilities.examples(path.split('/')[-2]))
            if path.startswith('/api/jobs/') and not path.endswith('/export'):
                return self.send(200,app.store.job(path.split('/')[-1]))
            if path.startswith('/api/documents/'):
                return self.send(200,app.store.document(path.split('/')[-1]))
            if path.startswith('/api/jobs/') and path.endswith('/export'):
                job=app.store.job(path.split('/')[-2]);fmt=parse_qs(url.query).get('format',['md'])[0]
                if fmt=='json':return self.send(200,job,attachment=f'evaluacion-{job["id"][:8]}.json')
                report=conversation_report(job) if job['payload'].get('kind')=='conversation' else markdown_report(job)
                return self.send(200,report,'text/markdown; charset=utf-8',f'informe-{job["id"][:8]}.md')
            self.send(404,{'error':'Ruta no encontrada.'})
        except UserError as exc:self.send(404,{'error':str(exc)})

    def read_json_body(self):
        if self.headers.get('Transfer-Encoding'):raise UserError('Transferencia no admitida.')
        length=int(self.headers.get('Content-Length','0'))
        if length<=0 or length>MAX_BODY:raise UserError('Solicitud vacía o demasiado grande.')
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise UserError('Usá JSON.')
        raw=self.rfile.read(length)
        if len(raw)!=length:raise UserError('Solicitud incompleta.')
        data=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data,dict):raise UserError('Solicitud inválida.')
        return data

    def handle_integration_ask(self):
        if not self.integration_authorized():return
        try:
            data=self.read_json_body()
            app=self.server.app
            wait_seconds=data.pop('wait_seconds',60)
            if type(wait_seconds) is not int or not 5<=wait_seconds<=120:raise UserError('wait_seconds debe ser un entero entre 5 y 120.')
            data.setdefault('allow_cloud',app.config.cloud_enabled)
            job=app.chat(data)
            deadline=time.monotonic()+wait_seconds
            current=job
            while time.monotonic()<deadline and current['status'] in ('queued','running'):
                time.sleep(0.3);current=app.store.job(job['id'])
            self.send(200,integration_view(current))
        except (UserError,ValueError,TypeError,UnicodeDecodeError) as exc:self.send(400,{'error':str(exc) if isinstance(exc,UserError) else 'Revisá los datos enviados.'})
        except Exception:self.send(500,{'error':'No se pudo completar la operación. Los trabajos guardados se conservan.'})

    def do_POST(self):
        if not self.permitted():return
        if urlsplit(self.path).path=='/api/integration/ask':return self.handle_integration_ask()
        if not self.authorized():return
        try:
            data=self.read_json_body()
            app=self.server.app;path=urlsplit(self.path).path
            if path=='/api/documents':return self.send(201,app.add_document(data))
            if path=='/api/demo':return self.send(201,app.demo())
            if path=='/api/jobs':return self.send(201,app.submit(data))
            if path=='/api/settings/local':return self.send(200,app.configure_local(data))
            if path=='/api/settings/cloud':return self.send(200,app.configure_cloud(data))
            if path=='/api/chat':return self.send(201,app.chat(data))
            if path=='/api/engine/prepare':return self.send(202,app.engine.prepare(data.get('profile','balanced')))
            if path=='/api/engine/pause':return self.send(200,app.engine.pause())
            if path=='/api/capabilities':return self.send(201,app.capabilities.save(data))
            if path=='/api/capabilities/activate':return self.send(200,app.capabilities.activate(data.get('id'),data.get('version')))
            if path=='/api/capabilities/examples':return self.send(201,app.add_capability_example(data))
            if path=='/api/capabilities/improve':return self.send(201,app.improve_capability(data))
            if path=='/api/integration/key/rotate':return self.send(200,app.rotate_integration_key())
            if path=='/api/integration/key/revoke':return self.send(200,app.revoke_integration_key())
            if path=='/api/documents/delete':return self.send(200,app.delete_document(data.get('id')))
            if path=='/api/conversations/delete':return self.send(200,app.delete_conversation(data.get('id')))
            if path=='/api/shutdown':
                self.send(200,{'closing':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            if path.startswith('/api/jobs/'):
                parts=path.split('/');id=parts[-2]
                if parts[-1]=='cancel':app.store.cancel(id);return self.send(200,app.store.job(id))
                if parts[-1]=='resume':app.store.resume(id);app.wake.set();return self.send(200,app.store.job(id))
            self.send(404,{'error':'Ruta no encontrada.'})
        except (UserError,ValueError,TypeError,UnicodeDecodeError) as exc:self.send(400,{'error':str(exc) if isinstance(exc,UserError) else 'Revisá los datos enviados.'})
        except Exception:self.send(500,{'error':'No se pudo completar la operación. Los trabajos guardados se conservan.'})


def create_server(port=8765,data_dir=None,config=None):
    # Bind before opening storage: a second launch on the same port cannot alter jobs.
    server=Server(('127.0.0.1',port),Handler)
    try:server.app=Application(data_dir,config)
    except Exception:server.server_close();raise
    server.session=secrets.token_urlsafe(32)
    return server


def main():
    parser=argparse.ArgumentParser(description='IA Cuantitativa — asistente local')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--data-dir')
    args=parser.parse_args()
    try:server=create_server(args.port,args.data_dir)
    except (OSError,ValueError) as exc:parser.exit(1,f'No se pudo iniciar: {exc}\n')
    url=f'http://127.0.0.1:{server.server_port}'
    print(f'IA Cuantitativa 1.0 — {url}\nCerrá desde la aplicación o con Ctrl+C.',flush=True)
    if not args.no_browser:threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.app.close();server.server_close()


if __name__=='__main__':main()
