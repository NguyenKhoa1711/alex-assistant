@echo off
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo Can cai uv va Python 3.11 truoc.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" uv venv --python 3.11 .venv
uv --system-certs pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import yaml,sys;sys.exit(0 if yaml.safe_load(open('config.yaml',encoding='utf-8'))['stt']['device']=='cuda' else 1)"
if not errorlevel 1 (
  uv --system-certs pip install --python ".venv\Scripts\python.exe" -r requirements-gpu.txt
  if errorlevel 1 echo CUDA chua cai xong. Pet se thu CPU int8 va bao loi ro rang.
)
".venv\Scripts\python.exe" download_models.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import yaml,sys;sys.exit(0 if yaml.safe_load(open('config.yaml',encoding='utf-8'))['tts'].get('engine')=='vieneu_turbo' else 1)"
if not errorlevel 1 (
  if not exist ".venv-voice\Scripts\python.exe" uv venv --python 3.11 .venv-voice
  uv --system-certs pip install --python ".venv-voice\Scripts\python.exe" -r requirements-voice.txt
  if errorlevel 1 goto failed
  ".venv-voice\Scripts\python.exe" voice_preview_turbo.py
  if errorlevel 1 goto failed
)
echo Da san sang. Chay run.bat de mo Alex.
pause
exit /b 0
:failed
echo Cai dat chua xong. Xem loi o tren.
pause
exit /b 1
