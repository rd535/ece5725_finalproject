try:
    from rpi_ws281x import PixelStrip, Color
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

from pacer.event_log import log_event

class LEDDriver:
    def __init__(self, count, pin):
        self.count = count
        self.pin = pin

        if HARDWARE_AVAILABLE:
            self.strip = PixelStrip(count, pin)
            self.strip.begin()
        else:
            self.strip = None

    def set_pixel(self, i, color):
        if HARDWARE_AVAILABLE:
            self.strip.setPixelColor(i, color)
        else:
            return None

    def show(self):
        if HARDWARE_AVAILABLE:
            self.strip.show()
        else:
            return None

    def clear(self):
        if HARDWARE_AVAILABLE:
            for i in range(self.count):
                self.strip.setPixelColor(i, 0)
            self.strip.show()
        else:
            log_event("Simulated LED strip cleared", category="hardware")
