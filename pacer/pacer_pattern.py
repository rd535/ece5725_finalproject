import os
import time

from pacer.event_log import log_event

try:
    from rpi_ws281x import PixelStrip, Color, ws
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

    def Color(r, g, b):
        return (int(r), int(g), int(b))


class SimulatedStrip:
    def __init__(self, num_leds):
        self._pixels = [Color(0, 0, 0)] * num_leds

    def setPixelColor(self, index, color):
        if 0 <= index < len(self._pixels):
            self._pixels[index] = color

    def show(self):
        return None

    def numPixels(self):
        return len(self._pixels)


def normalize_pace(pace):
    if isinstance(pace, (int, float)):
        return [pace]
    return list(pace)


def make_strip(num_leds, pin):
    if not HARDWARE_AVAILABLE:
        log_event("Using simulated LED strip", level="WARNING", category="hardware")
        return SimulatedStrip(num_leds)

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        log_event("LED strip requires root; using simulated strip", level="WARNING", category="hardware")
        return SimulatedStrip(num_leds)

    try:
        strip = PixelStrip(
            num_leds,
            pin,
            800000,
            10,
            False,
            128,
            0,
            ws.SK6812_STRIP_GRBW,
        )
        strip.begin()
        return strip
    except RuntimeError as exc:
        log_event("LED strip init failed; using simulated strip", level="ERROR", category="hardware", error=str(exc))
        return SimulatedStrip(num_leds)


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
        
        # Lap timing instrumentation
        self.lap_start_time = None
        self.last_lap_count = 0

    def start(self):
        self.active = True
        self.pos = 0.0
        self.curr_lap = 0
        self.last_time = time.time()
        
        # Initialize lap timing
        self.lap_start_time = time.time()
        self.last_lap_count = 0
        log_event("Starting pacer", category="pacer", pace=self.pace)

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

        # Check for completed laps and log timing
        if self.curr_lap > self.last_lap_count and self.lap_start_time is not None:
            t_end = time.time()
            T_measured = t_end - self.lap_start_time
            lap_number = self.last_lap_count + 1
            log_event("Lap completed", 
                     category="pacer_timing", 
                     lap_number=lap_number,
                     measured_time_s=round(T_measured, 3),
                     target_pace_s=self.pace[0],
                     t_start=self.lap_start_time,
                     t_end=t_end)
            
            # Start timing for next lap
            self.lap_start_time = t_end
            self.last_lap_count = self.curr_lap

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
            
            # Log lap timing
            if self.lap_start_time is not None:
                t_end = time.time()
                T_measured = t_end - self.lap_start_time
                lap_number = self.curr_lap
                current_pace = self.pace[min(self.pace_index - 1, len(self.pace) - 1)]
                log_event("Lap completed", 
                         category="pacer_timing", 
                         lap_number=lap_number,
                         measured_time_s=round(T_measured, 3),
                         target_pace_s=current_pace,
                         t_start=self.lap_start_time,
                         t_end=t_end)
                
                # Start timing for next lap
                self.lap_start_time = t_end

        if self.curr_lap >= self.lap_count or self.pace_index >= len(self.pace):
            self.active = False
            log_event("Dynamic pacer finished", category="pacer", pace=self.pace, laps=self.curr_lap)
            return 0

        return self.pos
