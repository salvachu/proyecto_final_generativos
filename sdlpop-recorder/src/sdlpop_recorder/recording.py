from __future__ import annotations

import hashlib
import json
import operator
import os
import uuid
from pathlib import Path

import h5py
import numpy as np

from .engine import BUTTONS, DEFAULT_ENGINE, NATIVE_ENDS, REVISION, RGB_SHAPE, STATE_KEYS, TIMEBASE, Game

SCHEMA = "sdlpop-1"
CUTS = ("closed", "restart", "step_limit", "interrupted")


def _series(file, name, shape, dtype, chunk, **kwargs):
    return file.create_dataset(name, shape=(0, *shape), maxshape=(None, *shape),
                               chunks=(chunk, *shape), dtype=dtype, fletcher32=True, **kwargs)


def _append(dataset, index, value):
    dataset.resize(index + 1, axis=0)
    dataset[index] = value


class Recorder:
    def __init__(self, output, group, *, engine=DEFAULT_ENGINE, level=1, seed=None, max_steps=None):
        self.root = Path(output)
        self.group = group
        if not isinstance(group, str) or not group.strip() or "\x00" in group:
            raise ValueError("Se requiere un identificador de grupo.")
        self.max_steps = None if max_steps is None else operator.index(max_steps)
        if self.max_steps is not None and self.max_steps < 1:
            raise ValueError("max_steps debe ser un entero positivo.")
        self.game = Game(engine, level, seed)
        self.episode_id = uuid.uuid4().hex
        self.steps = 0
        self.sim_ticks = 0
        self.end_reason = None
        self.file = None
        self.path = self.root / "episodes" / (self.episode_id + ".h5")
        self.working = self.path.with_suffix(".h5.partial")
        self.manifest = self.root / "manifests" / (self.episode_id + ".json")

    @property
    def frame(self):
        return self.game.frame

    def __enter__(self):
        if self.frame is not None or self.end_reason is not None:
            raise RuntimeError("Crea un Recorder para cada episodio.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.game.__enter__()
        try:
            settings = hashlib.sha256((self.game.directory / "SDLPoP.ini").read_bytes()).hexdigest()
            self.file = h5py.File(self.working, "x")
            self.rgb = _series(self.file, "states/rgb", RGB_SHAPE, "u1", 1,
                               compression="gzip", compression_opts=1)
            self.state = _series(self.file, "states/aux", (len(STATE_KEYS),), "<i2", 128)
            self.buttons = _series(self.file, "actions/buttons", (len(BUTTONS),), "u1", 128)
            self.durations = _series(self.file, "transitions/dt_ticks", (), "<u2", 128)
            self.state.attrs["columns"] = json.dumps(STATE_KEYS)
            self.buttons.attrs["columns"] = json.dumps(BUTTONS)
            _append(self.rgb, 0, self.frame.rgb)
            _append(self.state, 0, self.frame.state)
            self.file.attrs.update(schema=SCHEMA, episode_id=self.episode_id, group=self.group,
                                   level=self.game.level, seed=self.game.seed, timebase=TIMEBASE,
                                   engine_revision=REVISION, settings_sha256=settings)
        except BaseException:
            if self.file is not None:
                self.file.close()
            self.game.close()
            raise
        return self

    def step(self, buttons=()):
        if self.file is None or self.end_reason is not None:
            raise RuntimeError("El episodio no está activo.")
        frame = self.game.step(buttons)
        try:
            _append(self.rgb, frame.index, frame.rgb)
            _append(self.state, frame.index, frame.state)
            _append(self.buttons, self.steps, [(frame.mask >> i) & 1 for i in range(len(BUTTONS))])
            _append(self.durations, self.steps, frame.dt_ticks)
            if frame.index % 64 == 0:
                self.file.flush()
        except KeyboardInterrupt:
            # Keep only complete transitions when collection is interrupted.
            try:
                for dataset in (self.rgb, self.state):
                    dataset.resize(self.steps + 1, axis=0)
                for dataset in (self.buttons, self.durations):
                    dataset.resize(self.steps, axis=0)
            except BaseException:
                self.file.close()
                self.file = None
                self.game.close()
                raise
            raise
        except Exception:
            self.file.close()
            self.file = None
            self.game.close()
            raise
        self.steps = frame.index
        self.sim_ticks += frame.dt_ticks
        if frame.end != "playing":
            self.finish(frame.end)
        elif self.steps == self.max_steps:
            self.finish("step_limit")
        return frame

    def finish(self, reason="closed"):
        if self.file is None:
            return
        if reason not in (*NATIVE_ENDS, *CUTS):
            raise ValueError(f"Fin de episodio desconocido: {reason}")
        if reason in NATIVE_ENDS and reason != self.frame.end:
            raise ValueError("El motivo de finalización no coincide con el motor.")
        self.end_reason = reason
        file, self.file = self.file, None
        try:
            with file:
                file.attrs.update(steps=self.steps, sim_ticks=self.sim_ticks, end_reason=reason)
                metadata = {key: val.item() if isinstance(val, np.generic) else val
                            for key, val in file.attrs.items()}
            if self.steps:
                temp_manifest = self.manifest.with_suffix(".json.partial")
                temp_manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
                os.replace(self.working, self.path)
                os.replace(temp_manifest, self.manifest)
            else:
                self.working.unlink()
        finally:
            self.game.close()

    def __exit__(self, exc_type, *_):
        self.finish("interrupted" if exc_type else "closed")
