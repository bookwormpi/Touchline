#!/usr/bin/env python3
"""128x64 swim-training interface for an RGB Matrix Bonnet."""

from datetime import datetime

from PIL import Image, ImageDraw
from navigation import HOME_ITEMS, SETTING_ITEMS
from workout import Phase

# Display colors (RGB)
COLORS = {
    "background": (0, 0, 0),
    "white":      (235, 242, 250),
    "muted":      (115, 130, 148),
    "divider":    (48, 59, 73),
    "freestyle":  (35, 230, 115),
    "backstroke": (55, 135, 255),
    "breaststroke": (255, 75, 75),
    "butterfly":  (255, 195, 35),
    "neutral":    (160, 170, 185),
}

STROKE_COLORS = {
    "FR": "freestyle",
    "BK": "backstroke",
    "BR": "breaststroke",
    "FL": "butterfly",
    "REST": "neutral",
}

# 3x5 bitmap font. Each row is a three-bit pattern.
FONT_3X5 = {
    "0": (0b111, 0b101, 0b101, 0b101, 0b111),
    "1": (0b010, 0b110, 0b010, 0b010, 0b111),
    "2": (0b111, 0b001, 0b111, 0b100, 0b111),
    "3": (0b111, 0b001, 0b111, 0b001, 0b111),
    "4": (0b101, 0b101, 0b111, 0b001, 0b001),
    "5": (0b111, 0b100, 0b111, 0b001, 0b111),
    "6": (0b111, 0b100, 0b111, 0b101, 0b111),
    "7": (0b111, 0b001, 0b010, 0b010, 0b010),
    "8": (0b111, 0b101, 0b111, 0b101, 0b111),
    "9": (0b111, 0b101, 0b111, 0b001, 0b111),
    "A": (0b010, 0b101, 0b111, 0b101, 0b101),
    "B": (0b110, 0b101, 0b110, 0b101, 0b110),
    "C": (0b011, 0b100, 0b100, 0b100, 0b011),
    "D": (0b110, 0b101, 0b101, 0b101, 0b110),
    "E": (0b111, 0b100, 0b110, 0b100, 0b111),
    "F": (0b111, 0b100, 0b110, 0b100, 0b100),
    "G": (0b011, 0b100, 0b101, 0b101, 0b011),
    "H": (0b101, 0b101, 0b111, 0b101, 0b101),
    "I": (0b111, 0b010, 0b010, 0b010, 0b111),
    "J": (0b001, 0b001, 0b001, 0b101, 0b010),
    "K": (0b101, 0b101, 0b110, 0b101, 0b101),
    "L": (0b100, 0b100, 0b100, 0b100, 0b111),
    "M": (0b101, 0b111, 0b111, 0b101, 0b101),
    "N": (0b101, 0b111, 0b111, 0b111, 0b101),
    "O": (0b010, 0b101, 0b101, 0b101, 0b010),
    "P": (0b110, 0b101, 0b110, 0b100, 0b100),
    "Q": (0b010, 0b101, 0b101, 0b111, 0b011),
    "R": (0b110, 0b101, 0b110, 0b101, 0b101),
    "S": (0b011, 0b100, 0b010, 0b001, 0b110),
    "T": (0b111, 0b010, 0b010, 0b010, 0b010),
    "U": (0b101, 0b101, 0b101, 0b101, 0b111),
    "V": (0b101, 0b101, 0b101, 0b101, 0b010),
    "W": (0b101, 0b101, 0b111, 0b111, 0b101),
    "X": (0b101, 0b101, 0b010, 0b101, 0b101),
    "Y": (0b101, 0b101, 0b010, 0b010, 0b010),
    "Z": (0b111, 0b001, 0b010, 0b100, 0b111),
    ":": (0b000, 0b010, 0b000, 0b010, 0b000),
    "/": (0b001, 0b001, 0b010, 0b100, 0b100),
    "-": (0b000, 0b000, 0b111, 0b000, 0b000),
    ".": (0b000, 0b000, 0b000, 0b000, 0b010),
    " ": (0b000, 0b000, 0b000, 0b000, 0b000),
}


