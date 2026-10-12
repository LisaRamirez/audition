@echo off
REM Instalacion de AuSecret en UN solo paso: Python (si falta), librerias, tareas, acceso directo y la interfaz.
setlocal
cd /d "%~dp0"
title Instalando AuSecret
set "PY="
call :buscar
if not defined PY (
    echo No encuentro Python. Lo instalo con winget ^(un par de minutos^)...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    call :buscar
)
if not defined PY (
    echo.
    echo No pude instalar Python solo. Instalalo desde https://www.python.org/downloads/
    echo marcando "Add python.exe to PATH" y vuelve a abrir este archivo.
    pause
    exit /b 1
)
echo Python: %PY%
for %%D in ("%PY%") do set "PYW=%%~dpDpythonw.exe"
>"%~dp0ruta_python.txt" echo %PYW%

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo Fallo la instalacion de las librerias. Revisa tu conexion a internet y vuelve a abrir este archivo.
    pause
    exit /b 1
)
echo.
echo Creando las tareas: acepta el aviso de administrador ^(una sola vez^)...
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0instalar_tareas.ps1\" -Python \"%PY%\"'"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0crear_acceso.ps1"
echo.
echo Listo. Se crearon los accesos "AuSecret" y "Detener AuSecret" en el Escritorio. Abriendo la interfaz...
call "%~dp0iniciar_interfaz.bat"
echo.
echo Siguiente paso: en la pestana Cuenta escribe tu usuario y contrasena y pulsa Guardar cuenta.
pause
exit /b 0

:buscar
REM Python real (no el atajo de la Microsoft Store): rutas habituales o el que responda en el PATH
for %%P in ("%LocalAppData%\Programs\Python\Python312\python.exe" "%LocalAppData%\Programs\Python\Python313\python.exe" "%LocalAppData%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python312\python.exe") do (
    if not defined PY if exist "%%~P" set "PY=%%~P"
)
if not defined PY (
    python -c "import sys" >nul 2>nul && for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)"') do set "PY=%%i"
)
exit /b 0
