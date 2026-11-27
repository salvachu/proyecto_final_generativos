# SDLPoP Recorder

Juega Prince of Persia y graba episodios para entrenar un world model. Cada acción avanza un paso del motor y queda asociada a las imágenes RGB anterior y posterior.

## Instalación en Ubuntu

Descomprime el ZIP y abre una terminal en la carpeta `sdlpop-recorder`. Si necesitas crear el entorno Conda `gm`, ejecuta estos dos comandos.

```bash
conda create -n gm python=3.12 pip -y
conda env config vars set PYTHONNOUSERSITE=1 -n gm
```

Activa `gm` e instala el grabador y el motor. Puedes usar un entorno existente con Python 3.10 o superior.

```bash
conda activate gm
sudo apt-get update
sudo apt-get install -y build-essential git pkg-config libsdl2-dev libsdl2-image-dev
python -m pip install -e ".[play]"
python -m sdlpop_recorder setup
python -m sdlpop_recorder doctor
```

`setup` descarga y compila SDLPoP en `runtime/SDLPoP`. Conserva esa carpeta para jugar. `doctor` corre el nivel 2, mueve al personaje y comprueba que se pueden releer 24 acciones y 25 imágenes. Para trabajar únicamente con grabaciones basta con `python -m pip install -e .`.

## Jugar y grabar

```bash
python -m sdlpop_recorder play --level 1 --group grupo01 --output data/grupo01
```

Cambia `grupo01` por tu identificador. Elige el nivel inicial con `--level` (1 a 14 en la numeración interna de SDLPoP). Se puede volver a usar la misma carpeta de salida. Cada partida recibe un identificador nuevo.

| Tecla | Acción |
|---|---|
| Izquierda / derecha, o A / D | Girar o correr. Con Shift, dar un paso corto. |
| Arriba, o W | Saltar, trepar o bloquear con la espada. Combínala con una dirección para saltar hacia ese lado. |
| Abajo, o S | Agacharse, bajar o guardar la espada. |
| Shift | Agarrarse de un borde al caer, recoger un objeto o atacar con la espada. |
| F8 o Esc | Pausar o reanudar la partida. |
| F9 | Guardar el episodio y volver a empezar el nivel. |
| F10 o cerrar la ventana | Guardar el episodio y salir. |

La grabación se pausa al perder el foco y continúa al volver a la ventana. Una pausa manual se mantiene hasta que la reanudes. Las pausas y la barra de controles quedan fuera de las muestras.

El episodio se guarda al morir, completar el nivel, ganar o agotar el reloj del juego. Pulsa F8 o Enter para jugar de nuevo. Tras completar un nivel se abre el siguiente como una partida nueva, con los valores iniciales de salud y tiempo. El grabador admite partidas de duración libre o un límite como `--max-steps 1200`. Con `--seed 42` cada episodio se inicia con la misma semilla. Al omitirla, se elige una nueva.

## Validar y compartir

```bash
python -m sdlpop_recorder validate data/grupo01
python -m sdlpop_recorder read data/grupo01 --length 8
```

Comprueba que `valid` sea mayor que cero y que `invalid` sea cero. `simulated_seconds` suma el tiempo de juego de los episodios válidos. Para compartirlos, copia la carpeta `grupo01` completa, con `episodes/<id>.h5` y `manifests/<id>.json`. El lector también acepta la carpeta `data` con varios grupos.

## Leer secuencias

```python
from sdlpop_recorder import SequenceDataset

dataset = SequenceDataset("data/grupo01", sequence_length=8)
sample = dataset[0]
rgb = sample["observations"]["rgb"]        # (9, 200, 320, 3), uint8
buttons = sample["actions"]["buttons"]     # (8, 5), uint8
dt = sample["transitions"]["dt_ticks"] / 60
inputs, targets = rgb[:-1], rgb[1:]
```

`buttons[t]` contiene cinco valores binarios en el orden `left, right, up, down, shift`. Pueden activarse varios a la vez. Por ejemplo, `[0, 1, 1, 0, 0]` corresponde a derecha y arriba. La misma tecla tiene efectos distintos según el estado del personaje. Cada par `inputs[t], buttons[t]` corresponde a `targets[t]`.

Una ventana de longitud `L` contiene `L` acciones y `L+1` imágenes de un mismo episodio. El ritmo habitual es de 12 pasos por segundo con la espada guardada y 10 con la espada desenvainada. `dt[t]` es la duración simulada del paso en segundos. `terminated` marca un final del juego o del nivel y `truncated` marca un corte por cierre, reinicio, interrupción o límite de pasos.

Con `SequenceDataset("data/grupo01", sequence_length=8, include_state=True)`, `sample["privileged"]` incluye nivel, sala, coordenadas internas del personaje, dirección, salud, fotograma de animación y estado de la espada. Las imágenes conservan el HUD del juego. La sesión de captura se ejecuta en silencio.

## Grabar desde Python

```python
from sdlpop_recorder import Recorder

with Recorder("data/prueba", group="prueba", level=2, seed=42) as game:
    initial_rgb = game.frame.rgb
    for _ in range(30):
        frame = game.step(["right"])
        if game.end_reason:
            break
```

`step([])` avanza un paso sin pulsar botones. También se pueden indicar acciones como `{"right": 1, "shift": 1}`. El HDF5 guarda las imágenes y acciones de forma incremental. Los episodios aparecen en el lector al cerrarse.

La licencia del código está en `LICENSE`. El motor y los recursos del juego proceden de [NagyD/SDLPoP](https://github.com/NagyD/SDLPoP).
