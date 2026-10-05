@echo off
REM Inicia AudiHacks con la semilla: menta_verde (pide permisos de administrador)
powershell -NoProfile -Command "Start-Process -FilePath python -ArgumentList 'audihacks.py ciclo --semilla menta_verde' -WorkingDirectory '%~dp0' -Verb RunAs"
