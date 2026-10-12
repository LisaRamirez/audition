@echo off
REM Para notebooks / pantallas con escala de Windows al 125 %, 150 %...: hace que Audition se vea en 1024x768 reales.
REM Solo cambia la compatibilidad de Audition.exe para TU usuario (no toca nada mas). Despues, cierra y reabre el juego.
setlocal
cd /d "%~dp0"
set "EXE="
for /f "usebackq delims=" %%L in (`powershell -NoProfile -Command "try{ $l=(Get-Content '%~dp0ajustes.json' -Raw | ConvertFrom-Json).lanzador }catch{}; if(-not $l){ try{ $l=(Get-Content '%~dp0config.json' -Raw | ConvertFrom-Json).reingreso.lanzador }catch{} }; if($l){ Join-Path (Split-Path $l) 'Audition.exe' }"`) do set "EXE=%%L"
if not defined EXE goto manual
if not exist "%EXE%" goto manual
reg add "HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers" /v "%EXE%" /t REG_SZ /d "~ HIGHDPIAWARE" /f >nul
echo Listo para: %EXE%
echo Cierra el juego por completo y vuelve a abrirlo. Despues el programa lo vera en 1024x768.
pause
exit /b 0
:manual
echo No encontre Audition.exe. Hazlo a mano:
echo   clic derecho en Audition.exe - Propiedades - Compatibilidad - Cambiar la configuracion de PPP alto
echo   marca "Invalidar el comportamiento de escalado de PPP alto" y elige "Aplicacion". Aceptar y reabre el juego.
echo Si el lanzador no esta configurado, escribe su ruta en la interfaz (Cuenta - Detectar) y repite.
pause
