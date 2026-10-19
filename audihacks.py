"""AudiHacks: automatiza el ciclo del Secret Garden de Audition (v1).

Uso (se relanza solo como administrador):
    python audihacks.py ciclo --semilla romero            # ciclo continuo
    python audihacks.py ciclo --semilla romero --seco     # mueve el mouse pero NO hace clic
    python audihacks.py ciclo --semilla romero --ciclos 1
    python audihacks.py una-parcela --semilla romero      # prueba: siembra solo la parcela 0,0
Emergencia: mantener F12 (detiene todo).
"""
import argparse
import ctypes
import json
import os
import random
import subprocess
import sys
import threading
import time
from ctypes import wintypes

from PIL import Image, ImageChops, ImageStat

import ajustes
import cuenta
import sonido

AQUI = os.path.dirname(os.path.abspath(__file__))
user32 = ctypes.windll.user32
try:        # por monitor: con varios monitores de distinta escala (notebook + pantalla externa) todo va en pixeles reales
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    if not user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):       # PER_MONITOR_AWARE_V2
        user32.SetProcessDPIAware()
except (AttributeError, OSError):
    user32.SetProcessDPIAware()


def asegurar_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, AQUI, 1)
    sys.exit(0)


with open(os.path.join(AQUI, "config.json"), encoding="utf-8") as f:
    CFG = json.load(f)


class Detenido(Exception):
    pass


class LimiteItems(Exception):
    """El juego dijo que se excedio el maximo de items en el suelo: hay que levantar y reintentar."""


class PantallaDesconocida(Detenido):
    """El juego esta en una pantalla que no conozco (login, desconexion...). Se espera, no se muere."""


class SinJuego(PantallaDesconocida):
    """No hay ventana 'Audition' (el juego se cerro o aun no abre)."""


class Interferencia(Exception):
    """El usuario movio el mouse o hizo clic mientras el programa trabajaba."""


_ESPERADO = None      # (x, y) de pantalla donde dejamos el cursor; None = no vigilar
_DERIVAS = []         # instantes de las ultimas correcciones de deriva del mouse
_PULSANDO = False     # True mientras el propio programa mantiene un boton pulsado


def desarmar():
    global _ESPERADO
    _ESPERADO = None


def _revisar_usuario():
    if _ESPERADO is None:
        return
    cur = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cur))
    tol = CFG["tolerancia_mouse"]
    dx, dy = cur.x - _ESPERADO[0], cur.y - _ESPERADO[1]
    if (abs(dx) > tol or abs(dy) > tol) and not _PULSANDO and max(abs(dx), abs(dy)) <= CFG.get("tolerancia_deriva", 45):
        # desvio chico (vibracion, mouse inalambrico...): se devuelve el cursor a su sitio en vez de abortar,
        # salvo que pase muchas veces seguidas (entonces es una persona moviendo el mouse)
        ahora = time.time()
        _DERIVAS[:] = [t for t in _DERIVAS if ahora - t < 6]
        if len(_DERIVAS) < 5:
            _DERIVAS.append(ahora)
            user32.SetCursorPos(_ESPERADO[0], _ESPERADO[1])
            if len(_DERIVAS) == 1:
                log(f"Deriva del mouse corregida: ({dx},{dy}) px")
            return
    if abs(dx) > tol or abs(dy) > tol:
        raise Interferencia(f"el mouse se movio: esperado {_ESPERADO}, estaba en ({cur.x},{cur.y}), "
                            f"desvio ({cur.x - _ESPERADO[0]},{cur.y - _ESPERADO[1]}), "
                            f"{segundos_sin_tocar():.1f} s desde la ultima entrada del usuario")
    if not _PULSANDO and (user32.GetAsyncKeyState(0x01) & 0x8000):
        raise Interferencia(f"clic del usuario ({segundos_sin_tocar():.1f} s desde la ultima entrada)")


_STOP = threading.Event()


def _vigia_f12():
    """Hilo aparte: mira F12 cada 15 ms, aunque el programa este en una espera larga."""
    while True:
        if user32.GetAsyncKeyState(0x7B) & 0x8001:   # pulsada ahora o desde la ultima consulta
            _STOP.set()
        time.sleep(0.015)


threading.Thread(target=_vigia_f12, daemon=True).start()


def emergencia():
    return _STOP.is_set()


def revisar():
    if _STOP.is_set():
        raise Detenido("F12 pulsado")


def dormir(seg):
    """Espera en trozos de 30 ms para poder cancelar al instante."""
    fin = time.time() + seg
    while True:
        revisar()
        _revisar_usuario()
        resto = fin - time.time()
        if resto <= 0:
            return
        time.sleep(min(0.03, resto))


def alarma(veces=4):
    """Avisos sonoros para llamar la atencion (volumen e interruptores en sonido.json, desde la interfaz)."""
    for _ in range(veces):
        sonido.pitar(1000, 250)
        sonido.pitar(600, 250)


try:
    import faulthandler
    _HANG = open(os.path.join(AQUI, "colgado.log"), "a", encoding="utf-8")
except Exception:                                    # el vigilante de cuelgues nunca debe impedir arrancar
    faulthandler = None


