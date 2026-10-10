"""Ajustes de espera de AudiHacks, editables desde la interfaz y leidos por el programa en cada vuelta
(sin reiniciar). Archivo: ajustes.json (no se sube al repositorio)."""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(AQUI, "ajustes.json")
POR_DEFECTO = {
    "revision_activa": True,      # revisar la pantalla (tomando el foco) mientras espera a que maduren
    "intervalo_seg": 30,          # cada cuantos segundos revisa cuando ya paso la hora y aun no estan listas
    "margen_seg": 0,              # segundos extra tras la hora calculada antes de empezar a cortar
    "minutos": {"romero": 7, "menta_verde": 23, "menta": 127},
    "lanzador": "",               # ruta de Patcher.exe (vacio = detectarla sola)
    "excluir": [],                # parcelas "f,c" plantadas por el usuario: el programa no las toca
}
_cache = {"mtime": None, "datos": None}


def detectar_lanzador():
    """Busca el acceso directo 'Audition' del menu Inicio y devuelve la ruta de Patcher.exe ('' si no la halla)."""
    import subprocess
    cmd = ("$sh=New-Object -ComObject WScript.Shell; Get-ChildItem "
           "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\",\"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\" "
           "-Recurse -Filter *.lnk -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'udition' } | "
           "ForEach-Object { $sh.CreateShortcut($_.FullName).TargetPath }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             creationflags=0x08000000, timeout=30).stdout.splitlines()
    except Exception:
        return ""
    for t in out:
        t = t.strip()
        if t.lower().endswith("patcher.exe") and os.path.exists(t):
            return t
    return ""


def ruta_lanzador(config_ruta=""):
    """Ruta del lanzador: la de los ajustes, la de config.json o la detectada en el menu Inicio."""
    for r in (leer().get("lanzador", ""), config_ruta):
        if r and os.path.exists(r):
            return r
    return detectar_lanzador()


def _mezclar(d):
    r = {**POR_DEFECTO, **d}
    r["minutos"] = {**POR_DEFECTO["minutos"], **d.get("minutos", {})}
    return r


def leer():
    try:
        m = os.path.getmtime(ARCHIVO)
        if m != _cache["mtime"] or _cache["datos"] is None:
            with open(ARCHIVO, encoding="utf-8") as f:
                _cache["datos"] = _mezclar(json.load(f))
            _cache["mtime"] = m
    except (OSError, ValueError):
        if _cache["datos"] is None:
            _cache["datos"] = _mezclar({})
    return _cache["datos"]


def guardar(datos):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(_mezclar(datos), f, indent=2)
