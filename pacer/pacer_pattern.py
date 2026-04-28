import threading
import time

from pacer.event_log import log_event

try:
    from rpi_ws281x import PixelStrip, Color, ws
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

    def Color(r, g, b):
        return (r, g, b)

    class ws:
        SK6812_STRIP_RGBW = None

    class PixelStrip:
        def __init__(self, count, pin, *args, **kwargs):
            self.count = count
            self.pin = pin

        def begin(self):
            log_event("Using simulated LED strip", category="hardware", count=self.count, pin=self.pin)

        def setPixelColor(self, i, color):
            return None

        def show(self):
            return None


def normalize_pace(pace):
    if isinstance(pace, (int, float)):
        return [pace]
    return list(pace)


def make_strip(num_leds, pin):
    strip = PixelStrip(
        num_leds,
        pin,
        800000,
        10,
        False,
        128,
        0,
        ws.SK6812_STRIP_RGBW,
    )
    strip.begin()
    return strip


class NewConstantPacer:
    """
    Pacer state object for NewPacerManager. It computes position only; the
    manager owns the LED strip and renders the combined frame.
    """

    TYPE = "constant"

    def __init__(self, num_leds=300, pace=60, rep_distance=400, lap_count=4, color=Color(0, 255, 0)):
        self.num_leds = num_leds
        self.pace = normalize_pace(pace)
        self.color = color
        self.rep_distance = rep_distance
        self.lap_count = lap_count

        self.active = False
        self.curr_lap = 0
        self.last_time = None
        self.pos = 0.0

    def start(self):
        log_event("Starting pacer", category="pacer", pace=self.pace, color=self.color)
        self.active = True
        self.pos = 0.0
        self.curr_lap = 0
        self.last_time = time.time()

    def stop(self):
        self.active = False
        log_event("Stopping pacer", category="pacer", pace=self.pace)

    def run(self):
        if not self.active:
            return self.pos

        speed = self.num_leds / self.pace[0]

        if self.last_time is None:
            self.last_time = time.time()

        current_time = time.time()
        dt = current_time - self.last_time
        self.last_time = current_time

        self.pos += speed * dt

        if self.pos >= self.num_leds:
            self.curr_lap += int(self.pos // self.num_leds)

        if self.curr_lap >= self.lap_count:
            self.active = False
            log_event("Pacer finished", category="pacer", pace=self.pace, laps=self.curr_lap)
            return 0

        self.pos = self.pos % self.num_leds
        return self.pos


class ConstantPacerWithPacer:
    """
    Pacer pattern with a single color for the pacer and a different color for the actual pace.
    Pace is seconds per lap on the configured LED strip.
    """

    def __init__(self, num_leds=300, pin=12, pace=60, rep_distance=400, lap_count=4):
        self.num_leds = num_leds
        self.pin = pin
        self.pace = normalize_pace(pace)
        self.rep_distance = rep_distance
        self.active = False
        self.thread = None
        self.curr_lap = 0
        self.lap_count = lap_count
        self.strip = make_strip(self.num_leds, self.pin)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            log_event("Starting constant-with-pacer pattern", category="pacer", pace=self.pace)
            self.active = True
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.active = False
        log_event("Stopping constant-with-pacer pattern", category="pacer", pace=self.pace)

    def run(self):
        segment_length = 8
        pacer_segment_length = 3
        speed = self.num_leds / self.pace[0]
        pos = 0.0
        last_time = time.time()
        self.curr_lap = 0

        while self.active:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time
            pos += speed * dt

            if pos >= self.num_leds:
                self.curr_lap += int(pos // self.num_leds)

            if self.curr_lap >= self.lap_count:
                self.active = False
                break

            pos = pos % self.num_leds

            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))

            for k in range(pacer_segment_length):
                pacer_idx = int((pos + k) % self.num_leds)
                self.strip.setPixelColor(pacer_idx, Color(255, 0, 0))

            for j in range(segment_length):
                idx_init = pos - j
                if self.curr_lap == 0 and idx_init < 0:
                    continue
                idx = int(idx_init % self.num_leds)
                self.strip.setPixelColor(idx, Color(0, 255, 0))

            self.strip.show()
            time.sleep(0.02)

        self.clear()
        log_event("Constant-with-pacer pattern finished", category="pacer", pace=self.pace, laps=self.curr_lap)

    def clear(self):
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()


class DynamicPacer:
    """
    Pacer pattern with a dynamic pace that changes per lap.
    """

    def __init__(self, num_leds=300, pin=12, pace=None, rep_distance=400, lap_count=None):
        self.num_leds = num_leds
        self.pin = pin
        self.pace = normalize_pace(pace or [20, 15, 10, 5])
        self.rep_distance = rep_distance
        self.active = False
        self.thread = None
        self.curr_lap = 0
        self.lap_count = lap_count or len(self.pace)
        self.strip = make_strip(self.num_leds, self.pin)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            log_event("Starting dynamic pacer", category="pacer", pace=self.pace)
            self.active = True
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.active = False
        log_event("Stopping dynamic pacer", category="pacer", pace=self.pace)

    def run(self):
        segment_length = 8
        speed_index = [self.num_leds / s for s in self.pace]
        pos = 0.0
        last_time = time.time()
        pace_index = 0
        self.curr_lap = 0

        while self.active:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time
            speed = speed_index[pace_index]

            prev_pos = pos
            pos = (pos + speed * dt) % self.num_leds

            if pos < prev_pos:
                self.curr_lap += 1
                pace_index += 1

                if pace_index >= len(speed_index) or self.curr_lap >= self.lap_count:
                    self.active = False
                    break

            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))

            for j in range(segment_length):
                idx_init = pos - j
                if idx_init < 0 and self.curr_lap == 0:
                    continue
                idx = int(idx_init % self.num_leds)
                self.strip.setPixelColor(idx, Color(0, 255, 0))

            self.strip.show()
            time.sleep(0.02)

        self.clear()
        log_event("Dynamic pacer finished", category="pacer", pace=self.pace, laps=self.curr_lap)

    def clear(self):
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()


class ConstantPacer:
    def __init__(self, num_leds=300, pin=12):
        self.num_leds = num_leds
        self.pin = pin
        self.active = False
        self.thread = None
        self.strip = make_strip(self.num_leds, self.pin)

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            log_event("Starting constant pacer", category="pacer")
            self.active = True
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.active = False
        log_event("Stopping constant pacer", category="pacer")

    def run(self):
        segment_length = 3
        speed = 2.0
        pos = 0.0

        while self.active:
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0, 0, 0))

            for j in range(segment_length):
                idx = int((pos + j) % self.num_leds)
                self.strip.setPixelColor(idx, Color(0, 255, 0))

            self.strip.show()
            pos = (pos + speed) % self.num_leds
            time.sleep(1)

        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0))
        self.strip.show()
