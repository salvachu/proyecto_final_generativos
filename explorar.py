"""Explorador de mazmorras generadas con memoria de las salas visitadas."""

import os
import secrets
import sqlite3
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from niveles import MOTOR, RECURSO, Game, MotorTemporal
from palacio import nuevo_palacio, posiciones
from partidas import Biblioteca, Partida
from salas import GeneradorNeuronal

FONDO, PANEL, TEXTO, ORO, GRIS = "#111b24", "#1c2934", "#f5eddd", "#efbb73", "#a9bac5"
TECLAS = {
    "a": 1,
    "left": 1,
    "d": 2,
    "right": 2,
    "w": 4,
    "up": 4,
    "s": 8,
    "down": 8,
    "shift_l": 16,
    "shift_r": 16,
    "space": 0,
}
FIN = {
    "level_complete": "¡Has salido de la mazmorra!",
    "death": "El príncipe ha caído.",
    "victory": "¡Victoria!",
    "time_expired": "Se ha agotado el tiempo.",
}


def directorio_usuario():
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PrinceOfPersiaMundos"
        )
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "prince-of-persia-mundos"
    )


class Explorador:
    def __init__(self, root, carpeta=None):
        self.root = root
        self.bib = Biblioteca((carpeta or directorio_usuario()) / "mundos.sqlite3")
        self.modelo = GeneradorNeuronal()
        self.motor = MotorTemporal()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.creacion = None
        self.partida = self.timer = self.mapa_dibujado = None
        self.teclas = set()
        self.jugando = False
        root.title("Prince of Persia · Nivel original y mazmorras generadas")
        root.configure(bg=FONDO)
        main = tk.Frame(root, bg=FONDO, padx=18, pady=14)
        main.pack()
        self.texto(main, "Mazmorras de Persia", 23, TEXTO, True).grid(
            row=0, column=0, sticky="w"
        )
        barra = tk.Frame(main, bg=FONDO)
        barra.grid(row=0, column=1, sticky="e")
        self.lista = ttk.Combobox(barra, width=21, state="readonly", takefocus=False)
        self.lista.pack(side="left", padx=(0, 6))
        self.lista.bind("<<ComboboxSelected>>", self.elegir)
        ttk.Button(
            barra, text="Nivel 1 original", command=self.original, takefocus=False
        ).pack(side="left", padx=(0, 4))
        self.generar = ttk.Button(
            barra, text="Generar nivel", command=self.nuevo, takefocus=False
        )
        self.generar.pack(side="left")
        cuerpo = tk.Frame(main, bg=FONDO)
        cuerpo.grid(row=1, column=0, columnspan=2, pady=(12, 8))
        self.vista = tk.Label(cuerpo, bg="black", borderwidth=0)
        self.vista.grid(row=0, column=0, sticky="nw")
        lateral = tk.Frame(cuerpo, bg=PANEL, padx=12, pady=9)
        lateral.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.texto(lateral, "Mapa explorado", 15, TEXTO, True).pack(anchor="w")
        self.ubicacion = self.texto(lateral, "", 12, ORO, True)
        self.ubicacion.pack(anchor="w", pady=(8, 0))
        self.contador = self.texto(lateral, "", 10, GRIS)
        self.contador.pack(anchor="w")
        self.mapa = tk.Canvas(
            lateral, width=254, height=158, bg=PANEL, highlightthickness=0
        )
        self.mapa.pack(anchor="w", pady=(6, 1))
        self.mapa.bind(
            "<Motion>", lambda e: self.ayuda_mapa(self.destino_bajo_cursor())
        )
        self.mapa.bind("<Leave>", lambda e: self.ayuda_mapa())
        self.mapa.bind("<Button-1>", self.clic_mapa)
        self.desplazar = ttk.Scrollbar(
            lateral, orient="horizontal", command=self.mapa.xview
        )
        self.mapa.configure(xscrollcommand=self.desplazar.set)
        self.accion_mapa = self.texto(lateral, "", 10, TEXTO)
        self.accion_mapa.pack(anchor="w", pady=(8, 0))
        self.estado = self.texto(main, "", 12, ORO, True)
        self.estado.grid(row=2, column=0, columnspan=2, sticky="w")
        self.pista = self.texto(main, "", 11, TEXTO)
        self.pista.grid(row=3, column=0, columnspan=2, sticky="w")
        self.texto(
            main,
            "A / D   mover     W   saltar o bloquear     S   bajar     Shift   agarrar, recoger o atacar     P   pausa",
            10,
            GRIS,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 7))
        controles = tk.Frame(main, bg=FONDO)
        controles.grid(row=5, column=0, columnspan=2, sticky="w")
        self.play = ttk.Button(
            controles, text="Jugar", command=self.alternar, takefocus=False
        )
        self.play.pack(side="left", padx=(0, 5))
        ttk.Button(
            controles,
            text="Reintentar desde la entrada",
            command=self.reintentar,
            takefocus=False,
        ).pack(side="left")
        root.bind("<KeyPress>", self.pulsar)
        root.bind("<KeyRelease>", lambda e: self.teclas.discard(e.keysym.lower()))
        root.bind("<FocusOut>", self.perder_foco)
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        if self.bib.activo() is None:
            mundos = self.bib.listar()
            if mundos:
                self.abrir(mundos[0][0])
            else:
                self.original()
        else:
            self.abrir(self.bib.activo())

    @staticmethod
    def texto(padre, s, size, color, bold=False):
        return tk.Label(
            padre,
            text=s,
            bg=padre["bg"],
            fg=color,
            anchor="w",
            font=("Segoe UI", size, "bold" if bold else "normal"),
        )

    def original(self):
        self.pausar()
        mundo = self.bib.original()
        if mundo is None:
            mapa = (MOTOR / RECURSO).read_bytes()
            self.motor.cargar(mapa)
            with Game(self.motor.ruta, 1, 1) as g:
                mundo = self.bib.crear(1, mapa, b"", g.frame, tipo="original")
        self.abrir(mundo)

    def construir(self, seed):
        # El motor y SQLite de la partida activa pertenecen al hilo de la interfaz.
        motor = MotorTemporal()
        try:
            return nuevo_palacio(motor, self.modelo, seed)
        finally:
            motor.cerrar()

    def nuevo(self):
        if self.creacion:
            return
        self.pausar()
        self.generar.configure(state="disabled", text="Generando…")
        seed = secrets.randbelow(2**31)
        self.creacion = self.executor.submit(self.construir, seed)
        self.recibir_nivel(seed)

    def recibir_nivel(self, seed):
        if not self.creacion.done():
            self.root.after(100, self.recibir_nivel, seed)
            return
        try:
            mapa, ruta = self.creacion.result()
            self.motor.cargar(mapa)
            with Game(self.motor.ruta, 1, seed) as g:
                mundo = self.bib.crear(seed, mapa, ruta, g.frame, tipo="palacio")
            self.abrir(mundo)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as e:
            messagebox.showerror("Creación del nivel", str(e), parent=self.root)
        finally:
            self.creacion = None
            self.generar.configure(state="normal", text="Generar nivel")

    def elegir(self, _evento):
        self.abrir(self.mundos[self.lista.current()][0])

    def abrir(self, mundo, reiniciar=False):
        self.pausar()
        # La partida anterior sigue disponible si la nueva no se puede restaurar.
        nueva = Partida(self.bib, self.motor, mundo, reiniciar, self.modelo)
        if self.partida:
            self.partida.game.close()
        self.partida = nueva
        self.mundos = self.bib.listar()
        original = self.bib.original()
        edicion = self.bib.db.execute(
            "SELECT tipo FROM edicion WHERE mundo=?", (mundo,)
        ).fetchone()
        self.pista.configure(
            text=(
                "Busca la espada, explora las galerías y pulsa W ante la salida abierta."
                if edicion
                else "Explora hacia la derecha, pisa la placa y pulsa W ante la salida abierta."
            )
        )
        self.lista.configure(
            values=[
                "Nivel 1 original" if i == original else f"Mundo {i}  ·  {s}"
                for i, s in self.mundos
            ]
        )
        self.lista.current(
            next(j for j, (i, _) in enumerate(self.mundos) if i == mundo)
        )
        self.mapa_dibujado = None
        self.mostrar()
        self.root.focus_set()

    def reintentar(self):
        if self.partida:
            self.pausar()
            if self.partida.game.frame.index and not messagebox.askyesno(
                "Volver a la entrada",
                "¿Reiniciar este intento? El mapa explorado seguirá guardado.",
                parent=self.root,
            ):
                return
            self.abrir(self.partida.id, True)

    def perder_foco(self, e):
        if e.widget == self.root:
            self.pausar()

    def pausar(self):
        self.jugando = False
        self.teclas.clear()
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.partida:
            self.play.configure(text="Jugar")
            self.rotulo()

    def alternar(self):
        if self.jugando:
            self.pausar()
        else:
            self.iniciar()

    def iniciar(self):
        if (
            self.partida
            and self.partida.game.process
            and self.partida.game.frame.end == "playing"
            and not self.jugando
        ):
            self.jugando = True
            self.play.configure(text="Pausar")
            self.root.focus_set()
            self.tick()

    def pulsar(self, e):
        k = e.keysym.lower()
        if k == "p":
            self.alternar()
            return "break"
        if k in TECLAS:
            self.teclas.add(k)
            self.iniciar()
            return "break"

    def tick(self):
        self.timer = None
        if not self.jugando:
            return
        mask = 0
        for k in self.teclas:
            mask |= TECLAS[k]
        if mask & 1:
            mask &= ~2
        if mask & 4:
            mask &= ~8
        try:
            frame = self.partida.paso(mask)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as e:
            self.pausar()
            messagebox.showerror("Partida detenida", str(e), parent=self.root)
            return
        if frame.end != "playing":
            self.pausar()
        self.mostrar()
        if self.jugando:
            self.timer = self.root.after(round(1000 * frame.next_ticks / 60), self.tick)

    def rotulo(self):
        f = self.partida.game.frame
        estado = FIN.get(f.end) or ("Jugando" if self.jugando else "En pausa")
        self.estado.configure(
            text=f"{estado}    ·    Sala {f.state[1]}    ·    Paso {f.index} guardado"
        )

    def mostrar(self):
        p = self.partida
        frame = p.game.frame
        foto = Image.fromarray(frame.rgb).resize((512, 320), Image.Resampling.NEAREST)
        self.vista.image = ImageTk.PhotoImage(foto)
        self.vista.configure(image=self.vista.image)
        self.dibujar_mapa()
        self.rotulo()

    def dibujar_mapa(self):
        p = self.partida
        actual = p.game.frame.state[1]
        jugable = p.game.frame.end == "playing"
        clave = (p.id, actual, frozenset(p.vistas), jugable)
        if self.mapa_dibujado == clave:
            return
        self.mapa_dibujado = clave
        plano = posiciones(p.mapa)
        self.ubicacion.config(text=f"Estás en la sala {actual}")
        self.contador.config(text=f"{len(p.vistas)} de {len(plano)} salas descubiertas")
        self.mapa.delete("all")
        self.ayuda_mapa()
        visibles = {s: plano[s] for s in p.vistas if s in plano}
        xs, ys = zip(*visibles.values())
        dx, dy, w, h = 50, 46, 42, 36
        ancho = max(254, dx * (max(xs) - min(xs) + 1))
        self.mapa.configure(scrollregion=(0, 0, ancho, 158))
        if ancho > 254:
            self.desplazar.pack(fill="x", before=self.accion_mapa)
            cx = (plano.get(actual, (min(xs), 0))[0] - min(xs)) * dx + dx / 2
            self.mapa.xview_moveto(max(0, cx - 127) / ancho)
        else:
            self.desplazar.pack_forget()
            self.mapa.xview_moveto(0)
        for sala, (col, fila) in visibles.items():
            x, y = 3 + dx * (col - min(xs)), 3 + dy * (fila - min(ys))
            links = p.mapa[1952 + 4 * (sala - 1) : 1956 + 4 * (sala - 1)]
            if links[1] in p.vistas:
                self.mapa.create_line(x + w, y + h / 2, x + dx, y + h / 2, fill=GRIS)
            if links[3] in p.vistas:
                self.mapa.create_line(x + w / 2, y + h, x + w / 2, y + dy, fill=GRIS)
            aqui = sala == actual
            tag = f"s{sala}"
            self.mapa.create_rectangle(
                x,
                y,
                x + w,
                y + h,
                fill=ORO if aqui else "#334857",
                outline=ORO if aqui else GRIS,
                tags=tag,
            )
            self.mapa.create_text(
                x + w / 2,
                y + h / 2,
                text=str(sala),
                font=("Segoe UI", 11, "bold"),
                fill=FONDO if aqui else TEXTO,
                tags=tag,
            )

    def destino_bajo_cursor(self):
        frame = self.partida.game.frame
        if frame.end == "playing":
            for tag in self.mapa.gettags("current"):
                if tag.startswith("s") and tag[1:].isdigit():
                    sala = int(tag[1:])
                    if sala != frame.state[1]:
                        return sala
        return None

    def clic_mapa(self, _evento):
        sala = self.destino_bajo_cursor()
        if sala is not None:
            self.ver_sala(sala)

    def ayuda_mapa(self, destino=None):
        self.mapa.configure(cursor="hand2" if destino else "")
        texto = "Haz clic en otra sala para viajar."
        if destino:
            texto = f"Viajar a la sala {destino}"
        elif self.partida.game.frame.end != "playing":
            texto = "Este intento ha terminado."
        elif len(self.partida.vistas) == 1:
            texto = "Explora otra sala para poder volver."
        self.accion_mapa.config(text=texto)

    def ver_sala(self, sala):
        self.pausar()
        try:
            frame = self.partida.viajar(sala)
            self.mostrar()
            if frame.state[1] != sala:
                self.estado.config(
                    text="Esta sala ya no tiene un punto de llegada seguro."
                )
            else:
                self.estado.config(
                    text=f"Llegaste a la sala {sala}. Pulsa A o D para moverte."
                )
            self.root.focus_set()
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as e:
            self.estado.config(text=str(e))

    def cerrar(self):
        self.pausar()
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.partida:
            self.partida.game.close()
        self.motor.cerrar()
        self.bib.db.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    try:
        app = Explorador(root)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as e:
        messagebox.showerror("No se pudo abrir el explorador", str(e), parent=root)
        root.destroy()
        raise SystemExit(1)
    root.mainloop()
