"""Extraction with stable references. No OCR, no silent truncation."""
import base64
import binascii
import hashlib
import io
import re
import zipfile
from pathlib import Path
from .domain import UserError

MAX_BYTES=8*1024*1024
MAX_CHARS=200000


def decode_upload(filename,encoded):
    if not isinstance(filename,str) or not isinstance(encoded,str): raise UserError('Archivo inválido.')
    try: data=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error): raise UserError('Contenido de archivo inválido.')
    if not data or len(data)>MAX_BYTES: raise UserError('El archivo debe tener entre 1 byte y 8 MB.')
    return extract(filename,data)


def extract(filename,data):
    name=Path(filename.replace('\\','/')).name[:180]
    ext=Path(name).suffix.lower()
    units=[];warnings=[]
    try:
        if ext in ('.txt','.md'):
            text=data.decode('utf-8-sig')
            for n,paragraph in enumerate(re.split(r'\n\s*\n',text),1):
                if paragraph.strip(): units.append((f'Párrafo {n}',paragraph.strip()))
        elif ext=='.pdf':
            try: from pypdf import PdfReader
            except ImportError: raise UserError('Falta el lector PDF. Ejecutá instalar.bat o usá TXT.')
            reader=PdfReader(io.BytesIO(data))
            if reader.is_encrypted: raise UserError('El PDF está protegido. Subí una copia sin contraseña.')
            if len(reader.pages)>100: raise UserError('Esta versión admite PDF de hasta 100 páginas.')
            for n,page in enumerate(reader.pages,1):
                text=page.extract_text() or ''
                if not text.strip(): warnings.append(f'Página {n} sin texto extraíble; podría requerir OCR.')
                else: units.append((f'Página {n}',text.strip()))
        elif ext=='.docx':
            try: from docx import Document
            except ImportError: raise UserError('Falta el lector DOCX. Ejecutá instalar.bat o usá TXT.')
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(x.file_size for x in archive.infolist())>40*1024*1024:
                    raise UserError('El DOCX expandido supera el límite de 40 MB.')
            doc=Document(io.BytesIO(data))
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            n=0
            for node in doc.element.body.iterchildren():
                n+=1
                if node.tag.endswith('}p'):
                    text=Paragraph(node,doc).text.strip()
                    if text: units.append((f'Bloque {n}',text))
                elif node.tag.endswith('}tbl'):
                    table=Table(node,doc)
                    text='\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows)
                    if text.strip(): units.append((f'Tabla en bloque {n}',text))
            warnings.append('DOCX: se leen cuerpo y tablas; no encabezados, pies ni cuadros de texto.')
        else: raise UserError('Usá TXT, Markdown, PDF digital o DOCX.')
    except UserError: raise
    except UnicodeDecodeError: raise UserError('El texto debe estar guardado en UTF-8.')
    except Exception: raise UserError('No se pudo leer el archivo. Comprobá su formato o exportalo a TXT.')
    count=sum(len(t) for _,t in units)
    if not count: raise UserError('No hay texto legible. Los documentos escaneados necesitan OCR, todavía no incluido.')
    if count>MAX_CHARS: raise UserError('El documento supera los 200.000 caracteres de esta alfa.')
    chunks=[]
    for location,text in units:
        # Preserve exact substring; overlap prevents simple boundaries losing terms.
        for offset in range(0,len(text),1300):
            segment=text[offset:offset+1500]
            chunks.append({'id':f's{len(chunks)+1}','location':location,'text':segment})
    return {'name':name,'sha256':hashlib.sha256(data).hexdigest(),'characters':count,
            'segments':chunks,'units':[{'location':l,'text':t} for l,t in units],
            'warnings':warnings,'format':ext[1:]}


def retrieve(document,query,max_chars=10000):
    # A transparent lexical baseline; semantic index is a later milestone.
    terms=set(re.findall(r'\w{3,}',query.casefold()))
    ranked=sorted(enumerate(document['segments']),key=lambda x:(-sum(t in x[1]['text'].casefold() for t in terms),x[0]))
    selected=[];used=0
    for _,s in ranked:
        if used+len(s['text'])>max_chars: continue
        selected.append(s);used+=len(s['text'])
    selected.sort(key=lambda s:int(s['id'][1:]))
    return selected
