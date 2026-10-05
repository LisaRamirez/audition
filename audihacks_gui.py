"""AudiHacks - interfaz. Elige la planta, Iniciar/Detener y mira el estado en vivo.

Se abre como administrador (Audition lo exige) y lanza audihacks.py como proceso hijo.
Emergencia: F12 (o el boton Detener).
"""
import ctypes
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk

AQUI = os.path.dirname(os.path.abspath(__file__))
user32 = ctypes.windll.user32


def asegurar_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    exe = sys.executable
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, AQUI, 1)
    sys.exit(0)


NOMBRES = {"Por horario: dia Menta Verde / noche Romero": "horario", "Alternar: 3 Romero + 1 Menta Verde": "alternar", "Romero (7 min)": "romero", "Menta Verde (23 min)": "menta_verde"}
LOG = os.path.join(AQUI, "audihacks.log")
ESTADO = os.path.join(AQUI, "estado.json")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AudiHacks - Secret Garden")
        self.geometry("620x440")
        self.minsize(520, 380)
        self.proc = None

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Planta:").pack(side="left")
        self.sel = ttk.Combobox(top, values=list(NOMBRES), state="readonly", width=22)
        self.sel.current(0)
        self.sel.pack(side="left", padx=8)
        self.btn_ini = ttk.Button(top, text="Iniciar", command=self.iniciar)
        self.btn_ini.pack(side="left", padx=4)
        self.btn_det = ttk.Button(top, text="Detener", command=self.detener, state="disabled")
        self.btn_det.pack(side="left", padx=4)

        self.estado = tk.StringVar(value="Detenido")
        self.proxima = tk.StringVar(value="")
        info = ttk.Frame(self, padding=(10, 0))
        info.pack(fill="x")
        ttk.Label(info, textvariable=self.estado, font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(info, textvariable=self.proxima).pack(anchor="w")
        ttk.Label(info, foreground="#666",
                  text="F12 detiene al instante. Durante una rafaga no muevas el mouse ni escribas.").pack(anchor="w", pady=(2, 6))

        marco = ttk.Frame(self, padding=(10, 0, 10, 10))
        marco.pack(fill="both", expand=True)
        self.txt = tk.Text(marco, height=10, state="disabled", wrap="none", font=("Consolas", 9),
                           background="#111", foreground="#ddd")
        sc = ttk.Scrollbar(marco, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sc.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sc.pack(side="right", fill="y")

        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.after(500, self.refrescar)

    # --- control ---
    def otros_procesos(self):
        cmd = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'audihacks\\.py' } "
               "| ForEach-Object { $_.ProcessId }")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                           creationflags=0x08000000)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]

    def iniciar(self):
        if self.proc and self.proc.poll() is None:
            return
        for pid in self.otros_procesos():           # evitar dos programas a la vez
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=0x08000000)
        semilla = NOMBRES[self.sel.get()]
        self.proc = subprocess.Popen(
            [sys.executable.replace("pythonw.exe", "python.exe"), "audihacks.py", "ciclo", "--semilla", semilla],
            cwd=AQUI, creationflags=0x08000000, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sel.configure(state="disabled")
        self.btn_ini.configure(state="disabled")
        self.btn_det.configure(state="normal")

    def detener(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        user32.mouse_event(0x0004, 0, 0, 0, 0)       # por si quedo el boton del mouse pulsado
        self.fin_ejecucion()

    def fin_ejecucion(self):
        self.sel.configure(state="readonly")
        self.btn_ini.configure(state="normal")
        self.btn_det.configure(state="disabled")

    def cerrar(self):
        self.detener()
        self.destroy()

    # --- estado en vivo ---
    def refrescar(self):
        activo = self.proc is not None and self.proc.poll() is None
        if self.proc is not None and not activo:
            self.fin_ejecucion()
            self.proc = None
        try:
            with open(LOG, encoding="utf-8", errors="replace") as f:
                lineas = f.read().splitlines()[-60:]
            ultima = next((l for l in reversed(lineas) if "Empiezo en" not in l and "Confirmar" not in l), "")
        except OSError:
            lineas, ultima = [], ""
        self.estado.set(("En marcha" if activo else "Detenido") + (f"  -  {ultima[9:]}" if activo and ultima else ""))
        try:
            with open(ESTADO, encoding="utf-8") as f:
                e = json.load(f)
            falta = e.get("listo_en", 0) - time.time()
            self.proxima.set(
                f"Planta actual: {e.get('semilla', '?')}   |   Proxima cosecha: "
                + (time.strftime("%H:%M:%S", time.localtime(e["listo_en"])) +
                   (f"  (en {int(falta//60)}:{int(falta%60):02d})" if falta > 0 else "  (ya toca)")
                   if e.get("listo_en") else "al detectar plantas maduras"))
        except (OSError, ValueError):
            self.proxima.set("")
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "\n".join(lineas))
        self.txt.see("end")
        self.txt.configure(state="disabled")
        self.after(1000, self.refrescar)


if __name__ == "__main__":
    asegurar_admin()
    App().mainloop()
