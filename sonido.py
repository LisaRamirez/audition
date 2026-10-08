"""Avisos sonoros de AudiHacks con volumen ajustable. La interfaz escribe sonido.json y el programa lo lee
en cada aviso, asi los cambios valen al instante (sin reiniciar)."""
import io
import json
import math
import os
import struct
import wave

AQUI = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(AQUI, "sonido.json")
POR_DEFECTO = {"alertas": True, "cuenta_atras": False, "volumen": 40}
_cache = {"mtime": None, "datos": dict(POR_DEFECTO)}


def leer():
    try:
        m = os.path.getmtime(ARCHIVO)
        if m != _cache["mtime"]:
            with open(ARCHIVO, encoding="utf-8") as f:
                _cache["datos"] = {**POR_DEFECTO, **json.load(f)}
            _cache["mtime"] = m
    except (OSError, ValueError):
        _cache["datos"] = dict(POR_DEFECTO)
    return _cache["datos"]


def guardar(alertas, cuenta_atras, volumen):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump({"alertas": bool(alertas), "cuenta_atras": bool(cuenta_atras), "volumen": int(volumen)}, f)


def _tono(freq, ms, volumen):
    """WAV en memoria con el volumen aplicado (0-100) a la amplitud."""
    sr = 22050
    n = int(sr * ms / 1000)
    amp = 32767 * 0.9 * max(0, min(100, volumen)) / 100
    fade = int(sr * 0.006)
    datos = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade) if fade else 1.0
        datos += struct.pack("<h", int(amp * env * math.sin(2 * math.pi * freq * i / sr)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(datos))
    return buf.getvalue()


def pitar(freq, ms, tipo="alerta", forzar=False):
    """tipo: 'alerta' (algo fallo) o 'cuenta' (cuenta atras). forzar=True ignora los interruptores (prueba)."""
    import winsound
    c = leer()
    if not forzar:
        if tipo == "alerta" and not c["alertas"]:
            return
        if tipo == "cuenta" and not c["cuenta_atras"]:
            return
    if c["volumen"] <= 0:
        return
    winsound.PlaySound(_tono(freq, ms, c["volumen"]), winsound.SND_MEMORY)
