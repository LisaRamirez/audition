@echo off
REM Detiene AudiHacks (cierra los procesos de Python). Tambien sirve la tecla F12.
powershell -NoProfile -Command "Start-Process powershell -ArgumentList '-NoProfile','-Command','Get-Process python3.12,python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force' -Verb RunAs"
