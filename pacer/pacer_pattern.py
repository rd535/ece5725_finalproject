# pacer_pattern.py

import threading
import time
from tkinter import OFF
from rpi_ws281x import PixelStrip, Color, ws
from pacer.pace_calculator import pace_to_speed, scale_pace

class ConstantPacerWithPacer:
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
        self.lap_count = 0

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
        # conv_pace = scale_pace(self.pace, self.rep_distance)
        # SPEED = pace_to_speed(conv_pace, self.rep_distance)
        SPEED = 300 / self.pace 

        # UPDATE_INTERVAL = 0.1 # can be faster/slower depending on pace, time.sleep(UPDATE_INTERVAL) 

        pos = 0.0 
        last_time = time.time()

        self.lap_count = 0

        while self.active:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            # current pos + LED/s * dt w/ overflow reset
            old_pos = pos
            pos = pos + SPEED * dt

            if pos >= self.num_leds:
                self.lap_count += 1

            pos = pos % self.num_leds

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
                if self.lap_count == 0 and idx_init < 0:
                    continue
                idx = int((idx_init) % self.num_leds)
                self.strip.setPixelColor(idx, Color(0,255,0))

            self.lap_count += 1
                
            self.strip.show()

        # turn off strip when stopping
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0,0,0))
        self.strip.show()

# can enter an array of paces and execute each per lap
class DynamicPacer:
    """
    Pacer pattern with a dynamic pace that changes over time.
    Pace = index of pace array, which corresponds to lap number. ex. pace[0] is pace for first lap, pace[1] is pace for second lap, etc.
    """
    def __init__(self, num_leds=300, pin=12, pace=[20, 15, 10, 5], rep_distance=400):
        self.num_leds = num_leds
        self.pin = pin
        self.pace = pace
        self.rep_distance = rep_distance
        self.active = False
        self.thread = None
        self.lap_count = 0

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

        # convert pace to 5m for LED strip
        # conv_pace = [scale_pace(p, self.rep_distance) for p in self.pace]
        # speed_index = [pace_to_speed(p, self.rep_distance) for p in conv_pace]
        speed_index = [300 / s for s in self.pace] # convert to LED/s

        # UPDATE_INTERVAL = 0.1 # can be faster/slower depending on pace, time.sleep(UPDATE_INTERVAL) 

        pos = 0.0 
        last_time = time.time()

        pace_index = 0

        while self.active:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            SPEED = speed_index[pace_index]

            # current pos + LED/s * dt w/ overflow reset
            prev_pos = pos
            pos = (pos + SPEED * dt) % self.num_leds

            # detect lap completion by checking wraparound  
            if pos < prev_pos:
                self.lap_count += 1
                pace_index += 1

                # break if all laps done
                if pace_index >= len(speed_index):
                    self.active = False
                    break

            # clear strip
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0,0,0))

            # draw moving segment
            for j in range(SEGMENT_LENGTH):
                idx_init = pos - j
                # dont overflow on first time
                if idx_init < 0 and self.lap_count == 0:
                    idx_init = 0
                idx = int((idx_init) % self.num_leds)
                self.strip.setPixelColor(idx, Color(0,255,0))
        
            self.strip.show()


        # turn off strip when stopping
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
