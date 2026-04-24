# pacer_pattern.py

import threading
import time
from tkinter import OFF
from rpi_ws281x import PixelStrip, Color, ws
from pace_calculator import pace_to_speed, scale_pace

class PacerWithPacer:
    """
    Pacer pattern with a single color for the pacer and a different color for the actual pace.
    ex. At wake forest, pacer light was set for 52.5s and our pace was 53s for first lap of an 800m
    This is "race mode". since people follow pacer and want the people to hit pace so set pacer pace faster
    Pace = seconds
    """
    def __init__(self, num_leds=300, pin=12, pace=60, rep_distance=400):
        self.num_leds = num_leds
        self.pin = pin
        self.pace = pace
        self.rep_distance = rep_distance
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
            ws.SK6812_STRIP_RGBW
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
        SEGMENT_LENGTH = 8

        # shorter segment as for just one dude 
        PACER_SEG_LENGTH = 3

        # convert pace to 5m for LED strip
        conv_pace = scale_pace(self.pace, self.rep_distance)
        SPEED = pace_to_speed(conv_pace, self.rep_distance)

        # UPDATE_INTERVAL = 0.1 # can be faster/slower depending on pace, time.sleep(UPDATE_INTERVAL) 

        pos = 0.0 
        pacer_pos = 0.0
        last_time = time.time()

        first_time = True

        while self.active:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            # current pos + LED/s * dt w/ overflow reset
            pos = (pos + SPEED * dt) % self.num_leds

            # clear strip
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0,0,0))

            # do first so can overwrite with real pace color if they overlap
            for k in range(PACER_SEG_LENGTH):
                pacer_idx = int((pos + k) % self.num_leds)
                self.strip.setPixelColor(pacer_idx, Color(255,0,0))

            # draw moving segment
            for j in range(SEGMENT_LENGTH):
                idx_init = pos - j
                # dont overflow on first time
                if idx_init < 0 and first_time:
                    idx_init = 0
                    first_time = False
                idx = int((idx_init) % self.num_leds)
                self.strip.setPixelColor(idx, Color(0,255,0))
                
            self.strip.show()

        # turn off strip when stopping
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0,0,0))
        self.strip.show()

        # while self.active:
        #     now = time.monotonic()
        #     dt = now - last_time
        #     last_time = now

        #     pos = (pos + SPEED * dt) % self.num_leds
        #     pacer_pos = (pacer_pos + PACER_SPEED * dt) % self.num_leds

        #     actual_start = int(pos)
        #     pacer_start = int(pacer_pos)

        #     actual_indices = {
        #         (actual_start + j) % self.num_leds
        #         for j in range(SEGMENT_LENGTH)
        #     }

        #     pacer_indices = {
        #         (pacer_start + k) % self.num_leds
        #         for k in range(PACER_SEG_LENGTH)
        #     }

        #     # Only clear LEDs touched last frame or this frame
        #     affected = prev_actual | prev_pacer | actual_indices | pacer_indices

        #     for idx in affected:
        #         self.strip.setPixelColor(idx, OFF)
        #         self.strip.show()

        #     # Draw actual pace first
        #     for idx in actual_indices:
        #         self.strip.setPixelColor(idx, Color(0,255,0))
        #         self.strip.show()

        #     # Draw pacer second so it overwrites overlap
        #     for idx in pacer_indices:
        #         self.strip.setPixelColor(idx, Color(255,0,0))
        #         self.strip.show()

            

        #     prev_actual = actual_indices
        #     prev_pacer = pacer_indices

        #     time.sleep(UPDATE_INTERVAL)

        # # clean shutdown
        # for idx in prev_actual | prev_pacer:
        #     self.strip.setPixelColor(idx, OFF)
        #     self.strip.show()


# can enter an array of paces and execute each per lap
class DynamicPacer:
    def __init__(self, num_leds=300, pin=12):
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
            ws.SK6812_STRIP_RGBW
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

        # only update every 250ms? or 500ms? to save CPU cycles and reduce flickering
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

class GreenPacer:
    def __init__(self, num_leds=300, pin=12):
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
            ws.SK6812_STRIP_RGBW
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

        # only update every 250ms? or 500ms? to save CPU cycles and reduce flickering
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
