# Color Test
from rpi_ws281x import PixelStrip, Color
import time

LED_PIN = 12
LED_COUNT = 10
strip = PixelStrip(LED_COUNT, LED_PIN)
strip.begin()

def set_color_all(r, g, b):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(r, g, b))
    strip.show()

try:
    while True:
        set_color_all(255, 0, 0)
        time.sleep(1)
        set_color_all(0, 255, 0)
        time.sleep(1)
        set_color_all(0, 0, 255)
        time.sleep(1)

except KeyboardInterrupt:
    pass