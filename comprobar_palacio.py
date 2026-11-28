"""Pruebas de integración en SDLPoP. Todas las partidas de prueba son temporales."""

import hashlib
import tempfile
from pathlib import Path

from niveles import MOTOR, RECURSO, Game, MotorTemporal
from palacio import nuevo_palacio, posiciones, ruta_palacio
from partidas import Biblioteca, Partida, huella
from salas import GeneradorNeuronal


def probar_viaje(motor, mapa, seed, ruta):
    with tempfile.TemporaryDirectory() as tmp:
        bib = Biblioteca(Path(tmp) / "prueba.db")
        motor.cargar(mapa)
        with Game(motor.ruta, 1, seed) as g:
            mundo = bib.crear(seed, mapa, ruta, g.frame)
        partida = Partida(bib, motor, mundo)
        try:
            try:
                partida.viajar(15)
            except ValueError:
                pass
            else:
                raise AssertionError("Se permitió viajar sin descubrir la sala.")
            for accion in ruta:
                if partida.paso(accion).state[1] == 2:
                    break
            assert set(partida.vistas) == {1, 2}
            antes = partida.game.frame
            f = partida.viajar(1)
            assert (
                f.state[1] == 1
                and f.index == antes.index + 1
                and f.state[5] == antes.state[5]
            )
            f = partida.viajar(2)
            assert f.state[1] == 2
            firma = huella(f)
            partida.game.close()
            partida = Partida(bib, motor, mundo)
            assert huella(partida.game.frame) == firma and partida.mapa == mapa
        finally:
            partida.game.close()
            bib.db.close()


def probar_combate(motor, mapa, seed):
    # Aislar el encuentro con la API del motor, sin desbloquear salas en la interfaz.
    motor.cargar(mapa)
    for duracion in (30, 38, 21, 33, 40, 18, 26, 42, 34):
        with Game(motor.ruta, 1, seed) as g:
            g.travel(15)
            for _ in range(duracion):
                g.step(("left",))
            for _ in range(18):
                g.step(())
            recogida = [g.step(("shift",)).state[6] for _ in range(75)]
            if 229 not in recogida:
                continue
            g.travel(3)
            for t in range(100):
                f = g.step(("right",) if t < 16 else ("shift",))
                if f.state[7] == 2:
                    return
                if f.end != "playing":
                    break
    raise AssertionError(
        "No se consiguió recoger y desenvainar la espada ante el guardia."
    )


def main():
    motor = MotorTemporal()
    try:
        original = (MOTOR / RECURSO).read_bytes()
        ruta = ruta_palacio(motor, original, 1)
        assert ruta
        probar_viaje(motor, original, 1, ruta)
        probar_combate(motor, original, 1)
        red = GeneradorNeuronal()
        firmas = set()
        for seed in range(101, 109):
            mapa, ruta = nuevo_palacio(motor, red, seed)
            plano = posiciones(mapa)
            assert len(set(plano.values())) == len(plano)
            for s, (x, y) in plano.items():
                for i, (dx, dy) in enumerate(((-1, 0), (1, 0), (0, -1), (0, 1))):
                    vecina = mapa[1952 + 4 * (s - 1) + i]
                    if vecina:
                        assert plano[vecina] == (x + dx, y + dy)
                        assert mapa[1952 + 4 * (vecina - 1) + (i ^ 1)] == s
            firmas.add(hashlib.sha256(mapa).digest())
            print(
                f"Semilla {seed}: {len(plano)} salas, salida en {len(ruta)} pasos",
                flush=True,
            )
            if seed == 101:
                probar_viaje(motor, mapa, seed, ruta)
                probar_combate(motor, mapa, seed)
        assert len(firmas) == 8
    finally:
        motor.cerrar()


if __name__ == "__main__":
    main()
