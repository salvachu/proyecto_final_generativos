# Un world model del primer nivel de Prince of Persia

La red recibe dos imágenes consecutivas del juego y los botones que se van a pulsar. Predice la siguiente imagen. Al encadenar predicciones puede imaginar varios pasos usando sus propias imágenes y una secuencia de controles. La partida real sirve para comprobar después cuánto acertó.

**Para ver el resultado**, abre `resultados/comparacion.gif`. La columna izquierda muestra la partida, la central muestra la predicción y la derecha mantiene congelado el punto de partida. `resultados/cambio_de_sala.gif` muestra un caso difícil. La memoria en `output/pdf/Memoria.pdf` recoge el método y los resultados.

## Demostración interactiva

Con el entorno de PyTorch activo, ejecuta `python interfaz.py` y mantén **D**. A la izquierda verás el juego real y a la derecha la imagen que calculó la red para la misma acción. Suelta la tecla para congelar ambas pantallas. Puedes usar A/D para moverte, W/S para subir o bajar, Shift para agarrarte y espacio para avanzar sin pulsar ningún botón del juego. Los botones de la ventana avanzan un paso por clic.

**Predecir un paso** usa las dos últimas imágenes reales cada vez. **Encadenar predicciones** parte de la escena actual y sigue usando los dibujos del modelo. Reiniciar te devuelve al mismo punto del primer nivel para que puedas comparar las dos modalidades. En otro equipo, instala las dependencias y prepara el motor siguiendo las instrucciones de este documento. Después ejecuta `python interfaz.py`.

## Qué contiene la entrega

| Archivo o carpeta | Contenido |
| --- | --- |
| `resultados/mundo.pt` | Pesos de la red entrenada, listos para la inferencia en CPU o GPU. |
| `datos/compactos/` | 120 episodios RGB reducidos, los cinco botones de cada paso y el índice con la partición, la semilla y el identificador del HDF5 original. |
| `resultados/metricas.json` y `resultados/entrenamiento.json` | Resultados de prueba y evolución de la pérdida de validación. |
| `imaginar.py`, `modelo.py`, `entrenar.py`, `evaluar.py` | Generación de imágenes, definición de la red, entrenamiento y evaluación. |
| `capturar.py`, `preparar.py`, `motor_windows.py` y `sdlpop-recorder/` | Recogida reproducible de datos con el grabador del profesor y preparación de las imágenes. |

Las capturas originales están en `datos/nivel1/` en el equipo de trabajo. Para compartirlas se ha preparado el archivo independiente `Grabaciones_nivel1.tar.xz`. Se puede extraer desde la raíz del proyecto con `tar -xf Grabaciones_nivel1.tar.xz`. El ZIP principal incluye todos los datos que consume la red.

## Datos y método

Se grabaron **120 episodios**, con **36.703 acciones** y **36.823 imágenes** a 320 × 200. El grabador validó los 120 HDF5. Se recorrieron cinco salas del nivel 1 (1, 2, 3, 6 y 9). Treinta episodios llegaron a la salida, treinta terminaron con la muerte del príncipe y sesenta se cortaron al alcanzar su límite de pasos. La simulación suma unos 51 minutos.

El controlador de captura combina tramos aleatorios de teclas sostenidas con recorridos guiados por la posición del príncipe. El recorrido a la salida pasa por el guardia y activa la placa que abre la puerta. La política de recogida toma las decisiones durante esas partidas. Las coordenadas, la salud y el número de sala quedan fuera de las entradas de la red.

| Partición por episodios | Partidas | Acciones |
| --- | ---: | ---: |
| Entrenamiento | 86 | 26.677 |
| Validación | 17 | 5.086 |
| Prueba | 17 | 4.940 |

La división se fijó por semillas antes de entrenar. Cada ventana pertenece a una sola partida. Hay rutas y tramos iniciales compartidos entre semillas porque todos empiezan en el mismo nivel y usan la misma familia de controladores. La prueba mide la generalización a partidas nuevas de esta distribución.

`preparar.py` reduce el RGB a 80 × 50 promediando bloques de 4 × 4. La red convolucional tiene 63.558 parámetros. El codificador procesa la última imagen, su diferencia con la anterior y dos coordenadas fijas de pantalla. En la representación comprimida incorpora izquierda, derecha, arriba, abajo y Shift. El decodificador aprende un desplazamiento por píxel y una corrección de color. En conjunto pueden mover al personaje y reconstruir parte del fondo que deja a la vista.

Se entrenó con AdamW durante 3.600 actualizaciones de 24 ventanas. La pérdida absoluta da peso 16 a los píxeles cuyo cambio máximo entre canales supera 0,04 en escala de 0 a 1. Tras las primeras 1.200 actualizaciones se alternaron objetivos a uno y dos pasos. La pérdida de validación a cuatro pasos seleccionó el checkpoint de la actualización 3.300.

## Evaluación

Las 4.736 ventanas de prueba disponen de dos imágenes de contexto y doce acciones posteriores. A partir de ahí el modelo se alimenta de sus propias predicciones. Se evalúa el error absoluto medio RGB en escala de 0 a 255, donde un valor menor es mejor. Las ventanas se solapan dentro de cada partida.

