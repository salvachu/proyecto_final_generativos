"""Amplía el world model visual con una salida autorregresiva de terreno."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from niveles import MOTOR, RECURSO, ModeloColumnas, MotorTemporal, certificar
from salas import ABAJO, ARRIBA, DERECHA, INICIAL, IZQUIERDA, MISMA, VACIO, reducir, rol, tokens


def muestra(prev, actual, botones, mapa, origen, destino, tipo, dir_, grupo):
    return (
        prev,
        actual,
        botones,
        tokens(mapa, origen) if origen else [VACIO] * 10,
        tipo,
        dir_,
        tokens(mapa, destino),
        grupo,
    )


def recoger(lote):
    motor = MotorTemporal()
    docente = ModeloColumnas((MOTOR / RECURSO).read_bytes())
    ejemplos = []
    try:
        for seed in lote:
            mapa = docente.generar(seed)
            total = mapa[2048]
            previo = None

            def observar(antes, mask, despues):
                nonlocal previo
                origen, destino = antes.state[1], despues.state[1]
                actual = reducir(antes.rgb)
                bits = [(mask >> j) & 1 for j in range(5)]
                if previo is None:
                    ejemplos.append(muestra(actual, actual, [0] * 5, mapa, 0, 1, 0, INICIAL, seed))
                    if seed % 8:
                        # El arranque original tiene una única postura. Permitir que
                        # cada galería interior sirva también de terreno inicial.
                        for destino_inicial in range(2, total - 1):
                            ejemplos.append(
                                muestra(
                                    actual,
                                    actual,
                                    [0] * 5,
                                    mapa,
                                    0,
                                    destino_inicial,
                                    0,
                                    INICIAL,
                                    seed,
                                )
                            )
                elif origen != destino or antes.index % 41 == 0:
                    ejemplos.append(
                        muestra(
                            previo,
                            actual,
                            bits,
                            mapa,
                            origen,
                            destino,
                            rol(destino, total),
                            DERECHA if origen != destino else MISMA,
                            seed,
                        )
                    )
                previo = actual

            certificar(motor, mapa, seed, observar)
    finally:
        motor.cerrar()
    return ejemplos


def originales():
    mapa = (MOTOR / RECURSO).read_bytes()
    base = Path("datos/compactos")
    muestras = []
    for ep in json.loads((base / "indice.json").read_text("utf8"))["episodios"]:
        # Las partidas de prueba del modelo visual no intervienen en el ajuste.
        if ep["conjunto"] != "entrenamiento":
            continue
        with np.load(base / f"{ep['semilla']}.npz") as f:
            rgb, acciones, salas = f["rgb"], f["botones"], f["salas"]
        for t in range(1, len(acciones)):
            a, b = map(int, salas[t : t + 2])
            if a == b and t % 57:
                continue
            enlaces = mapa[1952 + 4 * (a - 1) : 1956 + 4 * (a - 1)]
            if a != b and b not in enlaces:
                continue
            direccion = MISMA if a == b else (IZQUIERDA, DERECHA, ARRIBA, ABAJO)[enlaces.index(b)]
            tipo = {1: 0, 9: 2, 2: 3}.get(b, 1)
            muestras.append(
                muestra(
                    rgb[t - 1], rgb[t], acciones[t], mapa, a, b, tipo, direccion, -ep["semilla"]
                )
            )
    return muestras


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mundos", type=int, default=96)
    p.add_argument("--pasos", type=int, default=1800)
    p.add_argument("--salida", type=Path, default=Path("resultados"))
    args = p.parse_args()
    args.salida.mkdir(exist_ok=True, parents=True)
    semillas = list(range(31000, 31000 + args.mundos))
    with ProcessPoolExecutor(4) as pool:
        tareas = [pool.submit(recoger, semillas[i::4]) for i in range(4)]
        muestras = originales()
        for tarea in tareas:
            muestras.extend(tarea.result())
    ajustar(args, muestras)


def ajustar(args, muestras):
    import torch
    from torch.nn import functional as F
    from modelo import MundoEspacial

    torch.manual_seed(175)
    torch.set_num_threads(3)
    rng = np.random.default_rng(175)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    modelo = MundoEspacial()
    visual = torch.load("resultados/mundo.pt", map_location="cpu", weights_only=True)["modelo"]
    modelo.load_state_dict(visual, strict=False)
    modelo.to(device)
    grupos = np.array([m[-1] for m in muestras])
    # Mundos completos aparte. El conjunto reservado usa solo semillas sintéticas nuevas.
    val = np.where((grupos > 0) & (grupos % 8 == 0))[0]
    train = np.where((grupos < 0) | (grupos % 8 != 0))[0]
    campos = [torch.as_tensor(np.stack(c), device=device) for c in zip(*muestras)]
    ant, act, botones, vecina, tipo, dir_, objetivo, _ = campos
    ant = ant.permute(0, 3, 1, 2).float() / 255
    act = act.permute(0, 3, 1, 2).float() / 255
    with torch.no_grad():
        latente = torch.cat(
            [
                modelo.contexto_visual(
                    ant[i : i + 48], act[i : i + 48], botones[i : i + 48].float()
                )
                for i in range(0, len(ant), 48)
            ]
        )
    optim = torch.optim.AdamW(modelo.terreno.parameters(), lr=0.001)
    mejor = float("inf")
    path = args.salida / "mundo_espacial.pt"

    def logits(i):
        return modelo.terreno(
            latente[i], vecina[i].long(), tipo[i].long(), dir_[i].long(), objetivo[i].long()
        )

    cruces = train[(grupos[train] > 0) & (dir_[train].cpu().numpy() != MISMA)]
    for t in range(args.pasos):
        i = np.concatenate([rng.choice(train, 48), rng.choice(cruces, 48)])
        loss = F.cross_entropy(logits(i).transpose(1, 2), objetivo[i].long())
        optim.zero_grad()
        loss.backward()
        optim.step()
        if (t + 1) % 200 == 0 or t + 1 == args.pasos:
            with torch.no_grad():
                error = F.cross_entropy(logits(val).transpose(1, 2), objetivo[val].long()).item()
            if error < mejor:
                mejor = error
                torch.save(dict(modelo=modelo.state_dict(), paso=t + 1), path)
    modelo.load_state_dict(torch.load(path, map_location=device, weights_only=True)["modelo"])
    modelo.cpu().eval()
    from torch import nn

    class Exportar(nn.Module):
        def __init__(self, red):
            super().__init__()
            self.red = red

        def forward(self, anterior, actual, botones, vecina, rol, direccion, prefijo):
            return self.red.predecir_sala(
                anterior, actual, botones, vecina, rol, direccion, prefijo
            )

    entradas = (
        ant[:1].cpu(),
        act[:1].cpu(),
        botones[:1].float().cpu(),
        vecina[:1].long().cpu(),
        tipo[:1].long().cpu(),
        dir_[:1].long().cpu(),
        objetivo[:1].long().cpu(),
    )
    nombres = ["anterior", "actual", "botones", "vecina", "rol", "direccion", "prefijo"]
    torch.onnx.export(
        Exportar(modelo),
        entradas,
        args.salida / "mundo_salas.onnx",
        dynamo=False,
        input_names=nombres,
        output_names=["logits"],
        opset_version=17,
    )
    import onnxruntime as ort

    sesion = ort.InferenceSession(
        str(args.salida / "mundo_salas.onnx"), providers=["CPUExecutionProvider"]
    )
    ref = Exportar(modelo)(*entradas).detach().numpy()
    out = sesion.run(None, dict(zip(nombres, [a.numpy() for a in entradas])))[0]
    np.testing.assert_allclose(ref, out, rtol=1e-4, atol=2e-5)
    with np.load("datos/compactos/47000.npz") as f:
        Image.fromarray(f["rgb"][0]).save(args.salida / "contexto_entrada.png")
    baseline = np.bincount(objetivo[train].cpu().numpy().ravel(), minlength=24) + 1
    constante = float(-np.log(baseline / baseline.sum())[objetivo[val].cpu().numpy()].mean())
    datos = dict(
        ejemplos_entrenamiento=len(train),
        ejemplos_validacion=len(val),
        mundos_docentes=args.mundos,
        mundos_validacion=len(np.unique(grupos[val])),
        entropia_cruzada_validacion=mejor,
        referencia_frecuencias=constante,
        error_max_exportacion=float(np.max(np.abs(ref - out))),
    )
    (args.salida / "ajuste_espacial.json").write_text(json.dumps(datos, indent=2), "utf8")
    print(datos, flush=True)


if __name__ == "__main__":
    main()
