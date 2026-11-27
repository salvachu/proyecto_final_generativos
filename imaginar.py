"""Genera un GIF de una secuencia de prueba o prueba tus propios controles."""
import argparse
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from modelo import cargar

BOTONES = ("izquierda", "derecha", "arriba", "abajo", "shift")


def controles(texto):
    nombres = set(texto.lower().split("+"))
    if nombres == {"quieto"}:
        return np.zeros(5, dtype=np.uint8)
    if (nombres - set(BOTONES) or {"izquierda", "derecha"} <= nombres
            or {"arriba", "abajo"} <= nombres):
        raise ValueError(f"Controles incompatibles: {texto}")
    return np.array([b in nombres for b in BOTONES], dtype=np.uint8)


def fuente(tamano):
    for nombre in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(nombre, tamano)
        except OSError:
            pass
    return ImageFont.load_default(size=tamano)


def paneles(imagenes, titulos, seed, inicio, paso, accion):
    ancho, alto = 320, 200
    margen, hueco = 18, 12
    lienzo = Image.new("RGB", (margen*2 + ancho*len(titulos) + hueco*(len(titulos)-1), 313), "#101822")
    dibujo = ImageDraw.Draw(lienzo)
    dibujo.text((margen, 11), f"Prince of Persia   /   Nivel 1", fill="#f2e7d0", font=fuente(20))
    for idx, (im, titulo) in enumerate(zip(imagenes, titulos)):
        x = margen + idx*(ancho+hueco)
        dibujo.text((x, 47), titulo, fill="#b9c7d2", font=fuente(15))
        lienzo.paste(Image.fromarray(im).resize((ancho, alto), Image.Resampling.NEAREST), (x, 71))
    texto = f"Partida {seed}   ·   Inicio {inicio}   ·   Paso +{paso}   ·   {accion}"
    dibujo.text((margen, 284), texto, fill="#e1be82", font=fuente(15))
    return lienzo


@torch.inference_mode()
def animar(red, archivo, inicio, horizonte, ruta, accion=None):
    with np.load(archivo) as data:
        rgb, botones = data["rgb"], data["botones"]
    real = accion is None
    if inicio < 1 or inicio >= len(rgb) or horizonte < 1 or (real and inicio+horizonte >= len(rgb)):
        raise ValueError("El inicio y el horizonte deben caber en el episodio para la comparación.")
    ant, actual = torch.from_numpy(rgb[inicio-1:inicio+1].copy()).permute(0, 3, 1, 2).float().div(255).split(1)
    semilla = archivo.stem
    salida = []
    for k in range(horizonte+1):
        etiqueta = "Contexto observado"
        if k:
            accion_k = botones[inicio+k-1] if real else accion
            ant, actual = actual, red(ant, actual, torch.from_numpy(accion_k).float()[None])
            etiqueta = " + ".join(b for b, v in zip(BOTONES, accion_k) if v) or "Sin pulsar"
        pred = actual[0].permute(1, 2, 0).mul(255).round().byte().numpy()
        imagenes = [rgb[inicio+k], pred, rgb[inicio]] if real else [rgb[inicio], pred]
        titulos = ["Juego grabado", "Predicción del modelo", "Repetir la última imagen"] if real else [
            "Punto de partida", "Futuro imaginado"]
        salida.append(paneles(imagenes, titulos, semilla, inicio, k, etiqueta))
    ruta.parent.mkdir(exist_ok=True, parents=True)
    salida[0].save(ruta, save_all=True, append_images=salida[1:], loop=0,
                   duration=[650]+[160]*(horizonte-1)+[950], disposal=2)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--datos", type=Path, default=Path("datos/compactos"))
    p.add_argument("--modelo", default="resultados/mundo.pt")
    p.add_argument("--semilla", type=int, default=47090)
    p.add_argument("--inicio", type=int, default=145)
    p.add_argument("--pasos", type=int, default=12)
    p.add_argument("--accion", help="P. ej., derecha+arriba o quieto. Si se omite, usa los controles reales.")
    p.add_argument("--salida", type=Path, default=Path("resultados/comparacion.gif"))
    args = p.parse_args()
    torch.set_num_threads(2)
    animar(cargar(args.modelo, "cpu"), args.datos / f"{args.semilla}.npz",
           args.inicio, args.pasos, args.salida, controles(args.accion) if args.accion else None)


if __name__ == "__main__":
    main()
