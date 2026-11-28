# Mazmorras de Persia

Juega el primer nivel original de *Prince of Persia* o explora una variante creada por el world model. Ambas opciones usan SDLPoP para el movimiento, el combate y las puertas. Cada mundo tiene su propia partida y su propio mapa explorado.

## Abrir y jugar

En la carpeta del proyecto en Windows, ejecuta lo siguiente en PowerShell.

```powershell
.\Abrir_demo.cmd
```

En una instalación nueva, usa Python 3.13 con Tk y crea el entorno una sola vez. El repositorio incluye el motor compilado para Windows x64 y los pesos necesarios para jugar.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy Pillow h5py onnxruntime
.\Abrir_demo.cmd
```

- **Nivel 1 original** abre o reanuda el mapa original. **Generar nivel** prepara otra variante y la abre en cuanto SDLPoP comprueba un recorrido hasta la salida. Puedes retomar cada partida desde la lista.
- **A / D** o las flechas mueven al príncipe. **W** salta y **W + Shift** permite agarrarse a un borde. **S** sirve para agacharse o bajar. Frente a la espada, mantén **Shift** para recogerla. En combate, **Shift** ataca y **W** bloquea. Ante la puerta abierta, pulsa **W** para salir.
- **P** pausa o reanuda. **Espacio** reanuda en reposo. La sala dorada indica dónde estás. Pasa el cursor sobre otra sala descubierta para ver el destino y haz clic para viajar. El príncipe aparece en la sala elegida con su inventario y su vida. Pulsa **A** o **D** para seguir jugando.
- **Reintentar desde la entrada** empieza otro intento y conserva las salas descubiertas. Cerrar la ventana guarda el último paso confirmado. En Windows, la biblioteca está en `%LOCALAPPDATA%\PrinceOfPersiaMundos\mundos.sqlite3`.

## Qué genera el modelo

La variante recupera la búsqueda de la espada hacia el oeste, los guardias, las trampas, las rutas a distintas alturas y la salida del nivel original. Se construye al crear el mundo y se descubre al recorrerlo. La semilla determina qué tramos se amplían y el punto de caída inicial y dónde aparece la espada dentro de su sala.

1. La red espacial ONNX propone las diez columnas de cada galería nueva. Recibe imágenes reales del motor en una sala de referencia, las columnas de la vecina, la dirección y una acción de avance. Las galerías pueden extender los accesos al guardia o los dos pisos del sector occidental. En el acceso al guardia, el relieve propuesto sirve para situar un pozo con pinchos entre dos zonas de carrera y aterrizaje.
2. Una segunda red, entrenada para reconstruir casillas ocultas de las salas del nivel 1, muestrea suelo, pilares, escombros, antorchas y partes del techo según las casillas próximas. El entrenamiento final usa las 21 salas del plano original. En una prueba previa con cuatro salas reservadas, la entropía cruzada fue 1,018.
3. El ensamblado conserva la estructura de las salas de misión, los enlaces entre plantas y los mecanismos originales. El método combina terreno aprendido y diseño original. Antes de ofrecer cada mundo, un jugador automático debe llegar al evento nativo de fin de nivel con las teclas normales.
4. SQLite guarda las acciones y los viajes. Al abrir una partida, la aplicación reproduce el historial y comprueba la imagen y el estado del motor. Se pueden retomar también los mundos de las versiones anteriores.

## Reproducir las pruebas

```powershell
.\.venv\Scripts\python.exe comprobar_palacio.py
```

La prueba recorre el original y ocho mapas diferentes, verifica los enlaces bidireccionales y comprueba que solo se pueda viajar a salas conocidas desde la partida. También prueba la reanudación y, en encuentros aislados con el motor, la recogida de la espada y su uso frente a un guardia.

Para reproducir el entrenamiento, instala `requirements.txt`. Ejecuta `entrenar_salas.py` para la red espacial y `entrenar_teselas.py` para el modelo de detalle. Los pesos de juego están en `resultados/mundo_salas.onnx` y `resultados/teselas_nivel1.npz`. En Linux compila el motor con el parche actualizado siguiendo `sdlpop-recorder/README.md` en una carpeta nueva.

La primera versión generaba pasillos y un sótano al descubrirlos. Sus experimentos y entregables siguen disponibles en la [memoria de generación](output/pdf/Memoria_generacion.pdf), la [evaluación visual](PREDICCION.md) y la [entrega histórica v1.0.0](https://github.com/salvachu/proyecto_final_generativos/releases/tag/v1.0.0).

## Referencias

- Snodgrass y Ontañón investigan cómo incorporar el movimiento del jugador en la generación de niveles. En este proyecto la comprobación de movimiento se realiza directamente con el motor. [Player Movement Models for Video Game Level Generation, IJCAI 2017](https://www.ijcai.org/proceedings/2017/105)
- El formato de salas y la simulación física proceden de SDLPoP, con el parche de captura distribuido en clase. [Código del motor, revisión utilizada](https://github.com/NagyD/SDLPoP/tree/f7be2e939375d369d26e1d10bcdd5ca74d3002a2)
