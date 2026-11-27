"""Entrena con predicción recursiva y elige el checkpoint en validación."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from modelo import Mundo, Partidas


def perdida(pred, objetivo, previo):
    cambio = (objetivo - previo).abs().amax(1, keepdim=True)
    peso = 1 + 15 * (cambio > 0.04)
    return ((pred - objetivo).abs() * peso).mean()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--datos", default="datos/compactos")
    p.add_argument("--salida", type=Path, default=Path("resultados"))
    p.add_argument("--pasos", type=int, default=3600)
    p.add_argument("--lote", type=int, default=24)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args()
    args.salida.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(193)
    torch.manual_seed(193)
    torch.set_num_threads(4)
    train = Partidas(args.datos, "entrenamiento", args.device)
    val = Partidas(args.datos, "validacion", args.device)
    opciones = train.inicios(2)
    fijos = torch.tensor(val.inicios(4, 11), device=args.device)
    red = Mundo().to(args.device, memory_format=torch.channels_last)
    optim = torch.optim.AdamW(red.parameters(), lr=0.0015)
    programa = torch.optim.lr_scheduler.CosineAnnealingLR(optim, args.pasos, eta_min=0.00015)
    mejor, historial = float("inf"), []
    for n in range(1, args.pasos + 1):
        indices = torch.tensor(rng.choice(opciones, args.lote), device=args.device)
        ant, act = train.imagen(indices-1), train.imagen(indices)
        horizonte = 2 if n > args.pasos // 3 and n % 2 == 0 else 1
        loss = 0
        for k in range(horizonte):
            futuro = red(ant, act, train.acciones[indices+k])
            verdad = train.imagen(indices+k+1)
            loss += perdida(futuro, verdad, train.imagen(indices+k))
            ant, act = act, futuro
        optim.zero_grad(set_to_none=True)
        (loss / horizonte).backward()
        torch.nn.utils.clip_grad_norm_(red.parameters(), 1.0)
        optim.step()
        programa.step()
        if n % 150 == 0 or n == args.pasos:
            with torch.inference_mode():
                suma = 0
                for i in fijos.split(args.lote):
                    ant, act = val.imagen(i-1), val.imagen(i)
                    for k in range(4):
                        ant, act = act, red(ant, act, val.acciones[i+k])
                    suma += float(perdida(act, val.imagen(i+4), val.imagen(i+3))) * len(i)
                media = suma / len(fijos)
            historial.append(dict(paso=n, validacion=media))
            if media < mejor:
                mejor = media
                torch.save(dict(modelo=red.state_dict(), paso=n), args.salida / "mundo.pt")
            print(f"{n:4} / {args.pasos} | validación a 4 pasos {media:.5f}", flush=True)
            (args.salida / "entrenamiento.json").write_text(json.dumps(historial, indent=2), "utf-8")


if __name__ == "__main__":
    main()
