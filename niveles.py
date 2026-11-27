"""Generación condicionada por columnas del nivel 1 y certificación con SDLPoP."""

import random
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "sdlpop-recorder" / "src"))
from sdlpop_recorder.engine import BUTTONS, Game

MOTOR = RAIZ / "runtime" / "SDLPoP"
if getattr(sys, "frozen", False):
    MOTOR = Path(sys.executable).resolve().parent.parent / "runtime" / "SDLPoP"
RECURSO = Path("data/LEVELS/res2001.bin")
VACIO, SUELO, PILAR, PLACA, PUERTA, ANTORCHA, MURO = 0, 1, 3, 15, 16, 19, 20
PISABLES = {1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 14, 15, 16, 17, 18, 19, 21, 22}


def botones(mask):
    return [nombre for i, nombre in enumerate(BUTTONS) if mask & (1 << i)]


class ModeloColumnas:
    """Cadena de Markov de columnas de tres casillas con restricciones de paso."""

    def __init__(self, original):
        self.frecuencias = Counter()
        self.pares = defaultdict(Counter)
        self.tramos = []
        # Solo se ajustan estadísticas en salas enlazadas desde la entrada.
        pendientes, vistas = [original[2112]], set()
        while pendientes:
            sala = pendientes.pop()
            if sala in vistas:
                continue
            vistas.add(sala)
            p = 1952 + 4 * (sala - 1)
            pendientes.extend(s for s in original[p : p + 4] if s and s not in vistas)
            offset = (sala - 1) * 30
            anterior, longitud = None, 0
            for col in range(10):
                fichas = tuple(original[offset + fila * 10 + col] & 31 for fila in range(3))
                alto = fichas[1] in PISABLES and fichas[2] == MURO
                bajo = fichas[2] in PISABLES and fichas[1] == VACIO
                if not (alto or bajo):
                    if longitud:
                        self.tramos.append(longitud)
                    anterior, longitud = None, 0
                    continue
                altura = 1 if alto else 2
                piso = fichas[altura]
                piso = piso if piso in (PILAR, ANTORCHA, 14) else SUELO
                # Mantener el relieve y el tipo de techo, y reservar los mecanismos
                # con enlaces para la fase de composición del nivel.
                techo = fichas[0] if fichas[0] in (VACIO, MURO, PILAR, SUELO, ANTORCHA) else VACIO
                token = (altura, techo, piso)
                self.frecuencias[token] += 1
                if anterior is not None:
                    self.pares[anterior][token] += 1
                if anterior and anterior[0] != altura:
                    self.tramos.append(longitud)
                    longitud = 0
                longitud += 1
                anterior = token
            if longitud:
                self.tramos.append(longitud)

    def generar(self, seed):
        rng = random.Random(seed)
        n = rng.randint(4, 7)
        ancho = n * 10
        alturas = [1] * 5
        alto = 2
        # Alternar terrazas y galerías. Los anchos proceden de las rachas del
        # nivel original, con espacio mínimo para que quepan carrera y trepa.
        while len(alturas) < ancho - 10:
            largo = min(9, max(3, rng.choice(self.tramos) + rng.randint(1, 3)))
            alturas.extend([alto] * largo)
            alto = 3 - alto
        alturas = alturas[: ancho - 10] + [2] * 10
        for borde in range(10, ancho, 10):
            alturas[borde] = alturas[borde - 1]
        data = bytearray(2305)
        data[2119:2143] = bytes([30]) * 24  # salas sin guardia
        data[2048] = n + 1
        data[2112:2115] = bytes([1, 3, 255])
        anterior = None
        for x, h in enumerate(alturas):
            opciones = [t for t in self.frecuencias if t[0] == h]
            cond = self.pares.get(anterior, {})
            pesos = [cond.get(t, 0) + 0.05 * self.frecuencias[t] for t in opciones]
            anterior = rng.choices(opciones, weights=pesos)[0]
            _, techo, piso = anterior
            sala, col = divmod(x, 10)
            base = sala * 30 + col
            cerca_borde = any(v != h for v in alturas[max(0, x - 2) : x + 3])
            data[base] = VACIO if cerca_borde or x < 5 else techo
            data[base + 10] = piso if h == 1 else VACIO
            data[base + 20] = MURO if h == 1 else piso
            if piso == SUELO:
                data[720 + base + 10 * h] = rng.randrange(2)
        # Un tramo de losas sueltas sobre una galería se puede recorrer por
        # arriba o por abajo. Su estado lo simula el motor durante la partida.
        for x in range(5, ancho - 11):
            if alturas[x - 1 : x + 2] == [1, 2, 2]:
                base = (x // 10) * 30 + x % 10
                data[base + 10] = 11
        for i in range(n):
            idx = 1952 + 4 * i
            data[idx : idx + 4] = bytes([i, i + 2 if i < n - 1 else 0, 0, 0])
            data[2049 + i], data[2073 + i] = i + 1, 1
        # Bordes exteriores cerrados. La placa del último pasillo abre su puerta.
        for fila in range(3):
            data[fila * 10] = MURO
            data[(n - 1) * 30 + fila * 10 + 9] = MURO
        base = (n - 1) * 30
        salida = rng.choice((5, 6))
        for col in range(1, 9):
            data[base + 10 + col] = VACIO
        data[base + 21 : base + 24] = bytes([PLACA]) * 3
        data[720 + base + 21 : 720 + base + 24] = bytes([1]) * 3
        data[base + 20 + salida : base + 22 + salida] = bytes([PUERTA, PUERTA + 1])
        data[720 + base + 20 + salida : 720 + base + 22 + salida] = bytes(2)
        data[1440] = 0x80  # evento cero separado del pulsador de salida
        data[1441] = 0x80 | ((n & 3) << 5) | (20 + salida)
        data[1697] = (n & 0x1C) << 3
        # Una galería lateral bajo la entrada permite bajar y regresar.
        # La boca tiene un descansillo de un piso entre los dos saltos.
        data[1952 + 3] = n + 1
        data[1952 + 4 * n + 2] = 1
        data[2049 + n], data[2073 + n] = 1, 2
        for col in (1, 2):
            data[col] = data[10 + col] = VACIO
        data[21], data[22] = VACIO, SUELO
        base = 30 * n
        for col in range(10):
            data[base + col] = SUELO if col in (1, 2) else VACIO
            data[base + 10 + col] = ANTORCHA if col == 4 else SUELO
            data[base + 20 + col] = MURO
        data[base + 16] = 10  # poción roja en el ramal
        data[720 + base + 16] = 0
        for fila in range(3):
            for col in (0, 9):
                data[base + 10 * fila + col] = MURO
        return bytes(data)


class MotorTemporal:
    """Cada sesión escribe su recurso en una copia privada del motor."""

    def __init__(self, origen=MOTOR):
        self.tmp = tempfile.TemporaryDirectory(prefix="persia-mundo-")
        self.ruta = Path(self.tmp.name)
        try:
            shutil.copytree(origen / "data", self.ruta / "data")
            for nombre in ("SDLPoP.ini", "prince.exe", "prince", "SDL2.dll", "SDL2_image.dll"):
                if (origen / nombre).is_file():
                    shutil.copy2(origen / nombre, self.ruta / nombre)
        except BaseException:
            self.cerrar()
            raise

    def cargar(self, nivel):
        (self.ruta / RECURSO).write_bytes(nivel)

    def cerrar(self):
        self.tmp.cleanup()


def certificar(motor, nivel, seed, observar=None):
    """La ruta solo se acepta si termina con el evento nativo level_complete."""
    motor.cargar(nivel)
    n = nivel[2048] - 1
    salida = nivel[(n - 1) * 30 + 20 : n * 30].index(PUERTA)
    meta_x = 58 + 14 * salida + 8
    ruta = bytearray()
    previo, inmovil, trepa = None, 0, 0
    with Game(motor.ruta, 1, seed) as game:
        for _ in range(n * 240):
            _, sala, x, y, _, _, animacion, _ = game.frame.state
            if sala == n and x >= meta_x - 30 and y >= 177:
                mask = 0
                if animacion == 15:
                    if abs(x - meta_x) <= 13:
                        mask = 4
                    else:
                        mask = 18 if x < meta_x else 17
            elif trepa:
                mask = 20
                trepa -= 1
            else:
                mask = 2
            pos = (sala, x, y)
            inmovil = inmovil + 1 if pos == previo else 0
            previo = pos
            if inmovil >= 5 and sala != n and not trepa and y == 181 and animacion == 15:
                trepa = 34
                inmovil = 0
            antes = game.frame
            frame = game.step(botones(mask))
            if observar is not None:
                observar(antes, mask, frame)
            ruta.append(mask)
            if frame.end != "playing":
                return bytes(ruta) if frame.end == "level_complete" else None
    return None


def nuevo_nivel(modelo, motor, seed):
    for intento in range(32):
        variante = (seed + intento * 104729) % (2**31)
        nivel = modelo.generar(variante)
        ruta = certificar(motor, nivel, variante)
        if ruta:
            return variante, nivel, ruta
    raise RuntimeError(
        "El motor no encontró una ruta completa para estas variantes. Prueba otra semilla."
    )
