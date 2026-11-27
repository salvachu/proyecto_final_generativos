"""Modelo visual de dinámica y lectura de episodios compactos."""
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def bloque(entrada, salida, stride=1):
    return nn.Sequential(nn.Conv2d(entrada, salida, 3, stride, 1), nn.LeakyReLU(0.1),
                         nn.Conv2d(salida, salida, 3, padding=1), nn.LeakyReLU(0.1))


class Mundo(nn.Module):
    """Dos imágenes RGB y cinco botones -> siguiente imagen RGB."""
    def __init__(self):
        super().__init__()
        self.local = bloque(8, 16)
        self.medio = bloque(16, 24, 2)
        self.fondo = bloque(24, 40, 2)
        self.control = nn.Linear(5, 40)
        self.fusion = bloque(64, 24)
        self.detalle = bloque(40, 16)
        self.salida = nn.Conv2d(16, 6, 3, padding=1)
        nn.init.normal_(self.salida.weight, std=0.002)
        nn.init.zeros_(self.salida.bias)
        y, x = torch.meshgrid(torch.linspace(-1, 1, 50), torch.linspace(-1, 1, 80), indexing="ij")
        self.register_buffer("coords", torch.stack([x, y])[None])

    def codificar(self, anterior, actual, botones):
        coords = self.coords.expand(len(actual), -1, -1, -1)
        local = self.local(torch.cat([actual, actual - anterior, coords], 1))
        medio = self.medio(local)
        fondo = self.fondo(medio) + self.control(botones)[:, :, None, None]
        return local, medio, fondo

    def forward(self, anterior, actual, botones):
        local, medio, fondo = self.codificar(anterior, actual, botones)
        coords = self.coords.expand(len(actual), -1, -1, -1)
        medio = self.fusion(torch.cat([F.interpolate(fondo, size=medio.shape[-2:]), medio], 1))
        detalle = self.detalle(torch.cat([F.interpolate(medio, size=local.shape[-2:]), local], 1))
        salida = self.salida(detalle)
        escala = self.coords.new_tensor([2/79, 2/49])[None, :, None, None]
        rejilla = (coords + 6 * salida[:, :2].tanh() * escala).permute(0, 2, 3, 1)
        movido = F.grid_sample(actual, rejilla, padding_mode="border", align_corners=True)
        correccion = salida[:, 2:5].tanh() * salida[:, 5:6].sigmoid()
        return (movido + correccion).clamp(0, 1)


class CabezaTerreno(nn.Module):
    """Distribución de la próxima columna según el contexto y el prefijo generado."""
    def __init__(self):
        super().__init__()
        self.ficha = nn.Embedding(25, 8)
        self.posicion = nn.Embedding(10, 8)
        self.tipo = nn.Embedding(4, 8)
        self.direccion = nn.Embedding(6, 8)
        self.escena = nn.Sequential(nn.LayerNorm(320), nn.Linear(320, 40), nn.Tanh())
        self.columnas = nn.Sequential(nn.Linear(168, 112), nn.LeakyReLU(.1),
                                     nn.Linear(112, 80), nn.LeakyReLU(.1), nn.Linear(80, 24))

    def forward(self, latente, vecina, rol, direccion, prefijo):
        situacion = torch.cat([self.escena(latente), self.ficha(vecina).flatten(1),
                               self.tipo(rol), self.direccion(direccion)], 1)
        pasado = F.pad(prefijo, (3, 0), value=24)
        indices = torch.arange(10, device=prefijo.device)
        entradas = [situacion[:, None].expand(-1, 10, -1),
                    self.posicion(indices)[None].expand(len(vecina), -1, -1)]
        entradas.extend(self.ficha(pasado[:, i:i+10]) for i in range(3))
        return self.columnas(torch.cat(entradas, -1))


class MundoEspacial(Mundo):
    """Un codificador visual condicionado por acciones y dos salidas, RGB y mapa."""
    def __init__(self):
        super().__init__()
        self.terreno = CabezaTerreno()

    def contexto_visual(self, anterior, actual, botones):
        fondo = self.codificar(anterior, actual, botones)[2]
        # El fondo mide 13 x 20. Cuatro regiones a lo ancho por dos a lo alto.
        return F.avg_pool2d(fondo[:, :, :12], (6, 5)).flatten(1)

    def predecir_sala(self, anterior, actual, botones, vecina, rol, direccion, prefijo):
        return self.terreno(self.contexto_visual(anterior, actual, botones),
                            vecina, rol, direccion, prefijo)


class Partidas:
    def __init__(self, carpeta, conjunto, device):
        indice = json.loads((Path(carpeta) / "indice.json").read_text("utf-8"))
        self.episodios = [ep for ep in indice["episodios"] if ep["conjunto"] == conjunto]
        imagenes, acciones = [], []
        self.limites = []
        offset = 0
        for ep in self.episodios:
            with np.load(Path(carpeta) / f"{ep['semilla']}.npz") as archivo:
                rgb, botones = archivo["rgb"], archivo["botones"]
            assert len(rgb) == len(botones) + 1
            imagenes.append(rgb)
            # Un elemento de relleno alinea los índices de acciones e imágenes.
            acciones.append(np.pad(botones, ((0, 1), (0, 0))))
            self.limites.append((offset, offset + len(rgb)))
            offset += len(rgb)
        self.rgb = torch.from_numpy(np.concatenate(imagenes)).permute(0, 3, 1, 2).to(device)
        self.acciones = torch.from_numpy(np.concatenate(acciones)).float().to(device)

    def inicios(self, horizonte, salto=1):
        return np.concatenate([np.arange(a+1, b-horizonte, salto) for a, b in self.limites])

    def imagen(self, indices):
        return self.rgb[indices].float() / 255


def cargar(ruta, device):
    peso = torch.load(ruta, map_location=device, weights_only=True)
    red = Mundo().to(device)
    red.load_state_dict(peso["modelo"])
    return red.eval()
