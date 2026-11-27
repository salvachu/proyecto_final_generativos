"""Prueba mapas nuevos, recorridos nativos y la recuperación de partidas."""

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

from niveles import MOTOR, RECURSO, Game, ModeloColumnas, MotorTemporal, botones, nuevo_nivel
from partidas import Biblioteca, Partida, huella


def exigir(condicion, mensaje):
    if not condicion:
        raise AssertionError(mensaje)


def ida_y_vuelta(motor, seed, mapa):
    # Caminar a la izquierda hasta caer al sótano. Girar y trepar al descansillo.
    motor.cargar(mapa)
    abajo = 0
    with Game(motor.ruta, 1, seed) as g:
        for paso in range(180):
            _, sala, _, _, direccion, _, _, _ = g.frame.state
            if sala == mapa[2048]:
                abajo += 1
            if paso < 24 or 0 < abajo < 25:
                mask = 0
            elif abajo == 0:
                mask = 1
            else:
                mask = 2 if direccion == -1 else 20
            frame = g.step(botones(mask))
            if abajo and frame.state[1] == 1:
                return paso + 1
            if frame.end != "playing":
                break
    raise AssertionError(f"No se pudo volver del sótano en {seed}.")


def probar_memoria(motor, seed, mapa, ruta, carpeta):
    db = carpeta / "ensayo.sqlite3"
    motor.cargar(mapa)
    b = Biblioteca(db)
    with Game(motor.ruta, 1, seed) as g:
        mundo = b.crear(seed, mapa, ruta, g.frame)
    p = Partida(b, motor, mundo)
    corte = len(ruta) // 2
    for mask in ruta[:corte]:
        p.paso(mask)
    firma, vistas = huella(p.game.frame), p.vistas.copy()
    p.game.close()
    b.db.close()
    b = Biblioteca(db)
    p = Partida(b, motor, b.activo())
    exigir(p.vistas == vistas and huella(p.game.frame) == firma, "Cambió la partida al reabrir.")
    for mask in ruta[corte:]:
        p.paso(mask)
    exigir(p.game.frame.end == "level_complete", "No se pudo terminar tras la reanudación.")
    p.game.close()
    final = Partida(b, motor, mundo)
    exigir(final.game.frame.end == "level_complete", "No se conservó la salida completada.")
    final.game.close()
    revisita = Partida(b, motor, mundo, reiniciar=True)
    exigir(
        set(vistas) <= set(revisita.vistas) and revisita.game.frame.index == 0,
        "Se perdió el mapa descubierto al reintentar.",
    )
    revisita.game.close()
    b.db.close()
    return len(vistas)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cantidad", type=int, default=24)
    parser.add_argument("--salida", type=Path, default=Path("resultados/generacion.json"))
    args = parser.parse_args()
    original = (MOTOR / RECURSO).read_bytes()
    modelo = ModeloColumnas(original)
    motor = MotorTemporal()
    ensayos = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(args.cantidad):
                s, mapa, ruta = nuevo_nivel(modelo, motor, 12000 + i)
                exigir(
                    mapa == modelo.generar(s) and mapa != original, "Semilla o novedad incorrectas."
                )
                retorno = ida_y_vuelta(motor, s, mapa)
                reanudacion = probar_memoria(motor, s, mapa, ruta, Path(tmp)) if i < 3 else None
                ensayos.append(
                    dict(
                        semilla=s,
                        salas=mapa[2048],
                        pasos_salida=len(ruta),
                        ida_y_vuelta=retorno,
                        salas_al_reanudar=reanudacion,
                        sha256=hashlib.sha256(mapa).hexdigest(),
                    )
                )
        exigir(len({e["sha256"] for e in ensayos}) == len(ensayos), "Se repitió un mapa.")
        exigir((MOTOR / RECURSO).read_bytes() == original, "Cambió el nivel original.")
    finally:
        motor.cerrar()
    resultado = dict(
        niveles=len(ensayos),
        distintos=len({e["sha256"] for e in ensayos}),
        salas=dict(Counter(e["salas"] for e in ensayos)),
        ensayos=ensayos,
    )
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(resultado, indent=2), "utf-8")
    print(
        f"{len(ensayos)} mapas distintos completados. Regreso desde el sótano verificado en todos."
    )


if __name__ == "__main__":
    main()
