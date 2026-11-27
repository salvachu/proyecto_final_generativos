from __future__ import annotations

import bisect
import json
import operator
import re
from pathlib import Path

import h5py
import numpy as np

from .engine import BUTTONS, NATIVE_ENDS, REVISION, RGB_SHAPE, STATE_KEYS, TIMEBASE
from .recording import CUTS, SCHEMA


def _episode(manifest):
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(meta, dict) or not re.fullmatch(r"[0-9a-f]{32}", manifest.stem):
        raise ValueError("Manifiesto no válido.")
    if meta.get("schema") != SCHEMA or meta.get("episode_id") != manifest.stem:
        raise ValueError("Esquema o identificador de episodio incompatible.")
    if (type(meta.get("steps")) is not int or meta["steps"] < 1
            or type(meta.get("sim_ticks")) is not int or meta["sim_ticks"] < meta["steps"]
            or meta.get("timebase") != TIMEBASE or meta.get("engine_revision") != REVISION
            or not re.fullmatch(r"[0-9a-f]{64}", str(meta.get("settings_sha256", "")))
            or meta.get("end_reason") not in (*NATIVE_ENDS, *CUTS)
            or not isinstance(meta.get("group"), str) or not meta["group"].strip()
            or type(meta.get("level")) is not int or not 1 <= meta["level"] <= 14
            or type(meta.get("seed")) is not int or not 0 <= meta["seed"] < 2**31):
        raise ValueError("Metadatos de episodio no válidos.")
    path = manifest.parent.parent / "episodes" / (manifest.stem + ".h5")
    if not path.is_file():
        raise FileNotFoundError(f"Falta {path.name}.")
    return meta, path


def validate(root):
    root = Path(root)
    errors = []
    seen = set()
    paired_files = set()
    valid = steps = ticks = 0
    for manifest in sorted(root.rglob("manifests/*.json")):
        try:
            meta, path = _episode(manifest)
            paired_files.add(path)
            if meta["episode_id"] in seen:
                raise ValueError("Identificador duplicado.")
            seen.add(meta["episode_id"])
            n = meta["steps"]
            with h5py.File(path, "r") as f:
                if any(f.attrs.get(key) != val for key, val in meta.items()):
                    raise ValueError("Los metadatos HDF5 y JSON difieren.")
                rgb, state = f["states/rgb"], f["states/aux"]
                buttons, dt = f["actions/buttons"], f["transitions/dt_ticks"]
                for dataset, shape, dtype in (
                    (rgb, (n + 1, *RGB_SHAPE), "uint8"),
                    (state, (n + 1, len(STATE_KEYS)), "int16"),
                    (buttons, (n, len(BUTTONS)), "uint8"), (dt, (n,), "uint16"),
                ):
                    if dataset.shape != shape or dataset.dtype != dtype:
                        raise ValueError(f"Forma o tipo incorrecto en {dataset.name}.")
                if (json.loads(buttons.attrs["columns"]) != list(BUTTONS)
                        or json.loads(state.attrs["columns"]) != list(STATE_KEYS)):
                    raise ValueError("Orden de columnas incompatible.")
                actions, durations, states = buttons[:], dt[:], state[:]
                if (np.any(actions > 1) or np.any(actions[:, 0] & actions[:, 1])
                        or np.any(actions[:, 2] & actions[:, 3])):
                    raise ValueError("Botones no válidos.")
                if (np.any(durations == 0) or int(durations.sum()) != meta["sim_ticks"]
                        or np.any(states[:, 0] != meta["level"])):
                    raise ValueError("Duración o nivel incoherente.")
                for start in range(0, n + 1, 16):
                    rgb[start:start + 16]  # Triggers HDF5 chunk checksums.
            valid += 1
            steps += n
            ticks += meta["sim_ticks"]
        except (ValueError, KeyError, OSError, TypeError) as exc:
            errors.append(f"{manifest}: {exc}")
    for path in sorted(set(root.rglob("episodes/*.h5")) - paired_files):
        errors.append(f"{path}: falta un manifiesto válido.")
    for path in sorted(root.rglob("*.partial")):
        if path.parent.name in ("episodes", "manifests"):
            errors.append(f"{path}: archivo incompleto o grabación en curso.")
    if not valid and not errors:
        errors.append(f"{root}: no se encontraron episodios.")
    return {"valid": valid, "steps": steps, "simulated_seconds": ticks / TIMEBASE,
            "invalid": len(errors), "errors": errors}


class SequenceDataset:
    def __init__(self, root, sequence_length=8, *, include_state=False):
        self.length = operator.index(sequence_length)
        if self.length < 1:
            raise ValueError("sequence_length debe ser positivo.")
        self.include_state = include_state
        self.episodes = []
        self.ends = []
        self.episode_ids = []
        total = 0
        seen = set()
        manifests = sorted(Path(root).rglob("manifests/*.json"))
        if not manifests:
            raise FileNotFoundError(f"No hay episodios publicados en {root}.")
        for manifest in manifests:
            meta, path = _episode(manifest)
            if meta["episode_id"] in seen:
                raise ValueError(f"Episodio duplicado: {manifest.stem}")
            seen.add(meta["episode_id"])
            self.episode_ids.append(meta["episode_id"])
            count = meta["steps"] - self.length + 1
            if count > 0:
                total += count
                self.episodes.append((meta, path))
                self.ends.append(total)

    def __len__(self):
        return self.ends[-1] if self.ends else 0

    def __getitem__(self, index):
        index = operator.index(index)
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        episode = bisect.bisect_right(self.ends, index)
        start = index - (self.ends[episode - 1] if episode else 0)
        stop = start + self.length
        meta, path = self.episodes[episode]
        terminated = np.zeros(self.length, dtype=bool)
        truncated = np.zeros_like(terminated)
        if stop == meta["steps"]:
            flags = terminated if meta["end_reason"] in NATIVE_ENDS else truncated
            flags[-1] = True
        with h5py.File(path, "r") as f:
            sample = {
                "episode_id": meta["episode_id"], "start": start,
                "observations": {"rgb": f["states/rgb"][start:stop + 1]},
                "actions": {"buttons": f["actions/buttons"][start:stop]},
                "transitions": {"dt_ticks": f["transitions/dt_ticks"][start:stop],
                                "terminated": terminated, "truncated": truncated},
            }
            if self.include_state:
                states = f["states/aux"][start:stop + 1]
                sample["privileged"] = {key: states[:, i] for i, key in enumerate(STATE_KEYS)}
        return sample
