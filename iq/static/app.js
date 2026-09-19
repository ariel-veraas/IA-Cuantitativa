let token='',state=null,selectedJob=null,timer=null,nextId=1;
const $=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const labels={queued:'En cola',running:'Evaluando',completed:'Evaluación terminada',cancelled:'Cancelada',interrupted:'Interrumpida',failed:'Falló'};
const verdict={meets:'Cumple el criterio',does_not_meet:'No cumple el criterio',needs_review:'Necesita revisión'};
function notice(message,error=false){$('notice').textContent=message;$('notice').className=error?'error':'';$('notice').hidden=false;}
async function api(path,body){const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-IQ-Session':token},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'No se pudo completar la operación.');return data;}
function guarded(fn){return async(...args)=>{try{await fn(...args);}catch(e){notice(e.message,true);}};}
function view(name){document.querySelectorAll('.view').forEach(n=>n.hidden=n.id!=='view-'+name);document.querySelectorAll('.nav').forEach(n=>{n.classList.toggle('active',n.dataset.view===name);if(n.dataset.view===name)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});}
function field(parent,label,node){const id='field-'+nextId++;node.id=id;const l=el('label',label);l.htmlFor=id;parent.append(l,node);return node;}
function input(value='',type='text'){const n=el('input');n.type=type;n.value=value;return n;}
function select(options,value){const n=el('select');for(const [v,l] of options){const o=el('option',l);o.value=v;n.append(o);}n.value=value;return n;}
function addCriterion(c={}){
 if($('criteria').children.length>=15)return notice('Podés usar hasta 15 criterios.',true);
 const box=el('div',undefined,'criterion');box.dataset.cid=c.id||'criterio-'+nextId++;
 const top=el('div',undefined,'criterion-top');top.append(el('strong','CRITERIO'));const rm=el('button','Quitar','remove');rm.type='button';rm.onclick=()=>box.remove();top.append(rm);box.append(top);
 const title=field(box,'Qué querés comprobar',input(c.label||''));title.maxLength=500;title.dataset.key='label';
 const grid=el('div',undefined,'criterion-grid');box.append(grid);const left=el('div'),right=el('div');grid.append(left,right);
 const kind=field(left,'Tipo',select([['phrase','Presencia de una frase'],['number_max','Valor máximo explícito'],['semantic','Interpretación con IA']],c.kind||'semantic'));kind.dataset.key='kind';
 const weight=field(right,'Peso',input(c.weight||10,'number'));weight.min=1;weight.max=100;weight.dataset.key='weight';
 const options=el('div');box.append(options);
 function optionsForKind(){options.replaceChildren();
  if(kind.value==='phrase'){const p=field(options,'Frase a encontrar (solo presencia literal)',input(c.phrase||''));p.dataset.key='phrase';}
  if(kind.value==='number_max'){const g=el('div',undefined,'criterion-subgrid');options.append(g);for(const [key,label,v] of [['field','Campo',c.field||''],['unit','Unidad',c.unit||''],['maximum','Máximo',c.maximum??'']]){const d=el('div');g.append(d);const p=field(d,label,input(v,key==='maximum'?'number':'text'));p.dataset.key=key;if(key==='maximum'){p.min=0;p.step='any';}}}
 }
 kind.onchange=optionsForKind;optionsForKind();
 const required=el('label',undefined,'check');const chk=input('','checkbox');chk.checked=!!c.required;chk.dataset.key='required';required.append(chk,el('span','Obligatorio'));box.append(required);$('criteria').append(box);
}
function readRubric(){return {name:$('rubric-name').value,criteria:[...$('criteria').children].map(box=>{const c={id:box.dataset.cid};box.querySelectorAll('[data-key]').forEach(n=>c[n.dataset.key]=n.type==='checkbox'?n.checked:n.dataset.key==='weight'?Number(n.value):n.value);return c;})};}
function loadRubric(r){if(!r||!Array.isArray(r.criteria)||r.criteria.length>15)throw Error('Rúbrica inválida.');$('rubric-name').value=r.name||'';$('criteria').replaceChildren();r.criteria.forEach(addCriterion);}
function download(blob,name){const u=URL.createObjectURL(blob);const a=el('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),5000);}
async function exportJob(id,format){const r=await fetch(`/api/jobs/${id}/export?format=${format}`,{headers:{'X-IQ-Session':token}});if(!r.ok)throw Error('No se pudo exportar.');download(await r.blob(),`evaluacion-${id.slice(0,8)}.${format}`);}
function docInfo(){const d=state.documents.find(x=>x.id===$('documents').value);$('doc-info').replaceChildren();if(d){$('doc-info').append(el('p',`${d.characters.toLocaleString('es-AR')} caracteres · ${d.format.toUpperCase()}`));for(const w of d.warnings)$('doc-info').append(el('p',w,'warning'));}}
function renderResult(job){
 $('empty-result').hidden=!!job;$('result').hidden=!job;$('result').replaceChildren();if(!job){$('job-status').textContent='Sin evaluación';return;}
 $('job-status').textContent=labels[job.status];const r=job.result,s=r.summary;
 if(s){const score=el('div',undefined,'score-box');const num=el('div',String(s.score_min),'score');num.append(el('small',' / 100'));score.append(el('p',r.review_required?'PUNTAJE PRELIMINAR':'PUNTAJE SEGÚN CRITERIOS','eyebrow'),num,el('p',`Hasta ${s.score_max} puntos si se resuelven los pendientes.`));if(s.pending_weight)score.append(el('p',`${s.pending_weight} de ${s.total_weight} unidades de peso pendientes.`));$('result').append(score);}
 if(job.error)$('result').append(el('p',job.error,'warning'));
 if(job.status==='running'||job.status==='queued'){
  const p=el('p',`${r.rows.length} de ${job.payload.rubric.criteria.length} criterios procesados. Una llamada en curso puede tardar hasta ${job.payload.config.timeout_seconds} segundos.`,'hint');$('result').append(p);
 }
 const actions=el('div',undefined,'result-actions');
 for(const fmt of ['md','json']){const b=el('button',fmt==='md'?'Descargar informe':'Descargar registro','secondary small');b.onclick=guarded(()=>exportJob(job.id,fmt));actions.append(b);}
 if(['queued','running'].includes(job.status)){const b=el('button','Cancelar','link');b.onclick=guarded(async()=>{await api(`/api/jobs/${job.id}/cancel`,{});await refresh();});actions.append(b);}
 if(['interrupted','failed'].includes(job.status)){const b=el('button','Reanudar','primary small');b.onclick=guarded(async()=>{await api(`/api/jobs/${job.id}/resume`,{});await refresh();});actions.append(b);}
 $('result').append(actions);
 if(r.rows.some(x=>x.review_required))$('result').append(el('p','Los criterios interpretados por IA son preliminares: comprobar una cita no garantiza que la conclusión sea correcta.','warning'));
 for(const row of r.rows){const card=el('article',undefined,'result-row');card.append(el('span',verdict[row.status],'tag '+row.status),el('h3',row.label),el('p',row.explanation));
  const method={rule:'Regla calculada',local:'Modelo local',gemini:'Gemini',pending:'Pendiente'}[row.method]||row.method;
  card.append(el('p',`${method} · ${row.elapsed_seconds??0} s`,'muted'));
  for(const ev of row.evidence){const d=el('details');d.append(el('summary','Ver fuente · '+ev.location),el('blockquote',ev.quote));card.append(d);}
  if(row.context)card.append(el('p',`${row.context.selected_characters.toLocaleString('es-AR')} caracteres seleccionados para este criterio. No equivale a tokens facturados.`,'hint'));
  $('result').append(card);
 }
 if(r.elapsed_seconds!==undefined)$('result').append(el('p',`Procesamiento: ${r.elapsed_seconds} s · Skill ${job.payload.skill.version}`,'hint'));
}
function renderActivity(){const list=$('activity-list');list.replaceChildren();if(!state.jobs.length)list.append(el('div','Todavía no hay evaluaciones. Empezá con el documento de ejemplo.','card'));
 for(const j of state.jobs){const box=el('div',undefined,'card activity-row'),info=el('div');info.append(el('strong',j.payload.rubric.name),el('p',`${labels[j.status]} · ${new Date(j.created).toLocaleString('es-AR')}`,'muted'));const b=el('button','Ver evaluación','secondary small');b.onclick=()=>{selectedJob=j.id;renderResult(j);view('evaluate');window.scrollTo(0,0);};box.append(info,b);list.append(box);}}
function renderState(){
 const selection=$('documents').value;$('documents').replaceChildren();const empty=el('option','Seleccioná un documento');empty.value='';$('documents').append(empty);for(const d of state.documents){const n=el('option',d.name);n.value=d.id;$('documents').append(n);}if(state.documents.some(d=>d.id===selection))$('documents').value=selection;docInfo();
 $('engine-status').textContent=state.config.local_enabled?'Modelo local habilitado':'Modo de reglas · sin modelo';
 $('mode').querySelector('[value=local]').disabled=!state.config.local_enabled;
 if(!state.config.local_enabled)$('mode').value='rules';
 $('cloud').disabled=!(state.config.cloud_enabled&&state.gemini_key_present);if($('cloud').disabled)$('cloud').checked=false;
 $('cloud-info').textContent=$('cloud').disabled?'La asistencia externa está desactivada o falta la clave.':`Se enviarán criterios y fragmentos a Google. Límite por trabajo: USD ${state.config.per_job_budget_usd}.`;
 renderResult(state.jobs.find(j=>j.id===selectedJob));renderActivity();
 $('external-status').textContent=state.config.cloud_enabled?'Gemini habilitado; cada trabajo requiere marcar la opción de asistencia.':'Gemini está apagado. No se envían archivos a proveedores externos.';
 $('usage').replaceChildren(el('p',`Uso contabilizado este mes: USD ${state.usage.accounted_usd.toFixed(6)}`),el('p',`Reservas sin consumo confirmado: USD ${state.usage.unconfirmed_usd.toFixed(6)}`),el('p',`Solicitudes generativas registradas: ${state.usage.calls}`));
}
async function refresh(){state=await api('/api/state');state.jobs=state.jobs.filter(j=>j.payload.rubric);renderState();clearTimeout(timer);if(state.jobs.some(j=>['running','queued'].includes(j.status)))timer=setTimeout(guarded(refresh),900);}
async function fileToBase64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('No se pudo leer el archivo.'));reader.readAsDataURL(file);});}
document.querySelectorAll('.nav').forEach(n=>n.onclick=()=>view(n.dataset.view));
$('add-criterion').onclick=()=>addCriterion();$('documents').onchange=docInfo;
$('demo').onclick=guarded(async()=>{const r=await api('/api/demo',{});loadRubric(r.rubric);await refresh();$('documents').value=r.document.id;docInfo();notice('Ejemplo listo. Las reglas resuelven tres criterios; el cuarto necesita interpretación.');});
$('file').onchange=guarded(async()=>{const f=$('file').files[0];if(!f)return;if(f.size>8*1024*1024)throw Error('El archivo supera los 8 MB.');notice('Leyendo el documento…');const d=await api('/api/documents',{filename:f.name,base64:await fileToBase64(f)});await refresh();$('documents').value=d.id;docInfo();notice('Documento listo para evaluar.');});
$('save-text').onclick=guarded(async()=>{const d=await api('/api/documents',{text:$('paste').value});await refresh();$('documents').value=d.id;docInfo();notice('Texto guardado.');});
$('evaluate').onclick=guarded(async()=>{if(!$('documents').value)throw Error('Elegí un documento antes de evaluar.');$('evaluate').disabled=true;try{const j=await api('/api/jobs',{document_id:$('documents').value,rubric:readRubric(),mode:$('mode').value,allow_cloud:$('cloud').checked});selectedJob=j.id;await refresh();notice('Evaluación creada. Podés seguir el resultado a la derecha.');}finally{$('evaluate').disabled=false;}});
$('save-rubric').onclick=()=>download(new Blob([JSON.stringify(readRubric(),null,2)],{type:'application/json'}),'mi-rubrica.json');
$('import-button').onclick=()=>$('rubric-file').click();$('rubric-file').onchange=guarded(async()=>{const f=$('rubric-file').files[0];if(f){if(f.size>100000)throw Error('La rúbrica es demasiado grande.');loadRubric(JSON.parse(await f.text()));notice('Rúbrica importada.');}});
$('local-settings').onsubmit=guarded(async(e)=>{e.preventDefault();await api('/api/settings/local',{enabled:$('local-enabled').checked,url:$('local-url').value,model:$('local-model').value});await refresh();notice('Conexión guardada. Se usará en las próximas evaluaciones.');});
guarded(async()=>{token=(await(await fetch('/api/session')).json()).token;await refresh();$('local-url').value=state.config.local_url;$('local-model').value=state.config.local_model;$('local-enabled').checked=state.config.local_enabled;for(const skill of state.skills){const card=el('div',undefined,'card');card.append(el('span','INSTALADA · '+skill.version,'tag meets'),el('h2',skill.display_name),el('p',skill.description));$('skill-list').append(card);}addCriterion({label:'El documento describe las condiciones del servicio',kind:'semantic',weight:100});})();