def log(txt):
    linea = time.strftime("%H:%M:%S ") + txt
    print(linea, flush=True)
    with open(os.path.join(AQUI, "audihacks.log"), "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    if faulthandler:                                 # si pasan 10 min sin escribir nada, vuelca dónde está parado
        faulthandler.dump_traceback_later(600, repeat=True, file=_HANG)


def buscar_plantilla(img, ref, paso=2):
    """Desliza la plantilla 'ref' sobre 'img' (ambas PIL) y devuelve (diferencia media, (x, y)) del mejor sitio."""
    import numpy as np
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r = np.asarray(ref.convert("RGB")).astype(np.int16)
    h, w = r.shape[:2]
    mejor, pos = 1e9, None
    for y in range(0, a.shape[0] - h + 1, paso):
        for x in range(0, a.shape[1] - w + 1, paso):
            d = float(np.abs(a[y:y + h, x:x + w] - r).mean())
            if d < mejor:
                mejor, pos = d, (x, y)
    if pos is not None and paso > 1:                       # afina a 1 px alrededor del mejor sitio
        bx, by = pos
        for y in range(max(0, by - paso + 1), min(a.shape[0] - h, by + paso - 1) + 1):
            for x in range(max(0, bx - paso + 1), min(a.shape[1] - w, bx + paso - 1) + 1):
                d = float(np.abs(a[y:y + h, x:x + w] - r).mean())
                if d < mejor:
                    mejor, pos = d, (x, y)
    return mejor, pos


class Audition:
    def __init__(self, seco=False):
        self.seco = seco
        self.hwnd = 0
        self.ox = self.oy = 0

    # --- ventana ---
    def localizar(self):
        self.hwnd = user32.FindWindowW(None, "Audition")
        if not self.hwnd:
            raise SinJuego("No encuentro la ventana de Audition")
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, 9)
        for _ in range(4):
            # Alt "desbloquea" el cambio de ventana en primer plano
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            dormir(0.5)
            if user32.GetForegroundWindow() == self.hwnd:
                break
        else:
            raise Reintentar("No pude traer Audition al frente (otra ventana lo tapa)")
        p = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(p))
        self.ox, self.oy = p.x, p.y
        self._revisar_tamano()
        if abs(getattr(self, "esc", 1.0) - 1.0) > 0.03 and getattr(self, "_movidas", 0) < 2:
            # la ventana quedo en un monitor con escala de Windows (125 %...): la llevo al monitor principal (0,0)
            # donde el juego se ve a 1024x768 reales; solo si hay un monitor principal con esa escala
            self._movidas = getattr(self, "_movidas", 0) + 1
            log("Muevo la ventana del juego al monitor principal para verla a 1024x768")
            user32.SetWindowPos(self.hwnd, 0, 448, 167, 0, 0, 0x0001 | 0x0004)       # SWP_NOSIZE | SWP_NOZORDER
            dormir(1.5)
            p = wintypes.POINT(0, 0)
            user32.ClientToScreen(self.hwnd, ctypes.byref(p))
            self.ox, self.oy = p.x, p.y
            self._revisar_tamano()

    def _revisar_tamano(self):
        """Avisa (una vez) si la ventana del juego no mide 1024x768 en pixeles reales: pasa en notebooks con la
        escala de Windows al 125 % / 150 % o con pantalla menor de 1366x768. Todas las coordenadas suponen 1024x768."""
        rc = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        w, h = rc.right - rc.left, rc.bottom - rc.top
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)          # escritorio virtual: varios monitores
        sw, sh = vx + user32.GetSystemMetrics(78), vy + user32.GetSystemMetrics(79)
        # escala de la ventana (Windows la estira al 125 %/150 % en pantallas con escala): todas las
        # coordenadas del programa son de 1024x768, se convierten a pixeles reales con self.esc
        esc = w / 1024.0 if w else 1.0
        if abs(esc - h / 768.0) > 0.03 or not 0.5 <= esc <= 3:
            esc = 1.0                                   # proporcion rara: no es una escala, no corrijo
        self.esc = esc
        clave = (w, h, sw, sh, self.ox, self.oy)
        if getattr(self, "_tam_avisado", None) == clave:
            return
        self._tam_avisado = clave
        log(f"Pantalla: {sw}x{sh} px; ventana del juego: {w}x{h} px en ({self.ox},{self.oy})")
        if abs(esc - 1.0) > 0.03:
            log(f"La ventana del juego esta escalada x{esc:.2f}: ajusto capturas y clics a esa escala")
        elif abs(w - 1024) > 12 or abs(h - 768) > 12:
            log(f"AVISO: la ventana del juego mide {w}x{h}, no 1024x768 (proporcion distinta): los clics caeran corridos.")
            sonido.pitar(500, 400)
        elif self.ox < vx or self.oy < vy or self.ox + 1024 > sw or self.oy + 768 > sh:
            log("AVISO: parte de la ventana del juego queda fuera de la pantalla: muevela para que se vea completa.")

    def captura(self, caja):
        from PIL import ImageGrab
        x0, y0, x1, y1 = caja
        e = getattr(self, "esc", 1.0)
        if abs(e - 1.0) < 0.01:
            return ImageGrab.grab(bbox=(self.ox + x0, self.oy + y0, self.ox + x1, self.oy + y1),
                                  all_screens=True).convert("RGB")
        im = ImageGrab.grab(bbox=(self.ox + round(x0 * e), self.oy + round(y0 * e),
                                  self.ox + round(x1 * e), self.oy + round(y1 * e)),
                            all_screens=True).convert("RGB")
        return im.resize((x1 - x0, y1 - y0), Image.LANCZOS)      # de vuelta a la escala de 1024x768

    def en_secret_garden(self):
        ref = Image.open(os.path.join(AQUI, "referencias", "secret_garden_cartel.png")).convert("RGB")
        vivo = self.captura((100, 40, 270, 110))
        dif = sum(ImageStat.Stat(ImageChops.difference(ref, vivo)).mean) / 3
        return dif < CFG["umbral_cartel"], dif

    def recuperar(self, motivo):
        """Suelta cualquier boton, espera a que el usuario suelte el mouse y vuelve a ubicar la ventana."""
        global _PULSANDO
        desarmar()
        _PULSANDO = False
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        log(f"Interferencia ({motivo}): espero a que sueltes el mouse y retomo desde el estado real")
        esperar_turno(minimo=3)
        self.localizar()

    # --- cuadros que bloquean el juego ---
    def ventana_mensaje(self):
        """Cuadro de Windows (clase #32770) del proceso de Audition, p. ej. 'Desconectado del servidor'.
        Devuelve (hwnd, texto) o None."""
        h_juego = user32.FindWindowW(None, "Audition")
        if not h_juego:
            return None
        pid_juego = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h_juego, ctypes.byref(pid_juego))
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        hallados = []

        def textos_hijos(h):
            out = []

            def cb2(hh, _l):
                b = ctypes.create_unicode_buffer(300)
                user32.GetWindowTextW(hh, b, 300)
                if b.value.strip():
                    out.append(b.value.strip())
                return True
            user32.EnumChildWindows(h, enum(cb2), 0)
            return " | ".join(out)

        def cb(h, _l):
            if h == h_juego or not user32.IsWindowVisible(h):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value != pid_juego.value:
                return True
            clase = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, clase, 64)
            if clase.value == "#32770":
                hallados.append((h, textos_hijos(h)))
            return True
        user32.EnumWindows(enum(cb), 0)
        return hallados[0] if hallados else None

    def aceptar_mensaje(self, hwnd_msg):
        """Pulsa el boton del cuadro de Windows (BM_CLICK al primer Button)."""
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        botones = []

        def cb(hh, _l):
            clase = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hh, clase, 32)
            if clase.value == "Button":
                botones.append(hh)
            return True
        user32.EnumChildWindows(hwnd_msg, enum(cb), 0)
        if botones:
            user32.SendMessageW(botones[0], 0x00F5, 0, 0)        # BM_CLICK
        else:
            user32.PostMessageW(hwnd_msg, 0x0010, 0, 0)          # WM_CLOSE

    def manejar_mensajes(self):
        """Atiende cuadros de Windows del juego. True si habia uno."""
        m = self.ventana_mensaje()
        if not m:
            return False
        hwnd_msg, texto = m
        log(f"Cuadro de Windows del juego: {texto!r}")
        alarma()
        self.aceptar_mensaje(hwnd_msg)
        dormir(3.0)
        if "esconect" in texto:
            log("DESCONECTADO del servidor: espero a que vuelvas a iniciar sesion y entro al Secret Garden")
        return True

    def hay_aviso_maximo(self):
        ref = Image.open(os.path.join(AQUI, "referencias", "aviso_maximo.png")).convert("RGB")
        vivo = self.captura((322, 348, 703, 422))
        return sum(ImageStat.Stat(ImageChops.difference(ref, vivo)).mean) / 3 < CFG["umbral_dialogo"] * 2

    def revisar_aviso_maximo(self):
        """'Has excedido el numero maximo, no puedes cosechar': cerrar el cuadro y pedir levantar los
        items del suelo (LimiteItems); la rafaga lo atiende y reintenta."""
        if self.hay_aviso_maximo():
            log("AVISO: el juego dice que se excedio el maximo de items y no deja cosechar")
            self.mover(*CFG["boton_aviso_maximo"])
            self._pulsar()
            dormir(1.0)
            raise LimiteItems("limite de items en el suelo")

    def en_couple_garden(self):
        ref = Image.open(os.path.join(AQUI, "referencias", "couple_garden_boton.png")).convert("RGB")
        vivo = self.captura((228, 40, 380, 86))
        return sum(ImageStat.Stat(ImageChops.difference(ref, vivo)).mean) / 3 < CFG["umbral_cartel"]

    def ir_a_secret_garden(self):
        """Si esta en el Couple Garden, pulsa 'Ir a Secret Garden' y espera a que cargue."""
        previo = getattr(self, "_sin_vigilar", False)
        self._sin_vigilar = True
        try:
            self.soltar_herramienta()
            self.mover(*CFG["boton_cambiar_jardin"])
            self._pulsar()
            for _ in range(15):
                dormir(1.0)
                if self.en_secret_garden()[0]:
                    dormir(1.5)
                    return True
            return False
        finally:
            self._sin_vigilar = previo

    # --- en que pantalla estoy y como llegar al Secret Garden ---
    PANTALLAS = {
        "secret":  (100, 40, 270, 110),
        "couple":  (228, 40, 380, 86),
        "entrada": (40, 610, 400, 700),
        "ciudad":  (400, 470, 640, 590),
        "canales": (10, 255, 190, 290),
    }

    def detectar_pantalla(self):
        """Compara con una imagen de referencia de cada pantalla; devuelve el nombre o None."""
        mejor, mejor_dif = None, 1e9
        import glob
        for nombre, caja in self.PANTALLAS.items():
            vivo = self.captura(caja)
            # varias referencias por pantalla (pantalla_ciudad.png, pantalla_ciudad_halloween.png...): los eventos
            # del juego cambian el decorado
            for ruta in glob.glob(os.path.join(AQUI, "referencias", f"pantalla_{nombre}*.png")):
                ref = Image.open(ruta).convert("RGB")
                if ref.size != vivo.size:
                    continue
                dif = sum(ImageStat.Stat(ImageChops.difference(ref, vivo)).mean) / 3
                if dif < mejor_dif:
                    mejor, mejor_dif = nombre, dif
        return mejor if mejor_dif < CFG["umbral_pantalla"] else None

    def esperar_pantalla(self, distinta_de, max_seg=45):
        fin = time.time() + max_seg
        while time.time() < fin:
            dormir(1.0)
            if self.cerrar_avisos():                 # un cuadro de error con boton circular tapa y bloquea los clics
                continue
            p = self.detectar_pantalla()
            if p and p != distinta_de:
                dormir(1.5)
                return p
        return None

    def navegar_a_secret_garden(self):
        """Desde cualquier pantalla conocida llega al Secret Garden. Pantalla desconocida: se detiene."""
        previo = getattr(self, "_sin_vigilar", False)
        self._sin_vigilar = True
        try:
            for _ in range(8):
                if self.cerrar_avisos():             # cualquier cuadro con boton circular: se acepta siempre
                    dormir(1.0)
                p = self.detectar_pantalla()
                for _ in range(15):                      # la pantalla puede estar cargando (tras entrar): dar hasta 30 s
                    if p is not None:
                        break
                    dormir(2.0)
                    if self.cerrar_avisos():
                        dormir(1.0)
                    p = self.detectar_pantalla()
                if p == "secret":
                    return True
                if p is None:
                    if self.cerrar_avisos():             # un cartel tapa la pantalla: cerrarlo y mirar de nuevo
                        dormir(1.0)
                        continue
                    if not getattr(self, "_clic_cartel", False):
                        # la animacion 'Secret Garden presenta' puede quedar oscureciendo la pantalla hasta un clic
                        self._clic_cartel = True
                        log("Pantalla sin reconocer: un clic en terreno libre por si es el cartel de entrada")
                        self.mover(*CFG["terreno_libre"]); self._pulsar()
                        dormir(4.0)
                        continue
                    self._clic_cartel = False
                    raise PantallaDesconocida("Pantalla desconocida (login, desconexion u otra). No toco nada.")
                log(f"Estoy en '{p}': voy hacia el Secret Garden")
                self.soltar_herramienta() if p in ("couple",) else None
                if p == "couple":
                    self.mover(*CFG["boton_cambiar_jardin"]); self._pulsar()
                elif p == "entrada":
                    self.mover(*CFG["nav_couple_garden"]); self._pulsar()
                elif p == "ciudad":
                    self.mover(*CFG["nav_icono_garden"]); self._pulsar()
                elif p == "canales":
                    for k in ("nav_servidor", "nav_canal", "nav_entrar"):
                        self.mover(*CFG[k]); self._pulsar(); dormir(0.9)
                if self.esperar_pantalla(distinta_de=p) is None:
                    raise Detenido(f"No cambio de pantalla tras actuar en '{p}'")
            raise Detenido("No llegue al Secret Garden tras 8 pasos")
        finally:
            self._sin_vigilar = previo


    # --- reingreso automatico (lanzador -> login -> carteles) ---
    REF_REINGRESO = {
        "login":         ("pantalla_login.png",      (356, 322, 711, 458)),
        "items_nuevos":  ("cartel_items_nuevos.png", (618, 146, 658, 181)),
        "aviso_circulo": ("aviso_circulo.png",       (579, 404, 619, 422)),
        "mercado":       ("panel_mercado.png",       (320, 105, 700, 170)),
    }

    def coincide(self, nombre, umbral=None):
        """True si la zona de pantalla se parece a la referencia. False si aun no se ha guardado."""
        archivo, caja = self.REF_REINGRESO[nombre]
        ruta = os.path.join(AQUI, "referencias", archivo)
        if nombre == "login":
            # el fondo del login cambia con cada evento (conejos, arcoiris...): se mira solo lo opaco del cuadro,
            # el titulo y los botones Cancelar y Registrate, que no cambian
            import numpy as np
            esperado = {(366, 326, 500, 346): (228, 57, 199), (610, 393, 688, 413): (164, 103, 239),
                        (610, 420, 688, 440): (228, 123, 226)}
            for (x0, y0, x1, y1), rgb in esperado.items():
                m = np.asarray(self.captura((x0, y0, x1, y1))).reshape(-1, 3).mean(0)
                if max(abs(float(m[i]) - rgb[i]) for i in range(3)) > 14:
                    return False
            return True
        if not os.path.exists(ruta):
            return False
        ref = Image.open(ruta).convert("RGB")
        dif = sum(ImageStat.Stat(ImageChops.difference(ref, self.captura(caja))).mean) / 3
        return dif < (umbral or CFG["reingreso"]["umbral"])

    def guardar_captura(self, motivo):
        """Guarda una captura del juego en observacion/pantallas/ (maximo una cada 3 min) para ver que cartel
        o pantalla nueva bloquea al programa."""
        if time.time() - getattr(self, "_ult_foto", 0) < 180:
            return
        self._ult_foto = time.time()
        try:
            carpeta = os.path.join(AQUI, "observacion", "pantallas")
            os.makedirs(carpeta, exist_ok=True)
            ruta = os.path.join(carpeta, f"{time.strftime('%d%H%M%S')}_{motivo}.png")
            self.captura((0, 0, 1024, 768)).save(ruta)
            log(f"Captura guardada para revisar: {os.path.relpath(ruta, AQUI)}")
        except Exception as e:                                  # la captura nunca debe romper el ciclo
            log(f"No pude guardar la captura ({e})")

    def buscar_boton_circulo(self):
        """Busca el boton circular de los cuadros azules del juego en la zona central, sin importar donde caiga
        el cuadro. Devuelve (x, y) del cliente o None."""
        ruta = os.path.join(AQUI, "referencias", "boton_circulo.png")
        if not os.path.exists(ruta):
            return None
        zx0, zy0, zx1, zy1 = 250, 250, 780, 520
        ref = Image.open(ruta)
        dif, pos = buscar_plantilla(self.captura((zx0, zy0, zx1, zy1)), ref)
        if pos is None or dif > CFG["reingreso"].get("umbral_circulo", 16):
            return None
        return zx0 + pos[0] + ref.width // 2, zy0 + pos[1] + ref.height // 2

    def hay_error_servidor(self):
        """Cuadro azul 'No hay respuesta del servidor' (el juego perdio la conexion)."""
        zx0, zy0, zx1, zy1 = 250, 250, 780, 520
        zona = None
        for nombre in ("texto_error_servidor.png", "texto_desconectado.png"):     # 'No hay respuesta' / 'Desconectado'
            ruta = os.path.join(AQUI, "referencias", nombre)
            if not os.path.exists(ruta):
                continue
            zona = zona or self.captura((zx0, zy0, zx1, zy1))
            dif, _ = buscar_plantilla(zona, Image.open(ruta))
            if dif <= CFG["reingreso"].get("umbral_error_servidor", 14):
                return True
        return False

    def cerrar_juego_y_reingresar(self):
        """Pierde el servidor: se cierra el juego del todo (no sirve volver con la sesion rota) y se entra de cero."""
        global _PULSANDO
        log("ERROR DEL SERVIDOR ('No hay respuesta del servidor'): cierro el juego y reingreso de cero")
        desarmar()
        _PULSANDO = False
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        h = user32.FindWindowW(None, "Audition")
        if h:
            user32.PostMessageW(h, 0x0010, 0, 0)                       # WM_CLOSE
            for _ in range(15):
                dormir(1.0)
                if not user32.FindWindowW(None, "Audition"):
                    break
        if user32.FindWindowW(None, "Audition"):
            subprocess.run(["taskkill", "/F", "/IM", "Audition.exe"], capture_output=True, creationflags=0x08000000)
            dormir(3.0)
        dormir(2.0)
        return self.reingresar(forzar=True)

    def cerrar_avisos(self):
        """Cierra los carteles/avisos conocidos (Items nuevos, aviso con boton circular). True si cerro alguno."""
        r = CFG["reingreso"]
        cerro = False
        if self.hay_error_servidor():
            self.cerrar_juego_y_reingresar()
            raise SinJuego("Tras el error del servidor se reingreso: el ciclo vuelve a mirar el estado real")
        centro = self.buscar_boton_circulo()
        if centro:
            log(f"Cuadro azul del juego detectado (boton circular en {centro}): lo cierro")
            self.mover(*centro)
            self._pulsar()
            dormir(1.5)
            cerro = True
        for nombre, punto in (("items_nuevos", r["cerrar_items"]), ("mercado", r["cerrar_mercado"])):
            if self.coincide(nombre):
                log(f"Cartel '{nombre}' detectado: lo cierro")
                if nombre == "items_nuevos" and r.get("esconder_items"):
                    self.mover(*r["esconder_items"])          # marca 'Esconder por hoy' para que no vuelva a salir
                    self._pulsar()
                    dormir(0.5)
                self.mover(*punto)
                self._pulsar()
                dormir(1.0)
                cerro = True
        return cerro

    @staticmethod
    def hwnd_lanzador():
        """Ventana del lanzador ('Audition Setup Manager ...'), o 0."""
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        hallado = []

        def cb(h, _l):
            b = ctypes.create_unicode_buffer(120)
            user32.GetWindowTextW(h, b, 120)
            if b.value.startswith("Audition Setup Manager") and user32.IsWindowVisible(h):
                hallado.append(h)
            return True
        user32.EnumWindows(enum(cb), 0)
        return hallado[0] if hallado else 0

    def pulsar_jugar(self, h):
        """Pulsa 'JUGAR' del lanzador (boton abajo a la derecha de su ventana)."""
        for _ in range(3):
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            if user32.IsIconic(h):
                user32.ShowWindow(h, 9)
            user32.SetForegroundWindow(h)
            dormir(0.5)
            if user32.GetForegroundWindow() == h:
                break
        rc = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(rc))
        dx, dy = CFG["reingreso"]["jugar_desde_esquina_inf_der"]
        previo = (self.ox, self.oy)
        self.ox = self.oy = 0
        try:
            self.mover(rc.right - dx, rc.bottom - dy)
            self._pulsar()
        finally:
            self.ox, self.oy = previo

    @staticmethod
    def teclear(texto):
        """Escribe con teclas reales (el juego no acepta texto por mensajes)."""
        for ch in texto:
            r = user32.VkKeyScanW(ord(ch))
            if r == -1:
                continue
            vk, mayus = r & 0xFF, (r >> 8) & 1
            scan = user32.MapVirtualKeyW(vk, 0)
            if mayus:
                user32.keybd_event(0x10, 0x2A, 0, 0)
            user32.keybd_event(vk, scan, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(vk, scan, 2, 0)
            if mayus:
                user32.keybd_event(0x10, 0x2A, 2, 0)
            dormir(0.07)

    @staticmethod
    def borrar_campo(n=30):
        for _ in range(n):
            user32.keybd_event(0x08, 0x0E, 0, 0)
            user32.keybd_event(0x08, 0x0E, 2, 0)
            time.sleep(0.015)

    def iniciar_sesion(self, datos):
        r = CFG["reingreso"]
        clave = cuenta.password_en_claro()
        if datos.get("usuario"):
            self.mover(*r["campo_usuario"]); self._pulsar(); dormir(0.4)
            self.borrar_campo(); desarmar(); self.teclear(datos["usuario"])
        self.mover(*r["campo_password"]); self._pulsar(); dormir(0.4)
        self.borrar_campo(); desarmar(); self.teclear(clave)
        log("Login: usuario y contrasena escritos; pulso INGRESAR")
        self.mover(*r["ingresar"]); self._pulsar()

    def reingresar(self, forzar=False):
        """Si el juego se cerro o volvio al login: JUGAR en el lanzador, login, cerrar carteles.
        True si hizo algo (el ciclo vuelve a mirar el estado real). False si no era un caso conocido."""
        datos = cuenta.cargar()
        if not datos or not datos.get("reingreso_auto") or not datos.get("password"):
            return False
        ahora = time.time()
        self._reingresos = [t for t in getattr(self, "_reingresos", []) if ahora - t < 1800]
        h_lanz = self.hwnd_lanzador()
        h_juego = user32.FindWindowW(None, "Audition")
        en_login = False
        if h_juego:
            try:
                self.localizar()
                en_login = self.coincide("login")
            except SinJuego:
                h_juego = 0
            except Reintentar:                       # el juego existe pero no logre ponerlo al frente
                return False
        ruta = ajustes.ruta_lanzador(CFG["reingreso"].get("lanzador", ""))
        desde_cero = not h_juego and not h_lanz and bool(ruta) and os.path.exists(ruta)
        if not forzar and not en_login and not (h_lanz and not h_juego) and not desde_cero:
            return False       # solo: login, juego cerrado con lanzador visible, o todo cerrado
        if len(self._reingresos) >= 4:
            log("Reingreso: ya intente 4 veces en 30 min; espero antes de reintentar")
            alarma(3)
            dormir(60)
            return True
        self._reingresos.append(ahora)
        log("REINGRESO AUTOMATICO: el juego no esta en pantalla de juego")
        esperar_turno(minimo=2)
        try:
            if desde_cero:
                log(f"Reingreso desde cero: abro el lanzador {ruta}")
                subprocess.Popen([ruta], cwd=os.path.dirname(ruta))
                for _ in range(90):
                    dormir(1.0)
                    h_lanz = self.hwnd_lanzador()
                    if h_lanz:
                        dormir(8.0)                  # deja que cargue / revise parches
                        break
                else:
                    log("Reingreso: el lanzador no abrio")
                    return True
            if not h_juego and h_lanz:
                log("Reingreso: pulso JUGAR en el lanzador")
                for espera in range(150):            # espera a que abra la ventana del juego
                    if espera % 40 == 0 and self.hwnd_lanzador():
                        self.pulsar_jugar(self.hwnd_lanzador())     # reintenta JUGAR si sigue en el lanzador
                    dormir(1.0)
                    if user32.FindWindowW(None, "Audition"):
                        dormir(3.0)
                        break
                else:
                    log("Reingreso: el juego no abrio tras JUGAR")
                    return True
            logueado = False
            t_ini = time.time()
            ruta_login = os.path.join(AQUI, "referencias", self.REF_REINGRESO["login"][0])
            fin = time.time() + 150
            while time.time() < fin:
                dormir(1.0)
                try:
                    self.localizar()
                except (SinJuego, Reintentar):
                    continue
                if self.cerrar_avisos():
                    continue
                sin_ref = not os.path.exists(ruta_login)
                # sin imagen de referencia del login: si el juego recien abrio y no es ninguna pantalla conocida,
                # se asume que es el login (y se guarda la imagen para la proxima vez)
                if not logueado and (self.coincide("login") or (sin_ref and time.time() - t_ini > 40
                                                                 and not self.detectar_pantalla())):
                    self.iniciar_sesion(datos)
                    logueado = True
                    dormir(5.0)
                    continue
                if self.detectar_pantalla():
                    log("Reingreso: ya estoy dentro del juego")
                    return True
        except Interferencia as e:
            self.recuperar(str(e))
        return True

    # --- mouse ---
    def mover(self, cx, cy, rapido=False):
        cx += random.randint(-3, 3)
        cy += random.randint(-3, 3)
        cur = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cur))
        e = getattr(self, "esc", 1.0)
        tx, ty = self.ox + round(cx * e), self.oy + round(cy * e)
        dist = max(abs(tx - cur.x), abs(ty - cur.y))
        turbo = rapido and getattr(self, "_turbo_drops", False)      # solo mientras se levantan sacos
        pasos = max(2, min(8, dist // 45)) if turbo else max(4, min(25, dist // 18))
        desarmar()                                   # mientras nos movemos nosotros, no vigilar
        for i in range(1, pasos + 1):
            revisar()
            user32.SetCursorPos(cur.x + (tx - cur.x) * i // pasos, cur.y + (ty - cur.y) * i // pasos)
            time.sleep(0.005 if turbo else 0.010)
        global _ESPERADO
        _ESPERADO = (tx, ty)
        dormir(CFG["asentar_rapido"] if rapido else 0.3)

    def _pulsar(self, rapido=False):
        global _PULSANDO
        _revisar_usuario()
        _PULSANDO = True
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            dormir(random.uniform(0.07, 0.10) if rapido else random.uniform(0.10, 0.16))
        finally:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            _PULSANDO = False

    def hay_dialogo(self):
        ref = getattr(self, "_ref_dialogo", None)
        if ref is None:
            ref = self._ref_dialogo = Image.open(os.path.join(AQUI, "referencias", "dialogo_adquirir.png")).convert("RGB")
        vivo = self.captura((380, 245, 650, 300))
        return sum(ImageStat.Stat(ImageChops.difference(ref, vivo)).mean) / 3 < CFG["umbral_dialogo"]

    def vigilar(self):
        """Cierra el cuadro 'Adquirir' si aparece y para si el juego salio del Secret Garden."""
        if self.seco or getattr(self, "_sin_vigilar", False):
            return
        if user32.GetForegroundWindow() != self.hwnd:
            log("Audition perdio el primer plano: espero a que sueltes el mouse y lo recupero")
            desarmar()
            esperar_turno(minimo=3)
            self.localizar()
        self.revisar_aviso_maximo()
        for _ in range(3):
            if not self.hay_dialogo():
                break
            log("Cuadro 'Adquirir' detectado: pulso Confirmar")
            self.mover(*CFG["boton_confirmar"], rapido=True)
            self._pulsar()
            dormir(1.2)
        ok, dif = self.en_secret_garden()
        if not ok:
            raise Detenido(f"El juego salio del Secret Garden (diferencia {dif:.1f})")

    def clic(self, cx, cy, rapido=False):
        self.mover(cx, cy, rapido)
        if self.seco:
            return
        revisar()
        self._n = getattr(self, "_n", 0) + 1
        if self._n % 3 == 1:
            self.vigilar()
            self.mover(cx, cy, rapido=True)   # vigilar pudo mover el cursor
        self._pulsar()
        # el juego ignora clics mientras anima el anterior
        dormir(random.uniform(CFG["pausa_clic_min"], CFG["pausa_clic_max"]))

    # --- acciones del jardin ---
    def parcela(self, f, c):
        g = CFG["parcelas"]
        return g["x0"] + g["dx"] * c, g["y0"] + g["dy"] * f

    def punto_siembra(self, f, c):
        """El juego pone un cuadrado de 64x64 con esquina en la cuadricula de 32 px bajo el cursor.
        Para que caiga exactamente sobre la parcela hay que apuntar a su cuarto superior izquierdo."""
        g = CFG["siembra"]
        return g["x0"] + CFG["parcelas"]["dx"] * c, g["y0"] + CFG["parcelas"]["dy"] * f

    # --- clics verificados: se repite hasta que el juego reacciona ---
    @staticmethod
    def diferencia(a, b):
        import numpy as np
        return float(np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int)).mean())

    def caja_celda(self, f, c):
        cx, cy = self.parcela(f, c)
        # solo la planta de esta celda (sin invadir a las vecinas)
        return (cx - 26, cy - 40, cx + 26, cy + 30)

    def clic_verificado(self, cx, cy, caja, umbral, etiqueta, intentos=3):
        """Clic que se repite hasta que la zona 'caja' cambia (el juego reacciono)."""
        for n in range(1, intentos + 1):
            antes = self.captura(caja)
            self.clic(cx, cy, rapido=True)
            dormir(CFG["espera_verificar"])
            dif = self.diferencia(antes, self.captura(caja))
            if dif >= umbral:
                log(f"  {etiqueta}: ok (cambio {dif:.1f}, intento {n})")
                return True
            log(f"  {etiqueta}: sin reaccion (cambio {dif:.1f}), reintento {n}/{intentos}")
        return False

    def sobre_parcelas(self, herramienta, solo_una=False, pasadas=None):
        x, y = CFG["herramientas"][herramienta]
        self.clic(x, y)
        dormir(0.4)
        if self.seco or herramienta not in CFG["verificacion"]:
            self.sobre_parcelas_ya_elegido(solo_una, pasadas)
            return
        self.recorrer_verificado(herramienta, solo_una)

    def todas_las_celdas(self):
        """Las parcelas del programa: todas menos las que el usuario marco como suyas (ajustes 'excluir')."""
        excl = {tuple(int(x) for x in k.split(",")) for k in ajustes.leer().get("excluir", [])}
        ahora = time.time()
        atascadas = {k for k, t in getattr(self, "_atascadas", {}).items() if t > ahora}
        return [(f, c) for f in range(CFG["parcelas"]["filas"])
                for c in range(CFG["parcelas"]["columnas"]) if (f, c) not in excl and (f, c) not in atascadas]

    def recorrer_verificado(self, herramienta, solo_una=False, celdas=None):
        v = CFG["verificacion"][herramienta]
        celdas = celdas if celdas is not None else self.todas_las_celdas()
        fallos = 0
        for f, c in celdas:
            caja = tuple(v["contador"]) if "contador" in v else self.caja_celda(f, c)
            punto = self.punto_siembra(f, c) if herramienta == "sembrar" else self.parcela(f, c)
            ok = self.clic_verificado(*punto, caja, v["umbral"],
                                      f"{herramienta} ({f},{c})",
                                      intentos=v.get("intentos", 3))
            fallos += 0 if ok else 1
            if solo_una:
                return
        log(f"{herramienta}: {len(celdas) - fallos}/{len(celdas)} parcelas con reaccion")

    # --- globos de agua: marcan donde hay una planta sin regar ---
    def burbujas(self, tipo="agua"):
        """Centros de los globos de 'agua' (regadera rosa) o 'abono' (bolsita dorada), coordenadas del cliente."""
        import numpy as np
        from collections import deque
        x0, y0, x1, y1 = 330, 110, 720, 440
        a = np.asarray(self.captura((x0, y0, x1, y1))).astype(int)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        if tipo == "agua":
            m = (r > 205) & (g < 140) & (b > 85) & (b < 205) & (r - g > 85)
        else:
            m = (r > 150) & (g > 100) & (b < 90) & (r - b > 90)
        pend = set(zip(*[v.tolist() for v in np.nonzero(m)]))
        centros = []
        while pend:
            ini = pend.pop()
            cola, pts = deque([ini]), [ini]
            while cola:
                y, x = cola.popleft()
                for dy in range(-3, 4):
                    for dx in range(-3, 4):
                        q = (y + dy, x + dx)
                        if q in pend:
                            pend.discard(q)
                            cola.append(q)
                            pts.append(q)
            if len(pts) >= 40:
                ys = [t[0] for t in pts]
                xs = [t[1] for t in pts]
                centros.append((int(sum(xs) / len(xs)) + x0, int(sum(ys) / len(ys)) + y0))
        return sorted(centros, key=lambda t: (round(t[1] / 30), t[0]))

    def plantas_por_burbuja(self):
        """La planta queda ~33 px a la izquierda y ~35 px debajo de su globo."""
        return [(bx - 33, by + 35) for bx, by in self.burbujas()]

    @staticmethod
    def celda_de_burbuja(bx, by):
        """Globos de plantas bien alineadas: x = 416 + 64*c, y = 157 + 64*f."""
        c, f = round((bx - 416) / 64), round((by - 157) / 64)
        alineada = abs(bx - (416 + 64 * c)) <= 8 and abs(by - (157 + 64 * f)) <= 8
        return f, c, alineada

    def celdas_con_burbuja(self, tipo="agua"):
        """Parcelas con globo del tipo pedido (alineadas) y globos de plantas desalineadas."""
        ok, mal = [], []
        for bx, by in self.burbujas(tipo):
            f, c, alineada = self.celda_de_burbuja(bx, by)
            valida = 0 <= f < CFG["parcelas"]["filas"] and 0 <= c < CFG["parcelas"]["columnas"]
            if alineada and valida:
                ok.append((f, c))
            else:
                mal.append((bx - 33, by + 35))
        return sorted(set(ok)), mal

    def limpiar_desalineadas(self):
        """Corta SOLO las plantitas que quedaron fuera de la cuadrÃ­cula (las buenas no se tocan)."""
        for ronda in range(1, 4):
            _, mal = self.celdas_con_burbuja()
            if not mal:
                return
            log(f"Cortando {len(mal)} plantitas desalineadas (ronda {ronda})")
            self.clic(*CFG["herramientas"]["cosechar"])
            dormir(0.5)
            for x, y in mal:
                self.clic(x, y, rapido=True)
                dormir(CFG["espera_verificar"])
            dormir(1.5)

    def arrastrar_por(self, celdas, pausa=None):
        """Regar/abonar = mantener el boton pulsado y arrastrar por las plantas (zigzag)."""
        pausa = pausa if pausa is not None else CFG["pausa_arrastre"]
        orden = sorted(celdas, key=lambda k: (k[0], k[1] if k[0] % 2 == 0 else -k[1]))
        if not orden:
            return
        self.mover(*self.punto_siembra(*orden[0]))
        dormir(0.3)
        global _PULSANDO
        _revisar_usuario()
        _PULSANDO = True
        user32.mouse_event(0x0002, 0, 0, 0, 0)          # pulsar y MANTENER
        try:
            dormir(pausa)
            for k in orden:
                self.mover(*self.punto_siembra(*k), rapido=True)
                dormir(pausa)
        finally:
            user32.mouse_event(0x0004, 0, 0, 0, 0)      # soltar siempre
            _PULSANDO = False
        dormir(0.5)

    def regar_por_burbujas(self):
        self.clic(*CFG["herramientas"]["regar"])
        dormir(0.5)
        for ronda in range(1, 7):
            self.vigilar()
            celdas, _ = self.celdas_con_burbuja()
            if not celdas:
                log("Todas regadas (ya no quedan globos)")
                return True
            log(f"Regando {len(celdas)} plantas arrastrando (ronda {ronda})")
            self.arrastrar_por(celdas)
            dormir(1.5)
        celdas, _ = self.celdas_con_burbuja()
        if celdas:
            log(f"AVISO: quedan {len(celdas)} globos de agua tras 6 rondas")
        return not celdas

    def pulsar_mantenido(self, segundos):
        global _PULSANDO
        _revisar_usuario()
        _PULSANDO = True
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        try:
            dormir(segundos)
        finally:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            _PULSANDO = False

    def abonar_en(self, celdas):
        """Abonar = una pulsacion mantenida sobre CADA planta; el contador de abono confirma."""
        self.clic(*CFG["herramientas"]["fertilizar"])
        dormir(0.5)
        v = CFG["verificacion"]["fertilizar"]
        caja = tuple(v["contador"])
        fallos = 0
        for (f, c) in celdas:
            ok = False
            for intento in range(1, 4):
                self.vigilar()
                antes = self.captura(caja)
                self.mover(*self.punto_siembra(f, c), rapido=True)
                self.pulsar_mantenido(CFG["pausa_abono"])
                dormir(CFG["espera_verificar"])
                dif = self.diferencia(antes, self.captura(caja))
                if dif >= v["umbral"]:
                    log(f"  abonar ({f},{c}): ok (cambio {dif:.1f}, intento {intento})")
                    ok = True
                    break
                log(f"  abonar ({f},{c}): sin reaccion ({dif:.1f}), reintento {intento}/3")
            fallos += 0 if ok else 1
        log(f"abonar: {len(celdas) - fallos}/{len(celdas)} con reaccion")

    # --- drops: el saco que deja cada planta cosechada ---
    def cerrar_dialogo(self):
        """Si hay un cuadro 'Adquirir' abierto, pulsa Confirmar."""
        for _ in range(3):
            if not self.hay_dialogo():
                return
            log("Cuadro 'Adquirir': pulso Confirmar")
            self.mover(*CFG["boton_confirmar"], rapido=True)
            self._pulsar()
            dormir(1.2)
            if self.hay_dialogo():          # no se cerro con el clic: probar Enter
                user32.keybd_event(0x0D, 0, 0, 0)
                user32.keybd_event(0x0D, 0, 2, 0)
                dormir(1.0)

    def sin_herramienta(self):
        """True si la nubecita de herramienta junto al personaje no esta (ninguna herramienta activa)."""
        ref = Image.open(os.path.join(AQUI, "referencias", "sin_herramienta.png")).convert("RGB")
        vivo = self.captura((865, 185, 990, 305))
        return sum(ImageStat.Stat(ImageChops.difference(ref, vivo)).mean) / 3 < CFG["umbral_sin_herramienta"]

    def soltar_herramienta(self):
        """Clic derecho en terreno libre y COMPRUEBA que la herramienta se solto (si no, la hoz o la
        estrella siguen tiÃ±endo el jardin y las plantas vacias parecen marchitas)."""
        for intento in range(3):
            self.mover(*CFG["terreno_libre"])
            user32.mouse_event(0x0008, 0, 0, 0, 0)
            dormir(0.12)
            user32.mouse_event(0x0010, 0, 0, 0, 0)
            dormir(0.8)
            if self.seco or self.sin_herramienta():
                return True
        log("AVISO: no pude confirmar que la herramienta se soltara")
        return False

    def punto_saco(self, f, c):
        d = CFG["drops"]
        return d["x0"] + d["dx"] * c, d["y0"] + d["dy"] * f

    def hay_saco(self, img, f, c):
        """El saco es crema/blanco (r,g,b altos). Mide cuantos pixeles crema hay en su sitio."""
        import numpy as np
        x, y = self.punto_saco(f, c)
        a = np.asarray(img.crop((x - 14, y - 12, x + 14, y + 12))).astype(int)
        crema = (a[..., 0] > 205) & (a[..., 1] > 195) & (a[..., 2] > 160)
        return int(crema.sum()) >= CFG["saco_min_px"]

    def hay_saco_aqui(self, f, c):
        """Como hay_saco pero capturando solo la zona del saco (mucho mas barato que toda la pantalla)."""
        import numpy as np
        x, y = self.punto_saco(f, c)
        a = np.asarray(self.captura((x - 14, y - 12, x + 14, y + 12))).astype(int)
        crema = (a[..., 0] > 205) & (a[..., 1] > 195) & (a[..., 2] > 160)
        return int(crema.sum()) >= CFG["saco_min_px"]

    def sacos_presentes(self):
        img = self.captura((0, 0, 1024, 768))
        return [(f, c) for f, c in self.todas_las_celdas() if self.hay_saco(img, f, c)]

    def esperar_dialogo(self, max_seg=1.0):
        fin = time.time() + max_seg
        while time.time() < fin:
            if self.hay_dialogo():
                return True
            dormir(0.04)
        return False

    def confirmar_dialogo_rapido(self):
        """Pulsa Confirmar y sigue en cuanto el cuadro desaparece (sondeo cada 50 ms, tope 1.5 s).
        Si no se cierra, usa el metodo lento de siempre (clic + Enter)."""
        if CFG.get("drops_enter", True) and not (getattr(self, "_enter_mal", 0) >= 3
                                                  and not getattr(self, "_enter_bien", 0)):
            user32.keybd_event(0x0D, 0x1C, 0, 0)                 # Enter con scancode (0x1C)
            time.sleep(0.03)
            user32.keybd_event(0x0D, 0x1C, 2, 0)
            fin = time.time() + 0.7
            while time.time() < fin:
                dormir(0.03)
                if not self.hay_dialogo():
                    self._enter_bien = getattr(self, "_enter_bien", 0) + 1
                    return
            self._enter_mal = getattr(self, "_enter_mal", 0) + 1
        self.mover(*CFG["boton_confirmar"], rapido=True)
        self._pulsar(rapido=True)
        fin = time.time() + 1.5
        while time.time() < fin:
            if not self.hay_dialogo():
                return
            dormir(0.04)
        self.cerrar_dialogo()

    def recoger_drops(self):
        """Levanta los drops hasta que NO quede ningun saco a la vista. El saco desaparece cuando se
        levanta todo lo de esa parcela, asi que se comprueba mirando y se repite solo donde quede.
        (El juego admite ~40-50 items en el suelo; si se acumulan, no deja cosechar.)"""
        t0 = time.time()
        self.cerrar_dialogo()
        self.soltar_herramienta()
        total = 0
        objetivo = self.todas_las_celdas()
        if CFG.get("drops_solo_con_saco", True):
            # ir solo a las parcelas con saco: no gastar clics (2 x 1.1 s) en las que estan vacias
            objetivo = self.sacos_presentes()
            log(f"Sacos a la vista: {len(objetivo)} de {len(self.todas_las_celdas())} parcelas")
        restantes = []
        self._turbo_drops = True
        asentar_previo = CFG["asentar_rapido"]
        CFG["asentar_rapido"] = min(asentar_previo, 0.03)          # mover mas ligero mientras se recogen drops
        for pasada in range(1, 7):
            for f, c in objetivo:
                x, y = self.punto_saco(f, c)
                sin = 0
                for _ in range(CFG["max_drops_por_parcela"]):
                    ta = time.time()
                    self.vigilar_sin_dialogo()
                    self.mover(x, y, rapido=True)
                    self._pulsar(rapido=True)
                    tb = time.time()
                    if self.esperar_dialogo(0.9):
                        tc = time.time()
                        total += 1
                        sin = 0
                        self.confirmar_dialogo_rapido()
                        log(f"  drop ({f},{c}): clic {tb - ta:.1f} s, cuadro tarda {tc - tb:.1f} s, "
                            f"confirmar {time.time() - tc:.1f} s (enter ok {getattr(self, '_enter_bien', 0)}, "
                            f"fallo {getattr(self, '_enter_mal', 0)})")
                        if CFG.get("drops_una_por_pasada", True):
                            break      # siguiente parcela; si aun queda saco, la pasada siguiente vuelve solo ahi
                        if CFG.get("drops_corte_rapido", True):
                            dormir(0.18)
                            if not self.hay_saco_aqui(f, c):
                                break
                    else:
                        sin += 1
                        log(f"  sin cuadro en ({f},{c}) tras {time.time() - ta:.1f} s")
                        if sin >= CFG["drops_vacios_para_parar"]:
                            break
            self.mover(*CFG["terreno_libre"])
            dormir(0.8)
            restantes = self.sacos_presentes()
            if not restantes:
                break
            log(f"Pasada {pasada}: aun se ven sacos en {len(restantes)} parcelas {restantes}")
            objetivo = restantes
        CFG["asentar_rapido"] = asentar_previo
        self._turbo_drops = False
        self._items_suelo = len(restantes)
        if restantes:
            log(f"AVISO: quedan sacos en {len(restantes)} parcelas tras 6 pasadas")
        log(f"Drops recogidos: {total}; sacos que quedan a la vista: {len(restantes)} ({time.time() - t0:.0f} s)")
        return total

    def vigilar_sin_dialogo(self):
        if user32.GetForegroundWindow() != self.hwnd:
            raise Detenido("Audition perdio el primer plano (otra ventana encima)")

    # --- que hay en cada parcela ---
    def estado_celdas(self):
        """{(f,c): 'vacia' | 'joven' | 'madura' | 'marchita'} mirando la pantalla.
        vacia: sin hojas. Madura: hojas oscuras (pocas muy brillantes, <=10%); joven: verde claro brillante."""
        import numpy as np
        img = self.captura((0, 0, 1024, 768))
        res = {}
        for f, c in self.todas_las_celdas():
            cx, cy = self.parcela(f, c)
            a = np.asarray(img.crop((cx - 24, cy - 30, cx + 24, cy + 22))).astype(int)
            r, g, b = a[..., 0], a[..., 1], a[..., 2]
            oscuro = float((a.max(axis=2) < 60).mean())
            mask = (g > r + 8) & (g > b + 25) & (g > 85)
            hoja = float(mask.mean())
            tarjeta = float((a.min(axis=2) > 170).mean())    # la parcela vacia muestra una tarjeta crema (~4,5 %)
            if (CFG["auto_resucitar"] and oscuro > CFG["marchita_umbral"] and hoja < CFG["hoja_umbral"]
                    and tarjeta < 0.02):
                res[(f, c)] = "marchita"
            elif hoja < CFG["hoja_umbral"]:
                res[(f, c)] = "vacia"
            else:
                brillante = float(((g > 150) & mask).sum() / max(1, mask.sum()))
                if getattr(self, "semilla_actual", "romero") == "menta_verde":
                    m = CFG["madurez_menta_verde"]       # madura = hojas grandes y SIN el circulo azul
                    azul = float(((b > r + 40) & (b > 140)).mean())
                    ok = hoja >= m["hoja_min"] and azul <= m["azul_max"]
                else:
                    ok = brillante <= CFG["maduro_brillante"]
                res[(f, c)] = "madura" if ok else "joven"
        falsas = getattr(self, "_falsas_marchitas", None)
        if falsas:
            for k in list(falsas):
                if res.get(k) == "marchita":
                    res[k] = "vacia"
                else:
                    falsas.discard(k)
        if getattr(self, "semilla_actual", "") in CFG["madurez_por_reloj"]:
            # esta planta no se distingue bien por color: madura SOLO cuando se cumple su reloj
            cumplido = getattr(self, "reloj_cumplido", False)     # respaldo si no se la hora de siembra
            t_plan = ajustes.leer()["minutos"].get(self.semilla_actual, CFG["tiempos_min"][self.semilla_actual]) * 60
            plantado = getattr(self, "plantado_en", {})
            ahora = time.time()
            if not hasattr(self, "plantado_en"):
                self.plantado_en = plantado = {}
            vacias_vistas = self.__dict__.setdefault("_vistas_vacias", set())
            for k, v in res.items():
                if v == "vacia":
                    vacias_vistas.add(k)      # no se borra su hora: una lectura falsa (ventana encima) no debe reiniciar el reloj
                elif v in ("joven", "madura") and k not in plantado and k in vacias_vistas:
                    plantado[k] = ahora          # estaba vacia y ahora tiene planta (la puso alguien): empieza su reloj
                    vacias_vistas.discard(k)
            vis = dict(res)                      # lo que se ve en pantalla, antes de aplicar el reloj
            sin_ver = 0
            for k, v in res.items():
                if v in ("joven", "madura"):
                    inicio = plantado.get(k)
                    lista = (ahora >= inicio + t_plan) if inicio is not None else cumplido
                    if (lista and inicio is not None and self.semilla_actual == "menta_verde"
                            and vis[k] != "madura" and ahora < inicio + t_plan + CFG.get("gracia_visual_seg", 90)):
                        lista = False                # el reloj dice listo pero la planta aun se ve joven: espero un poco
                        sin_ver += 1
                    res[k] = "madura" if lista else "joven"
            if sin_ver and time.time() - getattr(self, "_t_aviso_visual", 0) > 20:
                self._t_aviso_visual = time.time()
                log(f"El reloj dice listo pero {sin_ver} plantas aun se ven jovenes: espero hasta {CFG.get('gracia_visual_seg', 90)} s")
        if getattr(self, "forzar_madura", False):
            for k, v in res.items():
                if v == "joven":
                    res[k] = "madura"
        return res

    @staticmethod
    def contar(estado):
        n = {"vacia": 0, "joven": 0, "madura": 0, "marchita": 0}
        for v in estado.values():
            n[v] += 1
        return n

    def elegir_semilla(self, semilla):
        # la ventana de semillas oscurece el jardin: no vigilar mientras esta abierta
        self._sin_vigilar = True
        try:
            self.clic(*CFG["herramientas"]["sembrar"])
            dormir(1.2)
            self.clic(*CFG["semillas"][semilla])
            dormir(1.2)
        finally:
            self._sin_vigilar = False

    def sembrar(self, semilla, solo_una=False, celdas=None):
        """Siembra de corrido y comprueba despues por los globos que aparecieron; repite las que faltan."""
        celdas = celdas if celdas is not None else self.todas_las_celdas()
        self.elegir_semilla(semilla)
        pendientes = list(celdas)
        for ronda in range(1, 4):
            for i, (f, c) in enumerate(pendientes):
                if i % 6 == 0:
                    self.vigilar()
                self.mover(*self.punto_siembra(f, c), rapido=True)
                self._pulsar(rapido=True)
                dormir(CFG["pausa_siembra"])
                if solo_una:
                    return
            dormir(1.0)
            plantadas, _ = self.celdas_con_burbuja()
            pendientes = [k for k in celdas if k not in set(plantadas)]
            log(f"Siembra ronda {ronda}: {len(celdas) - len(pendientes)}/{len(celdas)} plantadas")
            if not pendientes:
                return
        log(f"AVISO: {len(pendientes)} parcelas sin plantar tras 3 rondas")

    def cosechar_rapido(self, celdas):
        """Corta con calma y comprueba de verdad: tras cada pasada suelta la herramienta, mira que parcelas
        siguen con planta y repite solo esas (hasta 4 rondas)."""
        pendientes = list(celdas)
        for ronda in range(1, 5):
            self.clic(*CFG["herramientas"]["cosechar"])
            dormir(0.4)
            for i, (f, c) in enumerate(pendientes):
                if i % 6 == 0:
                    self.vigilar()
                self.mover(*self.parcela(f, c))
                dormir(CFG["asentar_cosecha"])
                self._pulsar()
                dormir(CFG["pausa_cosecha"])
            dormir(2.0)                      # que terminen las animaciones antes de mirar
            self.soltar_herramienta()
            est = self.estado_celdas()
            pendientes = [k for k in pendientes if est[k] != "vacia"]
            negras = [k for k in pendientes if est[k] == "marchita"]
            if len(negras) >= 4:
                # tras cortar, tierra vacia leida como 'negra' (sin tarjeta crema): no son plantas, se tratan como vacias
                log(f"{len(negras)} parcelas 'negras' tras cortar: es tierra vacia mal leida; las trato como vacias")
                self._falsas_marchitas = set(getattr(self, "_falsas_marchitas", set())) | set(negras)
                est = self.estado_celdas()
                pendientes = [k for k in pendientes if est[k] != "vacia"]
            if len(pendientes) >= 4 and not getattr(self, "_drops_en_cosecha", False):
                # tantas 'sin cortar' a la vez suelen ser los sacos que deja la cosecha tapando la parcela
                # (se leen como planta): los levanto y vuelvo a mirar antes de volver a cortar
                log(f"{len(pendientes)} parcelas parecen sin cortar: levanto los sacos y vuelvo a mirar")
                self._drops_en_cosecha = True
                try:
                    self.recoger_drops()
                finally:
                    self._drops_en_cosecha = False
                self.soltar_herramienta()
                est = self.estado_celdas()
                pendientes = [k for k in pendientes if est[k] != "vacia"]
            log(f"Cosecha ronda {ronda}: {len(celdas) - len(pendientes)}/{len(celdas)} cortadas")
            if not pendientes:
                return True
        log(f"AVISO: {len(pendientes)} parcelas sin cortar tras 4 rondas: {pendientes}")
        sonido.pitar(500, 400)
        return False

    def aplicar(self, herramienta, celdas):
        """Elige la herramienta y la usa solo en 'celdas', verificando cada clic."""
        self.clic(*CFG["herramientas"][herramienta])
        dormir(0.4)
        self.recorrer_verificado(herramienta, celdas=celdas)

    def sembrar_regar_fertilizar(self, semilla, solo_una=False):
        self.sembrar(semilla, solo_una)
        if solo_una:
            return
        self.sobre_parcelas("regar")
        self.sobre_parcelas("fertilizar")

    def sobre_parcelas_ya_elegido(self, solo_una=False, pasadas=None):
        """Recorre las 20 parcelas. Varias pasadas: lo que el juego ignora en una, lo toma la otra."""
        for _ in range(pasadas or CFG["pasadas"]):
            for f, c in self.todas_las_celdas():
                self.clic(*self.parcela(f, c), rapido=True)
                if solo_una:
                    return

    def celdas_marchitas(self):
        """Plantas marchitas = casi negras (65-70% de pixeles oscuros; sanas <12%, vacias ~0%)."""
        import numpy as np
        img = self.captura((0, 0, 1024, 768))
        marchitas = []
        for f, c in self.todas_las_celdas():
            cx, cy = self.parcela(f, c)
            a = np.asarray(img.crop((cx - 24, cy - 26, cx + 24, cy + 22))).astype(int)
            if float((a.max(axis=2) < 60).mean()) > CFG["marchita_umbral"]:
                marchitas.append((f, c))
        return marchitas

    def refrescar_jardin(self):
        """Bug visual del juego (plantas negras): ir al Couple Garden y volver al Secret Garden."""
        log("Plantas negras: refresco el jardin (Couple Garden y vuelta al Secret Garden)")
        self.soltar_herramienta()
        previo = getattr(self, "_sin_vigilar", False)
        self._sin_vigilar = True
        try:
            for destino in ("couple", "secret"):
                self.mover(*CFG["boton_cambiar_jardin"])
                self._pulsar()
                dormir(CFG["espera_cambio_jardin"])
                if destino == "secret":
                    for _ in range(12):               # esperar a que cargue el Secret Garden
                        ok, _dif = self.en_secret_garden()
                        if ok:
                            break
                        dormir(1.0)
                    else:
                        raise Detenido("No volvi al Secret Garden tras refrescar")
            dormir(1.5)
        finally:
            self._sin_vigilar = previo

    def resucitar_marchitas(self):
        """Resucita las plantas negras. Se mide SIN herramienta: con ella el terreno vacio tambien se oscurece."""
        for ronda in range(1, 3):
            self.soltar_herramienta()
            m = [k for k, v in self.estado_celdas().items() if v == "marchita"]
            log(f"Plantas marchitas: {len(m)}" + (f" (ronda {ronda})" if m else ""))
            if not m:
                return
            self.clic(*CFG["herramientas"]["resucitar"])
            dormir(0.5)
            for f, c in m:
                self.vigilar_sin_dialogo()
                self.mover(*self.parcela(f, c), rapido=True)
                self._pulsar(rapido=True)
                dormir(CFG["pausa_resucitar"])
            dormir(2.5)   # la animacion de revivir tarda: medir antes gasta estrellas de mas
        self.soltar_herramienta()
        log("AVISO: siguen marchitas tras 2 rondas; las dejo")

    def ir_a(self, destino):
        """Cambia de jardin ('couple' o 'secret') con el boton de la barra superior."""
        previo = getattr(self, "_sin_vigilar", False)
        self._sin_vigilar = True
        try:
            comprobar = self.en_couple_garden if destino == "couple" else (lambda: self.en_secret_garden()[0])
            if comprobar():
                return True
            self.soltar_herramienta()
            self.mover(*CFG["boton_cambiar_jardin"])
            self._pulsar()
            for _ in range(15):
                dormir(1.0)
                if comprobar():
                    dormir(1.5)
                    return True
            return False
        finally:
            self._sin_vigilar = previo

    def visita_couple(self):
        """v0: ir al Couple Garden en la hora en punto, sacar capturas cada 5 s (sin actuar) y volver."""
        log("== Visita al Couple Garden (hora en punto): solo observo ==")
        carpeta = os.path.join(AQUI, "observacion")
        os.makedirs(carpeta, exist_ok=True)
        if not self.ir_a("couple"):
            raise Detenido("No llegue al Couple Garden")
        self.mover(*CFG["terreno_libre"])
        desarmar()
        inicio = time.time()
        while time.time() - inicio < CFG["visita_seg"]:
            ahora = time.strftime("%H%M%S")
            self.captura((0, 0, 1024, 768)).resize((768, 576)).save(
                os.path.join(carpeta, f"couple_{ahora}.jpg"), quality=82)
            dormir(CFG["visita_cada_seg"])
        log(f"Visita terminada ({time.time() - inicio:.0f} s); vuelvo al Secret Garden")
        if not self.ir_a("secret"):
            raise Detenido("No pude volver al Secret Garden tras la visita")

    def mirar_pasivo(self):
        """Mira la pantalla SIN mover el mouse ni robar el foco. None si no se puede (ventana
        minimizada, tapada, o no es el Secret Garden)."""
        h = user32.FindWindowW(None, "Audition")
        if not h or user32.IsIconic(h):
            return None
        self.hwnd = h
        p = wintypes.POINT(0, 0)
        user32.ClientToScreen(h, ctypes.byref(p))
        self.ox, self.oy = p.x, p.y
        self._revisar_tamano()                   # la ventana pudo cambiar de monitor (otra escala)
        arriba = user32.WindowFromPoint(wintypes.POINT(self.ox + 500, self.oy + 400))
        if not arriba or user32.GetAncestor(arriba, 2) != h:      # 2 = GA_ROOT: otra ventana encima
            return None
        if not self.en_secret_garden()[0]:
            return None
        return self.estado_celdas()

    def cuidar_pendientes(self):
        """Riega las plantas con globo de agua y abona las que tienen globo de abono.
        Sirve si el jardin lo sembro el usuario a mano o si una rafaga se interrumpio."""
        hizo = False
        agua, _ = self.celdas_con_burbuja("agua")
        if agua:
            log(f"Cuidado pendiente: {len(agua)} plantas piden agua")
            self.regar_por_burbujas()
            hizo = True
            dormir(1.0)
        abono, _ = self.celdas_con_burbuja("abono")
        if abono:
            log(f"Cuidado pendiente: {len(abono)} plantas piden abono")
            self.abonar_en(abono)
            hizo = True
        return hizo

    def burst_inteligente(self, semilla, listo_en):
        """Mira el jardin: corta SOLO lo maduro (cuando ya no quedan jovenes), siembra lo vacio."""
        self.cerrar_dialogo()
        self.soltar_herramienta()            # sin herramienta el jardin se ve sin tintes
        est = self.estado_celdas()
        n = self.contar(est)
        log(f"Jardin: {n['madura']} maduras, {n['joven']} jovenes, {n['vacia']} vacias, {n['marchita']} marchitas")
        if n["marchita"] >= 8:
            # tantas marchitas a la vez no es real: es tierra vacia leida como negra (sin tarjeta crema)
            self._falsas_marchitas = {k for k, v in est.items() if v == "marchita"}
            log(f"{n['marchita']} 'marchitas' a la vez: es tierra vacia; las trato como vacias")
            est = self.estado_celdas()
            n = self.contar(est)
        if n["marchita"]:
            self.refrescar_jardin()
            self.soltar_herramienta()
            est = self.estado_celdas()
            n = self.contar(est)
            log(f"Tras refrescar: {n['madura']} maduras, {n['joven']} jovenes, {n['vacia']} vacias, {n['marchita']} marchitas")
        if n["marchita"]:
            log("Siguen negras tras refrescar: son marchitas de verdad, las resucito")
            self.resucitar_marchitas()
            self.soltar_herramienta()
            est = self.estado_celdas()
            n = self.contar(est)
            log(f"Tras resucitar: {n['madura']} maduras, {n['joven']} jovenes, {n['vacia']} vacias, {n['marchita']} marchitas")
            if n["marchita"]:
                # calibracion: siguen "negras" aunque se resucito y la pantalla las muestra sin planta (tierra
                # oscura sin tarjeta): son parcelas vacias que se leen mal; se tratan como vacias hasta que cambien
                resto_m = {k for k, v in est.items() if v == "marchita"}
                if len(resto_m) <= 3:
                    # pocas y no responden: es maleza u otro objeto, no una planta; las dejo en paz 30 min
                    self.__dict__.setdefault("_atascadas", {}).update({k: time.time() + 1800 for k in resto_m})
                    log(f"{sorted(resto_m)} no responden a resucitar ni a cortar: las dejo en paz 30 min y siembro el resto")
                else:
                    self._falsas_marchitas = resto_m
                    log(f"Calibro: {len(resto_m)} parcelas 'negras' no responden a resucitar: las trato como vacias")
                est = self.estado_celdas()
                n = self.contar(est)
        if n["joven"]:
            # aunque ya haya alguna madura mezclada: lo que pide agua o abono se atiende primero
            if self.cuidar_pendientes():
                self.t_siembra = time.time()      # el reloj corre desde el ultimo cuidado
                if getattr(self, "plantado_en", None):
                    # regla: los minutos se cuentan desde el ULTIMO abono; un riego/abono a mitad de ciclo reinicia la cuenta
                    self.plantado_en = {k: self.t_siembra for k in self.plantado_en}
                self.recoger_drops()
                return True
        maduras = [k for k, v in est.items() if v == "madura"]
        if maduras:
            if not hasattr(self, "_primer_maduro"):
                self._primer_maduro = time.time()
            espera = time.time() - self._primer_maduro
            if n["joven"] and espera < CFG["espera_maduracion_seg"]:
                log(f"{len(maduras)} maduras pero aun hay {n['joven']} jovenes: espero (llevo {espera:.0f} s)")
                return False
            if n["joven"] and CFG.get("sincronizar_jardin", True):
                # pasado el margen, lo que aun esta joven se corta junto con lo maduro: asi las 20 se vuelven a
                # sembrar a la vez y maduran juntas (cortar en tandas deja el jardin desfasado para siempre)
                jovenes = [k for k, v in est.items() if v == "joven"]
                log(f"Sincronizo el jardin: corto tambien {len(jovenes)} jovenes para sembrar todo junto")
                maduras = maduras + jovenes
            self.mover(*CFG["terreno_libre"])
            dormir(0.5)
            con_sacos = self.sacos_presentes()
            if len(con_sacos) > CFG["sacos_para_limpiar_antes"]:
                log(f"Hay sacos en {len(con_sacos)} parcelas antes de cortar: levanto primero")
                self.recoger_drops()
            log(f"Cosechando {len(maduras)} maduras")
            self.cosechar_rapido(maduras)
            for k in maduras:
                getattr(self, "plantado_en", {}).pop(k, None)
            self._items_suelo = getattr(self, "_items_suelo", 0) + len(maduras)
            if getattr(self, "forzar_madura", False):
                self.forzar_madura = False
                try:
                    os.remove(os.path.join(AQUI, "cosechar_ya.flag"))
                except OSError:
                    pass
                log("Orden 'cosechar ya' cumplida")
            del self._primer_maduro
            # comprobar parcela por parcela que quedaron vacias; las que no, se cortan de nuevo
            for ronda in range(1, 4):
                self.soltar_herramienta()
                est = self.estado_celdas()
                resto = [k for k in maduras if est[k] != "vacia"]
                if not resto:
                    break
                log(f"{len(resto)} parcelas siguen con planta tras cortar {resto}: las corto de nuevo (ronda {ronda})")
                self.cosechar_rapido(resto)
            else:
                self.soltar_herramienta()
                est = self.estado_celdas()
                resto = [k for k in maduras if est[k] != "vacia"]
                if resto:
                    log(f"AVISO: no pude vaciar {resto} tras 3 rondas")
                    sonido.pitar(500, 400)
                    if len(resto) <= 3:
                        # pocas y no se cortan: maleza u otro objeto; las dejo en paz 30 min en vez de insistir
                        self.__dict__.setdefault("_atascadas", {}).update({k: time.time() + 1800 for k in resto})
                        log(f"Dejo en paz {resto} durante 30 min: no hay nada que cortar ahi")
                    else:
                        # tantas a la vez no son objetos: es la lectura de la pantalla (imagen vieja). No excluyo
                        # nada: refresco el jardin y dejo que la siguiente vuelta lo vea y siembre las 20
                        log(f"{len(resto)} parcelas 'sin cortar' a la vez: es lectura, no objetos; refresco y no excluyo nada")
                        self.refrescar_jardin()
                        self.soltar_herramienta()
                        self._atascadas = {}
                        self._falsas_marchitas = set()
        elif n["joven"] and not n["vacia"]:
            log(f"{n['joven']} plantas jovenes aun creciendo: no cosecho")
            if self.celdas_con_burbuja("agua")[0]:           # riego interrumpido: terminar de regar y abonar
                log("Quedan plantas sin regar de una vuelta interrumpida: las riego")
                self.regar_por_burbujas()
                ab, _ = self.celdas_con_burbuja("abono")
                if ab:
                    self.abonar_en(ab)
            if self.sacos_presentes():                      # quedaron sacos de una vuelta interrumpida: levantarlos
                log("Quedan sacos en el suelo: los levanto")
                self.recoger_drops()
            return False
        if CFG["cortar_desalineadas"]:
            self.limpiar_desalineadas()
        else:
            _, mal = self.celdas_con_burbuja("agua")
            if mal:
                log(f"AVISO: {len(mal)} plantas fuera de la cuadricula; no las toco (cortar_desalineadas=false)")
        self.soltar_herramienta()
        est = self.estado_celdas()
        vacias = [k for k, v in est.items() if v == "vacia"]
        previas = sum(1 for v in est.values() if v == "joven")
        if not vacias:
            return False
        log(f"Sembrando {semilla} en {len(vacias)} parcelas vacias")
        self.sembrar(semilla, celdas=vacias)
        dormir(1.0)
        celdas, mal = self.celdas_con_burbuja()
        log(f"Plantitas alineadas tras sembrar: {len(celdas)} de {len(vacias)} (desalineadas: {len(mal)})")
        faltan = [k for k in vacias if k not in set(celdas)]
        if faltan:
            self.reparar_celdas(faltan, semilla)
            celdas, mal = self.celdas_con_burbuja("agua")
        self._anotar_siembra(semilla, celdas or vacias)    # ya hay planta: apuntar la hora YA, por si algo me interrumpe
        total = len(celdas) + previas
        n_par = len(self.todas_las_celdas())
        if total < n_par:
            log(f"AVISO: solo {total}/{n_par} parcelas con planta tras sembrar")
            sonido.pitar(500, 400)
        self.regar_por_burbujas()
        dormir(1.0)
        abono, _ = self.celdas_con_burbuja("abono")
        self.abonar_en(abono if abono else celdas)   # sin globo visible: abona las recien sembradas
        self._anotar_siembra(semilla, celdas or vacias)    # hora definitiva: tras regar y abonar
        self.recoger_drops()                  # mientras crecen, sin retrasar el reloj
        return True

    def _anotar_siembra(self, semilla, celdas):
        """Apunta la hora de siembra de esas parcelas y la guarda en estado.json en el acto: si el programa se
        interrumpe o se reinicia, nunca queda una hora vieja que haga cortar plantas recien sembradas."""
        self.t_siembra = time.time()
        self.semilla_actual = semilla
        if not hasattr(self, "plantado_en"):
            self.plantado_en = {}
        for k in celdas:
            self.plantado_en[k] = self.t_siembra
        if self.seco:
            return
        t = ajustes.leer()["minutos"].get(semilla, CFG["tiempos_min"][semilla]) * 60 + CFG["margen_seg"]
        listo = min(self.plantado_en.values()) + t
        try:
            with open(os.path.join(AQUI, "estado.json"), "w", encoding="utf-8") as f:
                json.dump({"semilla": semilla, "listo_en": listo, "indice": 1,
                           "plantado": {f"{k[0]},{k[1]}": v for k, v in self.plantado_en.items()}}, f)
        except OSError:
            pass

    def reparar_celdas(self, faltan, semilla):
        """Parcelas que no aceptaron semilla: probablemente hay una planta muerta. Resucitar, cortar
        lo que quede y volver a sembrar solo esas."""
        log(f"{len(faltan)} parcelas no aceptaron semilla {faltan}: resucito, corto y vuelvo a sembrar")
        self.clic(*CFG["herramientas"]["resucitar"])
        dormir(0.5)
        for f, c in faltan:
            self.mover(*self.parcela(f, c), rapido=True)
            self._pulsar(rapido=True)
            dormir(CFG["pausa_resucitar"])
        dormir(3.0)
        self.cosechar_rapido(faltan)
        self.soltar_herramienta()
        self.sembrar(semilla, celdas=faltan)

    def cosechar(self):
        self.resucitar_marchitas()
        self.sobre_parcelas("cosechar")


# --- convivencia con el usuario ---
class UltimoInput(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def segundos_sin_tocar():
    ii = UltimoInput(ctypes.sizeof(UltimoInput), 0)
    user32.GetLastInputInfo(ctypes.byref(ii))
    return (ctypes.windll.kernel32.GetTickCount() - ii.dwTime) / 1000.0


def esperar_turno(minimo=None):
    minimo = minimo or CFG["segundos_sin_tocar"]
    t0, ult = time.time(), 0
    while segundos_sin_tocar() < minimo:
        revisar()
        dormir(0.5)
        espera = time.time() - t0
        if espera > 30 and time.time() - ult > 120:      # no esperar en silencio: la planta se puede secar
            ult = time.time()
            log(f"Hay que cortar/atender pero estas usando el mouse o teclado (llevo {espera/60:.1f} min esperando): "
                f"sueltalos {minimo} s para que el programa trabaje")
            alarma(2)
    for n in range(CFG["cuenta_regresiva"], 0, -1):
        revisar()
        sonido.pitar(880, 120, "cuenta")
        log(f"Empiezo en {n}... (no muevas el mouse; F12 para cancelar)")
        dormir(1)


def rafaga(a, semilla, listo_en):
    """Una rÃ¡faga. Los problemas recuperables (cuadros de Windows, pantalla desconocida, demasiadas
    interferencias) NO matan el programa: se avisa, se espera y se vuelve a intentar."""
    try:
        return _rafaga(a, semilla, listo_en)
    except PantallaDesconocida as e:
        if a.reingresar():
            return False
        a.guardar_captura("pantalla_desconocida")
        ahora = time.time()
        if ahora - getattr(a, "_ult_alarma", 0) > 60:
            log(f"{e} Espero a que vuelvas a iniciar sesion / entrar al juego.")
            alarma(3)
            a._ult_alarma = ahora
        dormir(15)
        return False
    except Reintentar as e:
        log(f"{e}: espero 30 s y reintento")
        alarma(2)
        dormir(30)
        return False


class Reintentar(Exception):
    pass


def _rafaga(a, semilla, listo_en):
    primera = True
    limites = 0
    for intento in range(1, 8):
        if os.path.exists(os.path.join(AQUI, "reiniciar_cuenta.flag")) or os.path.exists(os.path.join(AQUI, "pausa.flag")):
            return False                          # orden de la interfaz: que el ciclo la atienda antes de seguir cortando
        try:
            if a.manejar_mensajes():
                primera = False                   # tras un cuadro, esperar turno otra vez abajo
            if primera:
                esperar_turno()
                primera = False
            a.localizar()
            if a.cerrar_avisos():
                dormir(1.0)
            ok, dif = a.en_secret_garden()
            if not ok:
                ok = a.navegar_a_secret_garden()
            if not ok:
                raise Detenido(f"No estoy en el Secret Garden (diferencia {dif:.1f}). Reviso y paro.")
            a.revisar_aviso_maximo()
            return a.burst_inteligente(semilla, listo_en)
        except LimiteItems:
            limites += 1
            if limites > 3:
                alarma(6)
                raise Detenido("El limite de items sigue ocupado tras 3 limpiezas: revisa el suelo del jardin")
            log(f"Limpieza por limite de items ({limites}/3): levanto todo y reintento la cosecha")
            a.soltar_herramienta()
            a.recoger_drops()
        except Interferencia as e:
            a.recuperar(str(e))
        finally:
            desarmar()
    raise Reintentar("Demasiadas interferencias seguidas")


def semilla_por_horario():
    """Devuelve la semilla que toca sembrar ahora segun CFG['horario'] (formato HH:MM, admite cruzar medianoche)."""
    ahora = time.localtime()
    m = ahora.tm_hour * 60 + ahora.tm_min
    for tramo in CFG["horario"]:
        d = int(tramo["desde"][:2]) * 60 + int(tramo["desde"][3:])
        h = int(tramo["hasta"][:2]) * 60 + int(tramo["hasta"][3:])
        if (d <= m < h) if d < h else (m >= d or m < h):
            return tramo["semilla"]
    return CFG["horario_por_defecto"]


def ciclo(args):
    a = Audition(seco=args.seco)
    alternar = args.semilla == "alternar"
    por_horario = args.semilla == "horario"
    patron = CFG["patron"] if alternar else ([semilla_por_horario()] if por_horario else [args.semilla])
    indice = 0
    a.semilla_actual = patron[0]              # planta que hay AHORA en el jardin (para detectar madurez)
    estado = os.path.join(AQUI, "estado.json")
    listo_en = None            # None = no se cuando se sembro: decide mirando el jardin
    if os.path.exists(estado) and not args.seco:
        with open(estado, encoding="utf-8") as f:
            e = json.load(f)
        if e.get("semilla") in CFG["tiempos_min"]:
            a.semilla_actual = e["semilla"]
            listo_en = e.get("listo_en")
            indice = e.get("indice", 0)
            a.plantado_en = {tuple(int(x) for x in k.split(",")): v for k, v in e.get("plantado", {}).items()}
            if listo_en and listo_en > time.time():
                log(f"Retomo ({a.semilla_actual}): faltan {(listo_en - time.time())/60:.1f} min para cosechar")
    if alternar:
        log(f"Modo alternar. Patron: {patron}")
    if por_horario:
        log(f"Modo horario: {CFG['horario']}; ahora toca {patron[0]}")
    for nombre_flag in ("cosechar_ya.flag", "reiniciar_cuenta.flag", "pausa.flag"):
        ruta_flag = os.path.join(AQUI, nombre_flag)
        if os.path.exists(ruta_flag) and time.time() - os.path.getmtime(ruta_flag) > 120:
            os.remove(ruta_flag)
            log(f"Orden vieja descartada al arrancar ({nombre_flag}): se dio con el programa parado")
    if os.path.exists(os.path.join(AQUI, "cosechar_ya.flag")):
        a.forzar_madura = True
        listo_en = None
        log("Orden 'cosechar ya': las plantas actuales se tratan como maduras en esta vuelta")
    n = 0
    ultimo_aviso = 0
    vis = {"hora": -1}

    def toca_visita():
        t = time.localtime()
        return bool(CFG["couple_visita"]) and t.tm_min < 3 and t.tm_hour != vis["hora"]

    def esperar(seg):
        """Espera en trozos de 1 s y se interrumpe si llega la hora en punto."""
        fin = time.time() + seg
        while (time.time() < fin and not toca_visita()
               and not os.path.exists(os.path.join(AQUI, "cosechar_ya.flag"))
               and not os.path.exists(os.path.join(AQUI, "reiniciar_cuenta.flag"))):
            dormir(1)

    flag_ya = os.path.join(AQUI, "cosechar_ya.flag")
    flag_reinicio = os.path.join(AQUI, "reiniciar_cuenta.flag")

    def guardar_estado(sig):
        if not args.seco:
            pl = getattr(a, "plantado_en", {})
            with open(estado, "w", encoding="utf-8") as f:
                json.dump({"semilla": sig, "listo_en": listo_en, "indice": indice,
                           "plantado": {f"{k[0]},{k[1]}": v for k, v in pl.items()}}, f)

    flag_pausa = os.path.join(AQUI, "pausa.flag")

    def en_pausa():
        """Pausa pedida desde la interfaz (planto yo): no toca el juego ni corta nada; solo mira la pantalla para
        anotar que parcelas estaban vacias y ahora tienen planta (las que pusiste tu empiezan su propio reloj)."""
        if not os.path.exists(flag_pausa):
            return False
        log("PAUSA: no toco el juego mientras plantas tu (se reanuda al quitar la pausa en la interfaz)")
        while os.path.exists(flag_pausa) and not _STOP.is_set():
            if not args.seco:
                try:
                    a.mirar_pasivo()
                except Exception:
                    pass
            dormir(3)
        log("Pausa terminada: sigo")
        return True

    while True:
        desarmar()
        en_pausa()
        aj = ajustes.leer()
        if os.path.exists(flag_ya) and not getattr(a, "forzar_madura", False):
            a.forzar_madura = True
            listo_en = None
            log("Orden desde la interfaz: 'cortar ahora' (las plantas se tratan como maduras)")
        if os.path.exists(flag_reinicio):
            os.remove(flag_reinicio)
            a.forzar_madura = False                  # "reiniciar cuenta" manda sobre un "cortar ahora" anterior
            try:
                os.remove(flag_ya)
            except OSError:
                pass
            mins = aj["minutos"].get(a.semilla_actual, CFG["tiempos_min"].get(a.semilla_actual, 7))
            listo_en = time.time() + mins * 60
            a.plantado_en = {k: time.time() for k in a.todas_las_celdas()}
            guardar_estado(a.semilla_actual)
            log(f"Orden desde la interfaz: reinicio la cuenta de {a.semilla_actual}: {mins} min desde ahora "
                f"({time.strftime('%H:%M:%S', time.localtime(listo_en))})")
        a.reloj_cumplido = bool(listo_en) and time.time() >= listo_en
        if toca_visita():
            vis["hora"] = time.localtime().tm_hour
            esperar_turno()
            a.localizar()
            try:
                a.visita_couple()
            except Interferencia as e:
                a.recuperar(str(e))
                a.ir_a("secret")
            continue
        t_mira, vacias_vistas, hay_cuadro = 0, 0, False
        while (listo_en and time.time() < listo_en + ajustes.leer()["margen_seg"]
               and not toca_visita() and not os.path.exists(flag_ya)
               and not os.path.exists(flag_reinicio)):                    # aun no toca
            if os.path.exists(flag_pausa):
                en_pausa()
            dormir(1)
            if not args.seco and time.time() - t_mira >= 40:
                # mirada silenciosa (sin mouse): si hay parcelas vacias en dos miradas seguidas, no esperar al reloj
                t_mira = time.time()
                try:
                    est_w = a.mirar_pasivo()
                except Exception:
                    est_w = None
                if getattr(a, "hwnd", 0) and not user32.FindWindowW(None, "Audition"):
                    # el juego se cerro mientras esperaba: reingresar ya, no esperar a la hora del corte
                    log("El juego se cerro mientras esperaba: reingreso ahora")
                    hay_cuadro = True
                    break
                try:
                    if getattr(a, "hwnd", 0) and (a.hay_error_servidor() or a.buscar_boton_circulo()):
                        log("Cuadro azul del juego (error / desconexion) mientras espero: lo atiendo ahora")
                        hay_cuadro = True
                        break
                except Exception:
                    pass
                if est_w is None and getattr(a, "hwnd", 0) and CFG.get("volver_al_jardin_esperando", False):
                    # apagado por defecto: mientras espero no tomo el mouse; la pantalla se corrige a la hora del corte
                    try:
                        otra = a.detectar_pantalla()
                    except Exception:
                        otra = None
                    if otra in ("canales", "ciudad", "entrada", "couple"):
                        log(f"Estoy en la pantalla '{otra}', no en el jardin: voy al Secret Garden sin esperar")
                        hay_cuadro = True
                        break
                if est_w is not None and time.time() - getattr(a, "_t_agua", 0) > 600:
                    try:
                        sedientas = len(a.celdas_con_burbuja("agua")[0])
                        hambrientas = len(a.celdas_con_burbuja("abono")[0])
                    except Exception:
                        sedientas = hambrientas = 0
                    if sedientas >= 10 or hambrientas >= 5:
                        # plantas que piden agua (vuelven a pedirla mientras crecen) o abono (una vuelta interrumpida):
                        # se atienden una vez (cada 10 min como maximo)
                        a._t_agua = time.time()
                        log(f"Veo {sedientas} plantas pidiendo agua y {hambrientas} abono mientras espero: las atiendo")
                        break
                if est_w is not None and CFG.get("vigilar_vacias", False):    # apagado: la espera la manda el reloj
                    vacias_vistas =vacias_vistas + 1 if a.contar(est_w)["vacia"] >= 2 else 0
                    if vacias_vistas >= 2:
                        log(f"Veo {a.contar(est_w)['vacia']} parcelas vacias mientras espero: las atiendo sin esperar el reloj")
                        break
        if os.path.exists(flag_reinicio) or (os.path.exists(flag_ya) and not getattr(a, "forzar_madura", False)):
            continue                      # orden nueva sin tomar: volver arriba a atenderla
        a.reloj_cumplido = bool(listo_en) and time.time() >= listo_en
        if toca_visita():
            continue
        # esperar sin molestar: solo se mira la pantalla (sin mouse, sin foco, sin pitidos)
        est = None if (args.seco or hay_cuadro) else a.mirar_pasivo()
        if est is not None:
            c = a.contar(est)
            agua = a.celdas_con_burbuja("agua")[0]
            abono = a.celdas_con_burbuja("abono")[0]
            pendiente = bool(agua or abono) or c["vacia"] > 0 or c["marchita"] > 0
            if not pendiente and c["madura"] == 0 and not getattr(a, "forzar_madura", False):
                if time.time() - ultimo_aviso > 60:
                    log(f"Plantas creciendo ({c['joven']} jovenes, ya cuidadas): espero sin molestar")
                    ultimo_aviso = time.time()
                esperar(20)
                continue
            if not pendiente and c["joven"]:
                a._p_maduro = getattr(a, "_p_maduro", None) or time.time()
                if time.time() - a._p_maduro < CFG["espera_maduracion_seg"]:
                    esperar(5)
                    continue
        a._p_maduro = None
        siguiente = semilla_por_horario() if por_horario else patron[indice % len(patron)]
        try:
            hizo = rafaga(a, siguiente, listo_en)
        except Detenido as e:
            if emergencia():
                raise                              # F12: parada de emergencia de verdad
            # un fallo recuperable (p. ej. el selector de canal no respondio): no morir, esperar y reintentar
            log(f"Fallo recuperable: {e}. Espero 60 s y reintento")
            a.guardar_captura("fallo")
            sonido.pitar(500, 400)
            esperar(60)
            continue
        if hizo:
            n += 1
            indice += 1
            a.semilla_actual = siguiente
            t_semilla = aj["minutos"].get(siguiente, CFG["tiempos_min"][siguiente]) * 60 + CFG["margen_seg"]
            listo_en = getattr(a, "t_siembra", time.time()) + t_semilla
            plantado = getattr(a, "plantado_en", {})
            if plantado and siguiente in CFG["madurez_por_reloj"]:
                listo_en = min(plantado.values()) + t_semilla      # la parcela que madura primero
            if not args.seco:
                with open(estado, "w", encoding="utf-8") as f:
                    json.dump({"semilla": siguiente, "listo_en": listo_en, "indice": indice,
                               "plantado": {f"{k[0]},{k[1]}": v for k, v in plantado.items()}}, f)
            proxima = semilla_por_horario() if por_horario else patron[indice % len(patron)]
            log(f"Ciclo {n} listo ({siguiente}). Proxima cosecha a las "
                f"{time.strftime('%H:%M:%S', time.localtime(listo_en))}; despues sembrare {proxima}")
            if args.ciclos and n >= args.ciclos:
                return
        else:
            # una vuelta interrumpida pudo sembrar y guardar la hora sin avisar: recargarla del archivo para esperar
            # en silencio hasta esa hora, en vez de tomar el mouse a mirar el jardin cada 3 min
            try:
                with open(estado, encoding="utf-8") as f:
                    e2 = json.load(f)
                if e2.get("listo_en") and e2["listo_en"] > time.time() and e2.get("semilla") in CFG["tiempos_min"]:
                    listo_en = e2["listo_en"]
                    a.semilla_actual = e2["semilla"]
                    a.plantado_en = {tuple(int(x) for x in k.split(",")): v for k, v in e2.get("plantado", {}).items()}
                    log(f"Recargo la hora de siembra: cosecho a las {time.strftime('%H:%M:%S', time.localtime(listo_en))}")
                    continue
            except (OSError, ValueError):
                pass
            espera = aj["intervalo_seg"] if aj["revision_activa"] else max(aj["intervalo_seg"], 180)
            log(f"Nada que hacer ahora; vuelvo a mirar en {espera} s"
                + ("" if aj["revision_activa"] else " (revision activa apagada)"))
            esperar(espera)


def cuidar(args):
    """Riega lo que tenga globo de agua, abona las 20 y levanta los drops (sin sembrar ni cosechar)."""
    a = Audition(seco=args.seco)
    esperar_turno(minimo=2)
    a.localizar()
    ok, dif = a.en_secret_garden()
    if not ok:
        raise Detenido(f"No estoy en el Secret Garden (diferencia {dif:.1f})")
    celdas, mal = a.celdas_con_burbuja()
    log(f"Con globo de agua: {len(celdas)} alineadas, {len(mal)} desalineadas")
    if celdas:
        a.regar_por_burbujas()
    a.abonar_en(a.todas_las_celdas())
    listo_en = time.time() + CFG["tiempos_min"][args.semilla] * 60 + CFG["margen_seg"]
    with open(os.path.join(AQUI, "estado.json"), "w", encoding="utf-8") as f:
        json.dump({"semilla": args.semilla, "listo_en": listo_en}, f)
    log(f"Cuidado listo. Proxima cosecha a las {time.strftime('%H:%M:%S', time.localtime(listo_en))}")
    a.recoger_drops()


def abonar(args):
    a = Audition(seco=args.seco)
    esperar_turno(minimo=2)
    a.localizar()
    ok, dif = a.en_secret_garden()
    if not ok:
        raise Detenido(f"No estoy en el Secret Garden (diferencia {dif:.1f})")
    a.abonar_en(a.todas_las_celdas())
    log("Abono listo")


def una_parcela(args):
    a = Audition(seco=args.seco)
    esperar_turno(minimo=2)
    a.localizar()
    ok, dif = a.en_secret_garden()
    log(f"Secret Garden: {ok} (diferencia {dif:.1f})")
    if not ok:
        raise Detenido("No estoy en el Secret Garden")
    a.elegir_semilla(args.semilla)
    a.sobre_parcelas_ya_elegido(solo_una=True)
    dormir(2)
    ruta = os.path.join(AQUI, "una_parcela_resultado.png")
    a.captura((0, 0, 1024, 768)).save(ruta)
    log(f"Captura guardada en {ruta}")


def capturar_ref(args):
    """Guarda la zona de pantalla actual como referencia del reingreso (login, items_nuevos, aviso_circulo)."""
    a = Audition()
    for n in range(5, 0, -1):
        log(f"Guardo la referencia '{args.nombre}' en {n} s (deja visible esa pantalla del juego)")
        time.sleep(1)
    h = user32.FindWindowW(None, "Audition")
    if not h:
        raise Detenido("No encuentro la ventana de Audition")
    p = wintypes.POINT(0, 0)
    user32.ClientToScreen(h, ctypes.byref(p))
    a.hwnd, a.ox, a.oy = h, p.x, p.y
    archivo, caja = Audition.REF_REINGRESO[args.nombre]
    os.makedirs(os.path.join(AQUI, "referencias"), exist_ok=True)
    a.captura(caja).save(os.path.join(AQUI, "referencias", archivo))
    log(f"Referencia '{args.nombre}' guardada ({archivo})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["ciclo", "una-parcela", "cuidar", "abonar", "capturar-ref"])
    ap.add_argument("--nombre", choices=["login", "items_nuevos", "aviso_circulo", "mercado"], default="login")
    ap.add_argument("--semilla", choices=["romero", "menta_verde", "alternar", "horario"], default="romero")
    ap.add_argument("--seco", action="store_true", help="mueve el mouse pero no hace clic")
    ap.add_argument("--ciclos", type=int, default=0, help="0 = infinito")
    ap.add_argument("--seguir", action="store_true", help="tras 'cuidar', continuar con el ciclo automatico")
    args = ap.parse_args()
    if args.modo != "capturar-ref":
        asegurar_admin()
    hwnd_consola = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd_consola:
        user32.ShowWindow(hwnd_consola, 6)   # minimizar: que no tape el juego
    try:
        {"ciclo": ciclo, "una-parcela": una_parcela, "cuidar": cuidar, "abonar": abonar,
         "capturar-ref": capturar_ref}[args.modo](args)
        if args.modo == "cuidar" and args.seguir:
            ciclo(args)
    except Detenido as e:
        log(f"DETENIDO: {e}")
        for _ in range(3):
            sonido.pitar(400, 300)
        try:
            input("Enter para cerrar...")
        except (EOFError, OSError):
            pass
