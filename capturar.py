"""Genera episodios HDF5 de nivel 1 con el grabador del curso."""
import argparse
import json
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sdlpop_recorder import Recorder

# Alternamos recorridos guiados y exploración. Cada semilla afecta al motor
# y al controlador. El estado interno solo se usa para recoger datos.
ACCIONES = [(), ("left",), ("right",), ("up",), ("down",), ("shift",),
            ("left", "up"), ("right", "up"), ("left", "shift"),
            ("right", "shift"), ("up", "shift")]


def politica(rng, modo):
    espera = rng.randint(0, 23)
    explorar_desde = [0, rng.randint(22, 82), rng.randint(93, 145),
                      rng.randint(152, 231), rng.randint(215, 300),
                      rng.randint(245, 340)][modo]
    restante = 0
    accion = ()
    for paso in range(380):
        frame = yield accion
        _, sala, x, y, _, _, _, _ = frame.state
        t = paso - espera
        if t < 0:
            accion = ()
        elif t < explorar_desde:
            if sala == 1:
                accion = ("right",) if y < 160 or x < 148 else ()
            elif sala == 2:
                if modo == 3:
                    accion = ("right",)
                elif x < 69 and y > 58:
                    accion = ("up", "shift")
                else:
                    accion = ("left",)
            elif sala == 6 and 118 < x < 139:
                accion = ("left", "up", "shift")
            else:
                accion = ("left",)
        elif restante == 0:
            # Tramos de dirección sostenida mezclados con maniobras cortas.
            accion = rng.choices(ACCIONES, weights=[2, 5, 5, 2, 1, 1, 2, 2, 2, 2, 1])[0]
            restante = rng.randint(3, 21)
        else:
            restante -= 1


def ruta_salida(rng, limite=400):
    espera = rng.randint(0, 22)
    pausa = rng.randint(18, 36)
    sala_final = 0
    instante_palanca = None
    accion = ()
    for t in range(limite):
        frame = yield accion
        _, sala, x, y, direccion, _, animacion, _ = frame.state
        if t < espera:
            accion = ()
        elif sala == 1:
            accion = ("right",) if y < 160 or x < 148 else ()
        elif sala == 3 and 133 <= x < 151:
            accion = ("right", "up")
        elif sala != 9:
            accion = ("right",)
        else:
            sala_final += 1
            if y == 55 and instante_palanca is None:
                instante_palanca = t
            if sala_final < 4:
                accion = ("right",)
            elif sala_final < 10:
                accion = ()
            elif instante_palanca is None:
                accion = ("left",) if direccion == 0 else ("up", "shift")
            elif t - instante_palanca < pausa:
                accion = ()
            elif y < 100:
                accion = ("right",)
            elif x < 100:
                accion = ("right", "shift")
            else:
                accion = ("up",) if animacion == 15 else ()


def grabar(args):
    engine, output, seed, index = args
    rng = random.Random(seed)
    control = politica(rng, index % 6) if index < 90 else ruta_salida(rng)
    next(control)
    with Recorder(output, "nivel1", level=1, engine=engine, seed=seed,
                  max_steps=rng.randint(290, 365) if index < 90 else 390) as game:
        frame = game.frame
        while not game.end_reason:
            frame = game.step(control.send(frame))
        return game.steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="runtime/SDLPoP")
    parser.add_argument("--output", type=Path, default=Path("datos/nivel1"))
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    # Reiniciar la captura reutiliza los episodios ya cerrados.
    usados = {json.loads(p.read_text("utf-8"))["seed"]
              for p in (args.output / "manifests").glob("*.json")}
    tareas = [(args.engine, args.output, 47000+i, i) for i in range(120)
              if 47000+i not in usados]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, pasos in enumerate(pool.map(grabar, tareas), 1):
            if i % 10 == 0 or i == len(tareas):
                print(f"{i}/{len(tareas)} episodios nuevos. Último episodio: {pasos} pasos.", flush=True)


if __name__ == "__main__":
    main()
