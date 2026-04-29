import time

from pacer.event_log import log_event

try:
    from rpi_ws281x import PixelStrip, Color, ws
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

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

        # wrap back around to 0
        self.pos = self.pos % self.num_leds
        return self.pos


class NewDynamicPacer(NewConstantPacer):
    """
    Dynamic state object for NewPacerManager. Each lap can use a different pace.
    """

    TYPE = "dynamic"

    def __init__(self, num_leds=300, pace=None, rep_distance=400, lap_count=None, color=Color(0, 255, 0)):
        pace = pace or [20, 15, 10, 5]
        super().__init__(
            num_leds=num_leds,
            pace=pace,
            rep_distance=rep_distance,
            lap_count=lap_count or len(pace),
            color=color,
        )
        self.pace_index = 0

    def start(self):
        super().start()
        self.pace_index = 0
    
    def stop(self):
        super().stop()

    def run(self):
        if not self.active:
            return self.pos

        current_pace = self.pace[min(self.pace_index, len(self.pace) - 1)]
        speed = self.num_leds / current_pace

        if self.last_time is None:
            self.last_time = time.time()

        current_time = time.time()
        dt = current_time - self.last_time
        self.last_time = current_time

        previous_pos = self.pos
        self.pos = (self.pos + speed * dt) % self.num_leds

        if self.pos < previous_pos:
            self.curr_lap += 1
            self.pace_index += 1

        if self.curr_lap >= self.lap_count or self.pace_index >= len(self.pace):
            self.active = False
            log_event("Dynamic pacer finished", category="pacer", pace=self.pace, laps=self.curr_lap)
            return 0

        return self.pos
