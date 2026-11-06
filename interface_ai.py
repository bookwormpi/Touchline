#!/usr/bin/env python3
"""
128x64 swim-training display
Hardware: Raspberry Pi 4 + Adafruit RGB Matrix Bonnet + HUB75 panel
Driver: https://github.com/hzeller/rpi-rgb-led-matrix

Run:
    sudo ~/rgbmatrix-env/bin/python swim_display.py

Edit CURRENT_SET and INTERVAL_HISTORY below to match your workout.
"""

import time
from datetime import timedelta

from PIL import Image, ImageDraw
from rgbmatrix import RGBMatrix, RGBMatrixOptions


# ---------------------------------------------------------------------------
# Workout data: edit these values
# ---------------------------------------------------------------------------

CURRENT_SET = {
    "distance": 50,
    "stroke": "FR",       # FR, BK, BR, FL, REST
    "repetition": 2,
    "total_repetitions": 4,
}

# Most recent interval first. Each item is (label, time_string, color_name).
# These are example values; replace them with measured interval results.
INTERVAL_HISTORY = [
    ("50 FR", "1:20", "freestyle"),
    ("50 BK", "1:50", "backstroke"),
    ("75 FR", "2:20", "freestyle"),
    ("REST",  "1:00", "neutral"),
]

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
    """Format elapsed seconds as MM:SS, or H:MM:SS after one hour."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def draw_main_timer(draw, elapsed_text):
    """Draw the large elapsed timer in the upper-left region."""
    draw_bitmap_text(
        draw, (4, 3), "ELAPSED",
        COLORS["muted"], scale=1, spacing=1
    )

    # Scale 3x5 glyphs to 6x10 pixels for the primary timer.
    timer_width = draw_bitmap_text(
        draw, (4, 14), elapsed_text,
        COLORS["white"], scale=2, spacing=1
    )

    # If the timer grows to H:MM:SS, reduce its scale to fit the left pane.
    if timer_width > 80:
        draw.rectangle((0, 12, 86, 31), fill=COLORS["background"])
        draw_bitmap_text(
            draw, (3, 16), elapsed_text,
            COLORS["white"], scale=1, spacing=1
        )


def draw_current_set(draw):
    """Draw the current interval/set in the lower-left region."""
    draw_bitmap_text(
        draw, (4, 35), "CURRENT SET",
        COLORS["muted"], scale=1, spacing=1
    )

    stroke = CURRENT_SET["stroke"].upper()
    distance = CURRENT_SET["distance"]
    color_key = STROKE_COLORS.get(stroke, "neutral")
    stroke_color = COLORS[color_key]

    draw_bitmap_text(
        draw, (4, 44), f"{distance} {stroke}",
        stroke_color, scale=2, spacing=1
    )

    rep_text = (
        f"REP {CURRENT_SET['repetition']}/"
        f"{CURRENT_SET['total_repetitions']}"
    )
    draw_bitmap_text(
        draw, (4, 57), rep_text,
        COLORS["muted"], scale=1, spacing=1
    )


def draw_interval_history(draw):
    """Draw four compact interval-history rows in the right column."""
    column_x = 89
    column_width = 39
    row_height = 16

    for index in range(4):
        y = index * row_height

        if index:
            draw.line(
                (column_x, y, 127, y),
                fill=COLORS["divider"],
                width=1,
            )

        if index >= len(INTERVAL_HISTORY):
            continue

        label, interval_time, color_name = INTERVAL_HISTORY[index]
        interval_color = COLORS.get(color_name, COLORS["neutral"])

        # Center each label and time within the 39-pixel column.
        label_width = len(label) * 4 - 1
        label_x = column_x + max(1, (39 - label_width) // 2)

        time_width = len(interval_time) * 4 - 1
        time_x = column_x + max(1, (39 - time_width) // 2)

        draw_bitmap_text(
            draw, (label_x, y + 2), label,
            interval_color, scale=1, spacing=1
        )
        draw_bitmap_text(
            draw, (time_x, y + 9), interval_time,
            COLORS["white"], scale=1, spacing=1
        )


def render_frame(elapsed_seconds):
    """Render one complete 128x64 frame."""
    image = Image.new("RGB", (128, 64), COLORS["background"])
    draw = ImageDraw.Draw(image)

    # Main layout dividers.
    draw.line((87, 0, 87, 63), fill=COLORS["divider"], width=1)
    draw.line((0, 32, 86, 32), fill=COLORS["divider"], width=1)

    draw_main_timer(draw, format_elapsed(elapsed_seconds))
    draw_current_set(draw)
    draw_interval_history(draw)

    return image


def create_matrix():
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

    return RGBMatrix(options=options)


def main():
    matrix = create_matrix()
    start_time = time.monotonic()

    print("Swim display running. Press Ctrl+C to stop.")

    try:
        while True:
            elapsed = time.monotonic() - start_time
            frame = render_frame(elapsed)
            matrix.SetImage(frame)
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopping display.")

    finally:
        matrix.Clear()


if __name__ == "__main__":
    main()
