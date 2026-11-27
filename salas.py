"""Vocabulario del world model y adaptación de sus columnas al formato de SDLPoP."""

import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from niveles import ANTORCHA, MURO, PILAR, PLACA, PUERTA, SUELO

RAIZ = (
    Path(sys.executable).resolve().parent.parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
PISOS = (SUELO, PILAR, ANTORCHA, 14)
TECHOS = (0, MURO, SUELO)
VACIO = 24  # token reservado para contexto desconocido
INICIO, PASILLO, META, SOTANO = range(4)
INICIAL, MISMA, DERECHA, IZQUIERDA, ABAJO, ARRIBA = range(6)


def rol(sala, total):
    return (
        INICIO if sala == 1 else SOTANO if sala == total else META if sala == total - 1 else PASILLO
    )


def tokens(mapa, sala):
    base = (sala - 1) * 30
    columnas = np.frombuffer(mapa, np.uint8, 30, base).reshape(3, 10) & 31
    resultado = []
    for techo, medio, bajo in columnas.T.tolist():
        alto = bajo == MURO or (medio not in (0, MURO) and bajo == 0)
        piso = medio if alto else bajo
        t = 0 if techo == 0 else 1 if techo == MURO else 2
        resultado.append((0 if alto else 12) + 4 * t + (PISOS.index(piso) if piso in PISOS else 0))
    return resultado


def reducir(rgb):
    return np.array(Image.fromarray(rgb).resize((80, 50), Image.Resampling.BOX))


def estructura(seed):
    # El grafo, la conexión de los bordes y el destino del pulsador son fijos por mundo.
    # Los espacios reservados contienen pasillos de prueba sustituibles al entrar.
    rng = random.Random(seed)
    n = rng.randint(4, 7)
    data = bytearray(2305)
    data[2048] = n + 1
    data[2119:2143] = bytes([30]) * 24
    data[2112:2115] = bytes([1, rng.choice((3, 4, 5)), 255])
    for sala in range(1, n + 1):
        i = sala - 1
        data[1952 + 4 * i : 1956 + 4 * i] = bytes(
            [i, sala + 1 if sala < n else 0, 0, n + 1 if sala == 1 else 0]
        )
        data[2049 + i], data[2073 + i] = sala, 1
    data[1952 + 4 * n + 2] = 1
    data[2049 + n], data[2073 + n] = 1, 2
    salida = rng.choice((5, 6))
    data[1440], data[1441], data[1697] = 128, 128 | ((n & 3) << 5) | (20 + salida), (n & 28) << 3
    for sala in range(1, n + 2):
        data = bytearray(escribir(data, sala, [0] * 10))
    return bytes(data)


def escribir(mapa, sala, codigos):
    data = bytearray(mapa)
    tipo = rol(sala, data[2048])
    fg = np.zeros((3, 10), np.uint8)
    bg = np.zeros_like(fg)
    for x, token in enumerate(codigos):
        h = 1 + token // 12
        fg[0, x] = TECHOS[(token % 12) // 4]
        fg[h, x] = PISOS[token % 4]
        if h == 1:
            fg[2, x] = MURO
    # Perfil compartido en las uniones para poder recorrerlas en ambos sentidos.
    if tipo != SOTANO:
        for x in (0, 1, 8, 9):
            fg[:, x] = [0, SUELO, MURO]
        for x in range(1, 10):
            if (fg[2, x] == MURO) != (fg[2, x - 1] == MURO):
                fg[0, max(0, x - 2) : min(10, x + 2)] = 0
                if fg[2, x] != MURO and x < 8:
                    fg[1, x] = 11  # losa frágil sobre el desnivel
    if tipo == INICIO:
        fg[:, 0] = MURO
        fg[:, 1] = 0
        fg[:, 2] = [0, 0, SUELO]
        fg[:, 3] = [0, SUELO, MURO]
        x = data[2113] % 10
        fg[0, x] = 0
        data[2113] = x if fg[2, x] == MURO else x + 10
    elif tipo == META:
        salida = (data[1441] & 31) - 20
        fg[1, 1:9] = 0
        fg[2, 1:4] = PLACA
        bg[2, 1:4] = 1
        fg[2, 4:9] = [PISOS[t % 4] for t in codigos[4:9]]
        fg[2, salida : salida + 2] = [PUERTA, PUERTA + 1]
        fg[:, 9] = MURO
    elif tipo == SOTANO:
        fg[:, 0] = fg[:, 9] = MURO
        fg[0, 1:3] = SUELO
        fg[0, 3] = 0
        fg[1, 1:4] = SUELO
        fg[2, 1:4] = MURO
    base = (sala - 1) * 30
    data[base : base + 30] = fg.tobytes()
    data[720 + base : 750 + base] = bg.tobytes()
    return bytes(data)


class GeneradorNeuronal:
    def __init__(self, directorio=None):
        import onnxruntime as ort

        directorio = Path(directorio or RAIZ / "resultados")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        self.red = ort.InferenceSession(
            str(directorio / "mundo_salas.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.entrada = np.array(Image.open(directorio / "contexto_entrada.png").convert("RGB"))

    def generar(self, mapa, sala, origen, anterior, actual, mask, direccion, seed, intento=0):
        bits = np.array([[(mask >> j) & 1 for j in range(5)]], dtype=np.float32)
        prefijo = np.full((1, 10), VACIO, np.int64)
        contexto = tokens(mapa, origen) if origen else [VACIO] * 10
        feed = dict(
            anterior=anterior.transpose(2, 0, 1)[None].astype("float32") / 255,
            actual=actual.transpose(2, 0, 1)[None].astype("float32") / 255,
            botones=bits,
            vecina=np.array([contexto], np.int64),
            rol=np.array([rol(sala, mapa[2048])], np.int64),
            direccion=np.array([direccion], np.int64),
            prefijo=prefijo,
        )
        azar = np.random.default_rng(np.random.SeedSequence([seed, sala, intento]))
        for col in range(10):
            logits = self.red.run(None, feed)[0][0, col].astype(float)
            prob = np.exp((logits - logits.max()) / 1.05)
            prefijo[0, col] = azar.choice(24, p=prob / prob.sum())
        return escribir(mapa, sala, prefijo[0].tolist())

    def candidata(self, motor, mapa, sala, origen, anterior, actual, mask, direccion, seed):
        from niveles import certificar

        for intento in range(20):
            nivel = self.generar(
                mapa, sala, origen, anterior, actual, mask, direccion, seed, intento
            )
            ruta = certificar(motor, nivel, seed)
            if ruta:
                yield nivel, ruta

    def entrada_nueva(self, motor, seed):
        mapa = estructura(seed)
        opciones = self.candidata(motor, mapa, 1, 0, self.entrada, self.entrada, 0, INICIAL, seed)
        for nivel, ruta in opciones:
            return nivel, ruta
        raise RuntimeError("No se encontró una entrada transitable para esta semilla.")
