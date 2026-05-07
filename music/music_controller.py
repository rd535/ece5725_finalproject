#!/usr/bin/env python3
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np
import smbus

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rpi_ws281x import PixelStrip, Color, ws
from pacer.event_log import log_event

# Same LED setup as strandtest.py.
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 24
LED_INVERT = False
LED_CHANNEL = 0
LED_STRIP = ws.SK6812_STRIP_GRBW


class ADS1115Reader:
    """Small ADS1115 I2C reader for the MAX9814 microphone output."""

    CONVERSION_REGISTER = 0x00
    CONFIG_REGISTER = 0x01

    CHANNEL_MUX = {
        0: 0x4000,
        1: 0x5000,
        2: 0x6000,
        3: 0x7000,
    }

    DATA_RATE = {
        128: 0x0080,
        250: 0x00A0,
        475: 0x00C0,
        860: 0x00E0,
    }

    def __init__(self, bus_number=1, address=0x48, channel=0, sample_rate=860, max_retries=3):
        self.bus = smbus.SMBus(bus_number)
        self.address = address
        self.channel = channel
        self.sample_rate = sample_rate
        self.sample_delay = 1.0 / sample_rate
        self.max_retries = max_retries
        self.configure()

    def configure(self):
        if self.channel not in self.CHANNEL_MUX:
            raise ValueError("ADS1115 channel must be 0, 1, 2, or 3")

        data_rate = self.DATA_RATE.get(self.sample_rate, self.DATA_RATE[860])
        config = (
            0x8000 |
            self.CHANNEL_MUX[self.channel] |
            0x0200 |
            0x0000 |
            data_rate |
            0x0003
        )
        self._write_register(self.CONFIG_REGISTER, config)
        time.sleep(0.01)

    def read_chunk(self, chunk_size):
        samples = np.zeros(chunk_size, dtype=float)
        for i in range(chunk_size):
            samples[i] = self.read_sample()
            time.sleep(self.sample_delay)
        return samples

    def read_sample(self):
        last_error = None
        for _ in range(self.max_retries):
            try:
                data = self.bus.read_i2c_block_data(self.address, self.CONVERSION_REGISTER, 2)
                raw = (data[0] << 8) | data[1]
                if raw & 0x8000:
                    raw -= 0x10000
                return raw / 32768.0
            except OSError as exc:
                last_error = exc
                time.sleep(0.01)
        raise last_error

    def _write_register(self, register, value):
        high = (value >> 8) & 0xFF
        low = value & 0xFF
        last_error = None
        for _ in range(self.max_retries):
            try:
                self.bus.write_i2c_block_data(self.address, register, [high, low])
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.01)
        raise last_error


