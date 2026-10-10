@echo off
REM Instala AudiHacks: librerias y tareas elevadas (iniciar/detener sin aviso de administrador).
REM Requiere Python 3.12 en el PATH.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Creando las tareas elevadas: acepta el aviso de administrador (una sola vez)...
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0instalar_tareas.ps1\"'"
echo.
echo Listo. Abre la interfaz con iniciar_interfaz.bat y sigue el "Primer uso" del README.
pause
