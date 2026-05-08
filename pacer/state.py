import threading
import time
from collections import deque

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, make_strip

class NewPacerManager:
    PACER_SEG_LENGTH = 3
    SEGMENT_LENGTH = 8
    UPDATE_INTERVAL = 0.02

    def __init__(self, num_leds=300, pin=12):
        self.pacers = []
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        self.active = False
        self.thread = None
        self.wake_event = threading.Event()
        self.num_leds = num_leds
        self.pin = pin
        self._next_order = 0
        self._last_frame_log = 0
        self.strip = make_strip(num_leds, pin)
        self.last_frame_time = time.perf_counter()
        self.frame_times = deque(maxlen=100)  # Rolling window

    def add_pacer(self, pacer, log=True):
        with self.lock:
            pacer.num_leds = self.num_leds
            pacer._manager_order = self._next_order
            self._next_order += 1
            self.pacers = [p for p in self.pacers if getattr(p, "name", None) != getattr(pacer, "name", None)]
            self.pacers.append(pacer)
            # Slower pacers render first; faster/newer pacers render later and win overlaps.
            self.pacers.sort(key=lambda p: (-p.pace[0], p._manager_order))
            total = len(self.pacers)

        self.wake_event.set()
        if log:
            log_event("Pacer added to manager", category="manager", pace=pacer.pace, total=total)

    def remove_pacer(self, pacer):
        with self.lock:
            if pacer not in self.pacers:
                return
            pacer.stop()
            self.pacers.remove(pacer)
            total = len(self.pacers)

        log_event("Pacer removed from manager", category="manager", pace=pacer.pace, total=total)
        self.wake_event.set()

    def remove_pacer_by_name(self, pacer_name):
        with self.lock:
            matches = [p for p in self.pacers if getattr(p, "name", None) == pacer_name]

        for pacer in matches:
            self.remove_pacer(pacer)

    def clear_pacers(self):
        with self.lock:
            old_pacers = list(self.pacers)
            self.pacers = []

        for pacer in old_pacers:
            pacer.stop()

        log_event("All pacers cleared from manager", category="manager")
        self.wake_event.set()

    # Make a safe copy of current pacers list so adding/removing doesn't cause issues
    def snapshot_pacers(self):
        with self.lock:
            return list(self.pacers)

    def update(self):
        log_event("Pacer manager update loop started", category="manager")

        try:
            while self.active:
                frame_start = time.perf_counter()
                dt = frame_start - self.last_frame_time
                self.frame_times.append(dt)

                led_updates = self.collect_led_updates()
                self.render(led_updates)
                self.log_frame(led_updates)
                self.wake_event.wait(self.UPDATE_INTERVAL)
                self.wake_event.clear()

                if len(self.frame_times) >= 50:
                    avg = sum(self.frame_times) / len(self.frame_times)
                    jitter = max(self.frame_times) - min(self.frame_times)
                    log_event("Frame timing", avg_ms=avg*1000, jitter_ms=jitter*1000)
                    
        except Exception as exc:
            self.active = False
            log_event("Pacer manager update loop crashed", level="ERROR", category="manager", error=repr(exc))
            raise

        if not self.active:
            self.clear()
            log_event("Pacer manager update loop stopped", category="manager")

    # Collect LED updates from all active pacers, returning a list of (position, color, type) tuples for rendering
    def collect_led_updates(self):
        led_updates = []

        for pacer in self.snapshot_pacers():
            if pacer.active:
                position = pacer.run()
                if pacer.active:
                    led_updates.append((position, pacer.color, pacer.TYPE))

        return led_updates

    def render_active_frame(self):
        led_updates = self.collect_led_updates()
        self.render(led_updates)
        self.log_frame(led_updates)

    # actual drawing step
    def render(self, led_updates):
        with self.render_lock:
            # clear strip first
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))

            # render paces first then segments, so segments win overlaps with pacers
            for position, color, pacer_type in led_updates:
                if pacer_type == "pacer":
                    for k in range(self.PACER_SEG_LENGTH):
                        pacer_idx = int((position + k) % self.num_leds)
                        # just make it white by default
                        self.strip.setPixelColor(pacer_idx, Color(255, 255, 255))

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
        with self.render_lock:
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))
            self.strip.show()

    def configure_strip(self, num_leds=None, pin=None):
        was_active = self.active
        if was_active:
            self.stop()
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=1.0)

        self.num_leds = num_leds or self.num_leds
        self.pin = pin or self.pin
        self.strip = make_strip(self.num_leds, self.pin)

        for pacer in self.snapshot_pacers():
            pacer.num_leds = self.num_leds

        log_event("LED strip configured", category="settings", num_leds=self.num_leds, pin=self.pin)


    # For debugging
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

    def start(self, log=True):
        if self.thread is not None and self.thread.is_alive():
            self.active = True
            self.wake_event.set()
            return

        if self.thread is None or not self.thread.is_alive():
            self.active = True
            self.thread = threading.Thread(target=self.update, daemon=True)
            self.thread.start()
            if log:
                log_event("Pacer manager started", category="manager", pacers=len(self.pacers))
        self.wake_event.set()

    def stop(self):
        self.active = False
        self.wake_event.set()
        for pacer in self.snapshot_pacers():
            pacer.stop()
        log_event("Pacer manager stop requested", category="manager")

