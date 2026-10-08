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
    "excluir": [],                # parcelas "f,c" plantadas por el usuario: el programa no las toca
}
_cache = {"mtime": None, "datos": None}


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
