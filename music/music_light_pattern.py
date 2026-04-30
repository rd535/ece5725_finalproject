#fallback for library not workign
try:
    from rpi_ws281x import Color
except ImportError:
    def Color(r, g, b):
        return (r, g, b)


class MusicLightPattern:
    """Simple full-strip flash that fades after each detected beat."""

    def __init__(self, color=(255, 255, 255), fade_rate=0.85, min_brightness=0.01):
        self.color = color
        self.fade_rate = fade_rate
        self.min_brightness = min_brightness
        self.brightness = 0.0

    def on_beat(self):
        """Call this when the beat detector finds a beat."""
        self.brightness = 1.0

    def render(self, strip, num_leds):
        """Draw the current flash brightness to the LED strip."""
        r, g, b = self._current_color()

        for i in range(num_leds):
            strip.setPixelColor(i, Color(r, g, b))

        strip.show()
        self._fade()

    def clear(self, strip, num_leds):
        """Turn the strip off and reset brightness."""
        self.brightness = 0.0
        for i in range(num_leds):
            strip.setPixelColor(i, Color(0, 0, 0))
        strip.show()

    def _current_color(self):
        r, g, b = self.color
        return (
            int(r * self.brightness),
            int(g * self.brightness),
            int(b * self.brightness),
        )

    def _fade(self):
        self.brightness *= self.fade_rate
        if self.brightness < self.min_brightness:
            self.brightness = 0.0
