"""Mundos y exploración persistente. Un paso confirmado equivale a una transacción."""

import hashlib
import sqlite3
import zlib
from pathlib import Path

from PIL import Image

from niveles import Game, botones
from salas import ABAJO, ARRIBA, DERECHA, IZQUIERDA, GeneradorNeuronal, reducir


def avanzar(juego, orden):
    return juego.travel(orden - 32) if orden > 32 else juego.step(botones(orden))


def huella(frame):
    return hashlib.sha256(
        repr((frame.index, frame.state, frame.end)).encode() + frame.rgb.tobytes()
    ).hexdigest()


class Biblioteca:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS mundo(
                id INTEGER PRIMARY KEY, semilla INTEGER NOT NULL, mapa BLOB NOT NULL,
                solucion BLOB NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                firma TEXT NOT NULL, pasos INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS paso(
                mundo INTEGER REFERENCES mundo(id), t INTEGER, botones INTEGER NOT NULL,
                PRIMARY KEY(mundo, t));
            CREATE TABLE IF NOT EXISTS visita(
                mundo INTEGER REFERENCES mundo(id), sala INTEGER, imagen BLOB NOT NULL,
                PRIMARY KEY(mundo, sala));
            CREATE TABLE IF NOT EXISTS activo(unico INTEGER PRIMARY KEY CHECK(unico=1),
                                              mundo INTEGER REFERENCES mundo(id));
            CREATE TABLE IF NOT EXISTS sala_neuronal(
                mundo INTEGER REFERENCES mundo(id), sala INTEGER, origen INTEGER NOT NULL,
                accion INTEGER NOT NULL, paso INTEGER NOT NULL, PRIMARY KEY(mundo,sala));
            CREATE TABLE IF NOT EXISTS edicion(
                mundo INTEGER PRIMARY KEY REFERENCES mundo(id), tipo TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS un_original ON edicion(tipo) WHERE tipo='original';
        """)

    def listar(self):
        return self.db.execute(
            "SELECT id,semilla FROM mundo ORDER BY id DESC"
        ).fetchall()

    def activo(self):
        fila = self.db.execute("SELECT mundo FROM activo").fetchone()
        return fila[0] if fila else None

    def activar(self, mundo):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO activo VALUES(1,?)", (mundo,))

    def visitas(self, mundo):
        filas = self.db.execute(
            "SELECT sala,imagen FROM visita WHERE mundo=?", (mundo,)
        )
        return {sala: imagen for sala, imagen in filas}

    def visitar(self, mundo, frame):
        im = Image.fromarray(frame.rgb).resize((96, 60), Image.Resampling.BOX)
        blob = zlib.compress(im.tobytes(), 1)
        self.db.execute(
            "INSERT OR REPLACE INTO visita VALUES(?,?,?)", (mundo, frame.state[1], blob)
        )
        return blob

    def original(self):
        fila = self.db.execute(
            "SELECT mundo FROM edicion WHERE tipo='original'"
        ).fetchone()
        return fila[0] if fila else None

    def crear(self, seed, mapa, solucion, frame, neuronal=False, tipo=None):
        with self.db:
            cur = self.db.execute(
                "INSERT INTO mundo(semilla,mapa,solucion,firma) VALUES(?,?,?,?)",
                (seed, mapa, solucion, huella(frame)),
            )
            self.visitar(cur.lastrowid, frame)
            if tipo:
                self.db.execute(
                    "INSERT INTO edicion VALUES(?,?)", (cur.lastrowid, tipo)
                )
            if neuronal:
                self.db.execute(
                    "INSERT INTO sala_neuronal VALUES(?,1,0,0,0)", (cur.lastrowid,)
                )
            return cur.lastrowid


class Partida:
    def __init__(self, biblioteca, motor, mundo, reiniciar=False, red=None):
        self.bib = biblioteca
        self.id = mundo
        # Una sola instantánea para el mapa, la revisión, las visitas y las acciones.
        db = biblioteca.db
        db.execute("BEGIN")
        try:
            seed, self.mapa, firma, self.revision, pasos = db.execute(
                "SELECT semilla,mapa,firma,revision,pasos FROM mundo WHERE id=?",
                (mundo,),
            ).fetchone()
            acciones = db.execute(
                "SELECT botones FROM paso WHERE mundo=? ORDER BY t", (mundo,)
            ).fetchall()
            self.vistas = biblioteca.visitas(mundo)
            self.creadas = {
                s
                for (s,) in db.execute(
                    "SELECT sala FROM sala_neuronal WHERE mundo=?", (mundo,)
                )
            }
        finally:
            db.commit()
        motor.cargar(self.mapa)
        self.red = (red or GeneradorNeuronal()) if self.creadas else None
        self.motor, self.seed = motor, seed
        self.historia = bytearray()
        self.ultima_nueva = False
        self.game = Game(motor.ruta, 1, seed)
        self.game.__enter__()
        self.previa = self.game.frame
        try:
            if reiniciar:
                with db:
                    self.comprobar_revision(huella(self.game.frame), 0)
                    db.execute("DELETE FROM paso WHERE mundo=?", (mundo,))
                    self.vistas[self.game.frame.state[1]] = biblioteca.visitar(
                        mundo, self.game.frame
                    )
                self.revision += 1
            else:
                if pasos != len(acciones):
                    raise ValueError("El registro de la partida está incompleto.")
                for (mask,) in acciones:
                    self.previa = self.game.frame
                    avanzar(self.game, mask)
                    self.historia.append(mask)
                if huella(self.game.frame) != firma:
                    raise ValueError(
                        "Este motor no reproduce la partida guardada. Se conserva el guardado."
                    )
            biblioteca.activar(mundo)
        except BaseException:
            self.game.close()
            raise

    def comprobar_revision(self, firma, t):
        cambio = self.bib.db.execute(
            "UPDATE mundo SET revision=revision+1,firma=?,pasos=? WHERE id=? AND revision=?",
            (firma, t, self.id, self.revision),
        )
        if cambio.rowcount != 1:
            raise RuntimeError(
                "Otra ventana actualizó este mundo. Vuelve a abrirlo para continuar."
            )

    def descubrir(self, antes, mask, sala):
        origen = antes.state[1]
        enlaces = self.mapa[1952 + 4 * (origen - 1) : 1956 + 4 * (origen - 1)]
        direccion = (IZQUIERDA, DERECHA, ARRIBA, ABAJO)[enlaces.index(sala)]
        opciones = self.red.candidata(
            self.motor,
            self.mapa,
            sala,
            origen,
            reducir(self.previa.rgb),
            reducir(antes.rgb),
            mask,
            direccion,
            self.seed,
        )
        for mapa, ruta in opciones:
            # SDLPoP lee el nivel al arrancar. Reconstruir el paso actual antes de
            # mostrar la sala permite instalarla sin tocar la partida del usuario.
            juego = Game(self.motor.ruta, 1, self.seed)
            juego.__enter__()
            aceptar = False
            try:
                for accion in self.historia:
                    if juego.frame.end != "playing":
                        break
                    avanzar(juego, accion)
                if juego.frame.state != antes.state or juego.frame.index != antes.index:
                    continue
                previa_reconstruida = juego.frame
                f = juego.step(botones(mask))
                if f.state[1] == sala and f.end == "playing":
                    aceptar = True
                    return juego, mapa, ruta, previa_reconstruida
            finally:
                if not aceptar:
                    juego.close()
        raise RuntimeError(
            "No se pudo enlazar la nueva sala desde este punto. El paso anterior está guardado."
        )

    def viajar(self, sala):
        if sala not in self.vistas:
            raise ValueError("Primero tienes que descubrir esa sala.")
        if self.game.frame.state[1] == sala:
            return self.game.frame
        if self.game.frame.end != "playing":
            raise ValueError("Reintenta desde la entrada para seguir explorando.")
        return self.paso(32 + sala)

    def paso(self, mask):
        if mask > 32 and mask - 32 not in self.vistas:
            raise ValueError("La sala todavía está sin explorar.")
        antes = self.game.frame
        nuevo_juego = None
        try:
            frame = avanzar(self.game, mask)
            sala = frame.state[1]
            self.ultima_nueva = self.red is not None and sala not in self.creadas
            if self.ultima_nueva:
                nuevo_juego, mapa, ruta, antes = self.descubrir(antes, mask, sala)
                frame = nuevo_juego.frame
            with self.bib.db:
                self.comprobar_revision(huella(frame), frame.index)
                if nuevo_juego:
                    self.bib.db.execute(
                        "UPDATE mundo SET mapa=?, solucion=? WHERE id=?",
                        (mapa, ruta, self.id),
                    )
                    self.bib.db.execute(
                        "INSERT INTO sala_neuronal VALUES(?,?,?,?,?)",
                        (self.id, sala, antes.state[1], mask, frame.index),
                    )
                self.bib.db.execute(
                    "INSERT INTO paso VALUES(?,?,?)", (self.id, frame.index, mask)
                )
                mini = self.bib.visitar(self.id, frame)
        except BaseException:
            # Evita seguir desde un estado que no se pudo confirmar en disco.
            self.game.close()
            if nuevo_juego:
                nuevo_juego.close()
            raise
        if nuevo_juego:
            self.game.close()
            self.game = nuevo_juego
            self.mapa = mapa
            self.creadas.add(sala)
        self.previa = antes
        self.historia.append(mask)
        self.revision += 1
        self.vistas[frame.state[1]] = mini
        return frame
