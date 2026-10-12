# Crea el acceso directo "AuSecret" en el Escritorio, con su icono.
$a = Split-Path -Parent $MyInvocation.MyCommand.Path
$d = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell
$l = $ws.CreateShortcut("$d\AuSecret.lnk")
$l.TargetPath = "$a\iniciar_interfaz.bat"
$l.WorkingDirectory = $a
$l.IconLocation = "$a\audihacks.ico"
$l.WindowStyle = 7
$l.Save()

# Acceso de parada de emergencia, con el icono del juego (si se encuentra Audition.exe)
$lanz = ""
try { $lanz = (Get-Content "$a\ajustes.json" -Raw | ConvertFrom-Json).lanzador } catch {}
if (-not $lanz) { try { $lanz = (Get-Content "$a\config.json" -Raw | ConvertFrom-Json).reingreso.lanzador } catch {} }
$exe = if ($lanz) { Join-Path (Split-Path $lanz) "Audition.exe" } else { "" }
$s = $ws.CreateShortcut("$d\Detener AuSecret.lnk")
$s.TargetPath = "$env:SystemRoot\System32\schtasks.exe"
$s.Arguments = "/run /tn AudiHacks_Detener"
$s.WorkingDirectory = $a
if ($exe -and (Test-Path $exe)) { $s.IconLocation = "$exe,0" } else { $s.IconLocation = "$a\audihacks.ico" }
$s.WindowStyle = 7
$s.Description = "Parada de emergencia de AuSecret"
$s.Save()
