"""Verifica HDF5, reduce el RGB a 80 × 50 y separa partidas enteras."""
import argparse
import json
from collections import Counter
from pathlib import Path

import h5py
import numpy as np
from PIL import Image
from sdlpop_recorder.dataset import validate


def particion(seed):
    # Bloques de seis para que los seis controladores aparezcan en cada grupo.
    if seed >= 47090:
        return {0: "prueba", 1: "validacion"}.get((seed - 47090) % 6, "entrenamiento")
    bloque = ((seed - 47000) // 6) % 15
    if bloque in (3, 12):
        return "validacion"
    if bloque in (6, 10):
        return "prueba"
    return "entrenamiento"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origen", type=Path, default=Path("datos/nivel1"))
    parser.add_argument("--salida", type=Path, default=Path("datos/compactos"))
    args = parser.parse_args()
    informe = validate(args.origen)
    if informe["invalid"] or not informe["valid"]:
        raise ValueError(informe)
    args.salida.mkdir(exist_ok=True, parents=True)
    episodios = []
    semillas = set()
    for path in sorted((args.origen / "episodes").glob("*.h5")):
        with h5py.File(path) as f:
            seed = int(f.attrs["seed"])
            if int(f.attrs["level"]) != 1 or seed in semillas:
                raise ValueError(f"Se esperaba nivel 1 y una semilla única en {path}")
            semillas.add(seed)
            parte = particion(seed)
            rgb = np.stack([np.asarray(Image.fromarray(frame).resize((80, 50), Image.Resampling.BOX))
                            for frame in f["states/rgb"]])
            botones = f["actions/buttons"][:]
            salas = f["states/aux"][:, 1]
            np.savez_compressed(args.salida / f"{seed}.npz", rgb=rgb, botones=botones, salas=salas)
            episodios.append(dict(semilla=seed, conjunto=parte, pasos=len(botones),
                                  salas=dict(Counter(map(int, salas))), fin=str(f.attrs["end_reason"]),
                                  id=path.stem))
    informe["episodios"] = sorted(episodios, key=lambda ep: ep["semilla"])
    (args.salida / "indice.json").write_text(json.dumps(informe, indent=2), encoding="utf-8")
    print({k: v for k, v in informe.items() if k != "episodios"})


if __name__ == "__main__":
    main()
