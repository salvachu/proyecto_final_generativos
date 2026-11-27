# Mazmorras de Persia

El propio world model genera el terreno de las salas mientras juegas. **Nuevo nivel** crea la entrada. Cuando cruzas por primera vez a otra sala, el modelo genera sus plataformas usando lo que acabas de ver, el mapa vecino y los controles del príncipe. El juego guarda la sala para las visitas posteriores. Para probar esta versión después de una actualización, abre la aplicación de nuevo y pulsa **Nuevo nivel**.

## Abrir y jugar

En Windows x64, descarga la [aplicación para Windows](https://github.com/salvachu/proyecto_final_generativos/releases/download/v1.0.0/World_model_Prince_of_Persia.zip), **extrae todo el ZIP** y abre **Abrir_demo.cmd**. Incluye la aplicación de escritorio y el motor. También puedes ejecutar directamente **Aplicacion/Mazmorras.exe**. Los datos personales de juego se crean al jugar.

- **D / A** para correr a derecha o izquierda. También funcionan las flechas.
- **W** para saltar. Para trepar una terraza, acércate al borde, mira hacia él y mantén **W + Shift**. **S** permite agacharse o bajar.
- **Jugar** o una tecla de movimiento inicia el tiempo del juego. **P** pausa. **Espacio** reanuda sin pulsar ningún botón del príncipe.
- **Nuevo nivel** crea otro mundo. El desplegable superior permite retomar cualquiera de los anteriores.
- Pulsa una sala descubierta en el mapa para ver la última imagen guardada de tu visita. Al cerrar y volver a abrir, el juego continúa desde el último paso confirmado.
- **Reintentar desde la entrada** empieza un intento nuevo en la misma geometría y conserva las salas descubiertas. Para salir, pisa la placa del último pasillo, sitúate frente a las escaleras y pulsa **W** una vez abierta la puerta.

Para demostrar la memoria, entra en otra sala, pulsa **P**, cierra y vuelve a abrir. También puedes crear un segundo mundo y volver al primero desde la lista.

## Cómo se construye el nivel

1. **Una red con dos salidas.** Se amplió la CNN visual entrenada con las partidas del primer nivel. El checkpoint completo conserva la salida RGB y añade una salida que predice columnas de terreno. Las dos comparten el codificador de las últimas imágenes y la acción. Durante el ajuste espacial se congeló el predictor visual y se entrenó la nueva salida. La aplicación ejecuta en CPU la rama espacial exportada a ONNX.
2. **Qué aprende.** El entrenamiento utiliza las capturas de la partición original de entrenamiento y recorridos de SDLPoP en 96 mundos producidos por el anterior generador estadístico. Este último proporciona ejemplos durante el entrenamiento. El decodificador predice diez columnas de tres casillas, de izquierda a derecha. Cada elección utiliza el contexto visual, las teclas, la dirección de entrada, el tipo de sala, la geometría vecina y las columnas ya generadas. La primera sala utiliza una observación inicial de referencia y una semilla propia.
3. **Qué se fija con reglas.** El esqueleto del mundo reserva de cinco a ocho salas, un camino principal, un sótano y una salida. El modelo muestrea el relieve y el aspecto del interior. Se aseguran los bordes entre salas, el descansillo y la conexión entre placa y puerta. Al principio, las zonas desconocidas contienen pasillos provisionales para el motor. La interfaz los sustituye por el terreno neuronal antes de mostrar la primera imagen de cada nueva sala.
4. **Jugabilidad y memoria.** Antes de aceptar una ampliación, SDLPoP debe completar una ruta por el mapa disponible, con pasillos provisionales en las zonas futuras. El programa vuelve a comprobar la ruta con cada ampliación. SQLite guarda la geometría, qué salas ha generado la red, la sala de origen, la acción, el paso y la última vista. La aplicación recupera las acciones con el motor y comprueba la imagen y el estado al reabrir. Puede haber una breve pausa al descubrir una sala, especialmente en partidas largas. Los mundos creados con la versión anterior siguen disponibles.

## Comprobaciones

La validación espacial usó 222 ejemplos de 12 mundos docentes reservados. La entropía cruzada por columna fue 1,079 frente a 2,022 de una referencia basada en frecuencias globales. Es una medida del ajuste a esos ejemplos. La jugabilidad se comprobó por separado directamente con el motor.

Se jugaron ocho mundos neuronales con semillas 82000 a 82007. Los ocho tuvieron entradas distintas y llegaron a la salida. En cada uno se cruzó dos veces la misma frontera, se cerró y se reabrió la partida y se verificó la identidad del estado y de las salas conocidas. También se comprobó por separado el descenso y regreso desde el sótano en la semilla 82000.

- [Entrenamiento y validación espacial](resultados/ajuste_espacial.json)
- [Partidas de prueba del modelo neuronal](resultados/pruebas_salas.json)
- [Memoria del generador neuronal](output/pdf/Memoria_generacion.pdf)
- [Experimento inicial de predicción visual](PREDICCION.md)
- [Grabaciones originales de las 120 partidas](https://github.com/salvachu/proyecto_final_generativos/releases/download/v1.0.0/Grabaciones_nivel1.tar.xz)

## Ejecutar desde el código

Con Python 3.13, Tk y el motor disponible en `runtime/SDLPoP`, estos comandos arrancan la aplicación y repiten las pruebas. En Windows el motor ya viene compilado en el ZIP. En Linux se puede compilar con el procedimiento de `sdlpop-recorder/README.md` en una carpeta nueva, y usar el resultado como `runtime/SDLPoP`.

```text
python -m pip install numpy Pillow h5py onnxruntime
python explorar.py
python comprobar_red.py
```

| Archivo | Función |
| --- | --- |
| `modelo.py` y `salas.py` | Red compartida, salida de terreno, muestreo y escritura de las salas. |
| `entrenar_salas.py` y `niveles.py` | Entrenamiento espacial, generador docente y validación de recorridos con SDLPoP. |
| `partidas.py` | Biblioteca de mundos, guardado por paso y recuperación verificada. |
| `explorar.py` | Interfaz jugable y mapa de las visitas. |
| `comprobar_red.py` | Pruebas reproducibles de generación, regreso y memoria. |

Para reproducir el ajuste, instala `requirements.txt` y ejecuta `python entrenar_salas.py` desde la raíz. El checkpoint conjunto es `resultados/mundo_espacial.pt`; la aplicación carga `resultados/mundo_salas.onnx`. Los resultados de `comprobar_mundos.py` y `generacion.json` corresponden al generador estadístico de la versión anterior.

En Windows, el guardado está en `%LOCALAPPDATA%\PrinceOfPersiaMundos\mundos.sqlite3`. En Linux se usa `$XDG_DATA_HOME/prince-of-persia-mundos` o `~/.local/share/prince-of-persia-mundos`. Para llevar tus partidas a otro equipo, cierra la aplicación y copia la base de datos.

El ZIP contiene el código del proyecto, la aplicación para Windows, el motor con su código fuente de compilación, el grabador de clase y el material de la primera fase. La compilación de la interfaz se hace con PyInstaller en modo directorio, con `explorar.py` como entrada y `sdlpop-recorder/src` en la ruta de módulos.

## Referencias

- Snodgrass y Ontañón investigan cómo incorporar el movimiento del jugador en la generación de niveles. En este proyecto la comprobación de movimiento se realiza directamente con el motor. [Player Movement Models for Video Game Level Generation, IJCAI 2017](https://www.ijcai.org/proceedings/2017/105)
- El formato de salas y la simulación física proceden de SDLPoP, con el parche de captura distribuido en clase. [Código del motor, revisión utilizada](https://github.com/NagyD/SDLPoP/tree/f7be2e939375d369d26e1d10bcdd5ca74d3002a2)
