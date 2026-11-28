"""Ajusta el restaurador local de teselas con el recurso original del nivel 1."""

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from niveles import MOTOR, RECURSO
from palacio import MASCARA, posiciones, ventana
from salas import RAIZ


def ejemplos(mapa, salas):
    contextos, filas, objetivos = [], [], []
    for sala in salas:
        tiles = np.frombuffer(mapa, np.uint8, 30, (sala - 1) * 30).reshape(3, 10) & 31
        for f in range(3):
            for c in range(10):
                contextos.append(ventana(tiles, f, c))
                filas.append(f)
                objetivos.append(int(tiles[f, c]))
    return (
        torch.tensor(np.stack(contextos)),
        F.one_hot(torch.tensor(filas), 3).float(),
        torch.tensor(objetivos),
    )


def ajustar(datos, epocas):
    torch.manual_seed(2109)
    e, h, out = nn.Embedding(33, 8), nn.Linear(123, 64), nn.Linear(64, 32)

    def predecir(x, fila):
        return out(h(torch.cat((e(x).flatten(1), fila), 1)).relu())

    opt = torch.optim.AdamW(
        [*e.parameters(), *h.parameters(), *out.parameters()], lr=0.002
    )
    x, filas, y = datos
    for _ in range(epocas):
        for idx in torch.randperm(len(y)).split(96):
            vista = x[idx].masked_fill(torch.rand(x[idx].shape) < 0.12, MASCARA)
            loss = F.cross_entropy(predecir(vista, filas[idx]), y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
    return predecir, [e.weight, h.weight, h.bias, out.weight, out.bias]


if __name__ == "__main__":
    torch.set_num_threads(1)
    mapa = (MOTOR / RECURSO).read_bytes()
    salas = set(posiciones(mapa))
    reserva = {6, 11, 17, 21}
    train = ejemplos(mapa, sorted(salas - reserva))
    test = ejemplos(mapa, sorted(reserva))
    modelo, _ = ajustar(train, 32)
    with torch.no_grad():
        print(
            "Entropía en cuatro salas reservadas:",
            round(F.cross_entropy(modelo(*test[:2]), test[2]).item(), 3),
        )
    _, pesos = ajustar(ejemplos(mapa, sorted(salas)), 32)
    np.savez_compressed(
        RAIZ / "resultados/teselas_nivel1.npz",
        **{k: p.detach().numpy() for k, p in zip("ewbvc", pesos)},
    )
