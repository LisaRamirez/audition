@echo off
REM Abre la interfaz de AuSecret (pide permisos de administrador una vez). Si falla, deja el error en interfaz_error.log
set "PYW=pythonw"
if exist "%~dp0ruta_python.txt" set /p PYW=<"%~dp0ruta_python.txt"
powershell -NoProfile -Command "Start-Process -FilePath '%PYW%' -ArgumentList 'audihacks_gui.py' -WorkingDirectory '%~dp0' -Verb RunAs"
if errorlevel 1 (
    echo No se pudo abrir AuSecret. Ejecuta diagnostico.bat y mandame el resultado.
    pause
)
