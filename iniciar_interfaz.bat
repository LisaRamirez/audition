@echo off
REM Abre la interfaz de AuSecret (pide permisos de administrador una vez)
set "PYW=pythonw"
if exist "%~dp0ruta_python.txt" set /p PYW=<"%~dp0ruta_python.txt"
powershell -NoProfile -Command "Start-Process -FilePath '%PYW%' -ArgumentList 'audihacks_gui.py' -WorkingDirectory '%~dp0' -Verb RunAs"
