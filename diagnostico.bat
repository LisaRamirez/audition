@echo off
REM Si AuSecret no abre: doble clic aqui. Muestra que falla y guarda el resultado en diagnostico.txt
setlocal
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0ruta_python.txt" (
    set /p PYW=<"%~dp0ruta_python.txt"
    for %%D in ("%PYW%") do set "PY=%%~dpDpython.exe"
)
(
echo === AuSecret diagnostico ===
echo Carpeta: %CD%
echo Python usado: %PY%
"%PY%" --version
echo.
echo --- Paquetes ---
"%PY%" -c "import PIL; print('Pillow', PIL.__version__)"
"%PY%" -c "import numpy; print('numpy', numpy.__version__)"
"%PY%" -c "import customtkinter; print('customtkinter', customtkinter.__version__)"
echo.
echo --- Archivos ---
if exist referencias (echo referencias: OK) else (echo referencias: FALTA)
if exist audihacks_gui.py (echo audihacks_gui.py: OK) else (echo audihacks_gui.py: FALTA)
if exist ruta_python.txt (echo ruta_python.txt: OK) else (echo ruta_python.txt: FALTA - ejecuta instalar.bat)
echo.
echo --- Abrir la interfaz (el error sale aqui) ---
"%PY%" audihacks_gui.py
) > diagnostico.txt 2>&1
type diagnostico.txt
echo.
echo Se guardo diagnostico.txt. Mandame una foto de esta ventana o ese archivo.
pause
