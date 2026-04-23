#!/usr/bin/env python3

from models import Pacer
from state import PacerManager
import time
from rpi_ws281x import PixelStrip, Color, ws

# ---------------- LED CONFIG ----------------
LED_COUNT = 60
LED_PIN = 18
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 200
LED_INVERT = False
LED_CHANNEL = 0
LED_STRIP = ws.WS2811_STRIP_GRB   # adjust if needed

strip = PixelStrip(
    LED_COUNT,
    LED_PIN,
    LED_FREQ_HZ,
    LED_DMA,
    LED_INVERT,
    LED_BRIGHTNESS,
    LED_CHANNEL,
    LED_STRIP
)
strip.begin()

# ---------------- PACER SETUP ----------------
manager = PacerManager()

current_pacer = manager.create_single_pacer(
    pace=60,
    color=(0, 255, 0)
)

def create_pacer_wave():
    return [
        manager.create_single_pacer(
            pace=60 + i * 10,
            color=(0, 255 - i * 60, 255)
        )
        for i in range(4)
    ]

def create_pacer_spiral():
    colors = [
        (255, 0, 0),
        (255, 127, 0),
        (255, 255, 0),
        (0, 255, 0),
    ]
    return [
        manager.create_single_pacer(
            pace=70 + i * 5,
            color=colors[i]
        )
        for i in range(len(colors))
    ]

def create_pacer_strobe():
    return [
        manager.create_single_pacer(pace=120, color=(255, 255, 255)),
        manager.create_single_pacer(pace=120, color=(0, 0, 0)),
    ]

pacer_patterns = {
    "steady_green": [current_pacer],
    "rainbow_wave": create_pacer_wave(),
    "gradient_spiral": create_pacer_spiral(),
    "strobe": create_pacer_strobe(),
}

pattern_names = list(pacer_patterns.keys())
pattern_index = 0

# ---------------- HELPER FUNCTIONS ----------------

def clear_strip():
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(0, 0, 0))

def draw_pattern(pattern):
    clear_strip()

    for pacer in pattern:
        # SAFETY: make sure position exists
        if not hasattr(pacer, "position"):
            continue

        pos = int(pacer.position) % LED_COUNT
        r, g, b = pacer.color

        strip.setPixelColor(pos, Color(r, g, b))

    strip.show()

# ---------------- MAIN LOOP ----------------

last_time = time.time()
pattern_start_time = time.time()

while True:
    now = time.time()
    dt = now - last_time
    last_time = now

    # Switch pattern every 5 seconds
    if now - pattern_start_time > 5:
        pattern_index = (pattern_index + 1) % len(pattern_names)
        pattern_start_time = now
        print("Switching to:", pattern_names[pattern_index])

    current_pattern = pacer_patterns[pattern_names[pattern_index]]

    # UPDATE PACERS (movement)
    for pacer in current_pattern:
        if hasattr(pacer, "update"):
            pacer.update(dt)

    # DRAW TO LED STRIP
    draw_pattern(current_pattern)

    time.sleep(0.02)  # ~50 FPS smooth animation