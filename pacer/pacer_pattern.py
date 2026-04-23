# pacer_pattern.py

import threading
import time
from rpi_ws281x import PixelStrip, Color, ws

class GreenPacer:
    def __init__(self, num_leds=420, pin=18):
        self.num_leds = num_leds
        self.pin = pin
        self.active = False
        self.thread = None

        self.strip = PixelStrip(
            self.num_leds,
            self.pin,
            800000,
            10,
            False,
            128,
            0,
            ws.WS2811_STRIP_GRB
        )
        self.strip.begin()

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.active = True
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.active = False

    def run(self):
        SEGMENT_LENGTH = 3
        SPEED = 2.0
        pos = 0.0

        while self.active:
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0,0,0))

            for j in range(SEGMENT_LENGTH):
                idx = int((pos + j) % self.num_leds)
                self.strip.setPixelColor(idx, Color(0,255,0))

            self.strip.show()
            pos = (pos + SPEED) % self.num_leds
            time.sleep(1)

        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0,0,0))
        self.strip.show()
