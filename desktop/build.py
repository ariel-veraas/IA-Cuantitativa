"""Build the standalone Windows entrypoint. Run from any directory."""
import argparse
import os
from pathlib import Path
import subprocess
import zipfile

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser();parser.add_argument('--go',default='go');parser.add_argument('--output',default=str(root.parent/'outputs/IA-Cuantitativa.exe'));args=parser.parse_args()
if not (root/'vendor/pypdf').is_dir():raise SystemExit('Falta el lector PDF incluido en vendor/pypdf.')
with zipfile.ZipFile(root/'desktop/payload.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
    for folder in ['iq','skills','examples','vendor','licenses']:
        for p in sorted((root/folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':z.write(p,str(p.relative_to(root)))
    z.write(root/'run.py','run.py')
env=os.environ.copy();env.update(GOOS='windows',GOARCH='amd64',CGO_ENABLED='0')
output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
subprocess.run([args.go,'build','-trimpath','-ldflags=-s -w -H=windowsgui','-o',str(output),'.'],cwd=root/'desktop',env=env,check=True)
print(output)
