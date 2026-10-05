@echo off
REM Instala las dependencias de AudiHacks (requiere Python 3.12 en el PATH)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Listo. Abre la interfaz con iniciar_interfaz.bat
pause
