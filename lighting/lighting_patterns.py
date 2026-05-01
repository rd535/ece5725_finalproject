import math
import random

from pacer.pacer_pattern import Color


def color_to_rgb(color):
    if isinstance(color, (tuple, list)):
        return int(color[0]), int(color[1]), int(color[2])
    if all(hasattr(color, attr) for attr in ("r", "g", "b")):
        return int(color.r), int(color.g), int(color.b)
    value = int(color)
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def scale_color(color, scale):
    scale = max(0.0, min(1.0, scale))
    r, g, b = color_to_rgb(color)
    return Color(int(r * scale), int(g * scale), int(b * scale))


def blend_color(a, b, t):
    t = max(0.0, min(1.0, t))
    ar, ag, ab = color_to_rgb(a)
    br, bg, bb = color_to_rgb(b)
    return Color(
        int(ar + (br - ar) * t),
        int(ag + (bg - ag) * t),
        int(ab + (bb - ab) * t),
    )


def wheel(pos):
    pos = int(pos) & 255
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    if pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    pos -= 170
    return Color(0, pos * 3, 255 - pos * 3)


class LightingPattern:
    color_count = 1
    label = "Pattern"

    def __init__(self, colors=None, speed=1.0):
        self.colors = colors or [Color(255, 255, 255)]
        self.speed = max(0.1, float(speed or 1.0))

    def frame(self, led_count, elapsed):
        raise NotImplementedError


class StaticColorPattern(LightingPattern):
    color_count = 1
    label = "Static Color"

    def frame(self, led_count, elapsed):
        return [self.colors[0]] * led_count


class ColorFadePattern(LightingPattern):
    color_count = 2
    label = "Color Fade"

    def frame(self, led_count, elapsed):
        phase = (math.sin(elapsed * self.speed * math.pi) + 1) / 2
        color = blend_color(self.colors[0], self.colors[1], phase)
        return [color] * led_count


class TheaterChasePattern(LightingPattern):
    color_count = 1
    label = "Theater Lighting"

    def frame(self, led_count, elapsed):
        offset = int(elapsed * self.speed * 12) % 3
        off = Color(0, 0, 0)
        return [self.colors[0] if (i + offset) % 3 == 0 else off for i in range(led_count)]


class RainbowPattern(LightingPattern):
    color_count = 0
    label = "Rainbow"

    def frame(self, led_count, elapsed):
        offset = int(elapsed * self.speed * 60)
        return [wheel((i * 256 / max(1, led_count) + offset) & 255) for i in range(led_count)]


class PulsePattern(LightingPattern):
    color_count = 1
    label = "Pulse"

    def frame(self, led_count, elapsed):
        intensity = 0.15 + 0.85 * ((math.sin(elapsed * self.speed * math.pi * 2) + 1) / 2)
        return [scale_color(self.colors[0], intensity)] * led_count


class CometPattern(LightingPattern):
    color_count = 1
    label = "Comet"

    def frame(self, led_count, elapsed):
        if led_count <= 0:
            return []
        head = int(elapsed * self.speed * 35) % led_count
        frame = [Color(0, 0, 0)] * led_count
        tail = min(18, led_count)
        for j in range(tail):
            idx = (head - j) % led_count
            frame[idx] = scale_color(self.colors[0], 1 - (j / tail))
        return frame


class SparklePattern(LightingPattern):
    color_count = 2
    label = "Sparkle"

    def frame(self, led_count, elapsed):
        random.seed(int(elapsed * self.speed * 12))
        frame = [scale_color(self.colors[0], 0.08)] * led_count
        sparkle_count = max(1, led_count // 18)
        for _ in range(sparkle_count):
            frame[random.randrange(led_count)] = self.colors[1]
        return frame


class ScannerPattern(LightingPattern):
    color_count = 1
    label = "Scanner"

    def frame(self, led_count, elapsed):
        if led_count <= 1:
            return [self.colors[0]] * led_count
        span = (led_count - 1) * 2
        raw = int(elapsed * self.speed * 40) % span
        pos = raw if raw < led_count else span - raw
        frame = [Color(0, 0, 0)] * led_count
        width = min(10, led_count)
        for j in range(width):
            for idx in (pos - j, pos + j):
                if 0 <= idx < led_count:
                    frame[idx] = scale_color(self.colors[0], 1 - (j / width))
        return frame


PATTERN_REGISTRY = {
    "static_color": StaticColorPattern,
    "color_fade": ColorFadePattern,
    "theater_lighting": TheaterChasePattern,
    "rainbow": RainbowPattern,
    "pulse": PulsePattern,
    "comet": CometPattern,
    "sparkle": SparklePattern,
    "scanner": ScannerPattern,
}


def pattern_metadata():
    return {
        key: {"label": pattern.label, "color_count": pattern.color_count}
        for key, pattern in PATTERN_REGISTRY.items()
    }
