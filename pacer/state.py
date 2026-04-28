import threading
import time

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, ConstantPacerWithPacer
from rpi_ws281x import PixelStrip, Color, ws


class NewPacerManager:
    PACER_SEG_LENGTH = 3
    SEGMENT_LENGTH = 8
    UPDATE_INTERVAL = 0.02

    def __init__(self, num_leds=300, pin=12):
        self.pacers = []
        self.active = False
        self.thread = None
        self.num_leds = num_leds
        self.pin = pin
        self._next_order = 0
        self.strip = PixelStrip(
            num_leds,
            pin,
            800000,
            10,
            False,
            128,
            0,
            ws.SK6812_STRIP_RGBW,
            )
        self.strip.begin()

    def add_pacer(self, pacer):
        pacer.num_leds = self.num_leds
        pacer._manager_order = self._next_order
        self._next_order += 1
        self.pacers.append(pacer)
        # Sort pacers by pace (fastest last) and then by order added to manager
        self.pacers.sort(key=lambda p: (-p.pace[0], p._manager_order))
        log_event("Pacer added to manager", category="manager", pace=pacer.pace, total=len(self.pacers))

    def remove_pacer(self, pacer):
        if pacer in self.pacers:
            pacer.stop()
            self.pacers.remove(pacer)
            log_event("Pacer removed from manager", category="manager", pace=pacer.pace, total=len(self.pacers))

    def update(self):
        log_event("Pacer manager update loop started", category="manager")

        while self.active:
            led_updates = []

            for pacer in self.pacers:
                if pacer.active:
                    position = pacer.run()
                    if pacer.active:
                        led_updates.append((position, pacer.color, pacer.TYPE))

            self.render(led_updates)
            # may or may not need
            time.sleep(self.UPDATE_INTERVAL)

        self.clear()
        log_event("Pacer manager update loop stopped", category="manager")

    def render(self, led_updates):
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))

        for position, color, pacer_type in led_updates:
            if pacer_type == "pacer":
                for k in range(self.PACER_SEG_LENGTH):
                    pacer_idx = int((position + k) % self.num_leds)
                    self.strip.setPixelColor(pacer_idx, color)

            for j in range(self.SEGMENT_LENGTH):
                idx_init = position - j
                if idx_init < 0:
                    continue
                idx = int(idx_init % self.num_leds)
                self.strip.setPixelColor(idx, color)

        self.strip.show()

    def clear(self):
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.active = True
            self.thread = threading.Thread(target=self.update, daemon=True)
            self.thread.start()
            log_event("Pacer manager started", category="manager", pacers=len(self.pacers))

    def stop(self):
        self.active = False
        for pacer in self.pacers:
            pacer.stop()
        log_event("Pacer manager stop requested", category="manager")


class PacerManager:
    def __init__(self):
        self.pacers = []

    def create_single_pacer(self, pace, color):
        if not self.pacers:
            self.pacers.append(ConstantPacerWithPacer())

        p = self.pacers[0]
        p.pace = [pace] if isinstance(pace, (int, float)) else list(pace)
        p.color = color
        log_event("Legacy pacer settings updated", category="settings", pace=p.pace, color=color)
        return p

    def update(self, dt):
        for p in self.pacers:
            if p.active:
                p.position += dt * (p.rep_distance / p.pace[0])


manager = PacerManager()
