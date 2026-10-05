@echo off
REM Abre la interfaz de AudiHacks (pide permisos de administrador una vez)
powershell -NoProfile -Command "Start-Process -FilePath pythonw -ArgumentList 'audihacks_gui.py' -WorkingDirectory '%~dp0' -Verb RunAs"
