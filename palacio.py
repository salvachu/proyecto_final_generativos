"""Variantes del nivel uno. Las salas de enlace se sintetizan con las dos redes."""

import random

import numpy as np

from niveles import MOTOR, RECURSO, Game
from salas import DERECHA, PASILLO, RAIZ, escribir, reducir

MASCARA = 32
PISOS = (1, 3, 14, 19)
RESERVAS = (13, 18, 24)  # Fuera del plano jugable del recurso original.


def posiciones(mapa):
    return {
        s: (mapa[2048 + s], mapa[2072 + s])
        for s in range(1, 25)
        if mapa[2048 + s] not in (0, 255) and mapa[2072 + s] not in (0, 255)
    }


def ventana(sala, fila, col):
    vecinos = np.full((3, 5), MASCARA, np.int64)
    a, b = max(0, col - 2), min(10, col + 3)
    vecinos[:, a - col + 2 : b - col + 2] = sala[:, a:b]
    vecinos[fila, 2] = MASCARA
    return vecinos.ravel()


class ModeloTeselas:
    def __init__(self, archivo):
        with np.load(archivo) as datos:
            self.e, self.w, self.b, self.v, self.c = (
                datos[k] for k in ("e", "w", "b", "v", "c")
            )

    def elegir(self, sala, fila, col, opciones, rng):
        contexto = self.e[ventana(sala, fila, col)].ravel()
        x = np.concatenate((contexto, np.eye(3, dtype=np.float32)[fila]))
        logits = (np.maximum(0, self.w @ x + self.b) @ self.v.T + self.c)[
            list(opciones)
        ]
        pesos = np.exp((logits - logits.max()) / 1.15)
        return rng.choices(opciones, weights=pesos.tolist())[0]


