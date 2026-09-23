"""Conector de referencia: IA Cuantitativa contestando correos por IMAP.

Este script es "otra cosa que estás desarrollando" en los términos de la
propia app: un programa aparte, en esta misma computadora, que le manda
pedidos al cerebro local a través de /api/integration/ask y usa la
decisión que le devuelve (si lo resolvió solo o si hacía falta ayuda).

Nunca manda un correo solo. Por cada correo nuevo sin leer, arma un
borrador en la carpeta de borradores del propio buzón (IMAP APPEND) y lo
deja para que una persona lo revise, lo edite si hace falta, y lo mande
ella misma desde su cliente de correo habitual. Ese es el límite
deliberado: la app decide y redacta, la persona manda.

Uso:
  1. Copiá config.example.json a config.json y completá tus datos de IMAP
     y la clave de integración generada en Configuración -> Integraciones.
  2. python integrations/asistente_email.py --config integrations/config.json

Pensado como plantilla: un conector para WhatsApp, un sistema de tickets o
un CRM tiene la misma forma -- reemplazar solo cómo se leen los mensajes
entrantes y cómo se entrega el borrador, no la llamada a ask_brain().
"""
import argparse
import email
import imaplib
import json
import time
from email.header import decode_header, make_header
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def ask_brain(api_base, api_key, message, wait_seconds=60):
    """Le manda el pedido al cerebro local y devuelve su decisión ya resuelta."""
    body = json.dumps({'message': message[:6000], 'wait_seconds': wait_seconds}).encode()
    req = Request(api_base.rstrip('/') + '/api/integration/ask', data=body,
                  headers={'Content-Type': 'application/json', 'X-IQ-Api-Key': api_key})
    try:
        with urlopen(req, timeout=wait_seconds + 10) as r:
            return json.loads(r.read())
    except HTTPError as e:
        try:detail = json.loads(e.read()).get('error', str(e))
        except Exception:detail = str(e)
        return {'status': 'error', 'error': detail}
    except URLError as e:
        return {'status': 'error', 'error': f'No se pudo conectar con IA Cuantitativa: {e.reason}'}


def decode(value):
    if not value:return ''
    return str(make_header(decode_header(value)))


def plain_text(msg: Message):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain' and 'attachment' not in str(part.get('Content-Disposition', '')):
                charset = part.get_content_charset() or 'utf-8'
                return part.get_payload(decode=True).decode(charset, errors='replace')
        return ''
    charset = msg.get_content_charset() or 'utf-8'
    return msg.get_payload(decode=True).decode(charset, errors='replace')


def build_draft(original_subject, original_from, decision):
    """A partir de la decisión del cerebro, arma el asunto y cuerpo del borrador."""
    if decision.get('status') == 'error':
        subject = '[NO SE PUDO PROCESAR] Re: ' + original_subject
        body = 'IA Cuantitativa no pudo procesar este correo: ' + decision.get('error', 'error desconocido')
        return subject, body
    needs_help = decision.get('needs_help', True)
    prefix = '[REVISAR] ' if needs_help else '[BORRADOR LISTO] '
    subject = prefix + 'Re: ' + original_subject
    lines = []
    if needs_help:
        lines.append('La IA no pudo resolver esto sola. Quedó como punto de partida, redactalo vos.')
    elif decision.get('escalated'):
        lines.append('Esta respuesta la terminó de armar Gemini porque el motor local pidió ayuda.')
    lines.append('')
    lines.append(decision.get('answer', ''))
    return subject, '\n'.join(lines)


def append_draft(imap, drafts_folder, to_addr, subject, body):
    msg = email.message.EmailMessage()
    msg['Subject'] = subject
    msg['To'] = to_addr
    msg.set_content(body)
    imap.append(drafts_folder, '\\Draft', imaplib.Time2Internaldate(time.time()), msg.as_bytes())


def run_once(cfg):
    imap = imaplib.IMAP4_SSL(cfg['imap_host'], cfg.get('imap_port', 993))
    imap.login(cfg['imap_user'], cfg['imap_password'])
    imap.select(cfg.get('inbox_folder', 'INBOX'))
    status, data = imap.search(None, 'UNSEEN')
    if status != 'OK':
        imap.logout();raise RuntimeError('No se pudo leer el buzón: ' + status)
    processed = 0
    for num in data[0].split():
        status, raw = imap.fetch(num, '(RFC822)')
        if status != 'OK':continue
        msg = email.message_from_bytes(raw[0][1])
        subject = decode(msg.get('Subject', '(sin asunto)'))
        sender = decode(msg.get('From', ''))
        text = plain_text(msg).strip()
        if not text:
            imap.store(num, '+FLAGS', '\\Seen');continue
        decision = ask_brain(cfg['api_base'], cfg['api_key'], f'Correo de {sender}, asunto "{subject}":\n\n{text}',
                              cfg.get('wait_seconds', 60))
        draft_subject, draft_body = build_draft(subject, sender, decision)
        append_draft(imap, cfg.get('drafts_folder', 'Drafts'), sender, draft_subject, draft_body)
        imap.store(num, '+FLAGS', '\\Seen')
        processed += 1
    imap.logout()
    return processed


def main():
    parser = argparse.ArgumentParser(description='Contesta correos nuevos armando borradores con IA Cuantitativa.')
    parser.add_argument('--config', required=True, help='Ruta a un JSON con imap_host, imap_user, imap_password, api_base, api_key.')
    parser.add_argument('--loop-seconds', type=int, default=0, help='Si se pasa, repite cada N segundos en vez de correr una sola vez.')
    args = parser.parse_args()
    with open(args.config, encoding='utf-8') as f:cfg = json.load(f)
    while True:
        try:
            n = run_once(cfg)
            print(f'{n} correo(s) nuevo(s) procesados. Borradores listos para revisar.', flush=True)
        except Exception as e:
            print(f'No se pudo completar esta pasada: {e}', flush=True)
        if not args.loop_seconds:break
        time.sleep(args.loop_seconds)


if __name__ == '__main__':main()
