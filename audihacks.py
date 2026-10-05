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
import sys
import threading
import time
from ctypes import wintypes

from PIL import Image, ImageChops, ImageStat

AQUI = os.path.dirname(os.path.abspath(__file__))
user32 = ctypes.windll.user32
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


class Interferencia(Exception):
    """El usuario movio el mouse o hizo clic mientras el programa trabajaba."""


_ESPERADO = None      # (x, y) de pantalla donde dejamos el cursor; None = no vigilar
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
    if abs(cur.x - _ESPERADO[0]) > tol or abs(cur.y - _ESPERADO[1]) > tol:
        raise Interferencia("el mouse se movio")
    if not _PULSANDO and (user32.GetAsyncKeyState(0x01) & 0x8000):
        raise Interferencia("clic del usuario")


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
    """Pitidos fuertes para llamar la atencion del usuario."""
    for _ in range(veces):
        ctypes.windll.kernel32.Beep(1000, 250)
        ctypes.windll.kernel32.Beep(600, 250)


def log(txt):
    linea = time.strftime("%H:%M:%S ") + txt
    print(linea, flush=True)
    with open(os.path.join(AQUI, "audihacks.log"), "a", encoding="utf-8") as f:
        f.write(linea + "\n")


class Audition:
    def __init__(self, seco=False):
        self.seco = seco
        self.hwnd = 0
        self.ox = self.oy = 0

    # --- ventana ---
    def localizar(self):
        self.hwnd = user32.FindWindowW(None, "Audition")
        if not self.hwnd:
            raise Detenido("No encuentro la ventana de Audition")
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
            raise Detenido("No pude traer Audition al frente")
        p = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(p))
        self.ox, self.oy = p.x, p.y

    def captura(self, caja):
        from PIL import ImageGrab
        x0, y0, x1, y1 = caja
        return ImageGrab.grab(bbox=(self.ox + x0, self.oy + y0, self.ox + x1, self.oy + y1),
                              all_screens=True).convert("RGB")

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
        for nombre, caja in self.PANTALLAS.items():
            ref = Image.open(os.path.join(AQUI, "referencias", f"pantalla_{nombre}.png")).convert("RGB")
            dif = sum(ImageStat.Stat(ImageChops.difference(ref, self.captura(caja))).mean) / 3
            if dif < mejor_dif:
                mejor, mejor_dif = nombre, dif
        return mejor if mejor_dif < CFG["umbral_pantalla"] else None

    def esperar_pantalla(self, distinta_de, max_seg=45):
        fin = time.time() + max_seg
        while time.time() < fin:
            dormir(1.0)
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
                p = self.detectar_pantalla()
                if p == "secret":
                    return True
                if p is None:
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

    # --- mouse ---
    def mover(self, cx, cy, rapido=False):
        cx += random.randint(-3, 3)
        cy += random.randint(-3, 3)
        cur = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cur))
        tx, ty = self.ox + cx, self.oy + cy
        dist = max(abs(tx - cur.x), abs(ty - cur.y))
        pasos = max(4, min(25, dist // 18))
        desarmar()                                   # mientras nos movemos nosotros, no vigilar
        for i in range(1, pasos + 1):
            revisar()
            user32.SetCursorPos(cur.x + (tx - cur.x) * i // pasos, cur.y + (ty - cur.y) * i // pasos)
            time.sleep(0.010)
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
        ref = Image.open(os.path.join(AQUI, "referencias", "dialogo_adquirir.png")).convert("RGB")
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
        return [(f, c) for f in range(CFG["parcelas"]["filas"])
                for c in range(CFG["parcelas"]["columnas"])]

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
        """Corta SOLO las plantitas que quedaron fuera de la cuadrícula (las buenas no se tocan)."""
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
        for ronda in range(1, 4):
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
            log(f"AVISO: quedan {len(celdas)} globos de agua tras 3 rondas")
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
        estrella siguen tiñendo el jardin y las plantas vacias parecen marchitas)."""
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

    def sacos_presentes(self):
        img = self.captura((0, 0, 1024, 768))
        return [(f, c) for f, c in self.todas_las_celdas() if self.hay_saco(img, f, c)]

    def esperar_dialogo(self, max_seg=1.0):
        fin = time.time() + max_seg
        while time.time() < fin:
            if self.hay_dialogo():
                return True
            dormir(0.08)
        return False

    def confirmar_dialogo_rapido(self):
        """Enter confirma el cuadro sin mover el mouse; si no se cierra, se pulsa el boton."""
        user32.keybd_event(0x0D, 0, 0, 0)
        user32.keybd_event(0x0D, 0, 2, 0)
        dormir(0.35)
        if self.hay_dialogo():
            self.cerrar_dialogo()

    def recoger_drops(self):
        """Levanta los drops hasta que NO quede ningun saco a la vista. El saco desaparece cuando se
        levanta todo lo de esa parcela, asi que se comprueba mirando y se repite solo donde quede.
        (El juego admite ~40-50 items en el suelo; si se acumulan, no deja cosechar.)"""
        self.cerrar_dialogo()
        self.soltar_herramienta()
        total = 0
        objetivo = self.todas_las_celdas()
        restantes = []
        for pasada in range(1, 4):
            for f, c in objetivo:
                x, y = self.punto_saco(f, c)
                sin = 0
                for _ in range(CFG["max_drops_por_parcela"]):
                    self.vigilar_sin_dialogo()
                    self.mover(x, y, rapido=True)
                    self._pulsar(rapido=True)
                    if self.esperar_dialogo(0.9):
                        total += 1
                        sin = 0
                        self.confirmar_dialogo_rapido()
                    else:
                        sin += 1
                        if sin >= CFG["drops_vacios_para_parar"]:
                            break
            self.mover(*CFG["terreno_libre"])
            dormir(0.8)
            restantes = self.sacos_presentes()
            if not restantes:
                break
            log(f"Pasada {pasada}: aun se ven sacos en {len(restantes)} parcelas {restantes}")
            objetivo = restantes
        self._items_suelo = len(restantes)
        if restantes:
            log(f"AVISO: quedan sacos en {len(restantes)} parcelas tras 3 pasadas")
        log(f"Drops recogidos: {total}; sacos que quedan a la vista: {len(restantes)}")
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
            if CFG["auto_resucitar"] and oscuro > CFG["marchita_umbral"] and hoja < CFG["hoja_umbral"]:
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
        if getattr(self, "semilla_actual", "") in CFG["madurez_por_reloj"]:
            # esta planta no se distingue bien por color: madura SOLO cuando se cumple su reloj
            cumplido = getattr(self, "reloj_cumplido", False)     # respaldo si no se la hora de siembra
            t_plan = CFG["tiempos_min"][self.semilla_actual] * 60
            plantado = getattr(self, "plantado_en", {})
            ahora = time.time()
            for k, v in res.items():
                if v in ("joven", "madura"):
                    inicio = plantado.get(k)
                    lista = (ahora >= inicio + t_plan) if inicio is not None else cumplido
                    res[k] = "madura" if lista else "joven"
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
            log(f"Cosecha ronda {ronda}: {len(celdas) - len(pendientes)}/{len(celdas)} cortadas")
            if not pendientes:
                return True
        log(f"AVISO: {len(pendientes)} parcelas sin cortar tras 4 rondas: {pendientes}")
        ctypes.windll.kernel32.Beep(500, 400)
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
            for f in range(CFG["parcelas"]["filas"]):
                for c in range(CFG["parcelas"]["columnas"]):
                    self.clic(*self.parcela(f, c), rapido=True)
                    if solo_una:
                        return

    def celdas_marchitas(self):
        """Plantas marchitas = casi negras (65-70% de pixeles oscuros; sanas <12%, vacias ~0%)."""
        import numpy as np
        img = self.captura((0, 0, 1024, 768))
        marchitas = []
        for f in range(CFG["parcelas"]["filas"]):
            for c in range(CFG["parcelas"]["columnas"]):
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
        if n["joven"] and not n["madura"]:
            if self.cuidar_pendientes():
                self.t_siembra = time.time()      # el reloj corre desde el ultimo cuidado
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
                    ctypes.windll.kernel32.Beep(500, 400)
        elif n["joven"] and not n["vacia"]:
            log(f"{n['joven']} plantas jovenes aun creciendo: no cosecho")
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
        total = len(celdas) + previas
        n_par = len(self.todas_las_celdas())
        if total < n_par:
            log(f"AVISO: solo {total}/{n_par} parcelas con planta tras sembrar")
            ctypes.windll.kernel32.Beep(500, 400)
        self.regar_por_burbujas()
        dormir(1.0)
        abono, _ = self.celdas_con_burbuja("abono")
        self.abonar_en(abono if abono else celdas)   # sin globo visible: abona las recien sembradas
        self.t_siembra = time.time()          # la planta madura 7 min despues de terminar de cuidarla
        if not hasattr(self, "plantado_en"):
            self.plantado_en = {}
        for k in (celdas or vacias):
            self.plantado_en[k] = self.t_siembra
        self.recoger_drops()                  # mientras crecen, sin retrasar el reloj
        return True

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
    while segundos_sin_tocar() < minimo:
        revisar()
        dormir(0.5)
    for n in range(CFG["cuenta_regresiva"], 0, -1):
        revisar()
        ctypes.windll.kernel32.Beep(880, 120)
        log(f"Empiezo en {n}... (no muevas el mouse; F12 para cancelar)")
        dormir(1)


def rafaga(a, semilla, listo_en):
    """Una ráfaga. Los problemas recuperables (cuadros de Windows, pantalla desconocida, demasiadas
    interferencias) NO matan el programa: se avisa, se espera y se vuelve a intentar."""
    try:
        return _rafaga(a, semilla, listo_en)
    except PantallaDesconocida as e:
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
        try:
            if a.manejar_mensajes():
                primera = False                   # tras un cuadro, esperar turno otra vez abajo
            if primera:
                esperar_turno()
                primera = False
            a.localizar()
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
        while time.time() < fin and not toca_visita():
            dormir(1)

    while True:
        desarmar()
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
        while listo_en and time.time() < listo_en and not toca_visita():   # aun no toca
            dormir(1)
        if toca_visita():
            continue
        # esperar sin molestar: solo se mira la pantalla (sin mouse, sin foco, sin pitidos)
        est = None if args.seco else a.mirar_pasivo()
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
        hizo = rafaga(a, siguiente, listo_en)
        if hizo:
            n += 1
            indice += 1
            a.semilla_actual = siguiente
            t_semilla = CFG["tiempos_min"][siguiente] * 60 + CFG["margen_seg"]
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
            log("Nada que hacer ahora; vuelvo a mirar en 30 s")
            esperar(30)


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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["ciclo", "una-parcela", "cuidar", "abonar"])
    ap.add_argument("--semilla", choices=["romero", "menta_verde", "alternar", "horario"], default="romero")
    ap.add_argument("--seco", action="store_true", help="mueve el mouse pero no hace clic")
    ap.add_argument("--ciclos", type=int, default=0, help="0 = infinito")
    ap.add_argument("--seguir", action="store_true", help="tras 'cuidar', continuar con el ciclo automatico")
    args = ap.parse_args()
    asegurar_admin()
    hwnd_consola = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd_consola:
        user32.ShowWindow(hwnd_consola, 6)   # minimizar: que no tape el juego
    try:
        {"ciclo": ciclo, "una-parcela": una_parcela, "cuidar": cuidar, "abonar": abonar}[args.modo](args)
        if args.modo == "cuidar" and args.seguir:
            ciclo(args)
    except Detenido as e:
        log(f"DETENIDO: {e}")
        for _ in range(3):
            ctypes.windll.kernel32.Beep(400, 300)
        try:
            input("Enter para cerrar...")
        except (EOFError, OSError):
            pass
