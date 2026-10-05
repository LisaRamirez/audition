@echo off
REM Inicia AudiHacks con la semilla: romero (pide permisos de administrador)
powershell -NoProfile -Command "Start-Process -FilePath python -ArgumentList 'audihacks.py ciclo --semilla romero' -WorkingDirectory '%~dp0' -Verb RunAs"
