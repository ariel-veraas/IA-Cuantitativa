"""Loopback-only development server. Deliberately not a shared production host."""
import argparse
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .app import Application
from .config import ROOT
from .domain import UserError
from .evaluator import markdown_report

MAX_BODY=12*1024*1024


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

    def do_GET(self):
        if not self.permitted():return
        url=urlsplit(self.path);path=url.path;app=self.server.app
        assets={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        if path in assets:
            file,mime=assets[path];return self.send(200,(ROOT/'iq'/'static'/file).read_bytes(),mime)
        if path=='/api/session':return self.send(200,{'token':self.server.session})
        if not self.authorized():return
        try:
            if path=='/api/state':return self.send(200,app.state())
            if path.startswith('/api/documents/'):
                return self.send(200,app.store.document(path.split('/')[-1]))
            if path.startswith('/api/jobs/') and path.endswith('/export'):
                job=app.store.job(path.split('/')[-2]);fmt=parse_qs(url.query).get('format',['md'])[0]
                if fmt=='json':return self.send(200,job,attachment=f'evaluacion-{job["id"][:8]}.json')
                return self.send(200,markdown_report(job),'text/markdown; charset=utf-8',f'evaluacion-{job["id"][:8]}.md')
            self.send(404,{'error':'Ruta no encontrada.'})
        except UserError as exc:self.send(404,{'error':str(exc)})

    def do_POST(self):
        if not self.permitted() or not self.authorized():return
        try:
            if self.headers.get('Transfer-Encoding'):raise UserError('Transferencia no admitida.')
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>MAX_BODY:return self.send(413,{'error':'Solicitud vacía o demasiado grande.'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise UserError('Usá JSON.')
            raw=self.rfile.read(length)
            if len(raw)!=length:raise UserError('Solicitud incompleta.')
            data=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(data,dict):raise UserError('Solicitud inválida.')
            app=self.server.app;path=urlsplit(self.path).path
            if path=='/api/documents':return self.send(201,app.add_document(data))
            if path=='/api/demo':return self.send(201,app.demo())
            if path=='/api/jobs':return self.send(201,app.submit(data))
            if path=='/api/settings/local':return self.send(200,app.configure_local(data))
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
    parser=argparse.ArgumentParser(description='IA Cuantitativa — alfa local')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--data-dir')
    args=parser.parse_args()
    try:server=create_server(args.port,args.data_dir)
    except (OSError,ValueError) as exc:parser.exit(1,f'No se pudo iniciar: {exc}\n')
    url=f'http://127.0.0.1:{server.server_port}'
    print(f'IA Cuantitativa 0.1 — {url}\nCerrá con Ctrl+C. Los datos quedan en este equipo.',flush=True)
    if not args.no_browser:threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.app.close();server.server_close()


if __name__=='__main__':main()