def draw_bitmap_text(draw, xy, text, color, scale=1, spacing=1):
    """Draw crisp bitmap text using the built-in 3x5 font."""
    x, y = xy
    start_x = x

    for character in str(text).upper():
        glyph = FONT_3X5.get(character, FONT_3X5[" "])

        for row, bits in enumerate(glyph):
            for column in range(3):
                if bits & (1 << (2 - column)):
                    x0 = x + column * scale
                    y0 = y + row * scale
                    draw.rectangle(
                        (x0, y0, x0 + scale - 1, y0 + scale - 1),
                        fill=color,
                    )

        x += (3 + spacing) * scale

    return x - start_x


def format_elapsed(seconds):
    """Format a signed countdown or elapsed time."""
    negative = seconds < 0
    total = int(abs(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        text = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        text = f"{minutes:02d}:{secs:02d}"
    return ("-" if negative else "") + text


MENU_ITEMS = ("RESUME", "EXTRA REST", "COMPLETE SET", "END WORKOUT")


def draw_workout_view(draw, session, detector, now, clock):
    """Draw the original timer, current-set and four-row history layout."""
    white, muted = COLORS["white"], COLORS["muted"]
    draw.line((87, 0, 87, 63), fill=COLORS["divider"])
    draw.line((0, 32, 86, 32), fill=COLORS["divider"])

    sendoff = session.next_sendoff(now)
    if sendoff is not None:
        due_at, location = sendoff
        remaining = due_at - now
        label = f"GO {location}" if remaining <= 0 else f"NEXT {location}"
        timer = format_elapsed(remaining)
    elif session.phase == Phase.SWIM:
        label, timer = "LAST REP", "--:--"
    elif session.phase == Phase.BREAK:
        label, timer = "SET COMPLETE", "OK NEXT SET"
    else:
        label, timer = "WORKOUT DONE", "OK TO EXIT"

    draw_bitmap_text(draw, (4, 3), label,
                     COLORS["freestyle"] if label.startswith("GO ") else muted)
    draw_bitmap_text(draw, (64, 3), clock.strftime("%H:%M"), white)
    total = format_elapsed(now - session.started_at)
    if len(total) > 9:
        total = "OVERFLOW"
    draw_bitmap_text(draw, (4, 25), f"T {total}", muted)
    if detector.fault:
        draw_bitmap_text(draw, (50, 25), "SENSOR ERR", COLORS["breaststroke"])
    elif session.phase in (Phase.READY, Phase.REST) and detector.occupied is not True:
        draw_bitmap_text(draw, (50, 25), "NO SWIM", COLORS["butterfly"])
    scale = 2 if len(timer) * 8 - 2 <= 80 else 1
    if len(timer) * 4 - 1 > 83:
        timer = "TIME OVERFLOW"
    draw_bitmap_text(draw, (4, 14), timer, white, scale=scale)

    current = session.current_set
    color = COLORS[STROKE_COLORS.get(current.label, "neutral")]
    draw_bitmap_text(draw, (4, 35), "CURRENT SET", muted)
    draw_bitmap_text(draw, (4, 44), f"{current.distance} {current.label[:2]}", color, scale=2)
    draw_bitmap_text(draw, (4, 57), f"DONE {session.completed}/{current.repetitions}", muted)

    for index in range(4):
        y = index * 16
        if index:
            draw.line((89, y, 127, y), fill=COLORS["divider"])
        if index >= len(session.history):
            continue
        distance, stroke, seconds, estimated = session.history[index]
        history_label = f"{distance} {stroke[:2]}" + (" EST" if estimated else "")
        result = "--:--" if seconds is None else format_elapsed(seconds)
        if len(result) > 9:
            result = "OVERFLOW"
        label_x = 89 + max(1, (39 - (len(history_label) * 4 - 1)) // 2)
        time_x = 89 + max(1, (39 - (len(result) * 4 - 1)) // 2)
        draw_bitmap_text(draw, (label_x, y + 2), history_label,
                         COLORS[STROKE_COLORS.get(stroke, "neutral")])
        draw_bitmap_text(draw, (time_x, y + 9), result, white)


def render_frame(session, detector, now, menu_index=None, clock=None, *,
                 navigation=None, settings=None):
    """Render live workout state and sensor health to the 128x64 panel."""
    image = Image.new("RGB", (128, 64), COLORS["background"])
    draw = ImageDraw.Draw(image)
    white, muted = COLORS["white"], COLORS["muted"]
    green, red = COLORS["freestyle"], COLORS["breaststroke"]

    def text(x, y, value, color=white, scale=1):
        draw_bitmap_text(draw, (x, y), value, color, scale=scale)

    if navigation is not None and navigation.screen == "home":
        text(4, 3, "TOUCHLINE", green, 2)
        text(4, 19, "SWIM TRAINER", muted)
        draw.line((4, 28, 123, 28), fill=COLORS["divider"])
        for i, item in enumerate(HOME_ITEMS):
            text(8, 33 + i * 10, ("- " if i == navigation.home_index else "  ") + item,
                 green if i == navigation.home_index else white)
        text(4, 57, "SENSOR ERROR" if detector.fault else "ARROWS MOVE  OK SELECT",
             red if detector.fault else muted)
        return image
    if navigation is not None and navigation.screen == "settings":
        text(4, 3, "SETTINGS", green)
        text(79, 3, "EDIT" if navigation.editing else "SELECT", muted)
        draw.line((4, 12, 123, 12), fill=COLORS["divider"])
        first = max(0, min(navigation.settings_index - 1, len(SETTING_ITEMS) - 3))
        for row, index in enumerate(range(first, first + 3)):
            label, field, _ = SETTING_ITEMS[index]
            value = getattr(settings, field) if field else ""
            if field == "sound":
                value = "ON" if value else "OFF"
            selected = index == navigation.settings_index
            text(4, 18 + row * 11, ("- " if selected else "  ") + label,
                 green if selected else white)
            text(96, 18 + row * 11, str(value), white)
        text(4, 57, "INVALID OR SAVE ERROR" if navigation.error else
             ("ARROWS CHANGE  OK DONE" if navigation.editing else "ARROWS MOVE  OK SELECT"),
             red if navigation.error else muted)
        return image
    if session.phase == Phase.STANDBY:
        text(32, 25, "STANDBY", muted, 2)
        text(24, 50, "OK TO WAKE", muted)
        return image
    if menu_index is not None:
        if menu_index >= len(MENU_ITEMS):
            action = MENU_ITEMS[menu_index - len(MENU_ITEMS)]
            text(4, 3, "CONFIRM ACTION", muted)
            text(4, 20, action, white, 2)
            text(4, 46, "OK CONFIRMS", green)
            text(4, 57, "ARROWS CANCEL", muted)
            return image
        text(4, 3, "WORKOUT MENU", muted)
        for i, item in enumerate(MENU_ITEMS):
            text(8, 15 + i * 10, ("- " if i == menu_index else "  ") + item,
                 green if i == menu_index else white)
        text(4, 57, "SENSOR ERROR" if detector.fault else "ARROWS MOVE  OK SELECT",
             red if detector.fault else muted)
        return image
    if session.phase == Phase.SELECT:
        text(4, 3, "TOUCHLINE", green)
        text(4, 17, "SELECT WORKOUT", muted)
        is_back = navigation is not None and navigation.select_index == len(session.workouts)
        text(4, 29, "BACK" if is_back else session.workout.name, white, 2)
        text(4, 49, "SENSOR ERROR" if detector.fault else
             ("RETURN HOME" if is_back else f"{len(session.workout.sets)} SETS"),
             red if detector.fault else muted)
        text(4, 57, "ARROWS MOVE  OK START", muted)
        return image

    draw_workout_view(draw, session, detector, now, clock or datetime.now())
    return image


def create_matrix():
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    options = RGBMatrixOptions()
    options.rows = 64
    options.cols = 128
    options.chain_length = 1
    options.parallel = 1

    # Adafruit RGB Matrix Bonnet
    options.hardware_mapping = "adafruit-hat"

    # Starting values; retain the settings that worked on your panel.
    options.row_address_type = 0
    options.multiplexing = 0
    options.gpio_slowdown = 5
    options.brightness = 100
    options.drop_privileges = False

    return RGBMatrix(options=options)