def sintetizar(motor, red, detalle, original, seed, intento):
    rng = random.Random((seed << 8) + intento)
    mapa = bytearray(original)
    # La topología occidental conserva las conexiones verticales de la búsqueda
    # de la espada. La longitud de los dos accesos a la guardia varía por semilla.
    reservas = list(RESERVAS)
    rng.shuffle(reservas)
    ampliar_oeste = rng.random() < 0.5
    antes = reservas[: 1 if ampliar_oeste else rng.choice((1, 2))]
    despues = (
        [] if ampliar_oeste else reservas[len(antes) : len(antes) + rng.randrange(2)]
    )
    cadena = [2, *antes, 3, *despues, 9]
    for i, sala in enumerate(cadena):
        p = 1952 + 4 * (sala - 1)
        if sala in reservas:
            mapa[p : p + 4] = bytes(4)
            mapa[2118 + sala] = 30
        if i:
            mapa[p] = cadena[i - 1]
        if i + 1 < len(cadena):
            mapa[p + 1] = cadena[i + 1]
        mapa[2048 + sala], mapa[2072 + sala] = 16 + i, 16

    nuevas = [
        (s, cadena[i - 1], 2 if s in antes else 3)
        for i, s in enumerate(cadena)
        if s in antes + despues
    ]
    if ampliar_oeste:
        for s, (x, _) in posiciones(original).items():
            if x <= 15:
                mapa[2048 + s] -= 1
        for sala, izq, der, y in ((reservas[1], 5, 1, 15), (reservas[2], 6, 2, 16)):
            p = 1952 + 4 * (sala - 1)
            mapa[p : p + 4] = bytes((izq, der, 0, 0))
            mapa[1952 + 4 * (izq - 1) + 1], mapa[1952 + 4 * (der - 1)] = sala, sala
            mapa[2048 + sala], mapa[2072 + sala], mapa[2118 + sala] = 15, y, 30
            nuevas.append((sala, izq, izq))

    # El mismo codificador visual y espacial de la partida propone diez columnas.
    # Se observa el motor en una sesión privada, antes de que el jugador entre.
    motor.cargar(original)
    with Game(motor.ruta, 1, seed) as referencia:
        contexto = {}
        for s in sorted({ref for _, _, ref in nuevas}):
            f = referencia.travel(s)
            contexto[s] = (reducir(f.rgb), reducir(referencia.step(()).rgb))
    for sala, vecina, ref in nuevas:
        col = red.columnas(
            mapa, sala, vecina, *contexto[ref], 2, DERECHA, seed, intento, PASILLO
        )
        mapa = bytearray(escribir(mapa, sala, col, PASILLO))
        base = (sala - 1) * 30
        if sala == antes[0]:
            # Un pozo en el acceso al guardia: la predicción del relieve decide
            # el emplazamiento. Reservar carrera, espacio de salto y aterrizaje.
            candidatos = [c for c in (4, 5, 6) if col[c] >= 12] or [4, 5, 6]
            pozo = rng.choice(candidatos)
            for c in range(pozo - 3, min(10, pozo + 4)):
                mapa[base + c] = 0
                mapa[base + 10 + c] = 0 if c == pozo else 1
                mapa[base + 20 + c] = 2 if c == pozo else 20
        elif ref == 5:
            # El paso occidental llega por el piso superior, el oriental por el medio.
            escalon = rng.choice((3, 4, 5))
            mapa[base : base + 10] = bytes([1] * escalon + [0] * (10 - escalon))
            mapa[base + 10 + escalon - 1 : base + 20] = bytes([1] * (11 - escalon))

    for sala in posiciones(mapa):
        base = (sala - 1) * 30
        tiles = np.array(mapa[base : base + 30], dtype=np.uint8).reshape(3, 10) & 31
        celdas = [(f, c) for f in range(3) for c in range(10)]
        rng.shuffle(celdas)
        for f, c in celdas:
            t = tiles[f, c]
            if t in PISOS and rng.random() < 0.68:
                opciones = PISOS
            elif (
                sala in antes + despues and f == 0 and 2 <= c <= 7 and tiles[2, c] == 20
            ):
                opciones = (0, 1, 3, 19, 20)
            else:
                continue
            tile = detalle.elegir(tiles, f, c, opciones, rng)
            tiles[f, c] = tile
            mapa[base + 10 * f + c] = tile
            mapa[720 + base + 10 * f + c] = 0
    # Tres posiciones en la misma repisa accesible. La espada sigue siendo un
    # objeto que hay que recoger y el combate lo resuelve la IA de SDLPoP.
    base = 14 * 30 + 20
    destino = rng.choice((1, 2, 4))
    mapa[base + 2], mapa[base + destino] = mapa[base + destino], mapa[base + 2]
    mapa[720 + base + 2], mapa[720 + base + destino] = (
        mapa[720 + base + destino],
        mapa[720 + base + 2],
    )
    mapa[2113] = rng.choice((0, 1, 2))  # Tres caídas de entrada con suelo debajo.
    return bytes(mapa)


def ruta_palacio(motor, mapa, seed):
    from capturar import ruta_salida

    motor.cargar(mapa)
    mando = ruta_salida(random.Random(seed), limite=1800)
    next(mando)
    ruta = bytearray()
    previo, quieto, trepa = None, 0, 0
    with Game(motor.ruta, 1, seed) as juego:
        for _ in range(1750):
            f = juego.frame
            accion = mando.send(f)
            _, sala, x, y, _, _, anim, _ = f.state
            if sala in RESERVAS:
                quieto = quieto + 1 if previo == (sala, x, y) else 0
                if quieto >= 4 and y == 181 and anim == 15 and not trepa:
                    trepa, quieto = 30, 0
                accion = ("up", "shift") if trepa else ("right",)
                trepa = max(0, trepa - 1)
                fondo = mapa[(sala - 1) * 30 + 20 : sala * 30]
                if 2 in fondo:
                    borde = 58 + 14 * fondo.index(2)
                    if borde - 31 <= x < borde - 11 and y == 118:
                        accion = ("right", "up")
            previo = sala, x, y
            f = juego.step(accion)
            ruta.append(f.mask)
            if f.end != "playing":
                return bytes(ruta) if f.end == "level_complete" else None
    return None


def nuevo_palacio(motor, red, seed):
    original = (MOTOR / RECURSO).read_bytes()
    detalle = ModeloTeselas(RAIZ / "resultados/teselas_nivel1.npz")
    for intento in range(16):
        mapa = sintetizar(motor, red, detalle, original, seed, intento)
        ruta = ruta_palacio(motor, mapa, seed)
        if ruta:
            return mapa, ruta
    raise RuntimeError("No se encontró un recorrido hasta la salida para esta semilla.")
