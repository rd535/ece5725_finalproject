import threading
import time

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, ConstantPacerWithPacer, make_strip


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
        self._last_frame_log = 0
        self.strip = make_strip(num_leds, pin)

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

        try:
            while self.active:
                led_updates = []

                for pacer in self.pacers:
                    if pacer.active:
                        position = pacer.run()
                        if pacer.active:
                            led_updates.append((position, pacer.color, pacer.TYPE))

                self.render(led_updates)
                self.log_frame(led_updates)
                time.sleep(self.UPDATE_INTERVAL)
        except Exception as exc:
            self.active = False
            log_event("Pacer manager update loop crashed", level="ERROR", category="manager", error=repr(exc))
            raise

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

    def log_frame(self, led_updates):
        now = time.time()
        if now - self._last_frame_log < 1.0:
            return

        self._last_frame_log = now
        if led_updates:
            first_position, _, first_type = led_updates[0]
            log_event(
                "Rendered LED frame",
                category="manager",
                updates=len(led_updates),
                first_position=round(first_position, 2),
                first_type=first_type,
            )

    def clear(self):
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()

    def flash_startup(self, color=None, duration=0.5):
        color = color or Color(0, 0, 255)
        width = min(12, self.num_leds)
        log_event("Flashing startup LED test", category="manager", width=width)

        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        for i in range(width):
            self.strip.setPixelColor(i, color)
        self.strip.show()
        time.sleep(duration)
        self.clear()

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
