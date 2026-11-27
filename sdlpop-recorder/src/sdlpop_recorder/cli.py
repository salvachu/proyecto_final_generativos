from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from .dataset import SequenceDataset, validate
from .engine import DEFAULT_ENGINE, prepare_engine
from .human import play
from .recording import Recorder


def _read(root, length):
    dataset = SequenceDataset(root, sequence_length=length)
    print(f"{len(dataset)} ventanas de {len(dataset.episode_ids)} episodios")
    if len(dataset):
        sample = dataset[0]
        rgb = sample["observations"]["rgb"]
        print("RGB", rgb.shape, rgb.dtype)
        print("Botones", sample["actions"]["buttons"].shape)
        print("Duraciones", sample["transitions"]["dt_ticks"].shape)


def _doctor(engine):
    with tempfile.TemporaryDirectory() as root:
        with Recorder(root, "doctor", engine=engine, level=2, seed=42, max_steps=24) as rec:
            for _ in range(24):
                rec.step(("right",))
        result = validate(root)
        sample = SequenceDataset(root, 24, include_state=True)[0]
        buttons = sample["actions"]["buttons"]
        positions = sample["privileged"]["x"]
        rgb = sample["observations"]["rgb"]
        passed = (result["valid"] == 1 and not result["errors"] and buttons[:, 1].all()
                  and int(buttons.sum()) == 24 and positions.min() != positions.max()
                  and (rgb[0] != rgb[-1]).any() and rec.end_reason == "step_limit")
        if not passed:
            raise RuntimeError(f"Falló la comprobación de captura: {result}")
        print(f"Motor OK · 24 acciones · {rgb.shape[0]} imágenes RGB de 320 × 200 · HDF5 válido")


def main():
    parser = argparse.ArgumentParser(prog="sdlpop-recorder", description="Grabación de Prince of Persia")
    subs = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("setup", "Preparar el motor"), ("doctor", "Comprobar el motor y el dataset"),
                            ("play", "Jugar y grabar")):
        sub = subs.add_parser(name, help=help_text)
        sub.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    play_parser = subs.choices["play"]
    play_parser.add_argument("--output", type=Path, required=True)
    play_parser.add_argument("--group", required=True)
    play_parser.add_argument("--level", type=int, choices=range(1, 15), default=1)
    play_parser.add_argument("--seed", type=int)
    play_parser.add_argument("--max-steps", type=int)
    play_parser.add_argument("--scale", type=int, default=2)
    check = subs.add_parser("validate", help="Verificar episodios y contar tiempo simulado")
    check.add_argument("dataset", type=Path)
    reader = subs.add_parser("read", help="Leer una ventana de entrenamiento")
    reader.add_argument("dataset", type=Path)
    reader.add_argument("--length", type=int, default=8)
    args = parser.parse_args()
    try:
        if args.command == "setup":
            print(prepare_engine(args.engine))
        elif args.command == "doctor":
            _doctor(args.engine)
        elif args.command == "play":
            play(args.output, args.group, engine=args.engine, level=args.level, seed=args.seed,
                 max_steps=args.max_steps, scale=args.scale)
        elif args.command == "validate":
            result = validate(args.dataset)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return int(bool(result["errors"]))
        elif args.command == "read":
            _read(args.dataset, args.length)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0
