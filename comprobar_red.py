"""Pruebas de integración del generador neuronal en el motor y el guardado."""

import argparse
import hashlib
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from niveles import Game, MotorTemporal
from salas import GeneradorNeuronal
from partidas import Biblioteca, Partida, huella


def verificar(seed):
    with tempfile.TemporaryDirectory() as tmp:
        motor = MotorTemporal()
        bib = Biblioteca(Path(tmp) / "prueba.db")
        partida = None
        try:
            red = GeneradorNeuronal()
            mapa, ruta = red.entrada_nueva(motor, seed)
            with Game(motor.ruta, 1, seed) as juego:
                ident = bib.crear(seed, mapa, ruta, juego.frame, neuronal=True)
            partida = Partida(bib, motor, ident, red=red)
            assert partida.creadas == {1}
            primera = hashlib.sha256(mapa[:30]).hexdigest()
            vuelta = False
            while partida.game.frame.end == "playing":
                t = partida.game.frame.index
                anterior = partida.mapa
                frame = partida.paso(ruta[t])
                if partida.ultima_nueva:
                    sala = frame.state[1]
                    ix = 30 * (sala - 1)
                    for base in (0, 720):
                        assert all(
                            anterior[base + j] == partida.mapa[base + j]
                            for j in range(720)
                            if not ix <= j < ix + 30
                        )
                    ruta = bib.db.execute(
                        "SELECT solucion FROM mundo WHERE id=?", (ident,)
                    ).fetchone()[0]
                    if sala == 2 and not vuelta:
                        # Cruzar dos veces la misma frontera sin crear otra sala.
                        antes = partida.mapa
                        for _ in range(75):
                            f = partida.paso(1)
                            if f.state[1] == 1:
                                break
                        assert f.state[1] == 1
                        for _ in range(120):
                            f = partida.paso(2)
                            if f.state[1] == 2:
                                break
                        assert (
                            f.state[1] == 2 and partida.mapa == antes and partida.creadas == {1, 2}
                        )
                        firma = huella(f)
                        vistas = partida.vistas.copy()
                        partida.game.close()
                        bib.db.close()
                        bib = Biblioteca(Path(tmp) / "prueba.db")
                        partida = Partida(bib, motor, ident, red=red)
                        assert (
                            partida.mapa == antes
                            and huella(partida.game.frame) == firma
                            and partida.vistas == vistas
                        )
                        partida.game.close()
                        partida = Partida(bib, motor, ident, reiniciar=True, red=red)
                        vuelta = True
            assert partida.game.frame.end == "level_complete" and vuelta
            pasos = partida.game.frame.index
            final = partida.mapa
            firma = huella(partida.game.frame)
            partida.game.close()
            partida = Partida(bib, motor, ident, red=red)
            assert huella(partida.game.frame) == firma
            return dict(
                semilla=seed,
                pasos=pasos,
                salas_generadas=len(partida.creadas),
                entrada=primera,
                mapa=hashlib.sha256(final).hexdigest(),
                regreso_y_reanudacion=True,
            )
        finally:
            if partida:
                partida.game.close()
            bib.db.close()
            motor.cerrar()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cantidad", type=int, default=8)
    args = parser.parse_args()
    with ProcessPoolExecutor(3) as pool:
        pruebas = list(pool.map(verificar, range(82000, 82000 + args.cantidad)))
    assert len({r["mapa"] for r in pruebas}) == len(pruebas)
    Path("resultados/pruebas_salas.json").write_text(json.dumps(pruebas, indent=2), "utf8")
    print(
        f"{len(pruebas)} mundos completados y reabiertos; {len({r['entrada'] for r in pruebas})} entradas distintas."
    )


if __name__ == "__main__":
    main()
