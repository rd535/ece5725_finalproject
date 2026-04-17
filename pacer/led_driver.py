try:
    from rpi_ws281x import PixelStrip, Color
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

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
            print(f"[SIM] set_pixel({i}, {color})")

    def show(self):
        if HARDWARE_AVAILABLE:
            self.strip.show()
        else:
            print("[SIM] show()")

    def clear(self):
        if HARDWARE_AVAILABLE:
            for i in range(self.count):
                self.strip.setPixelColor(i, 0)
            self.strip.show()
        else:
            print("[SIM] clear()")
