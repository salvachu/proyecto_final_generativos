"""Comparación interactiva del juego y el modelo entrenado."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import torch
from PIL import Image, ImageTk

from modelo import cargar

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "sdlpop-recorder" / "src"))
from sdlpop_recorder.engine import BUTTONS, Game, action_mask

TECLAS = {
    "a": "left", "left": "left", "d": "right", "right": "right",
    "w": "up", "up": "up", "s": "down", "down": "down",
    "shift_l": "shift", "shift_r": "shift", "space": None,
}
NOMBRES = ("Izquierda", "Derecha", "Arriba", "Abajo", "Shift")
FONDO, TEXTO, SECUNDARIO = "#13212a", "#f2ece0", "#b5c6cc"


def reducir(rgb):
    imagen = Image.fromarray(rgb).resize((80, 50), Image.Resampling.BOX)
    return torch.from_numpy(np.array(imagen)).permute(2, 0, 1)[None].float() / 255


class Interfaz:
    def __init__(self, root):
        self.root = root
        self.red = cargar(RAIZ / "resultados/mundo.pt", "cpu")
        self.game = None
        self.tarea = None
        self.pulsadas = set()
        self.modo = tk.StringVar(value="uno")
        root.title("Prince of Persia · Juego y predicción")
        root.configure(bg=FONDO)
        main = tk.Frame(root, bg=FONDO, padx=22, pady=18)
        main.pack()
        self.texto(main, "Prince of Persia  /  Nivel 1", 20).pack(anchor="w")
        self.texto(main, "Mantén D para correr a la derecha. Suelta la tecla para detener la comparación.", 11).pack(anchor="w", pady=(3, 13))
        paneles = tk.Frame(main, bg=FONDO)
        paneles.pack(anchor="w")
        self.pantallas = []
        for i, titulo in enumerate(("Juego real", "Predicción del modelo")):
            panel = tk.Frame(paneles, bg=FONDO)
            panel.grid(row=0, column=i, padx=(0, 12 if i == 0 else 0))
            self.texto(panel, titulo, 14).pack(anchor="w", pady=(0, 4))
            pantalla = tk.Label(panel, bg="black", borderwidth=0)
            pantalla.pack()
            self.pantallas.append(pantalla)
        opciones = tk.Frame(main, bg=FONDO)
        opciones.pack(anchor="w", pady=(14, 4))
        for etiqueta, valor in (("Predecir un paso", "uno"), ("Encadenar predicciones", "cadena")):
            ttk.Radiobutton(opciones, text=etiqueta, variable=self.modo, value=valor,
                            command=self.cambiar_modo, takefocus=False).pack(side="left", padx=(0, 10))
        self.ayuda = self.texto(main, "", 10, SECUNDARIO)
        self.ayuda.pack(anchor="w")
        acciones = tk.Frame(main, bg=FONDO)
        acciones.pack(anchor="w", pady=(11, 5))
        for tecla, nombre in (("a", "A · Izquierda"), ("d", "D · Derecha"), ("w", "W · Arriba"),
                              ("s", "S · Abajo"), ("space", "Espacio · Sin pulsar")):
            ttk.Button(acciones, text=nombre, takefocus=False,
                       command=lambda k=tecla: self.avanzar({k})).pack(side="left", padx=(0, 5))
        ttk.Button(acciones, text="Reiniciar", command=self.reiniciar, takefocus=False).pack(side="left")
        self.estado = self.texto(main, "", 11)
        self.estado.pack(anchor="w", pady=(5, 0))
        root.bind("<KeyPress>", self.pulsar)
        root.bind("<KeyRelease>", self.soltar)
        root.bind("<FocusOut>", self.al_perder_foco)
        root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.reiniciar()

    def texto(self, padre, contenido, size, color=TEXTO):
        return tk.Label(padre, text=contenido, bg=FONDO, fg=color, font=("Segoe UI", size))

    def detener(self):
        self.pulsadas.clear()
        if self.tarea is not None:
            self.root.after_cancel(self.tarea)
            self.tarea = None

    def al_perder_foco(self, evento):
        if evento.widget == self.root:
            self.detener()

    def reiniciar(self):
        self.detener()
        if self.game is not None:
            self.game.close()
        self.game = Game(RAIZ / "runtime/SDLPoP", level=1, seed=57000)
        self.game.__enter__()
        # Empezar tras la caída inicial, cuando el príncipe ya responde a las teclas.
        for _ in range(26):
            frame = self.game.step()
        self.anterior = reducir(frame.rgb)
        self.actual = reducir(self.game.step().rgb)
        self.pasos = 0
        self.cambiar_modo()
        self.root.focus_set()

    def cambiar_modo(self):
        self.detener()
        self.imaginada_anterior, self.imaginada = self.anterior, self.actual
        self.ayuda.configure(text=(
            "Cada predicción parte de las dos últimas imágenes reales." if self.modo.get() == "uno"
            else "Desde este punto, el modelo usa sus propios dibujos para imaginar los pasos siguientes."))
        self.dibujar(self.actual)
        self.estado.configure(text=f"Paso {self.pasos}   ·   Imagen real de partida")

    def dibujar(self, prediccion):
        for pantalla, foto in zip(self.pantallas, (self.actual, prediccion)):
            rgb = foto[0].permute(1, 2, 0).mul(255).round().byte().numpy()
            im = Image.fromarray(rgb).resize((400, 250), Image.Resampling.NEAREST)
            pantalla.imagen = ImageTk.PhotoImage(im)
            pantalla.configure(image=pantalla.imagen)

    @torch.inference_mode()
    def avanzar(self, teclas):
        if self.game.frame.end != "playing":
            return
        mask = action_mask([TECLAS[k] for k in teclas if TECLAS[k] is not None])
        bits = [(mask >> j) & 1 for j in range(len(BUTTONS))]
        acciones = [b for b, v in zip(BUTTONS, bits) if v]
        ant, act = ((self.anterior, self.actual) if self.modo.get() == "uno"
                    else (self.imaginada_anterior, self.imaginada))
        pred = self.red(ant, act, torch.tensor([bits], dtype=torch.float32))
        frame = self.game.step(acciones)
        self.anterior, self.actual = self.actual, reducir(frame.rgb)
        self.imaginada_anterior, self.imaginada = act, pred
        self.pasos += 1
        self.dibujar(pred)
        etiqueta = " + ".join(n for n, v in zip(NOMBRES, bits) if v) or "Sin pulsar"
        self.estado.configure(text=f"Paso {self.pasos}   ·   {etiqueta}   ·   Sala {frame.state[1]}")
        if frame.end != "playing":
            self.detener()
            final = {"death": "El príncipe ha muerto", "level_complete": "Nivel completado",
                     "time_expired": "Tiempo agotado", "victory": "Victoria"}[frame.end]
            self.estado.configure(text=f"{final}. Pulsa Reiniciar para volver a jugar.")

    def ciclo(self):
        self.tarea = None
        if self.pulsadas and self.game.frame.end == "playing":
            self.avanzar(self.pulsadas)
            if self.pulsadas:
                self.tarea = self.root.after(83, self.ciclo)

    def pulsar(self, evento):
        k = evento.keysym.lower()
        if k in TECLAS:
            self.pulsadas.add(k)
            if self.tarea is None:
                self.ciclo()
            return "break"

    def soltar(self, evento):
        self.pulsadas.discard(evento.keysym.lower())
        if not self.pulsadas:
            self.detener()

    def cerrar(self):
        self.detener()
        if self.game is not None:
            self.game.close()
        self.root.destroy()


if __name__ == "__main__":
    torch.set_num_threads(2)
    root = tk.Tk()
    root.withdraw()
    try:
        app = Interfaz(root)
    except (OSError, RuntimeError, ValueError) as error:
        messagebox.showerror("Error al abrir la demostración", str(error), parent=root)
        root.destroy()
        raise SystemExit(1)
    root.deiconify()
    root.after(150, root.focus_set)
    root.mainloop()