class MusicController:
    """Listen for BPM once, then blink the whole strip white at that BPM."""

    def __init__(
        self,
        num_leds=420,
        pin=12,
        fallback_bpm=123,
        calibration_seconds=8.0,
        sample_rate=860,
        chunk_size=64,
        min_bpm=80,
        max_bpm=150,
        pulse_seconds=0.05,
        silence_seconds=3.0,
        i2c_bus=1,
        adc_address=0x48,
        adc_channel=0,
    ):
        self.num_leds = num_leds
        self.pin = pin
        self.fallback_bpm = fallback_bpm
        self.calibration_seconds = calibration_seconds
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.pulse_seconds = pulse_seconds
        self.silence_seconds = silence_seconds
        self.i2c_bus = i2c_bus
        self.adc_address = adc_address
        self.adc_channel = adc_channel

        self.bpm = fallback_bpm
        self.beat_interval = 60.0 / fallback_bpm
        self.white = Color(255, 255, 255)
        self.strip = None
        self.adc = None
        self.thread = None
        self.monitor_thread = None
        self.silence_threshold = None
        self.active = False

    def start(self):
        """Listen for 8 seconds, estimate BPM, then start the blink thread."""
        if self.active:
            return

        self.strip = self._make_strip()
        self._fill_strip(0)
        self._startup_blink_test()
        self.adc = ADS1115Reader(
            bus_number=self.i2c_bus,
            address=self.adc_address,
            channel=self.adc_channel,
            sample_rate=self.sample_rate,
        )

        self.bpm = self.estimate_bpm()
        self.beat_interval = 60.0 / self.bpm
        self.active = True
        self.thread = threading.Thread(target=self._blink_at_bpm, daemon=True)
        self.monitor_thread = threading.Thread(target=self._monitor_silence, daemon=True)
        self.thread.start()
        self.monitor_thread.start()

        log_event(
            "Music BPM controller started",
            category="music",
            bpm=round(self.bpm, 1),
            beat_interval=round(self.beat_interval, 3),
            pulse_seconds=self.pulse_seconds,
            silence_threshold=round(self.silence_threshold, 6),
            silence_seconds=self.silence_seconds,
        )

    def stop(self):
        """Stop blinking and turn the strip off."""
        self.active = False
        current_thread = threading.current_thread()
        if self.thread and self.thread.is_alive() and self.thread is not current_thread:
            self.thread.join(timeout=1.0)
        if self.monitor_thread and self.monitor_thread.is_alive() and self.monitor_thread is not current_thread:
            self.monitor_thread.join(timeout=1.0)
        if self.strip:
            self._fill_strip(0)
        log_event("Music BPM controller stopped", category="music")


    def _startup_blink_test(self):
        """Prove the strip can turn on and off before audio starts."""
        print("LED startup blink test", flush=True)
        log_event("Music LED startup blink test", category="music")
        for blink in range(3):
            print(f"startup blink {blink + 1}", flush=True)
            self._fill_strip(self.white)
            time.sleep(0.15)
            self._fill_strip(0)
            time.sleep(0.25)

    def estimate_bpm(self):
        """Listen briefly, estimate tempo from the loudness envelope, and return BPM."""
        log_event("BPM calibration started", category="music", seconds=self.calibration_seconds)
        started = time.time()
        readings = []

        while time.time() - started < self.calibration_seconds:
            try:
                samples = self.adc.read_chunk(self.chunk_size)
            except OSError as exc:
                log_event("ADS1115 read failed during BPM calibration", level="ERROR", category="music", error=repr(exc))
                continue

            now = time.time()
            centered = samples - np.mean(samples)
            audio_level = float(np.std(centered))
            transient_level = float(np.std(np.diff(centered))) if len(centered) > 1 else 0.0
            level = max(audio_level, transient_level * 0.75)
            readings.append((now, level))

        self._set_silence_threshold(readings)
        peaks = self._find_peaks(readings)
        bpm = self._bpm_from_readings(readings)
        if bpm is None:
            log_event(
                "BPM calibration failed; using fallback",
                level="WARNING",
                category="music",
                fallback_bpm=self.fallback_bpm,
                readings=len(readings),
                peaks=len(peaks),
            )
            return self.fallback_bpm

        log_event("BPM calibration complete", category="music", bpm=round(bpm, 1), source="custom", peaks=len(peaks))
        return bpm

    def _bpm_from_readings(self, readings):
        if len(readings) < 6:
            return None

        times = np.array([timestamp for timestamp, _ in readings], dtype=float)
        levels = np.array([level for _, level in readings], dtype=float)
        dt_values = np.diff(times)
        if len(dt_values) == 0:
            return None

        dt = float(np.median(dt_values))
        if dt <= 0:
            return None

        envelope = levels - np.median(levels)
        envelope[envelope < 0] = 0.0
        if float(np.max(envelope)) <= 0:
            return None

        envelope = envelope / np.max(envelope)
        score_by_bpm = {}

        for bpm in range(self.min_bpm, self.max_bpm + 1):
            beat_interval = 60.0 / bpm
            lag = int(round(beat_interval / dt))
            if lag < 1 or lag >= len(envelope):
                continue

            left = envelope[:-lag]
            right = envelope[lag:]
            denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
            if denominator == 0:
                continue

            score_by_bpm[bpm] = float(np.dot(left, right) / denominator)

        if not score_by_bpm:
            return None

        raw_bpm = max(score_by_bpm, key=score_by_bpm.get)
        raw_score = score_by_bpm[raw_bpm]
        if raw_score <= 0:
            return None

        selected_bpm, selected_bucket = self._select_bpm_family(score_by_bpm, raw_bpm)
        log_event(
            "BPM candidates",
            category="music",
            raw_bpm=raw_bpm,
            raw_score=round(raw_score, 3),
            selected_bpm=selected_bpm,
            selected_score=round(score_by_bpm[selected_bpm], 3),
            selected_bucket=selected_bucket,
        )
        return float(selected_bpm)

    def _select_bpm_family(self, score_by_bpm, raw_bpm):
        selected_bpm = raw_bpm
        selected_score = score_by_bpm[raw_bpm]

        for _ in range(2):
            bucket = self._bpm_bucket(selected_bpm)
            next_bpm = None
            next_score = 0.0
            required_ratio = 1.0

            if bucket == "80-89":
                # Very slow readings can be either a genuinely slower pulse or
                # half-time for a fast song. Prefer fast only if it is strong.
                fast_bpm, fast_score = self._best_candidate(score_by_bpm, 140, 150)
                if fast_bpm is not None and fast_score >= selected_score * 0.82:
                    next_bpm, next_score = fast_bpm, fast_score
                    required_ratio = 0.82
                else:
                    next_bpm, next_score = self._best_candidate(score_by_bpm, 90, 109)
                    required_ratio = 0.70

            elif bucket == "90-99":
                # Some dance songs read near 100 even though the visually useful
                # flash pulse is in the 120s. Only move if that bucket is strong.
                next_bpm, next_score = self._best_candidate(score_by_bpm, 120, 129)
                required_ratio = 0.68

            elif bucket == "100-109":
                # This bucket can be either a slow song around 100, a dance song
                # around 123, or half-time for a fast song around 145. Check the
                # fast bucket first, then fall back to the 120s dance pulse.
                fast_bpm, fast_score = self._best_candidate(score_by_bpm, 140, 150)
                if fast_bpm is not None and fast_score >= selected_score * 0.82:
                    next_bpm, next_score = fast_bpm, fast_score
                    required_ratio = 0.82
                else:
                    next_bpm, next_score = self._best_candidate(score_by_bpm, 120, 129)
                    required_ratio = 0.82

            elif bucket == "110-119":
                # A syncopated slow song can land slightly too high. If the
                # true-slow bucket is close, pull it back toward 98.
                next_bpm, next_score = self._best_candidate(score_by_bpm, 95, 105)
                required_ratio = 0.76

            elif bucket == "120-129":
                # If we landed in the 120s from a half-time fast song, allow a
                # final jump to the 140s only when the fast score is very close.
                next_bpm, next_score = self._best_candidate(score_by_bpm, 140, 150)
                required_ratio = 0.94

            elif bucket in ("140-149", "150-150"):
                # Very fast readings are often subdivisions. Try the 2/3 tempo.
                target = int(round(selected_bpm * 2.0 / 3.0))
                next_bpm, next_score = self._best_near(score_by_bpm, target, window=2)
                required_ratio = 0.72

            if next_bpm is None or next_score < selected_score * required_ratio:
                break

            selected_bpm = next_bpm
            selected_score = next_score

        return selected_bpm, self._bpm_bucket(selected_bpm)

    def _bpm_bucket(self, bpm):
        bucket_low = self.min_bpm + int((bpm - self.min_bpm) // 10) * 10
        bucket_low = max(self.min_bpm, min(bucket_low, self.max_bpm))
        bucket_high = min(bucket_low + 9, self.max_bpm)
        return f"{bucket_low}-{bucket_high}"

    def _best_candidate(self, score_by_bpm, low, high):
        low = max(self.min_bpm, low)
        high = min(self.max_bpm, high)
        candidates = [(score_by_bpm[bpm], bpm) for bpm in range(low, high + 1) if bpm in score_by_bpm]
        if not candidates:
            return None, 0.0
        score, bpm = max(candidates)
        return bpm, score

    def _best_near(self, score_by_bpm, target, window=2):
        return self._best_candidate(score_by_bpm, target - window, target + window)

    def _set_silence_threshold(self, readings):
        if not readings:
            self.silence_threshold = 0.01
            return

        levels = [level for _, level in readings]
        normal_level = statistics.median(levels)
        self.silence_threshold = max(0.006, normal_level * 0.45)
        log_event(
            "Music silence threshold set",
            category="music",
            normal_level=round(normal_level, 6),
            silence_threshold=round(self.silence_threshold, 6),
        )

    def _monitor_silence(self):
        last_sound_time = time.time()

        while self.active:
            try:
                samples = self.adc.read_chunk(self.chunk_size)
            except OSError as exc:
                log_event("ADS1115 read failed during silence monitor", level="ERROR", category="music", error=repr(exc))
                time.sleep(0.05)
                continue

            centered = samples - np.mean(samples)
            audio_level = float(np.std(centered))
            threshold = self.silence_threshold or 0.01

            if audio_level >= threshold:
                last_sound_time = time.time()

            if time.time() - last_sound_time >= self.silence_seconds:
                log_event(
                    "Music stopped; turning lights off",
                    category="music",
                    audio_level=round(audio_level, 6),
                    silence_threshold=round(threshold, 6),
                    silence_seconds=self.silence_seconds,
                )
                self.active = False
                self._fill_strip(0)
                return

    def _blink_at_bpm(self):
        while self.active:
            log_event("Music BPM beat", category="music", bpm=round(self.bpm, 1))
            self._fill_strip(self.white)
            time.sleep(self.pulse_seconds)
            self._fill_strip(0)
            time.sleep(max(0.0, self.beat_interval - self.pulse_seconds))

    def _make_strip(self):
        strip = PixelStrip(
            self.num_leds,
            self.pin,
            LED_FREQ_HZ,
            LED_DMA,
            LED_INVERT,
            LED_BRIGHTNESS,
            LED_CHANNEL,
            LED_STRIP,
        )
        strip.begin()
        return strip

    def _fill_strip(self, pixel):
        pixel_count = self.strip.numPixels() if hasattr(self.strip, "numPixels") else self.num_leds
        for i in range(pixel_count):
            self.strip.setPixelColor(i, pixel)
        self.strip.show()

    def _find_peaks(self, readings):
        if len(readings) < 3:
            return []

        levels = [level for _, level in readings]
        baseline = statistics.median(levels)
        spread = statistics.pstdev(levels) if len(levels) > 1 else 0.0
        threshold = max(baseline + spread * 0.5, baseline * 1.08, 0.005)
        min_gap = 60.0 / self.max_bpm

        peaks = []
        last_peak_time = 0.0
        for index in range(1, len(readings) - 1):
            timestamp, level = readings[index]
            previous_level = readings[index - 1][1]
            next_level = readings[index + 1][1]
            if level < threshold:
                continue
            if level < previous_level or level < next_level:
                continue
            if timestamp - last_peak_time < min_gap:
                if peaks and level > peaks[-1][1]:
                    peaks[-1] = (timestamp, level)
                    last_peak_time = timestamp
                continue
            peaks.append((timestamp, level))
            last_peak_time = timestamp

        return peaks


if __name__ == "__main__":
    controller = MusicController()
    controller.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()
