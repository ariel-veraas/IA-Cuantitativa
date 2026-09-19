import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .domain import UserError


def now(): return datetime.now(timezone.utc).isoformat()
def month(): return datetime.now(timezone.utc).strftime('%Y-%m')


class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL,
              created TEXT NOT NULL, updated TEXT NOT NULL, payload TEXT NOT NULL,
              result TEXT NOT NULL, error TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
              criterion_id TEXT NOT NULL, month TEXT NOT NULL, amount INTEGER NOT NULL,
              state TEXT NOT NULL, usage TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS flags(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            c.execute("UPDATE jobs SET status='interrupted',error='La aplicación se cerró. Podés reanudar los pasos pendientes.' WHERE status IN ('running','queued')")
            c.execute("UPDATE ledger SET state='uncertain' WHERE state='reserved'")

    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()

    def add_document(self,doc):
        doc={**doc,'id':uuid.uuid4().hex,'created':now()}
        with self.db() as c:c.execute('INSERT INTO documents VALUES (?,?)',(doc['id'],json.dumps(doc,ensure_ascii=False)))
        return doc

    def document(self,id):
        with self.db() as c: row=c.execute('SELECT payload FROM documents WHERE id=?',(id,)).fetchone()
        if not row:raise UserError('Documento no encontrado.')
        return json.loads(row['payload'])

    def documents(self):
        with self.db() as c:rows=c.execute('SELECT payload FROM documents ORDER BY rowid DESC LIMIT 100').fetchall()
        return [{k:v for k,v in json.loads(r[0]).items() if k not in ('segments','units')} for r in rows]

    def create_job(self,payload):
        id=uuid.uuid4().hex
        result={'rows':[],'events':[]}
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=10:
                raise UserError('La cola tiene diez trabajos. Esperá a que termine alguno.')
            c.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',(id,'queued',now(),now(),json.dumps(payload,ensure_ascii=False),json.dumps(result),''))
        return self.job(id)

    def job(self,id):
        with self.db() as c:row=c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone()
        if not row:raise UserError('Trabajo no encontrado.')
        d=dict(row);d['payload']=json.loads(d['payload']);d['result']=json.loads(d['result']);return d

    def jobs(self):
        with self.db() as c:ids=c.execute('SELECT id FROM jobs ORDER BY created DESC LIMIT 50').fetchall()
        return [self.job(x[0]) for x in ids]

    def next_job(self):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:return None
            c.execute("UPDATE jobs SET status='running',updated=? WHERE id=?",(now(),row[0]))
        return self.job(row[0])

    def checkpoint(self,id,result,status=None,error=''):
        with self.db() as c:
            # A cancelled job must never become complete because a request finished late.
            if status:
                c.execute("UPDATE jobs SET result=?,status=CASE WHEN status='cancelled' THEN status ELSE ? END,updated=?,error=? WHERE id=?",
                          (json.dumps(result,ensure_ascii=False),status,now(),error,id))
            else:c.execute('UPDATE jobs SET result=?,updated=? WHERE id=?',(json.dumps(result,ensure_ascii=False),now(),id))

    def cancel(self,id):
        self.job(id)
        with self.db() as c:c.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=? AND status IN ('running','queued','interrupted')",(now(),id))

    def resume(self,id):
        with self.db() as c:
            cur=c.execute("UPDATE jobs SET status='queued',error='',updated=? WHERE id=? AND status IN ('interrupted','failed')",(now(),id))
            if not cur.rowcount:raise UserError('Solo se pueden reanudar trabajos interrumpidos o fallidos.')

    def has_cloud_attempt(self,job_id,cid):
        with self.db() as c:return bool(c.execute('SELECT 1 FROM ledger WHERE job_id=? AND criterion_id=?',(job_id,cid)).fetchone())

    def reserve(self,job_id,cid,amount,monthly_limit,job_limit):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM flags WHERE key='cloud_blocked'").fetchone():
                raise UserError('Se detectó una diferencia de facturación. Revisá el registro antes de habilitar nuevas llamadas.')
            if c.execute('SELECT 1 FROM ledger WHERE job_id=? AND criterion_id=?',(job_id,cid)).fetchone():
                raise UserError('Ya existe un intento externo para este criterio; no se repetirá automáticamente.')
            used=c.execute('SELECT coalesce(sum(amount),0) FROM ledger WHERE month=?',(month(),)).fetchone()[0]
            job_used=c.execute('SELECT coalesce(sum(amount),0) FROM ledger WHERE job_id=?',(job_id,)).fetchone()[0]
            if amount<=0 or used+amount>monthly_limit or job_used+amount>job_limit:
                raise UserError('El presupuesto disponible no alcanza para esta solicitud.')
            id=uuid.uuid4().hex
            c.execute('INSERT INTO ledger VALUES (?,?,?,?,?,?,?)',(id,job_id,cid,month(),amount,'reserved','{}'))
            return id

    def settle(self,id,actual,usage):
        with self.db() as c:
            row=c.execute('SELECT amount FROM ledger WHERE id=?',(id,)).fetchone()
            if actual>row[0]:
                c.execute("INSERT OR REPLACE INTO flags VALUES ('cloud_blocked','usage_exceeded_reservation')")
            c.execute("UPDATE ledger SET amount=?,state='settled',usage=? WHERE id=?",(actual,json.dumps(usage),id))

    def uncertain(self,id):
        with self.db() as c:c.execute("UPDATE ledger SET state='uncertain' WHERE id=?",(id,))

    def usage(self):
        with self.db() as c:
            rows=c.execute('SELECT * FROM ledger WHERE month=? ORDER BY rowid DESC',(month(),)).fetchall()
        items=[dict(r) for r in rows]
        return {'month_utc':month(),'accounted_usd':sum(r['amount'] for r in items)/1000000,
                'unconfirmed_usd':sum(r['amount'] for r in items if r['state']!='settled')/1000000,
                'calls':len(items),'ledger':items}