| Horizonte | Modelo | Última imagen congelada | Modelo con controles de otra ventana | Modelo en píxeles cambiados | Imagen congelada en píxeles cambiados |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 paso | 0,784 | 1,060 | 0,806 | 32,55 | 58,86 |
| 4 pasos | 2,351 | 2,577 | 2,451 | 49,97 | 68,94 |
| 12 pasos | 5,990 | 5,681 | 6,075 | 61,41 | 68,89 |

Los píxeles cambiados son aquellos cuyo valor real en al menos un canal difiere en más de 10 unidades respecto de la última imagen de contexto. A un paso representan solo el 1,79 % de la pantalla. Medirlos aparte evita que el fondo oculte los errores de movimiento. Las acciones permutadas se obtienen intercambiando secuencias completas entre ventanas con una semilla fija.

A un paso el error global baja un **26,0 %** frente a congelar la imagen. A cuatro pasos la ventaja se reduce al **8,8 %**. A doce pasos el error global es un **5,4 % mayor** que el de congelar la imagen. Con los controles correctos se obtiene un error menor que con los controles intercambiados en los tres horizontes. Las predicciones largas acumulan desenfoque y los cambios de sala pueden dejar visible el fondo anterior.

## Ejecutar con los pesos entregados

La ejecución se verificó con Python 3.13 de 64 bits y PyTorch 2.8. En una terminal abierta en la raíz del proyecto, usa un entorno virtual. En Windows puedes activarlo desde CMD con `.venv\Scripts\activate.bat`. En Bash, usa `source .venv/bin/activate` después del primer comando.

```text
python -m venv .venv
```

Con el entorno activo, estos comandos regeneran la demo y las métricas. La CPU es suficiente para producir un GIF.

```text
python -m pip install -r requirements.txt
python imaginar.py
python evaluar.py
```

Para imaginar doce pasos manteniendo izquierda desde el mismo punto de partida, usa este comando. El GIF conserva el fotograma de partida junto al futuro calculado para esas teclas.

```text
python imaginar.py --semilla 47090 --inicio 145 --pasos 12 --accion izquierda --salida resultados/izquierda.gif
```

Para repetir el entrenamiento con los datos compactos, ejecuta `python entrenar.py --salida resultados_nuevos`. Puedes evaluar esos pesos con `python evaluar.py --modelo resultados_nuevos/mundo.pt --salida resultados_nuevos/metricas.json`. La GPU se selecciona automáticamente cuando PyTorch detecta CUDA. Los últimos decimales pueden variar entre dispositivos.

## Volver a grabar desde el juego

Instala en el entorno el paquete del profesor con `python -m pip install -e ./sdlpop-recorder`. Para grabar jugando con el teclado, instala el extra de juego con `python -m pip install -e "./sdlpop-recorder[play]"`.

En **Windows x64**, con Git instalado, estos comandos compilan la revisión de SDLPoP y el parche de captura utilizados en el proyecto. Si el motor ya existe, el script ejecuta la prueba del grabador.

```text
python -m pip install ziglang==0.14.1
python motor_windows.py
```

En **Ubuntu**, el README de `sdlpop-recorder/` detalla las dependencias de compilación y SDL. Una vez instaladas, desde la raíz del proyecto ejecuta `python -m sdlpop_recorder setup` y `python -m sdlpop_recorder doctor`.

Para repetir la recogida en una carpeta nueva, validarla y volver a reducir las imágenes, ejecuta lo siguiente. Los nombres de archivo de los episodios son UUID generados por el grabador.

```text
python capturar.py --output datos/repeticion
python preparar.py --origen datos/repeticion --salida datos/compactos_nuevos
```

## Referencias

- Ha y Schmidhuber (2018) describen el aprendizaje de una representación predictiva de un entorno a partir de trayectorias. Este proyecto toma esa formulación y aprende directamente en el espacio de imágenes. [World Models](https://arxiv.org/abs/1803.10122) · [Experimentos de los autores en GitHub](https://github.com/hardmaru/WorldModelsExperiments)
- Oh y colaboradores (2015) estudian la predicción de imágenes futuras de videojuegos condicionada por las acciones. Es la referencia para plantear las entradas y evaluar predicciones encadenadas. [Action-Conditional Video Prediction using Deep Networks in Atari Games](https://arxiv.org/abs/1507.08750)
- Las capturas proceden del port SDLPoP y del grabador distribuido en clase. La revisión del motor es `f7be2e939375d369d26e1d10bcdd5ca74d3002a2`. [NagyD/SDLPoP en GitHub](https://github.com/NagyD/SDLPoP/tree/f7be2e939375d369d26e1d10bcdd5ca74d3002a2)
- Para explorar la ruta del guardia se consultó la descripción del salto cronometrado de eien86. La política implementada en `capturar.py` decide a partir del estado del grabador. [Descripción del recorrido del nivel 1](https://tasvideos.org/7134S)
