"""Read Office XML and CSV without executing formulas, macros or embedded objects."""
import csv
import io
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from .domain import UserError

W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
S='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def office_archive(data):
    z=zipfile.ZipFile(io.BytesIO(data))
    if sum(x.file_size for x in z.infolist())>40*1024*1024:
        z.close();raise UserError('El documento expandido supera los 40 MB.')
    return z


def read_docx(data):
    units=[]
    with office_archive(data) as z:
        root=ET.fromstring(z.read('word/document.xml'));body=root.find(W+'body')
        if body is None:raise UserError('El documento no tiene un cuerpo legible.')
        def paragraph(p):
            pieces=[]
            for e in p.iter():
                if e.tag==W+'t':pieces.append(e.text or '')
                elif e.tag in (W+'br',W+'cr'):pieces.append('\n')
                elif e.tag==W+'tab':pieces.append('\t')
            return ''.join(pieces)
        for n,element in enumerate(body,1):
            if element.tag==W+'p':text=paragraph(element);location=f'Bloque {n}'
            elif element.tag==W+'tbl':
                rows=[]
                for row in element.findall(W+'tr'):
                    rows.append(' | '.join('\n'.join(paragraph(p) for p in cell.findall(W+'p')) for cell in row.findall(W+'tc')))
                text='\n'.join(rows);location=f'Tabla en bloque {n}'
            else:continue
            if text.strip():units.append((location,text.strip()))
    return units,['DOCX: se leen cuerpo y tablas; no encabezados, pies ni cuadros de texto.']


def read_csv(data):
    text=data.decode('utf-8-sig')
    try:dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
    except csv.Error:dialect=csv.excel
    rows=[]
    for n,row in enumerate(csv.reader(io.StringIO(text),dialect),1):
        if n>10000 or len(row)>200:raise UserError('La tabla supera 10.000 filas o 200 columnas.')
        if any(x.strip() for x in row):rows.append((f'Fila {n}',' | '.join(row)))
    return rows,[]


def read_xlsx(data):
    units=[];formulas=False;cells=0
    with office_archive(data) as z:
        workbook=ET.fromstring(z.read('xl/workbook.xml'))
        relations=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        mapping={e.attrib['Id']:e.attrib['Target'] for e in relations if e.attrib.get('TargetMode')!='External'}
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(S+'si')]
        sheets=workbook.find(S+'sheets')
        if sheets is None:raise UserError('El libro no contiene hojas legibles.')
        if len(sheets)>30:raise UserError('Se admiten hasta 30 hojas.')
        for sheet in sheets:
            target=mapping.get(sheet.attrib.get(R+'id'))
            if not target:continue
            path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not path.startswith('xl/worksheets/'):continue
            root=ET.fromstring(z.read(path))
            for row in root.iter(S+'row'):
                parts=[]
                for cell in row.findall(S+'c'):
                    cells+=1
                    if cells>25000:raise UserError('El libro supera las 25.000 celdas admitidas.')
                    t=cell.attrib.get('t');value=cell.findtext(S+'v','')
                    if t=='s':value=strings[int(value)] if value else ''
                    elif t=='inlineStr':value=''.join(cell.find(S+'is').itertext()) if cell.find(S+'is') is not None else ''
                    elif t=='b':value='verdadero' if value=='1' else 'falso'
                    if cell.find(S+'f') is not None:formulas=True;value=value or '[fórmula sin valor guardado]'
                    if value:parts.append(cell.attrib.get('r','')+': '+value)
                if parts:units.append((sheet.attrib.get('name','Hoja')+' · fila '+row.attrib.get('r','?'),' | '.join(parts)))
    warnings=['XLSX: se leen valores guardados, sin formatos, gráficos ni cálculo de fórmulas.']
    if formulas:warnings.append('Hay fórmulas: sus valores guardados podrían estar desactualizados. Recalculá y guardá el libro antes de subirlo.')
    return units,warnings
