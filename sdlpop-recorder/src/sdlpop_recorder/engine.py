from __future__ import annotations

import operator
import os
import queue
import secrets
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import numpy as np

REVISION = "f7be2e939375d369d26e1d10bcdd5ca74d3002a2"
REPOSITORY = "https://github.com/NagyD/SDLPoP.git"
DEFAULT_ENGINE = Path("runtime/SDLPoP")
BUTTONS = ("left", "right", "up", "down", "shift")
STATE_KEYS = ("level", "room", "x", "y", "direction", "hp", "animation_frame", "sword")
RGB_SHAPE = (200, 320, 3)
NATIVE_ENDS = ("death", "level_complete", "time_expired", "victory")
TIMEBASE = 60


def prepare_engine(directory=DEFAULT_ENGINE):
    directory = Path(directory).resolve()
    for executable in ("git", "make", "pkg-config"):
        if not shutil.which(executable):
            raise RuntimeError(f"Falta {executable}. Instala las dependencias de compilación del README.")
    subprocess.run(["pkg-config", "--exists", "--print-errors", "sdl2", "SDL2_image"], check=True)
    directory.parent.mkdir(parents=True, exist_ok=True)

    def build(root):
        git = ["git", "-C", str(root)]
        revision = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
        if revision != REVISION or not (root / ".git").exists():
            raise ValueError(f"La carpeta {root} debe contener la revisión {REVISION} de SDLPoP.")
        native = files("sdlpop_recorder").joinpath("native")
        travel = native.joinpath("travel.patch").read_bytes()
        def applied(patch):
            result = subprocess.run([*git, "apply", "--reverse", "--check", "-"],
                                    input=patch, capture_output=True)
            return result.returncode == 0
        camera = native.joinpath("camera.patch").read_bytes()
        if not applied(camera):
            if not applied(travel):
                capture = native.joinpath("capture.patch").read_bytes()
                if not applied(capture):
                    subprocess.run([*git, "apply", "-"], input=capture, check=True)
                subprocess.run([*git, "apply", "-"], input=travel, check=True)
            subprocess.run([*git, "apply", "-"], input=camera, check=True)
        subprocess.run(["make", "-C", str(root / "src"), "-j", str(min(4, os.cpu_count() or 1))],
                       check=True)

    if directory.exists():
        build(directory)
    else:
        with tempfile.TemporaryDirectory(dir=directory.parent) as temp:
            source = Path(temp) / "SDLPoP"
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            git = ["git", "-C", str(source)]
            subprocess.run([*git, "remote", "add", "origin", REPOSITORY], check=True)
            subprocess.run([*git, "fetch", "-q", "--depth=1", "origin", REVISION], check=True)
            subprocess.run([*git, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
            build(source)
            source.rename(directory)
    return directory


def action_mask(names):
    if isinstance(names, str):
        names = (names,)
    mask = 0
    for name in names:
        if name not in BUTTONS:
            raise ValueError(f"Acción desconocida {name!r}. Acciones válidas: {', '.join(BUTTONS)}.")
        if isinstance(names, Mapping):
            if names[name] not in (0, 1):
                raise ValueError(f"{name} debe valer 0 o 1.")
            if not names[name]:
                continue
        mask |= 1 << BUTTONS.index(name)
    # The native keyboard gives priority to left and up on opposite inputs.
    if mask & 1:
        mask &= ~2
    if mask & 4:
        mask &= ~8
    return mask


@dataclass(frozen=True)
class Frame:
    index: int
    mask: int
    dt_ticks: int
    next_ticks: int
    end: str
    state: tuple[int, ...]
    rgb: np.ndarray
    camera_room: int | None = None


def _read_frames(pipe, messages):
    try:
        while True:
            line = pipe.readline(256)
            if not line:
                raise EOFError("El motor cerró el canal de captura.")
            fields = line.decode("ascii").split()
            state_end = 6 + len(STATE_KEYS)
            if len(fields) not in (state_end, state_end + 1) or fields[0] != "POP1":
                raise ValueError("El motor no reconoce el protocolo de captura. Ejecuta setup.")
            step, mask, dt, next_dt = map(int, fields[1:5])
            end = fields[5]
            if end not in ("playing", *NATIVE_ENDS) or next_dt <= 0:
                raise ValueError("Estado del motor no válido.")
            state = tuple(map(int, fields[6:state_end]))
            camera = int(fields[state_end]) if len(fields) > state_end else None
            payload = pipe.read(200 * 320 * 3)
            if len(payload) != 200 * 320 * 3:
                raise EOFError("Llegó una imagen incompleta.")
            rgb = np.frombuffer(payload, np.uint8).reshape(RGB_SHAPE)
            messages.put(Frame(step, mask, dt, next_dt, end, state, rgb, camera))
            if end != "playing":
                return
    except (OSError, ValueError, EOFError) as error:
        messages.put(error)


class Game:
    def __init__(self, engine=DEFAULT_ENGINE, level=1, seed=None):
        self.directory = Path(engine).resolve()
        self.level = operator.index(level)
        self.seed = secrets.randbelow(2**31) if seed is None else operator.index(seed)
        if not 1 <= self.level <= 14 or not 0 <= self.seed < 2**31:
            raise ValueError("El nivel debe ser de 1 a 14 y la semilla de 0 a 2147483647.")
        self.process = None
        self.frame = None

    def __enter__(self):
        if self.process is not None:
            raise RuntimeError("El motor ya está en ejecución.")
        binary = self.directory / ("prince.exe" if os.name == "nt" else "prince")
        if not binary.is_file():
            raise FileNotFoundError(f"Falta {binary}. Ejecuta python -m sdlpop_recorder setup.")
        environment = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy",
                           SDL_RENDER_DRIVER="software")
        self.messages = queue.Queue()
        self.process = subprocess.Popen(
            [str(binary), "--recorder", str(self.level), f"seed={self.seed}", "mute", "--recorder-camera"],
            cwd=self.directory, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.reader = threading.Thread(target=_read_frames, args=(self.process.stdout, self.messages),
                                       daemon=True)
        self.reader.start()
        try:
            self.frame = self._receive(0, 0)
            if self.frame.state[0] != self.level or self.frame.end != "playing" or self.frame.dt_ticks != 0:
                raise RuntimeError("El motor no devolvió el estado inicial solicitado.")
        except BaseException:
            self.close()
            raise
        return self

    def _receive(self, index, mask):
        try:
            result = self.messages.get(timeout=15)
        except queue.Empty as error:
            raise RuntimeError("El motor no respondió en 15 s. Comprueba el motor con doctor.") from error
        if isinstance(result, Exception):
            raise RuntimeError(f"Error de captura: {result}") from result
        if result.index != index or result.mask != mask or (index and result.dt_ticks != self.frame.next_ticks):
            raise RuntimeError("Se perdió la sincronización entre la acción y la imagen.")
        return result

    def step(self, buttons=()):
        return self._command(action_mask(buttons))

    def travel(self, room, *, legacy=False):
        room = operator.index(room)
        if not 1 <= room <= 24:
            raise ValueError("La sala debe estar entre 1 y 24.")
        if not legacy and self.frame.camera_room is None:
            raise RuntimeError("Actualiza el motor para usar el viaje entre salas.")
        return self._command((32 if legacy else 64) + room)

    def restore_camera(self):
        return self._command(64)

    def _command(self, mask):
        if self.process is None or self.frame.end != "playing":
            raise RuntimeError("El episodio no está activo.")
        self.process.stdin.write(bytes([mask]))
        self.process.stdin.flush()
        self.frame = self._receive(self.frame.index + 1, mask)
        return self.frame

    def close(self):
        proc = self.process
        if proc is None:
            return
        try:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            self.reader.join(timeout=2)
        finally:
            proc.stdout.close()
            self.process = None

    def __exit__(self, *exc):
        self.close()
