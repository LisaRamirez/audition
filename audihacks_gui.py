"""AudiHacks - interfaz nueva (fondo negro, letras blancas).

Iniciar / Detener / cuenta / estado en vivo / plantas cortadas. Abrir con iniciar_interfaz.bat (administrador).
Sin administrador tambien abre: Iniciar y Detener usan las tareas elevadas AudiHacks_Romero y AudiHacks_MentaVerde.
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from tkinter import messagebox

import customtkinter as ctk

import ajustes
import cuenta
import sonido

AQUI = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(AQUI, "audihacks.log")
ESTADO = os.path.join(AQUI, "estado.json")
NOVENTANA = 0x08000000

NEGRO, TARJETA, BORDE = "#000000", "#0d0814", "#3b2160"
BLANCO, GRIS = "#ffffff", "#b7a6cf"
VERDE, ROJO, AMBAR = "#a855f7", "#ec4899", "#f9a8d4"
BOTON, BOTON_H = "#1e1230", "#3b2160"

OPCIONES = {
    "Por horario: día Menta Verde / noche Romero": "horario",
    "Alternar: 3 Romero + 1 Menta Verde": "alternar",
    "Romero (7 min)": "romero",
    "Menta Verde (23 min)": "menta_verde",
}
TAREAS = {"romero": "AudiHacks_Romero", "menta_verde": "AudiHacks_MentaVerde"}
REFERENCIAS = (("login", "Pantalla de login"), ("items_nuevos", "Cartel Items nuevos"),
               ("aviso_circulo", "Aviso botón circular"), ("mercado", "Panel de semillas"))
RUIDO = ("Empiezo en", "Confirmar", "abonar (", "  drop (", "sin cuadro en")


def es_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def asegurar_admin():
    if es_admin():
        return
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, AQUI, 1)
    sys.exit(0)


def ejecutar(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=NOVENTANA)


def tarea_corriendo(nombre):
    out = ejecutar(["schtasks", "/query", "/tn", nombre, "/fo", "csv", "/nh"]).stdout.lower()
    return "running" in out or "ejecuci" in out


def leer_cola(ruta, maximo=70000):
    try:
        with open(ruta, "rb") as f:
            f.seek(0, os.SEEK_END)
            tam = f.tell()
            f.seek(max(0, tam - maximo))
            return f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def contar_plantas():
    """Cuenta del registro (primera ronda de cada cosecha). Devuelve hoy/total por semilla."""
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lineas = f.read().splitlines()
    except OSError:
        return None
    dias, actual, ant = [], [], -1
    for l in lineas:
        m = re.match(r"(\d\d):(\d\d):(\d\d) ", l)
        if not m:
            continue
        t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        if t < ant - 600:                       # salto hacia atras = otro dia
            dias.append(actual)
            actual = []
        actual.append(l)
        ant = t
    dias.append(actual)

    def cuenta_de(ls):
        semilla, cort, cos = "?", {}, 0
        for l in ls:
            m = re.search(r"Sembrando (\w+) en", l) or re.search(r"Retomo \((\w+)\)", l)
            if m:
                semilla = m[1]
            m = re.search(r"Cosecha ronda 1: (\d+)/", l)
            if m:
                cort[semilla] = cort.get(semilla, 0) + int(m[1])
                cos += 1
        return cort, cos
    def horas_de(ls, hueco=1800):
        """Segundos trabajando: suma de los tramos entre lineas del registro separados por menos de 30 min
        (la espera de la Menta Verde llega a unos 23 min sin escribir; un hueco mayor es una parada)."""
        seg, ant = 0, None
        for l in ls:
            m = re.match(r"(\d\d):(\d\d):(\d\d) ", l)
            if not m:
                continue
            t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
            if ant is not None and 0 <= t - ant <= hueco:
                seg += t - ant
            ant = t
        return seg
    hoy = cuenta_de(dias[-1])
    total = cuenta_de([l for d in dias for l in d])
    return hoy, total, sum(horas_de(d) for d in dias), horas_de(dias[-1])


class App(ctk.CTk):
    def __init__(self, sin_admin=False):
        super().__init__(fg_color=NEGRO)
        ctk.set_appearance_mode("dark")
        self.title("AudiHacks")
        self.geometry("610x415")
        self._ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audihacks.ico")
        self.after(250, self._poner_icono)      # customtkinter pone su icono propio al abrir: se cambia despues
        self.minsize(590, 400)
        self.proc = None
        self.corriendo_cache, self.ultima_consulta = False, 0
        self.sin_admin = sin_admin
        F = lambda t=11, w="normal": ctk.CTkFont(family="Segoe UI", size=t, weight=w)
        estilo_entrada = dict(height=24, fg_color=NEGRO, border_color=BORDE, text_color=BLANCO)
        estilo_boton = dict(height=26, fg_color=BOTON, hover_color=BOTON_H, text_color=BLANCO, font=F(11))

        # --- cabecera ---
        cab = ctk.CTkFrame(self, fg_color=NEGRO)
        cab.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(cab, text="AudiHacks", font=F(18, "bold"), text_color=BLANCO).pack(side="left")
        self.luz = ctk.CTkLabel(cab, text="●  Detenido", font=F(12, "bold"), text_color=ROJO)
        self.luz.pack(side="right")

        # --- estado ---
        self.est_planta = ctk.StringVar(value="")
        self.est_cosecha = ctk.StringVar(value="")
        self.est_ultima = ctk.StringVar(value="")
        self.cont = ctk.StringVar(value="calculando…")
        est = ctk.CTkFrame(self, fg_color=TARJETA, border_width=1, border_color=BORDE, corner_radius=10)
        est.pack(fill="x", padx=12, pady=(4, 4))
        a = ctk.CTkFrame(est, fg_color=TARJETA)
        a.pack(fill="x", padx=10, pady=(6, 0))
        ctk.CTkLabel(a, textvariable=self.est_cosecha, font=F(15, "bold"), text_color=BLANCO, anchor="w").pack(side="left")
        ctk.CTkLabel(a, textvariable=self.est_planta, font=F(11), text_color=GRIS, anchor="e").pack(side="right")
        ctk.CTkLabel(est, textvariable=self.cont, font=F(11), text_color=BLANCO, anchor="w", justify="left").pack(
            fill="x", padx=10)
        ctk.CTkLabel(est, textvariable=self.est_ultima, font=F(10), text_color=GRIS, anchor="w",
                     wraplength=560, justify="left").pack(fill="x", padx=10, pady=(0, 5))

        # --- control ---
        fila = ctk.CTkFrame(self, fg_color=NEGRO)
        fila.pack(fill="x", padx=12, pady=(0, 4))
        self.sel = ctk.CTkOptionMenu(fila, values=list(OPCIONES), width=250, height=26, fg_color=BOTON,
                                     button_color=BOTON_H, button_hover_color=BORDE, text_color=BLANCO,
                                     dropdown_fg_color=BOTON, dropdown_text_color=BLANCO,
                                     dropdown_hover_color=BOTON_H, font=F(11))
        self.sel.set("Romero (7 min)")
        self.sel.pack(side="left")
        self.btn_ini = ctk.CTkButton(fila, text="Iniciar", width=100, height=26, fg_color=VERDE,
                                     hover_color="#9333ea", text_color=BLANCO, font=F(11, "bold"),
                                     command=self.iniciar)
        self.btn_ini.pack(side="left", padx=(8, 4))
        self.btn_det = ctk.CTkButton(fila, text="Detener", width=100, height=26, fg_color=ROJO,
                                     hover_color="#db2777", text_color=BLANCO, font=F(11, "bold"),
                                     command=self.detener)
        self.btn_det.pack(side="left")
        ctk.CTkLabel(fila, text="F12 = emergencia", font=F(10), text_color=GRIS).pack(side="right")

        # --- pestañas ---
        tabs = ctk.CTkTabview(self, fg_color=TARJETA, border_width=1, border_color=BORDE, corner_radius=10,
                              segmented_button_fg_color=BOTON, segmented_button_selected_color=VERDE,
                              segmented_button_selected_hover_color="#9333ea", segmented_button_unselected_color=BOTON,
                              segmented_button_unselected_hover_color=BOTON_H, text_color=BLANCO, height=150)
        tabs.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.tabs = tabs
        for n in ("Cuenta", "Espera", "Parcelas", "Sonido", "Referencias", "Registro"):
            tabs.add(n)
        tabs._segmented_button.configure(font=F(11))

        # Espera
        t = tabs.tab("Espera")
        aj = ajustes.leer()
        g = ctk.CTkFrame(t, fg_color=TARJETA)
        g.pack(fill="x")
        g.grid_columnconfigure((0, 3, 6), weight=1, uniform="a")
        self.aj_revision = ctk.BooleanVar(value=aj["revision_activa"])
        ctk.CTkSwitch(g, text="Revisar la pantalla mientras espera", variable=self.aj_revision, text_color=BLANCO,
                      progress_color=VERDE, button_color=BLANCO, button_hover_color=GRIS, fg_color=BOTON_H,
                      font=F(11), command=self.guardar_ajustes, switch_width=34, switch_height=16).grid(
            row=0, column=0, columnspan=9, sticky="w", pady=(0, 6))

        def campo(fila, col, texto, valor, unidad):
            ctk.CTkLabel(g, text=texto, font=F(11), text_color=BLANCO, anchor="w").grid(
                row=fila, column=col, sticky="w", pady=2)
            e = ctk.CTkEntry(g, width=46, **estilo_entrada)
            e.insert(0, str(valor))
            e.grid(row=fila, column=col + 1, sticky="w", padx=(4, 2), pady=2)
            ctk.CTkLabel(g, text=unidad, font=F(10), text_color=GRIS).grid(row=fila, column=col + 2, sticky="w", padx=(0, 10))
            return e
        self.e_intervalo = campo(1, 0, "Revisar cada", aj["intervalo_seg"], "s")
        self.e_margen = campo(1, 3, "Margen extra", aj["margen_seg"], "s")
        ctk.CTkLabel(g, text="Minutos hasta cosechar", font=F(10), text_color=GRIS, anchor="w").grid(
            row=2, column=0, columnspan=9, sticky="w", pady=(6, 0))
        self.e_min = {}
        self.e_min["romero"] = campo(3, 0, "Romero", aj["minutos"]["romero"], "min")
        self.e_min["menta_verde"] = campo(3, 3, "Menta Verde", aj["minutos"]["menta_verde"], "min")
        self.e_min["menta"] = campo(3, 6, "Menta", aj["minutos"]["menta"], "min")
        f3 = ctk.CTkFrame(t, fg_color=TARJETA)
        f3.pack(fill="x", pady=(6, 0))
        for texto, cmd in (("Aplicar", self.guardar_ajustes), ("Cortar ahora", self.cortar_ahora),
                           ("Reiniciar cuenta", self.reiniciar_cuenta)):
            ctk.CTkButton(f3, text=texto, width=110, command=cmd, **estilo_boton).pack(side="left", padx=(0, 6))
        self.msg_aj = ctk.StringVar(value="")
        ctk.CTkLabel(f3, textvariable=self.msg_aj, font=F(10), text_color=VERDE, anchor="w", wraplength=200,
                     justify="left").pack(side="left", padx=6)

        # Parcelas
        t = tabs.tab("Parcelas")
        ctk.CTkLabel(t, text="Marca las parcelas que plantaste tú: el programa no las toca "
                             "(no siembra, riega, abona ni corta ahí).", font=F(10), text_color=GRIS, anchor="w",
                     wraplength=540, justify="left").pack(fill="x")
        cuad = ctk.CTkFrame(t, fg_color=TARJETA)
        cuad.pack(pady=(6, 0))
        self.excluidas = set(ajustes.leer().get("excluir", []))
        self.btn_parcela = {}
        for f in range(4):
            for c in range(5):
                k = f"{f},{c}"
                b = ctk.CTkButton(cuad, text="", width=70, height=28, font=F(10), command=lambda k=k: self.alternar_parcela(k))
                b.grid(row=f, column=c, padx=3, pady=2)
                self.btn_parcela[k] = b
                self.pintar_parcela(k)

        # Cuenta
        t = tabs.tab("Cuenta")
        c = ctk.CTkFrame(t, fg_color=TARJETA)
        c.pack(fill="x")
        c.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(c, text="ID de usuario", font=F(10), text_color=GRIS).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(c, text="Contraseña", font=F(10), text_color=GRIS).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.usuario = ctk.CTkEntry(c, **estilo_entrada)
        self.usuario.grid(row=1, column=0, sticky="ew")
        self.clave = ctk.CTkEntry(c, show="•", **estilo_entrada)
        self.clave.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        self.auto = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(t, text="Reingresar solo si me saca del juego (lanzador, login y carteles)",
                        variable=self.auto, text_color=BLANCO, fg_color=VERDE, hover_color="#9333ea",
                        border_color=GRIS, checkmark_color=BLANCO, font=F(11), checkbox_width=16,
                        checkbox_height=16).pack(anchor="w", pady=(8, 4))
        fc = ctk.CTkFrame(t, fg_color=TARJETA)
        fc.pack(fill="x")
        ctk.CTkButton(fc, text="Guardar cuenta", width=120, command=self.guardar_cuenta, **estilo_boton).pack(side="left")
        self.msg_cuenta = ctk.StringVar(value="")
        ctk.CTkLabel(fc, textvariable=self.msg_cuenta, font=F(10), text_color=VERDE).pack(side="left", padx=8)
        fl = ctk.CTkFrame(t, fg_color=TARJETA)
        fl.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(fl, text="Lanzador (Patcher.exe)", font=F(10), text_color=GRIS).pack(side="left")
        self.e_lanz = ctk.CTkEntry(fl, **estilo_entrada)
        self.e_lanz.pack(side="left", fill="x", expand=True, padx=6)
        self.e_lanz.insert(0, ajustes.leer().get("lanzador", ""))
        ctk.CTkButton(fl, text="Detectar", width=70, command=self.detectar_lanzador, **estilo_boton).pack(side="left")
        ctk.CTkLabel(t, text="Contraseña cifrada con Windows. Vacía = conserva la guardada.", font=F(10),
                     text_color=GRIS, anchor="w").pack(fill="x", pady=(3, 0))

        # Sonido
        t = tabs.tab("Sonido")
        cfg = sonido.leer()
        self.snd_alertas = ctk.BooleanVar(value=cfg["alertas"])
        self.snd_cuenta = ctk.BooleanVar(value=cfg["cuenta_atras"])
        sw = dict(text_color=BLANCO, progress_color=VERDE, button_color=BLANCO, button_hover_color=GRIS,
                  fg_color=BOTON_H, font=F(11), command=self.guardar_sonido, switch_width=34, switch_height=16)
        fs = ctk.CTkFrame(t, fg_color=TARJETA)
        fs.pack(fill="x")
        ctk.CTkSwitch(fs, text="Avisar si algo falla", variable=self.snd_alertas, **sw).pack(side="left")
        ctk.CTkSwitch(fs, text="Pitidos de cuenta atrás", variable=self.snd_cuenta, **sw).pack(side="left", padx=(18, 0))
        fv = ctk.CTkFrame(t, fg_color=TARJETA)
        fv.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(fv, text="Volumen", font=F(10), text_color=GRIS).pack(side="left")
        self.vol = ctk.CTkSlider(fv, from_=0, to=100, number_of_steps=20, width=300, progress_color=VERDE,
                                 button_color=BLANCO, button_hover_color=GRIS, fg_color=BOTON_H,
                                 command=self.cambio_volumen)
        self.vol.set(cfg["volumen"])
        self.vol.pack(side="left", padx=8)
        self.lbl_vol = ctk.CTkLabel(fv, text=f"{cfg['volumen']} %", font=F(11), text_color=BLANCO)
        self.lbl_vol.pack(side="left")
        ctk.CTkButton(fv, text="Probar", width=70, command=self.probar_sonido, **estilo_boton).pack(side="right")

        # Referencias
        t = tabs.tab("Referencias")
        ctk.CTkLabel(t, text="Con esa pantalla visible en el juego, pulsa el botón (guarda la imagen en 5 s):",
                     font=F(10), text_color=GRIS, anchor="w").pack(fill="x")
        fr = ctk.CTkFrame(t, fg_color=TARJETA)
        fr.pack(fill="x", pady=(6, 0))
        fr.grid_columnconfigure((0, 1), weight=1)
        for i, (nombre, texto) in enumerate(REFERENCIAS):
            ctk.CTkButton(fr, text=texto, command=lambda n=nombre: self.capturar_ref(n), **estilo_boton).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=(0, 6), pady=3)

        # Registro
        self.txt = ctk.CTkTextbox(tabs.tab("Registro"), fg_color="#07040c", text_color=BLANCO, border_width=1,
                                  border_color=BORDE, font=ctk.CTkFont(family="Consolas", size=10), wrap="none",
                                  corner_radius=6)
        self.txt.pack(fill="both", expand=True)
        self.txt.configure(state="disabled")
        tabs.set("Cuenta")

        datos = cuenta.cargar()
        if datos:
            self.usuario.insert(0, datos.get("usuario", ""))
            self.auto.set(bool(datos.get("reingreso_auto")))
            if datos.get("password"):
                self.msg_cuenta.set("Contraseña guardada")
        try:
            with open(ESTADO, encoding="utf-8") as f:
                actual = json.load(f).get("semilla")
            for texto, clave in OPCIONES.items():
                if clave == actual:
                    self.sel.set(texto)
        except (OSError, ValueError):
            pass
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.after(300, self.refrescar)
        self.after(500, self.refrescar_conteo)

    # --- parcelas propias ---
    def pintar_parcela(self, k):
        f, c = (int(x) + 1 for x in k.split(","))
        if k in self.excluidas:
            self.btn_parcela[k].configure(text=f"F{f}·C{c}  TUYA", fg_color=ROJO, hover_color="#db2777", text_color=BLANCO)
        else:
            self.btn_parcela[k].configure(text=f"F{f}·C{c}", fg_color=BOTON, hover_color=BOTON_H, text_color=BLANCO)

    def alternar_parcela(self, k):
        if k in self.excluidas:
            self.excluidas.discard(k)
        else:
            self.excluidas.add(k)
        self.pintar_parcela(k)
        datos = dict(ajustes.leer())
        datos["excluir"] = sorted(self.excluidas)
        ajustes.guardar(datos)

    # --- espera ---
    def guardar_ajustes(self):
        def num(e, defecto, minimo=0):
            try:
                return max(minimo, int(float(e.get().strip().replace(",", "."))))
            except ValueError:
                return defecto
        base = ajustes.leer()
        datos = {"revision_activa": bool(self.aj_revision.get()),
                 "intervalo_seg": num(self.e_intervalo, base["intervalo_seg"], 5),
                 "margen_seg": num(self.e_margen, base["margen_seg"], 0),
                 "minutos": {k: num(e, base["minutos"][k], 1) for k, e in self.e_min.items()},
                 "excluir": sorted(getattr(self, "excluidas", base.get("excluir", [])))}
        ajustes.guardar(datos)
        self.msg_aj.set("Guardado. Vale desde la próxima vuelta del programa (sin reiniciar).")

    def cortar_ahora(self):
        if not self.corriendo():
            self.msg_aj.set("El programa está detenido: pulsa Iniciar primero (la orden no se guarda).")
            return
        open(os.path.join(AQUI, "cosechar_ya.flag"), "w").close()
        self.msg_aj.set("Orden enviada: esperando que el programa la tome…")

    def reiniciar_cuenta(self):
        if not self.corriendo():
            self.msg_aj.set("El programa está detenido: pulsa Iniciar primero (la orden no se guarda).")
            return
        self.guardar_ajustes()
        open(os.path.join(AQUI, "reiniciar_cuenta.flag"), "w").close()
        self.msg_aj.set("Orden enviada: esperando que el programa la tome…")

    # --- sonido ---
    def guardar_sonido(self):
        sonido.guardar(self.snd_alertas.get(), self.snd_cuenta.get(), self.vol.get())

    def cambio_volumen(self, valor):
        self.lbl_vol.configure(text=f"{int(valor)} %")
        self.guardar_sonido()

    def probar_sonido(self):
        self.guardar_sonido()
        sonido.pitar(1000, 220, forzar=True)
        sonido.pitar(600, 220, forzar=True)

    # --- cuenta ---
    def _poner_icono(self):
        try:
            self.iconbitmap(self._ico)
        except Exception:
            pass

    def detectar_lanzador(self):
        ruta = ajustes.detectar_lanzador()
        self.e_lanz.delete(0, "end")
        self.e_lanz.insert(0, ruta)
        self.msg_cuenta.set("Lanzador detectado" if ruta else "No lo encontré: escribe la ruta de Patcher.exe")

    def guardar_cuenta(self):
        datos_aj = dict(ajustes.leer())
        datos_aj["lanzador"] = self.e_lanz.get().strip()
        ajustes.guardar(datos_aj)
        try:
            cuenta.guardar(self.usuario.get().strip(), self.clave.get(), self.auto.get())
        except OSError as e:
            self.msg_cuenta.set(f"Error: {e}")
            return
        self.clave.delete(0, "end")
        datos = cuenta.cargar() or {}
        self.msg_cuenta.set("Guardado" + (" (contraseña cifrada)" if datos.get("password") else " (falta la contraseña)"))

    def capturar_ref(self, nombre):
        if not messagebox.askyesno("Guardar imagen de referencia",
                                   f"¿Está visible AHORA en el juego la pantalla «{nombre}»?\n\n"
                                   "Si no lo está, se guardaría una imagen equivocada y el programa "
                                   "se confundiría."):
            return
        py = sys.executable.replace("pythonw.exe", "python.exe")
        subprocess.Popen([py, "audihacks.py", "capturar-ref", "--nombre", nombre], cwd=AQUI,
                         creationflags=NOVENTANA, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        self.msg_cuenta.set(f"Guardando «{nombre}» en 5 s: deja esa pantalla visible en el juego")

    # --- control ---
    def corriendo(self):
        if self.proc and self.proc.poll() is None:
            return True
        if time.time() - self.ultima_consulta > 4:
            self.ultima_consulta = time.time()
            self.corriendo_cache = any(tarea_corriendo(n) for n in TAREAS.values())
        return self.corriendo_cache

    def apartar_estado_si_cambia(self, semilla):
        """Si el estado guardado es de otra semilla, se aparta para que el programa mire el jardin real."""
        try:
            with open(ESTADO, encoding="utf-8") as f:
                previo = json.load(f).get("semilla")
        except (OSError, ValueError):
            return
        if previo and semilla in TAREAS and previo != semilla:
            os.replace(ESTADO, os.path.join(AQUI, f"estado.{previo}.bak"))

    def iniciar(self):
        semilla = OPCIONES[self.sel.get()]
        self.apartar_estado_si_cambia(semilla)
        if es_admin():
            cmd = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'audihacks\\.py' } "
                   "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
            ejecutar(["powershell", "-NoProfile", "-Command", cmd])
            self.proc = subprocess.Popen(
                [sys.executable.replace("pythonw.exe", "python.exe"), "audihacks.py", "ciclo", "--semilla", semilla],
                cwd=AQUI, creationflags=NOVENTANA, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif semilla in TAREAS:
            for n in TAREAS.values():
                ejecutar(["schtasks", "/end", "/tn", n])
            time.sleep(1.5)
            ejecutar(["schtasks", "/run", "/tn", TAREAS[semilla]])
        else:
            messagebox.showinfo("AudiHacks", "Este modo necesita la interfaz como administrador.\n"
                                "Ábrela con iniciar_interfaz.bat, o elige Romero o Menta Verde.")
            return
        self.ultima_consulta = 0

    def detener(self):
        for n in TAREAS.values():
            ejecutar(["schtasks", "/end", "/tn", n])
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)   # por si quedo el boton del mouse pulsado
        self.ultima_consulta = 0

    def cerrar(self):
        self.destroy()       # el programa de cosecha sigue corriendo: cerrar la ventana no lo detiene

    # --- estado en vivo ---
    def refrescar(self):
        lineas = leer_cola(LOG)
        activo = self.corriendo()
        pendiente = [n for n in ("cosechar_ya.flag", "reiniciar_cuenta.flag") if os.path.exists(os.path.join(AQUI, n))]
        if pendiente:
            self.msg_aj.set("Orden pendiente: el programa la toma en unos segundos…")
        elif self.msg_aj.get().startswith(("Orden enviada", "Orden pendiente")):
            self.msg_aj.set("Orden recibida por el programa.")
        # botones: el que ya esta "hecho" se apaga (oscuro), el que se puede usar queda brillante
        if activo:
            self.btn_ini.configure(text="▶  En marcha", state="disabled", fg_color="#2a1747", text_color_disabled="#9d7fd1")
            self.btn_det.configure(text="Detener", state="normal", fg_color=ROJO, text_color=BLANCO)
        else:
            self.btn_ini.configure(text="Iniciar", state="normal", fg_color=VERDE, text_color=BLANCO)
            self.btn_det.configure(text="■  Detenido", state="disabled", fg_color="#3a1230", text_color_disabled="#d27aa8")
        visibles = [l for l in lineas if not any(r in l for r in RUIDO)]
        ultima = visibles[-1] if visibles else ""
        espera = "Pantalla desconocida" in ultima or "DETENIDO" in ultima
        if not activo:
            self.luz.configure(text="●  Detenido", text_color=ROJO)
        elif espera:
            self.luz.configure(text="●  Esperando pantalla del juego", text_color=AMBAR)
        else:
            self.luz.configure(text="●  En marcha", text_color="#d946ef")
        self.est_ultima.set(ultima[9:] if len(ultima) > 9 else "")
        try:
            with open(ESTADO, encoding="utf-8") as f:
                e = json.load(f)
            falta = e.get("listo_en", 0) - time.time()
            self.est_planta.set("Planta actual: " + {"romero": "Romero", "menta_verde": "Menta Verde",
                                                    "menta": "Menta"}.get(e.get("semilla"), str(e.get("semilla"))))
            if e.get("listo_en"):
                hora = time.strftime("%H:%M:%S", time.localtime(e["listo_en"]))
                margen = ajustes.leer()["margen_seg"]
                resto = falta + margen                       # lo que falta contando el margen extra
                if falta > 0:
                    self.est_cosecha.set(f"Próxima cosecha {hora}  ·  en {int(falta // 60)}:{int(falta % 60):02d}")
                elif resto > 0:
                    self.est_cosecha.set(f"Esperando que maduren  ·  cuenta regresiva {int(resto // 60)}:{int(resto % 60):02d}")
                else:
                    pasado = -resto
                    self.est_cosecha.set(f"Esperando que maduren  ·  +{int(pasado // 60)}:{int(pasado % 60):02d} desde la hora")
            else:
                self.est_cosecha.set("Próxima cosecha: al detectar plantas maduras")
        except (OSError, ValueError):
            self.est_planta.set("")
            self.est_cosecha.set("—")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "\n".join(visibles[-70:]))
        self.txt.see("end")
        self.txt.configure(state="disabled")
        self.after(1000, self.refrescar)

    def refrescar_conteo(self):
        r = contar_plantas()
        if r:
            (hoy, hoy_c), (tot, tot_c), seg_total, seg_hoy = r

            def n(v):
                return f"{v:,}".replace(",", ".")

            def horas(seg):
                return f"{int(seg // 3600)} h {int(seg % 3600 // 60):02d} min"
            romero = tot.get("romero", 0)
            menta = tot.get("menta_verde", 0)
            sin_asignar = tot.get("?", 0)
            self.cont.set(f"Romero {n(romero)}  ·  Menta Verde {n(menta)}  ·  Total ambos {n(romero + menta + sin_asignar)} plantas\n"
                          f"Trabajando: {horas(seg_total)} en total  ·  hoy {horas(seg_hoy)}  ·  {tot_c} cosechas")
        self.after(15000, self.refrescar_conteo)


if __name__ == "__main__":
    sin = "--sin-admin" in sys.argv
    if not sin:
        asegurar_admin()
    App(sin_admin=sin).mainloop()

