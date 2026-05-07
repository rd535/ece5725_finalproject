import threading
import time

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, make_strip
from lighting.lighting_patterns import PATTERN_REGISTRY, pattern_metadata


class LightingManager:
    UPDATE_INTERVAL = 0.03

    def __init__(self, num_leds=300, pin=12, color_order="RGB"):
        self.num_leds = num_leds
        self.pin = pin
        self.color_order = color_order
        self.strip = make_strip(num_leds, pin)

        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()

        self.current_pattern = None
        self.current_pattern_name = None
        self.started_at = None

    def metadata(self):
        return pattern_metadata()

    def configure_strip(self, num_leds=None, pin=None, color_order=None):
        self.stop()
        with self.lock:
            self.num_leds = num_leds or self.num_leds
            self.pin = pin or self.pin
            self.color_order = color_order or self.color_order
            self.strip = make_strip(self.num_leds, self.pin)
        self.clear_strip()
        log_event("Lighting strip configured", category="lighting", num_leds=self.num_leds, pin=self.pin, color_order=self.color_order)

    def start_pattern(self, pattern_name, colors=None, speed=1.0):
        pattern_class = PATTERN_REGISTRY.get(pattern_name)
        if pattern_class is None:
            raise ValueError(f"Unknown lighting pattern: {pattern_name}")

        colors = colors or [(255, 255, 255)]
        required = pattern_class.color_count
        if required > 0 and len(colors) != required:
            raise ValueError(f"{pattern_class.label} requires {required} color(s)")

        self.stop(log=False)

        with self.lock:
            self.current_pattern = pattern_class(colors=colors, speed=speed)
            self.current_pattern_name = pattern_name
            self.started_at = time.time()
            self.stop_event.clear()

            self.thread = threading.Thread(target=self.update_loop, daemon=True)
            self.thread.start()

        log_event("Lighting pattern started", category="lighting", pattern=pattern_name, colors=len(colors), speed=speed)

    def update_loop(self):
        while not self.stop_event.is_set():
            with self.lock:
                pattern = self.current_pattern
                started_at = self.started_at
                led_count = self.num_leds

            if pattern is None or started_at is None:
                break

            elapsed = time.time() - started_at
            self.render(pattern.frame(led_count, elapsed))
            self.stop_event.wait(self.UPDATE_INTERVAL)

    def stop(self, join=True, log=True):
        with self.lock:
            old_thread = self.thread
            pattern_name = self.current_pattern_name
            self.stop_event.set()
            self.current_pattern = None
            self.current_pattern_name = None
            self.started_at = None

        if join and old_thread and old_thread.is_alive() and old_thread is not threading.current_thread():
            old_thread.join(timeout=1.0)

        with self.lock:
            if self.thread is old_thread:
                self.thread = None

        self.clear_strip()
        if log:
            log_event("Lighting stopped", category="lighting", pattern=pattern_name)

    def render(self, colors):
        with self.render_lock:
            for i in range(self.num_leds):
                color = colors[i] if i < len(colors) else (0, 0, 0)
                self.strip.setPixelColor(i, self.to_strip_color(color))
            self.strip.show()

    def clear_strip(self):
        with self.render_lock:
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))
            self.strip.show()

    def to_strip_color(self, color):
        if isinstance(color, (tuple, list)):
            r, g, b = int(color[0]), int(color[1]), int(color[2])
        else:
            value = int(color)
            r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255

        values = {"R": r, "G": g, "B": b}
        order = self.color_order.upper()
        return Color(values[order[0]], values[order[1]], values[order[2]])

    def status(self):
        with self.lock:
            return {
                "running": self.thread is not None and self.thread.is_alive(),
                "pattern": self.current_pattern_name,
                "started_at": self.started_at,
            }


LightingManagerV2 = LightingManager
