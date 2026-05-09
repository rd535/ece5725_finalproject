import threading
import time
from collections import deque

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, make_strip
from lighting.lighting_patterns import PATTERN_REGISTRY, pattern_metadata
from performance_logger import get_performance_logger


class LightingManagerV2:
    UPDATE_INTERVAL = 0.03
    CLEAR_REPEAT_COUNT = 3

    def __init__(self, num_leds=300, pin=12, color_order="RGB", strip=None):
        self.num_leds = num_leds
        self.pin = pin
        self.color_order = color_order
        self.strip = strip or make_strip(num_leds, pin)
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.active = False
        self.current_pattern = None
        self.current_pattern_name = None
        self.started_at = None
        
        # Performance metrics
        self.last_frame_time = time.perf_counter()
        self.frame_times = deque(maxlen=100)
        self.frame_generation_times = deque(maxlen=100)
        self.render_times = deque(maxlen=100)
        self.lock_wait_times = deque(maxlen=100)

    def metadata(self):
        return pattern_metadata()

    def configure_strip(self, num_leds=None, pin=None, color_order=None, strip=None):
        self.stop()
        with self.lock:
            self.num_leds = num_leds or self.num_leds
            self.pin = pin or self.pin
            self.color_order = color_order or self.color_order
            self.strip = strip or make_strip(self.num_leds, self.pin)
        self.clear_strip()
        log_event("Lighting strip configured", category="lighting", num_leds=self.num_leds, pin=self.pin, color_order=self.color_order)

    def start(self):
        with self.lock:
            if self.active:
                return
            self.active = True
            self.stop_event.set()
            self.current_pattern = None
            self.current_pattern_name = None
            self.started_at = None
        self.clear_strip()
        log_event("Lighting manager started", category="lighting")

    def stop(self):
        self.stop_pattern(log=False)
        with self.lock:
            was_active = self.active
            self.active = False
        self.clear_strip()
        if was_active:
            log_event("Lighting manager stopped", category="lighting")

    def start_pattern(self, pattern_name, colors=None, speed=1.0):
        pattern_start_time = time.perf_counter()
        
        pattern_class = PATTERN_REGISTRY.get(pattern_name)
        if pattern_class is None:
            raise ValueError(f"Unknown lighting pattern: {pattern_name}")

        colors = colors or [(255, 255, 255)]
        required = pattern_class.color_count
        if required > 0 and len(colors) != required:
            raise ValueError(f"{pattern_class.label} requires {required} color(s)")

        with self.lock:
            if not self.active:
                self.active = True

        self.stop_pattern(log=False)

        with self.lock:
            self.current_pattern = pattern_class(colors=colors, speed=speed)
            self.current_pattern_name = pattern_name
            self.started_at = time.time()
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.update_loop, daemon=True)
            self.thread.start()

        # Measure pattern switch latency (time to first frame)
        first_frame_start = time.perf_counter()
        # Wait for first frame to be rendered
        time.sleep(0.05)  # Give it a moment to start
        pattern_switch_latency = time.perf_counter() - pattern_start_time
        
        log_event(
            "Lighting pattern started",
            category="lighting",
            pattern=pattern_name,
            colors=len(colors),
            speed=speed,
            switch_latency_ms=round(pattern_switch_latency * 1000, 2)
        )

    def stop_pattern(self, log=True):
        with self.lock:
            old_thread = self.thread
            pattern_name = self.current_pattern_name
            self.stop_event.set()
            self.current_pattern = None
            self.current_pattern_name = None
            self.started_at = None

        if old_thread and old_thread.is_alive() and old_thread is not threading.current_thread():
            old_thread.join(timeout=1.0)

        with self.lock:
            if self.thread is old_thread:
                self.thread = None

        self.clear_strip()
        if log:
            log_event("Lighting pattern stopped", category="lighting", pattern=pattern_name)

    def update_loop(self):
        while not self.stop_event.is_set():
            frame_start = time.perf_counter()
            
            # Measure frame interval (jitter)
            dt = frame_start - self.last_frame_time
            self.frame_times.append(dt)
            self.last_frame_time = frame_start
            
            # Measure lock acquisition time
            lock_start = time.perf_counter()
            with self.lock:
                lock_acquired = time.perf_counter()
                pattern = self.current_pattern
                started_at = self.started_at
                led_count = self.num_leds
            lock_wait = lock_acquired - lock_start
            self.lock_wait_times.append(lock_wait)

            if pattern is None or started_at is None:
                break

            elapsed = time.time() - started_at
            
            # Measure pattern frame generation time
            frame_gen_start = time.perf_counter()
            colors = pattern.frame(led_count, elapsed)
            frame_gen_end = time.perf_counter()
            frame_gen_time = frame_gen_end - frame_gen_start
            self.frame_generation_times.append(frame_gen_time)
            
            # Measure render time
            render_start = time.perf_counter()
            self.render(colors)
            render_end = time.perf_counter()
            render_time = render_end - render_start
            self.render_times.append(render_time)
            
            # Log performance metrics periodically
            self._log_performance_metrics()
            
            self.stop_event.wait(self.UPDATE_INTERVAL)

    def _log_performance_metrics(self):
        """Log performance metrics every 3 seconds."""
        now = time.time()
        if not hasattr(self, '_last_metrics_log'):
            self._last_metrics_log = now
            return
        
        if now - self._last_metrics_log < 3.0:
            return
        
        self._last_metrics_log = now
        
        if len(self.frame_times) >= 10:
            avg_frame_interval = sum(self.frame_times) / len(self.frame_times)
            frame_jitter = max(self.frame_times) - min(self.frame_times)
            
            avg_frame_gen = sum(self.frame_generation_times) / len(self.frame_generation_times)
            avg_render = sum(self.render_times) / len(self.render_times)
            avg_lock_wait = sum(self.lock_wait_times) / len(self.lock_wait_times)
            
            total_frame_time = avg_frame_gen + avg_render
            
            # Log to event log
            log_event(
                "Lighting performance metrics",
                category="lighting_perf",
                frame_interval_ms=round(avg_frame_interval * 1000, 2),
                frame_jitter_ms=round(frame_jitter * 1000, 2),
                frame_gen_ms=round(avg_frame_gen * 1000, 2),
                render_ms=round(avg_render * 1000, 2),
                lock_wait_ms=round(avg_lock_wait * 1000, 2),
                total_frame_ms=round(total_frame_time * 1000, 2),
                target_interval_ms=self.UPDATE_INTERVAL * 1000,
                frames_collected=len(self.frame_times)
            )
            
            # Log to CSV for analysis
            perf_logger = get_performance_logger()
            perf_logger.log_lighting_performance(
                frame_interval_ms=avg_frame_interval * 1000,
                frame_jitter_ms=frame_jitter * 1000,
                frame_gen_ms=avg_frame_gen * 1000,
                render_ms=avg_render * 1000,
                lock_wait_ms=avg_lock_wait * 1000,
                total_frame_ms=total_frame_time * 1000
            )

    def render(self, colors):
        with self.render_lock:
            for i in range(self.pixel_count()):
                color = colors[i] if i < len(colors) else (0, 0, 0)
                self.strip.setPixelColor(i, self.to_strip_color(color))
            self.strip.show()

    def clear_strip(self):
        with self.render_lock:
            for _ in range(self.CLEAR_REPEAT_COUNT):
                for i in range(self.pixel_count()):
                    self.strip.setPixelColor(i, self.to_strip_color((0, 0, 0)))
                self.strip.show()
                time.sleep(0.01)

    def pixel_count(self):
        if hasattr(self.strip, "numPixels"):
            return min(self.num_leds, int(self.strip.numPixels()))
        return self.num_leds

    def to_strip_color(self, color):
        if isinstance(color, (tuple, list)):
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            values = {"R": r, "G": g, "B": b}
            order = self.color_order.upper()
            return Color(values[order[0]], values[order[1]], values[order[2]])
        else:
            return int(color)

    def status(self):
        with self.lock:
            status_dict = {
                "active": self.active,
                "running": self.thread is not None and self.thread.is_alive(),
                "pattern": self.current_pattern_name,
                "started_at": self.started_at,
            }
        
        # Add performance metrics if we have data
        if len(self.frame_times) >= 5:
            status_dict["performance"] = {
                "avg_frame_interval_ms": round(sum(self.frame_times) / len(self.frame_times) * 1000, 2),
                "frame_jitter_ms": round((max(self.frame_times) - min(self.frame_times)) * 1000, 2),
                "avg_frame_gen_ms": round(sum(self.frame_generation_times) / len(self.frame_generation_times) * 1000, 2),
                "avg_render_ms": round(sum(self.render_times) / len(self.render_times) * 1000, 2),
                "avg_lock_wait_ms": round(sum(self.lock_wait_times) / len(self.lock_wait_times) * 1000, 2),
                "samples": len(self.frame_times)
            }
        
        return status_dict


LightingManager = LightingManagerV2
