"""Extraction with stable references. No OCR, no silent truncation."""
import base64
import binascii
import hashlib
import io
import math
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
        elif ext in ('.docx','.csv','.xlsx'):
            from .office import read_docx,read_csv,read_xlsx
            units,warnings={'.docx':read_docx,'.csv':read_csv,'.xlsx':read_xlsx}[ext](data)
        else: raise UserError('Usá TXT, Markdown, PDF digital, DOCX, CSV o XLSX.')
    except UserError: raise
    except UnicodeDecodeError: raise UserError('El texto debe estar guardado en UTF-8.')
    except Exception: raise UserError('No se pudo leer el archivo. Comprobá su formato o exportalo a TXT.')
    count=sum(len(t) for _,t in units)
    if not count: raise UserError('No hay texto legible. Los documentos escaneados necesitan OCR, todavía no incluido.')
    if count>MAX_CHARS: raise UserError('El documento supera los 200.000 caracteres admitidos.')
    chunks=[]
    for location,text in units:
        # Preserve exact substring; overlap prevents simple boundaries losing terms.
        for offset in range(0,len(text),1300):
            segment=text[offset:offset+1500]
            chunks.append({'id':f's{len(chunks)+1}','location':location,'text':segment})
    return {'name':name,'sha256':hashlib.sha256(data).hexdigest(),'characters':count,
            'segments':chunks,'units':[{'location':l,'text':t} for l,t in units],
            'warnings':warnings,'format':ext[1:]}


def _terms(text):
    return re.findall(r'\w{3,}',text.casefold())


def _bm25_scores(segments,query_terms,k1=1.5,b=0.75):
    # Standard Okapi BM25 over whole-word matches (word boundaries via \w{3,}), scoped
    # to this document's own segments — not a corpus-wide index. Replaces the previous
    # naive substring count, which could match a query term inside an unrelated word.
    if not query_terms:return [0.0]*len(segments)
    doc_terms=[_terms(s['text']) for s in segments]
    lengths=[len(t) for t in doc_terms]
    avg_len=(sum(lengths)/len(lengths)) if lengths else 0.0
    n=len(segments);df={}
    for terms in doc_terms:
        for t in set(terms)&query_terms:df[t]=df.get(t,0)+1
    idf={t:math.log((n-df.get(t,0)+0.5)/(df.get(t,0)+0.5)+1) for t in query_terms}
    scores=[]
    for terms,length in zip(doc_terms,lengths):
        counts={}
        for t in terms:
            if t in query_terms:counts[t]=counts.get(t,0)+1
        norm=(length/avg_len) if avg_len else 1.0
        scores.append(sum(idf[t]*(tf*(k1+1))/(tf+k1*(1-b+b*norm)) for t,tf in counts.items()))
    return scores


def _cosine(a,b):
    if not a or not b or len(a)!=len(b):return None
    dot=sum(x*y for x,y in zip(a,b));na=math.sqrt(sum(x*x for x in a));nb=math.sqrt(sum(y*y for y in b))
    return (dot/(na*nb)) if na and nb else 0.0


def retrieve(document,query,max_chars=10000,provider=None,rerank_top=8):
    """Rank segments by BM25 (lexical, whole-document-local), then — only when `provider`
    has a configured embedding model — re-rank the top BM25 candidates by embedding
    cosine similarity. The optional step is a single batched embedding call (query plus
    up to `rerank_top` candidates), never one call per fragment, so turning it on cannot
    multiply model calls per request. With no embedding model configured (the default),
    behavior is pure BM25 and no extra network call happens."""
    segments=document['segments']
    query_terms=set(_terms(query))
    scores=_bm25_scores(segments,query_terms)
    ranked=sorted(range(len(segments)),key=lambda i:(-scores[i],i))
    if provider is not None and query_terms and len(ranked)>1:
        candidates=ranked[:min(rerank_top,len(ranked))]
        vectors=provider.embed([query]+[segments[i]['text'] for i in candidates])
        if vectors and len(vectors)==len(candidates)+1:
            qvec=vectors[0]
            order=sorted(range(len(candidates)),key=lambda k:-(_cosine(qvec,vectors[k+1]) or -1))
            reordered=[candidates[k] for k in order]
            ranked=reordered+[i for i in ranked if i not in candidates]
    selected=[];used=0
    for i in ranked:
        s=segments[i]
        if used+len(s['text'])>max_chars: continue
        selected.append(s);used+=len(s['text'])
    selected.sort(key=lambda s:int(s['id'][1:]))
    return selected
