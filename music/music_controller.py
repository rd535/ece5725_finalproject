#!/usr/bin/env python3
import threading
import time

import numpy as np
import smbus

from music.bpm_detector import BeatDetector
from music.music_light_pattern import MusicLightPattern
from pacer.event_log import log_event
from pacer.pacer_pattern import make_strip


class ADS1115Reader:
    """Small ADS1115 I2C reader for one microphone ADC channel."""

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

    def __init__(self, bus_number=1, address=0x48, channel=0, sample_rate=860):
        self.bus = smbus.SMBus(bus_number)
        self.address = address
        self.channel = channel
        self.sample_rate = sample_rate
        self.sample_delay = 1.0 / sample_rate
        self.configure()

    def configure(self):
        if self.channel not in self.CHANNEL_MUX:
            raise ValueError("ADS1115 channel must be 0, 1, 2, or 3")

        data_rate = self.DATA_RATE.get(self.sample_rate, self.DATA_RATE[860])
        config = (
            0x8000 |                         # start conversion
            self.CHANNEL_MUX[self.channel] | # single-ended channel
            0x0200 |                         # +/- 4.096 V range
            0x0000 |                         # continuous conversion mode
            data_rate |
            0x0003                           # disable comparator
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
        data = self.bus.read_i2c_block_data(self.address, self.CONVERSION_REGISTER, 2)
        raw = (data[0] << 8) | data[1]
        if raw & 0x8000:
            raw -= 0x10000
        return raw / 32768.0

    def _write_register(self, register, value):
        high = (value >> 8) & 0xFF
        low = value & 0xFF
        self.bus.write_i2c_block_data(self.address, register, [high, low])


class MusicController:
    """Read ADC microphone audio, detect bass beats, and flash the LED strip."""

    def __init__(
        self,
        num_leds=300,
        pin=12,
        sample_rate=860,
        chunk_size=128,
        color=(255, 255, 255),
        i2c_bus=1,
        adc_address=0x48,
        adc_channel=0,
        bass_low=20,
        bass_high=180,
        sensitivity=1.4,
        history_size=20,
        cooldown=0.12,
    ):
        self.num_leds = num_leds
        self.pin = pin
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.i2c_bus = i2c_bus
        self.adc_address = adc_address
        self.adc_channel = adc_channel
        self.bass_low = bass_low
        self.bass_high = bass_high
        self.sensitivity = sensitivity
        self.history_size = history_size
        self.cooldown = cooldown

        self.detector = BeatDetector(
            sample_rate=sample_rate,
            bass_low=bass_low,
            bass_high=bass_high,
            sensitivity=sensitivity,
            history_size=history_size,
            cooldown=cooldown,
        )
        self.pattern = MusicLightPattern(color=color)

        self.strip = None
        self.adc = None
        self.thread = None
        self.active = False

    def start(self):
        """Start ADC sampling and LED rendering in a background thread."""
        if self.active:
            return

        self.strip = make_strip(self.num_leds, self.pin)
        self.adc = ADS1115Reader(
            bus_number=self.i2c_bus,
            address=self.adc_address,
            channel=self.adc_channel,
            sample_rate=self.sample_rate,
        )
        self.active = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        log_event(
            "Music controller started",
            category="music",
            sample_rate=self.sample_rate,
            adc_address=hex(self.adc_address),
            adc_channel=self.adc_channel,
            bass_low=self.bass_low,
            bass_high=self.bass_high,
            sensitivity=self.sensitivity,
        )

    def stop(self):
        """Stop ADC sampling and turn the LEDs off."""
        self.active = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

        if self.strip:
            self.pattern.clear(self.strip, self.num_leds)

        log_event("Music controller stopped", category="music")

    def process_samples(self, samples):
        """Process one audio chunk. Useful for tests or non-ADC input."""
        if self.detector.detect(samples):
            self.pattern.on_beat()
            return True
        return False

    def _run(self):
        try:
            while self.active:
                samples = self.adc.read_chunk(self.chunk_size)
                self.process_samples(samples)
                self.pattern.render(self.strip, self.num_leds)
        except Exception as exc:
            self.active = False
            log_event("Music controller crashed", level="ERROR", category="music", error=repr(exc))
            raise


if __name__ == "__main__":
    controller = MusicController()
    controller.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()
