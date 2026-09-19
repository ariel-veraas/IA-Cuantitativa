@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Listo. Abri iniciar.bat.
pause
exit /b 0
:fail
echo No se completo la instalacion. Revisa que tengas Python 3.11 o superior y conexion a internet.
pause
exit /b 1
