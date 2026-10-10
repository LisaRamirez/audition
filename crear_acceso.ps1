# Crea el acceso directo "AudiHacks" en el Escritorio, con su icono.
$a = Split-Path -Parent $MyInvocation.MyCommand.Path
$d = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell
$l = $ws.CreateShortcut("$d\AudiHacks.lnk")
$l.TargetPath = "$a\iniciar_interfaz.bat"
$l.WorkingDirectory = $a
$l.IconLocation = "$a\audihacks.ico"
$l.WindowStyle = 7
$l.Save()
