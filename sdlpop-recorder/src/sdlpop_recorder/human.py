from __future__ import annotations

import time

from .engine import TIMEBASE
from .recording import Recorder

END_LABELS = {
    "death": "El príncipe murió", "level_complete": "Nivel completado",
    "time_expired": "Tiempo agotado", "victory": "Victoria", "step_limit": "Límite alcanzado",
}


def _episode(pg, screen, font, recording, size):
    keys = {
        pg.K_LEFT: "left", pg.K_a: "left", pg.K_RIGHT: "right", pg.K_d: "right",
        pg.K_UP: "up", pg.K_w: "up", pg.K_DOWN: "down", pg.K_s: "down",
        pg.K_LSHIFT: "shift", pg.K_RSHIFT: "shift",
    }
    held, pressed = set(), set()
    focused = bool(pg.key.get_focused())
    manual_pause = False
    frame = recording.frame
    deadline = time.monotonic() + frame.next_ticks / TIMEBASE
    clock = pg.time.Clock()
    dirty = True
    while True:
        for event in pg.event.get():
            if event.type == pg.QUIT:
                return "quit"
            if event.type in (pg.WINDOWFOCUSLOST, pg.WINDOWMINIMIZED, pg.WINDOWFOCUSGAINED):
                focused = event.type == pg.WINDOWFOCUSGAINED
                held.clear()
                pressed.clear()
                deadline = time.monotonic() + frame.next_ticks / TIMEBASE
                dirty = True
            elif event.type == pg.WINDOWEXPOSED:
                dirty = True
            elif event.type == pg.KEYUP:
                held.discard(event.key)
            elif event.type == pg.KEYDOWN and not getattr(event, "repeat", False):
                if event.key == pg.K_F10:
                    return "quit"
                if not focused:
                    continue
                if event.key == pg.K_F9:
                    return "restart"
                if event.key in (pg.K_F8, pg.K_ESCAPE, pg.K_RETURN):
                    if recording.end_reason:
                        if event.key in (pg.K_F8, pg.K_RETURN):
                            return "continue"
                        continue
                    manual_pause = not manual_pause
                    held.clear()
                    pressed.clear()
                    deadline = time.monotonic() + frame.next_ticks / TIMEBASE
                    dirty = True
                elif not manual_pause and not recording.end_reason and event.key in keys:
                    held.add(event.key)
                    pressed.add(event.key)

        if focused and not manual_pause and not recording.end_reason and time.monotonic() >= deadline:
            buttons = {keys[key] for key in held | pressed}
            pressed.clear()
            frame = recording.step(buttons)
            deadline = max(deadline + frame.next_ticks / TIMEBASE, time.monotonic())
            dirty = True
        if dirty:
            image = pg.image.frombuffer(frame.rgb.tobytes(), (320, 200), "RGB")
            screen.blit(pg.transform.scale(image, size), (0, 0))
            if recording.end_reason:
                status = f"{END_LABELS[recording.end_reason]}  |  F8 continuar  ·  F9 repetir  ·  F10 salir"
            elif manual_pause or not focused:
                status = "En pausa  |  F8 continuar" if manual_pause else "En pausa  |  Vuelve a la ventana"
            else:
                status = (f"Nivel {recording.game.level}  ·  {recording.steps} pasos  |  "
                          "F8 pausa  ·  F9 reiniciar  ·  F10 salir")
            pg.draw.rect(screen, (27, 27, 32), (0, size[1], size[0], 32))
            label = font.render(status, True, (241, 240, 230))
            if label.get_width() + 16 > size[0]:
                width = size[0] - 16
                label = pg.transform.smoothscale(label, (width, max(1, label.get_height() * width // label.get_width())))
            screen.blit(label, (8, size[1] + (32 - label.get_height()) // 2))
            pg.display.flip()
            dirty = False
        clock.tick(120)


def play(output, group, *, engine, level, seed, max_steps, scale):
    try:
        import pygame as pg
    except ImportError as exc:
        raise RuntimeError('Instala la interfaz con python -m pip install -e ".[play]".') from exc
    if not 1 <= scale <= 5:
        raise ValueError("La escala de la ventana debe ser de 1 a 5.")
    size = (320 * scale, 200 * scale)
    pg.display.init()
    pg.font.init()
    try:
        screen = pg.display.set_mode((size[0], size[1] + 32))
        pg.display.set_caption("Prince of Persia · Recorder")
        font = pg.font.Font(None, 23)
        while True:
            screen.fill((27, 27, 32))
            label = font.render(f"Abriendo nivel {level}…", True, (241, 240, 230))
            screen.blit(label, label.get_rect(center=screen.get_rect().center))
            pg.display.flip()
            with Recorder(output, group, engine=engine, level=level,
                          seed=seed, max_steps=max_steps) as recording:
                command = _episode(pg, screen, font, recording, size)
                recording.finish("restart" if command == "restart" else "closed")
            if recording.steps:
                print(f"{recording.path}  |  {recording.steps} pasos  |  {recording.end_reason}", flush=True)
            if command == "quit":
                return
            if command == "continue" and recording.end_reason == "level_complete":
                level = min(14, level + 1)
    finally:
        pg.quit()
