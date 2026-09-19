"""Development QA harness: all subprocesses share a network namespace."""
import os,subprocess,time,tempfile,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent.parent
base=root.parent
qa=base/'qa-browser';env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:11435',OLLAMA_MODELS=str(base/'qa-models'),OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1')
log=(qa/'browser-model.log').open('w');engine=subprocess.Popen([str(base/'build-cache/ollama/bin/ollama'),'serve'],env=env,stdout=log,stderr=log)
try:
 for _ in range(120):
  try:urllib.request.urlopen('http://127.0.0.1:11435/api/version',timeout=2).close();break
  except Exception:time.sleep(.5)
 with tempfile.TemporaryDirectory() as tmp:
  app=subprocess.Popen([os.environ['CODEX_PRIMARY_RUNTIME_PYTHON'],'run.py','--no-browser','--port','8765','--data-dir',tmp],cwd=root,stdout=subprocess.PIPE)
  try:
   app.stdout.readline()
   env.update(IQ_CHROMIUM=str(qa/'chromium'),IQ_QA_DIR=str(qa),FONTCONFIG_PATH=str(qa/'fontconfig'))
   result=subprocess.run([os.environ['CODEX_PRIMARY_RUNTIME_NODE'],'tests/product_browser.cjs'],cwd=root,env=env,timeout=600)
   raise SystemExit(result.returncode)
  finally:app.terminate();app.wait(timeout=10)
finally:engine.terminate();engine.wait(timeout=10);log.close()
