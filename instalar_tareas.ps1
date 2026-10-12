# Crea tareas programadas "a demanda" para AudiHacks con privilegios elevados.
# Ejecutar UNA SOLA VEZ en un PowerShell abierto "como administrador".
# Despues, cualquier proceso normal puede iniciarlas/detenerlas SIN aviso de UAC:
#   schtasks /run /tn AudiHacks_Romero
#   schtasks /run /tn AudiHacks_MentaVerde
#   schtasks /run /tn AudiHacks_Detener
# Solo estas tareas tienen privilegios elevados; el resto del PC no cambia.
param([string]$Python = "")

$carpeta = $PSScriptRoot
$python  = if ($Python -and (Test-Path $Python)) { $Python } else { (Get-Command python).Source }
$usuario = "$env:USERDOMAIN\$env:USERNAME"

$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
$config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable

function Nueva-Tarea($nombre, $argumentos) {
    $accion = New-ScheduledTaskAction -Execute $python -Argument $argumentos -WorkingDirectory $carpeta
    Register-ScheduledTask -TaskName $nombre -Action $accion -Principal $principal -Settings $config -Force | Out-Null
    Write-Host "Tarea creada: $nombre"
}

Nueva-Tarea "AudiHacks_Romero"     "audihacks.py ciclo --semilla romero"
Nueva-Tarea "AudiHacks_MentaVerde" "audihacks.py ciclo --semilla menta_verde"

# Detener: cierra solo los procesos de Python de AudiHacks
$cmd = "Get-Process python3.12,python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force"
$accionDet = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -Command `"$cmd`""
Register-ScheduledTask -TaskName "AudiHacks_Detener" -Action $accionDet -Principal $principal -Settings $config -Force | Out-Null
Write-Host "Tarea creada: AudiHacks_Detener"

Write-Host ""
Write-Host "Listo. Prueba (sin administrador):  schtasks /run /tn AudiHacks_Romero"
