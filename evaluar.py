"""Compara rollouts abiertos con persistencia en todas las ventanas de prueba."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from modelo import Partidas, cargar


@torch.inference_mode()
def evaluar(red, datos, device, horizontes=(1, 4, 12)):
    # Las mismas ventanas para todos los horizontes. Desde t+1, la red
    # recibe exclusivamente sus imágenes predichas y los botones registrados.
    indices = datos.inicios(max(horizontes))
    rng = np.random.default_rng(992)
    control = rng.permutation(indices)
    totales = {h: np.zeros((3, 2), np.float64) for h in horizontes}
    cantidades = {h: np.zeros(2, np.float64) for h in horizontes}
    for start in range(0, len(indices), 48):
        i = torch.tensor(indices[start:start+48], device=device)
        j = torch.tensor(control[start:start+48], device=device)
        ant, inicio = datos.imagen(i-1), datos.imagen(i)
        actual = inicio
        ant_control, sin_control = ant, inicio
        for k in range(1, max(horizontes)+1):
            ant, actual = actual, red(ant, actual, datos.acciones[i+k-1])
            ant_control, sin_control = sin_control, red(ant_control, sin_control, datos.acciones[j+k-1])
            if k not in horizontes:
                continue
            verdad = datos.imagen(i+k)
            mascara = (verdad - inicio).abs().amax(1) > 10/255
            cantidades[k] += (mascara.numel(), int(mascara.sum()))
            for fila, valor in enumerate((actual, inicio, sin_control)):
                error = (valor - verdad).abs().mean(1) * 255
                totales[k][fila] += (float(error.sum()), float((mascara * error).sum()))
    salida = {}
    for h in horizontes:
        valores = totales[h] / cantidades[h]
        salida[h] = {nombre: dict(mae_rgb=float(global_), mae_cambio=float(movimiento))
                     for nombre, (global_, movimiento) in zip(
                         ("modelo", "persistencia", "acciones_permutadas"), valores)}
        salida[h]["fraccion_pixeles_cambiados"] = cantidades[h][1] / cantidades[h][0]
    return dict(ventanas=len(indices), episodios=len(datos.episodios), horizontes=salida)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--datos", default="datos/compactos")
    p.add_argument("--modelo", default="resultados/mundo.pt")
    p.add_argument("--salida", type=Path, default=Path("resultados/metricas.json"))
    p.add_argument("--conjunto", choices=["prueba", "validacion"], default="prueba")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args()
    torch.set_num_threads(4)
    red = cargar(args.modelo, args.device)
    datos = Partidas(args.datos, args.conjunto, args.device)
    resultado = evaluar(red, datos, args.device)
    resultado["conjunto"] = args.conjunto
    resultado["paso_checkpoint"] = torch.load(args.modelo, map_location="cpu", weights_only=True)["paso"]
    args.salida.write_text(json.dumps(resultado, indent=2), "utf-8")
    print(json.dumps(resultado, indent=2))


if __name__ == "__main__":
    main()
