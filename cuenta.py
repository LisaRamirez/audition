"""Cuenta de Audition guardada en el PC. La contrasena se cifra con DPAPI de Windows: solo la puede
leer el mismo usuario de Windows en este PC. El archivo (cuenta.dat) no se sube al repositorio."""
import base64
import ctypes
import json
import os
from ctypes import wintypes

AQUI = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(AQUI, "cuenta.dat")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(datos):
    buf = ctypes.create_string_buffer(datos, len(datos))
    return _Blob(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _salida(b):
    datos = ctypes.string_at(b.pbData, b.cbData)
    ctypes.windll.kernel32.LocalFree(b.pbData)
    return datos


def _cifrar(texto):
    entrada, _buf = _blob(texto.encode("utf-8"))
    salida = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), "AudiHacks", None, None, None, 0,
                                                  ctypes.byref(salida)):
        raise OSError("No pude cifrar la contrasena")
    return base64.b64encode(_salida(salida)).decode("ascii")


def _descifrar(b64):
    entrada, _buf = _blob(base64.b64decode(b64))
    salida = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0,
                                                    ctypes.byref(salida)):
        raise OSError("No pude descifrar la contrasena (otro usuario de Windows u otro PC)")
    return _salida(salida).decode("utf-8")


def guardar(usuario, password, reingreso_auto):
    """Guarda usuario, contrasena cifrada y si el reingreso automatico esta activo."""
    previo = cargar()
    datos = {"usuario": usuario, "reingreso_auto": bool(reingreso_auto)}
    if password:
        datos["password"] = _cifrar(password)
    elif previo and previo.get("password"):
        datos["password"] = previo["password"]       # campo vacio = conservar la que ya habia
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f)


def cargar():
    """Devuelve {'usuario', 'password' (cifrada), 'reingreso_auto'} o None si no hay archivo."""
    try:
        with open(ARCHIVO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def password_en_claro():
    datos = cargar()
    if not datos or not datos.get("password"):
        return None
    return _descifrar(datos["password"])
