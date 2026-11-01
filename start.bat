@echo off
rem Zotivity starten (ohne Konsolenfenster) und Oberfläche im Browser öffnen
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  call install.bat || exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m zotivity serve --quiet --open
