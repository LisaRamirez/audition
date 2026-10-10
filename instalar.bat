@echo off
REM Instalacion de AudiHacks en un solo paso: Python (si falta), librerias, tareas, acceso directo y abre la interfaz.
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    echo No encuentro Python. Lo instalo con winget (puede tardar un par de minutos)...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not exist "%PY%" if /i not "%PY%"=="python" (
    echo No pude instalar Python solo. Instalalo desde python.org marcando "Add Python to PATH" y vuelve a abrir este archivo.
    pause
    exit /b 1
)
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
echo.
echo Creando las tareas: acepta el aviso de administrador (una sola vez)...
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0instalar_tareas.ps1\"'"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso.ps1"
echo.
echo Listo. Se creo el acceso "AudiHacks" en el Escritorio. Abriendo la interfaz...
call "%~dp0iniciar_interfaz.bat"
pause
