// Optional browser check. Start the app first with a disposable --data-dir.
// Requires a developer installation of Playwright plus its Chromium browser.
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES,'playwright') : 'playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];let dialogs=0;
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',async d=>{dialogs++;await d.dismiss();});
  await page.goto(process.env.IQ_TEST_URL||'http://127.0.0.1:8765/evaluate');
  await page.waitForFunction(()=>document.querySelector('#criteria').children.length===1);
  await page.locator('#demo').click();
  await page.waitForFunction(()=>document.querySelector('#criteria').children.length===4);
  await page.locator('#evaluate').click();
  await page.waitForFunction(()=>document.querySelector('#job-status').textContent==='Evaluación terminada');
  assert.match(await page.locator('.score').innerText(),/70/);
  assert.equal(await page.locator('.result-row').count(),4);
  assert.equal(await page.locator('.result-row .needs_review').count(),1);
  await page.locator('.result-row summary').first().click();
  assert.match(await page.locator('.result-row blockquote').first().innerText(),/soporte/i);
  const downloaded=page.waitForEvent('download');
  await page.getByRole('button',{name:'Descargar informe',exact:true}).click();
  const dl=await downloaded;assert.match(fs.readFileSync(await dl.path(),'utf8'),/Fuente:/);
  if(process.env.IQ_SCREENSHOT_DIR){
   fs.mkdirSync(process.env.IQ_SCREENSHOT_DIR,{recursive:true});
   await page.screenshot({path:path.join(process.env.IQ_SCREENSHOT_DIR,'desktop.png'),fullPage:true});
  }
  const malicious='<img src=x onerror="alert(1)">';
  await page.locator('#rubric-file').setInputFiles({name:'rubrica.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({name:malicious,criteria:[{id:'xss',label:malicious,kind:'phrase',phrase:malicious,weight:100}]}))});
  await page.waitForFunction(()=>document.querySelector('#criteria').children.length===1);
  await page.getByText('Pegar texto directamente',{exact:true}).click();
  await page.locator('#paste').fill(malicious);await page.locator('#save-text').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent==='Texto guardado.');
  await page.locator('#evaluate').click();
  await page.waitForFunction(()=>document.querySelector('#result h3')?.textContent.startsWith('<img'));
  assert.equal(await page.locator('#result img').count(),0);assert.equal(dialogs,0);
  await page.locator('[data-view=activity]').click();assert.ok(await page.locator('.activity-row').count()>=2);
  await page.locator('[data-view=skills]').click();assert.equal(await page.locator('#skill-list .card').count(),1);
  await page.locator('[data-view=settings]').click();await page.locator('#local-url').fill('https://external.example');
  await page.getByRole('button',{name:'Guardar conexión'}).click();
  await page.waitForFunction(()=>document.querySelector('#notice').classList.contains('error'));
  await page.locator('[data-view=evaluate]').click();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),true);
  if(process.env.IQ_SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.IQ_SCREENSHOT_DIR,'mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log('Browser checks passed: demo, citations, export, XSS rendering, navigation, settings, mobile overflow.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
