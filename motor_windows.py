"""Compila SDLPoP con el parche del grabador en Windows x64."""
import argparse
import hashlib
import importlib.resources
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from sdlpop_recorder.engine import REPOSITORY, REVISION

LIBRERIAS = [
    ("SDL", "SDL2", "2.30.12", "1ca980f9964fb44cf94be235c9818fa1dc8e3f76b08096d751b2d689e5e37d02"),
    ("SDL_image", "SDL2_image", "2.8.4", "ae2a3e85bee51086184d3f72a47086c61f2acec86984b33f8bb28dab23e5a0d0"),
]


def ejecutar(*comando, **kwargs):
    subprocess.run(comando, check=True, **kwargs)


def compilar(destino):
    destino = destino.resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        ejecutar(sys.executable, "-m", "sdlpop_recorder", "doctor", "--engine", str(destino))
        return
    with tempfile.TemporaryDirectory(dir=destino.parent) as tmp:
        tmp = Path(tmp)
        repo = tmp / "fuente"
        ejecutar("git", "init", "-q", str(repo))
        ejecutar("git", "-C", str(repo), "config", "core.autocrlf", "false")
        ejecutar("git", "-C", str(repo), "fetch", "-q", "--depth=1", REPOSITORY, REVISION)
        ejecutar("git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD")
        for nombre in ("capture.patch", "travel.patch", "camera.patch"):
            parche = importlib.resources.files("sdlpop_recorder").joinpath("native", nombre)
            ejecutar("git", "-C", str(repo), "apply", "-", input=parche.read_bytes())
        include = tmp / "include"
        cabeceras = include / "SDL2"
        cabeceras.mkdir(parents=True)
        libs = []
        salida = tmp / "motor"
        salida.mkdir()
        for proyecto, nombre, version, sha in LIBRERIAS:
            url = (f"https://github.com/libsdl-org/{proyecto}/releases/download/"
                   f"release-{version}/{nombre}-devel-{version}-VC.zip")
            archivo = tmp / f"{nombre}.zip"
            urllib.request.urlretrieve(url, archivo)
            if hashlib.sha256(archivo.read_bytes()).hexdigest() != sha:
                raise ValueError(f"El SHA-256 de {nombre} difiere del esperado.")
            with zipfile.ZipFile(archivo) as z:
                z.extractall(tmp)
            paquete = tmp / f"{nombre}-{version}"
            for h in (paquete / "include").glob("*.h"):
                shutil.copy2(h, cabeceras)
            libs.append(str(paquete / "lib" / "x64" / f"{nombre}.lib"))
            shutil.copy2(paquete / "lib" / "x64" / f"{nombre}.dll", salida)
        src = repo / "src"
        ejecutar(sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu",
                 "-std=gnu99", "-O2", "-DSDL_MAIN_HANDLED", "-Wno-implicit-function-declaration",
                 f"-I{include}", *(p.name for p in sorted(src.glob("*.c"))), *libs,
                 "-lshell32", "-luser32", "-o", str(salida / "prince.exe"), cwd=src)
        shutil.copytree(repo / "data", salida / "data")
        for nombre in ("SDLPoP.ini", "COPYING"):
            shutil.copy2(repo / nombre, salida)
        ejecutar(sys.executable, "-m", "sdlpop_recorder", "doctor", "--engine", str(salida))
        salida.rename(destino)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--destino", type=Path, default=Path("runtime/SDLPoP"))
    compilar(p.parse_args().destino)
