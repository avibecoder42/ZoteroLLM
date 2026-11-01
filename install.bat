@echo off
rem Zotivity – Einrichtung unter Windows (einmalig)
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if %errorlevel%==0 (
  echo Richte Python-Umgebung mit uv ein ...
  uv venv .venv --python 3.13 || goto :fail
  uv pip install --python .venv\Scripts\python.exe -e . || goto :fail
) else (
  echo Richte Python-Umgebung mit python -m venv ein ...
  python -m venv .venv || goto :fail
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -e . || goto :fail
)
echo.
echo Fertig. Starten mit start.bat
exit /b 0

:fail
echo.
echo Einrichtung fehlgeschlagen. Ist Python 3.11 oder neuer installiert?
exit /b 1
