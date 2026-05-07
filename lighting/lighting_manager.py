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
        self.wake_event = threading.Event()
        self.active = False
        self.thread = None
        self.current_pattern = None
        self.current_pattern_name = None
        self.started_at = None

    def configure_strip(self, num_leds=None, pin=None, color_order=None):
        was_active = self.active
        if was_active:
            self.stop()
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=1.0)

        self.num_leds = num_leds or self.num_leds
        self.pin = pin or self.pin
        self.color_order = color_order or self.color_order
        self.strip = make_strip(self.num_leds, self.pin)
        log_event("Lighting strip configured", category="lighting", num_leds=self.num_leds, pin=self.pin, color_order=self.color_order)

    def metadata(self):
        return pattern_metadata()

    def start_pattern(self, pattern_name, colors=None, speed=1.0):
        pattern_class = PATTERN_REGISTRY.get(pattern_name)
        if pattern_class is None:
            raise ValueError(f"Unknown lighting pattern: {pattern_name}")

        colors = colors or [(255, 255, 255)]
        required = pattern_class.color_count
        if required > 0 and len(colors) != required:
            raise ValueError(f"{pattern_class.label} requires {required} color(s)")

        with self.lock:
            self.current_pattern = pattern_class(colors=colors, speed=speed)
            self.current_pattern_name = pattern_name
            self.started_at = time.time()
            self.active = True

        self.render_active_frame()
        self.start_loop()
        log_event("Lighting pattern started", category="lighting", pattern=pattern_name, colors=len(colors), speed=speed)

    def start_loop(self):
        if self.thread is not None and self.thread.is_alive():
            self.wake_event.set()
            return

        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()
        self.wake_event.set()

    def update(self):
        try:
            while self.active:
                self.render_active_frame()
                self.wake_event.wait(self.UPDATE_INTERVAL)
                self.wake_event.clear()
        except Exception as exc:
            self.active = False
            log_event("Lighting manager update loop crashed", level="ERROR", category="lighting", error=repr(exc))
            raise

        self.clear()
        log_event("Lighting manager update loop stopped", category="lighting")

    def render_active_frame(self):
        with self.lock:
            pattern = self.current_pattern
            started_at = self.started_at

        if not pattern or started_at is None:
            return

        elapsed = time.time() - started_at
        self.render(pattern.frame(self.num_leds, elapsed))

    def render(self, colors):
        with self.render_lock:
            for i, color in enumerate(colors[:self.num_leds]):
                self.strip.setPixelColor(i, self.to_strip_color(color))
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

    def clear(self):
        with self.render_lock:
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))
            self.strip.show()

    def stop(self):
        self.active = False
        self.wake_event.set()
        with self.lock:
            pattern_name = self.current_pattern_name
            self.current_pattern = None
            self.current_pattern_name = None
            self.started_at = None
        self.clear()
        log_event("Lighting stopped", category="lighting", pattern=pattern_name)

    def status(self):
        with self.lock:
            return {
                "running": self.active,
                "pattern": self.current_pattern_name,
                "started_at": self.started_at,
            }
