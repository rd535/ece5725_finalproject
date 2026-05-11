try:
    from rpi_ws281x import Color
except ImportError:
    def Color(r, g, b):
        return (r, g, b)


class MusicLightPattern:
    """Simple full-strip on/off white pulse for each detected beat."""

    def __init__(self, color=(255, 255, 255), pulse_seconds=0.08):
        self.color = color
        self.pulse_seconds = pulse_seconds
        self.pulse_until = 0.0

    def on_beat(self):
        """Call this when beat detector finds a beat."""
        import time
        self.pulse_until = time.time() + self.pulse_seconds

    def render(self, strip, num_leds):
        """Draw full white during the pulse, otherwise turn strip off."""
        import time
        pixel = Color(*self.color) if time.time() < self.pulse_until else 0

        for i in range(num_leds):
            strip.setPixelColor(i, pixel)

        strip.show()

    def clear(self, strip, num_leds):
        """Turn strip off and reset pulse state."""
        self.pulse_until = 0.0
        for i in range(num_leds):
            strip.setPixelColor(i, 0)
        strip.show()
