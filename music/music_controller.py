#!/usr/bin/env python3
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, make_strip

try:
    import aubio
    AUBIO_AVAILABLE = True
except ImportError:
    aubio = None
    AUBIO_AVAILABLE = False


class BeatGridTracker:
    """Track beat phase and tempo from noisy onset candidates."""

    def __init__(self, min_bpm=80, max_bpm=180):
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.min_interval = 60.0 / max_bpm
        self.max_interval = 60.0 / min_bpm
        self.interval = None
        self.anchor_time = None
        self.candidates = []
        self.pending_candidates = []
        self.relock_candidates = []

    @property
    def bpm(self):
        if self.interval is None:
            return None
        return 60.0 / self.interval

    def update(self, beat_time):
        """Return True when this candidate fits, initializes, or re-locks the beat grid."""
        if self.interval is None:
            return self._try_initial_lock(beat_time)

        beats_since_anchor = round((beat_time - self.anchor_time) / self.interval)
        if beats_since_anchor < 1:
            return False

        predicted_time = self.anchor_time + beats_since_anchor * self.interval
        error = beat_time - predicted_time
        current_bpm = self.bpm
        if current_bpm is not None and current_bpm >= 135:
            phase_window = min(0.08, self.interval * 0.20)
            phase_gain = 0.45
            tempo_gain = 0.20
        else:
            phase_window = min(0.12, self.interval * 0.28)
            phase_gain = 0.35
            tempo_gain = 0.14

        if abs(error) <= phase_window:
            corrected_anchor = predicted_time + phase_gain * error
            corrected_interval = self.interval + tempo_gain * error / beats_since_anchor
            self.interval = self._clamp_interval(corrected_interval)
            self.anchor_time = corrected_anchor
            self.pending_candidates = []
            return True

        if self._try_fast_relock(beat_time):
            return True

        return self._try_tempo_change(beat_time)

    def _try_initial_lock(self, beat_time):
        self.candidates.append(beat_time)
        self.candidates = self.candidates[-8:]
        interval = self._interval_from_candidates(self.candidates, required_intervals=2, prefer_current=False)
        if interval is None:
            return False

        self.interval = interval
        self.anchor_time = self.candidates[-1]
        return True

    def _try_fast_relock(self, beat_time):
        self.relock_candidates.append(beat_time)
        self.relock_candidates = self.relock_candidates[-5:]

        interval = self._interval_from_candidates(self.relock_candidates, required_intervals=3, prefer_current=False)
        if interval is None:
            return False

        current_bpm = self.bpm
        new_bpm = 60.0 / interval
        if current_bpm is None:
            return False

        if abs(new_bpm - current_bpm) < max(5.0, current_bpm * 0.05):
            return False

        self.interval = interval
        self.anchor_time = self.relock_candidates[-1]
        self.candidates = self.relock_candidates[-4:]
        self.pending_candidates = []
        self.relock_candidates = []
        return True

    def _try_tempo_change(self, beat_time):
        self.pending_candidates.append(beat_time)
        self.pending_candidates = self.pending_candidates[-5:]
        current_bpm = self.bpm

        interval = self._interval_from_candidates(self.pending_candidates, required_intervals=2, prefer_current=False)
        if interval is None:
            return False

        new_bpm = 60.0 / interval

        if current_bpm is not None and abs(new_bpm - current_bpm) < max(3.0, current_bpm * 0.03):
            return False

        self.interval = interval
        self.anchor_time = self.pending_candidates[-1]
        self.candidates = self.pending_candidates[-4:]
        self.pending_candidates = []
        return True

    def _interval_from_candidates(self, candidates, required_intervals, prefer_current=True):
        if len(candidates) < required_intervals + 1:
            return None

        intervals = np.array([
            candidates[i] - candidates[i - 1]
            for i in range(1, len(candidates))
            if candidates[i] > candidates[i - 1]
        ], dtype=float)
        if intervals.size < required_intervals:
            return None

        intervals = intervals[(intervals >= self.min_interval * 0.65) & (intervals <= self.max_interval * 1.35)]
        if intervals.size < required_intervals:
            return None

        median_interval = float(np.median(intervals))
        raw_bpm = 60.0 / median_interval if median_interval > 0 else 0.0
        interval_tolerance = 0.16 if raw_bpm >= 135 else 0.22
        close = intervals[np.abs(intervals - median_interval) <= median_interval * interval_tolerance]
        if close.size < required_intervals:
            return None

        interval = float(np.median(close))
        interval = self._choose_music_interval(interval, prefer_current=prefer_current)

        if interval is not None and self.min_interval <= interval <= self.max_interval:
            return interval
        return None

    def _choose_music_interval(self, interval, prefer_current=True):
        raw_bpm = 60.0 / interval

        # If already locked, preserve plausible normal/fast song BPMs.
        # During initial lock, avoid grabbing a fast subdivision before the
        # slower main pulse has had a chance to appear.
        if self.bpm is not None and self.min_bpm <= raw_bpm <= 155:
            return interval

        if self.bpm is None and self.min_bpm <= raw_bpm <= self.max_bpm:
            return interval

        candidates = []
        for multiple in (1.0, 2.0, 3.0):
            candidate_interval = interval * multiple
            candidate_bpm = 60.0 / candidate_interval
            if 70 <= candidate_bpm <= self.max_bpm:
                candidates.append((candidate_bpm, candidate_interval))

        if not candidates:
            return None

        current_bpm = self.bpm
        if prefer_current and current_bpm is not None:
            slower_candidates = [item for item in candidates if 80 <= item[0] <= 115]
            if current_bpm >= 140 and raw_bpm >= 140 and slower_candidates:
                return min(slower_candidates, key=lambda item: abs(item[0] - 90.0))[1]
            return min(candidates, key=lambda item: abs(item[0] - current_bpm))[1]

        # For initial music lock, only force the slower pulse when the raw
        # candidate is a very dense subdivision. Otherwise choose a normal
        # music pulse near 110 so real 105-125 BPM songs do not fold too low.
        if raw_bpm >= self.max_bpm * 1.15:
            slow_candidates = [item for item in candidates if 70 <= item[0] <= 115]
            if slow_candidates:
                return min(slow_candidates, key=lambda item: abs(item[0] - 90.0))[1]

        return min(candidates, key=lambda item: abs(item[0] - 135.0))[1]

    def _clamp_interval(self, interval):
        return min(self.max_interval, max(self.min_interval, interval))


class MusicController:
    """Continuously detect BPM from a USB mic and flash the LEDs in sync."""

    def __init__(
        self,
        num_leds=420,
        pin=12,
        device="plughw:CARD=Device,DEV=0",
        sample_rate=44100,
        chunk_size=1024,
        min_bpm=80,
        max_bpm=180,
        pulse_seconds=0.05,
        silence_seconds=5.0,
        min_audio_level=0.0008,
        strip=None,
        startup_test=False,
        pulse_color=None,
        pulse_color_hex="#ffffff",
        beat_timeout_seconds=3.0,
        fade_seconds=0.22,
    ):
        self.num_leds = num_leds
        self.pin = pin
        self.device = device
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.min_bpm = min_bpm
        self.max_bpm = max_bpm
        self.pulse_seconds = pulse_seconds
        self.silence_seconds = silence_seconds
        self.min_audio_level = min_audio_level
        self.startup_test = startup_test
        self.pulse_color = pulse_color or Color(255, 255, 255)
        self.pulse_color_hex = pulse_color_hex
        self.beat_timeout_seconds = beat_timeout_seconds
        self.fade_seconds = fade_seconds

        self.strip = strip
        self.process = None
        self.audio_thread = None
        self.blink_thread = None
        self.active = False

        self.lock = threading.Lock()
        self.strip_lock = threading.Lock()
        self.tracker = BeatGridTracker(min_bpm=min_bpm, max_bpm=max_bpm)
        self.bpm = None
        self.beat_interval = None
        self.next_beat_time = None
        self.last_sound_time = None
        self.music_level = None
        self.last_logged_bpm = None
        self.started_time = None
        self.last_beat_wall_time = None
        self.silence_logged = False
        self.last_audio_level = 0.0
        self.last_signal_floor = self.min_audio_level
        self.audio_chunks = 0
        self.beat_candidates = 0
        self.accepted_beats = 0
        self.last_audio_time = None
        self.visual_pulse_started_at = None
        self.visual_pulse_intensity = 0.0
        self.high_bpm_count = 0

    def start(self):
        """Start audio tracking and LED blinking."""
        if self.active:
            return
        if not AUBIO_AVAILABLE:
            raise RuntimeError("aubio is not installed; music beat detection cannot start")

        if self.strip is None:
            self.strip = self._make_strip()
        self.clear()
        if self.startup_test:
            self._startup_blink_test()

        self.process = self._start_audio_process()
        now = time.time()
        self.last_sound_time = None
        self.started_time = now
        self.last_beat_wall_time = None
        self.silence_logged = False
        self.last_audio_level = 0.0
        self.last_signal_floor = self.min_audio_level
        self.audio_chunks = 0
        self.beat_candidates = 0
        self.accepted_beats = 0
        self.last_audio_time = None
        self.visual_pulse_started_at = None
        self.visual_pulse_intensity = 0.0
        self.active = True

        self.audio_thread = threading.Thread(target=self._track_audio, daemon=True)
        self.blink_thread = threading.Thread(target=self._blink_loop, daemon=True)
        self.audio_thread.start()
        self.blink_thread.start()

        log_event(
            "USB music controller started",
            category="music",
            mode="beat_grid_tracker",
            min_bpm=self.min_bpm,
            max_bpm=self.max_bpm,
            pulse_seconds=self.pulse_seconds,
            silence_seconds=self.silence_seconds,
            device=self.device,
        )

    def stop(self):
        """Stop audio capture and turn the LEDs off."""
        was_active = self.active
        self.active = False

        current_thread = threading.current_thread()
        if self.audio_thread and self.audio_thread.is_alive() and self.audio_thread is not current_thread:
            self.audio_thread.join(timeout=1.0)
        if self.blink_thread and self.blink_thread.is_alive() and self.blink_thread is not current_thread:
            self.blink_thread.join(timeout=1.0)

        self._stop_audio_process()
        self.clear()
        if was_active:
            log_event("USB music controller stopped", category="music")

    def configure_strip(self, num_leds=None, pin=None, strip=None):
        self.stop()
        self.num_leds = num_leds or self.num_leds
        self.pin = pin or self.pin
        self.strip = strip or make_strip(self.num_leds, self.pin)
        self.clear()
        log_event("USB music strip configured", category="music", num_leds=self.num_leds, pin=self.pin)

    def set_pulse_color(self, pulse_color, pulse_color_hex=None):
        with self.lock:
            self.pulse_color = pulse_color
            if pulse_color_hex:
                self.pulse_color_hex = pulse_color_hex

    def status(self):
        with self.lock:
            bpm = round(self.bpm, 1) if self.bpm is not None else None
            color = self.pulse_color_hex
            audio_level = round(self.last_audio_level, 6)
            signal_floor = round(self.last_signal_floor, 6)
            audio_chunks = self.audio_chunks
            beat_candidates = self.beat_candidates
            accepted_beats = self.accepted_beats
            last_audio_age = round(time.time() - self.last_audio_time, 2) if self.last_audio_time else None
            audio_process_alive = self.process is not None and self.process.poll() is None
            audio_thread_alive = self.audio_thread is not None and self.audio_thread.is_alive()
            healthy = self.active and audio_process_alive and audio_thread_alive and (
                last_audio_age is None or last_audio_age <= 2.0
            )
        return {
            "active": healthy,
            "controller_active": self.active,
            "bpm": bpm,
            "started_at": self.started_time,
            "color": color,
            "audio_level": audio_level,
            "signal_floor": signal_floor,
            "audio_chunks": audio_chunks,
            "beat_candidates": beat_candidates,
            "accepted_beats": accepted_beats,
            "last_audio_age": last_audio_age,
            "audio_process_alive": audio_process_alive,
            "audio_thread_alive": audio_thread_alive,
        }

    def clear(self):
        if not self.strip:
            return
        with self.strip_lock:
            for i in range(self.pixel_count()):
                self.strip.setPixelColor(i, Color(0, 0, 0))
            self.strip.show()

    def pixel_count(self):
        if self.strip and hasattr(self.strip, "numPixels"):
            return min(self.num_leds, int(self.strip.numPixels()))
        return self.num_leds

    def _track_audio(self):
        """Read USB mic audio once, correcting the beat grid from strong onsets."""
        onset = aubio.onset("default", self.chunk_size * 2, self.chunk_size, self.sample_rate)
        onset.set_silence(-70)
        onset.set_threshold(0.08)

        level_history = []
        audio_time = 0.0
        previous_time = None
        previous_level = None
        before_previous_level = None
        previous_aubio_onset = False
        min_candidate_gap = 60.0 / self.max_bpm * 0.65
        last_candidate_time = None

        try:
            while self.active:
                samples = self._read_audio_chunk()
                if samples is None:
                    if self.process is not None and self.process.poll() is not None:
                        self.active = False
                        self._reset_beat_lock()
                        self.clear()
                        log_event("USB audio process stopped", level="ERROR", category="music")
                        return
                    continue

                audio_time += len(samples) / self.sample_rate
                centered = samples - np.mean(samples)
                level = float(np.std(centered))
                now = time.time()
                with self.lock:
                    self.last_audio_level = level
                    self.audio_chunks += 1
                    self.last_audio_time = now

                self._update_sound_state(level, now)
                if self._music_stopped(level, now):
                    continue

                signal_floor = self.min_audio_level
                with self.lock:
                    self.last_signal_floor = signal_floor
                if level < signal_floor:
                    before_previous_level = previous_level
                    previous_level = level
                    previous_time = audio_time
                    previous_aubio_onset = False
                    continue

                max_abs = float(np.max(np.abs(centered)))
                normalized = centered / max_abs if max_abs > 0 else centered
                aubio_onset = bool(onset(normalized.astype(np.float32))[0])

                level_history.append(level)
                level_history = level_history[-40:]
                baseline = float(np.median(level_history))
                spread = float(np.std(level_history))
                threshold = max(self.min_audio_level * 1.5, baseline + spread * 1.15, baseline * 1.30)

                if previous_level is not None and before_previous_level is not None:
                    is_peak = previous_level >= before_previous_level and previous_level > level
                    is_loud = previous_level >= threshold
                    is_supported = previous_aubio_onset or previous_level >= baseline + spread * 1.6

                    if is_peak and is_loud and is_supported:
                        candidate_time = previous_time
                        if last_candidate_time is None or candidate_time - last_candidate_time >= min_candidate_gap:
                            last_candidate_time = candidate_time
                            with self.lock:
                                self.beat_candidates += 1
                            accepted = self.tracker.update(candidate_time)
                            if accepted:
                                self.last_sound_time = now
                                self._accept_tracked_beat(now)

                before_previous_level = previous_level
                previous_level = level
                previous_time = audio_time
                previous_aubio_onset = aubio_onset
        except Exception as exc:
            self.active = False
            self.clear()
            log_event("USB music controller crashed", level="ERROR", category="music", error=repr(exc))
            raise

    def _update_sound_state(self, level, now):
        if self.music_level is None and level >= self.min_audio_level:
            self.music_level = level
        elif self.music_level is not None and level > self.music_level:
            self.music_level = self.music_level * 0.90 + level * 0.10

        silence_level = self._silence_level()
        if self.bpm is None and level >= silence_level:
            self.last_sound_time = now
            self.silence_logged = False

    def _music_stopped(self, level, now):
        silence_level = self._silence_level()
        if level >= silence_level:
            self.silence_logged = False
            return False

        if self.started_time and now - self.started_time < self.silence_seconds + 3.0:
            return False

        if self.last_sound_time and now - self.last_sound_time < self.silence_seconds:
            return False

        if not self.silence_logged:
            log_event(
                "USB music stopped; turning lights off",
                category="music",
                audio_level=round(level, 6),
                silence_level=round(silence_level, 6),
            )
            self.silence_logged = True
        self._reset_beat_lock()
        self.clear()
        return False

    def _silence_level(self):
        if self.music_level is None:
            return self.min_audio_level
        return max(self.min_audio_level, self.music_level * 0.30)

    def _display_interval(self, bpm, interval):
        return interval

    def _accept_tracked_beat(self, wall_time):
        with self.lock:
            self.bpm = self.tracker.bpm
            self.beat_interval = self._display_interval(self.bpm, self.tracker.interval)
            if self.next_beat_time is None:
                self.next_beat_time = wall_time
            else:
                phase_error = wall_time - self.next_beat_time
                while phase_error > self.beat_interval / 2:
                    phase_error -= self.beat_interval
                while phase_error < -self.beat_interval / 2:
                    phase_error += self.beat_interval
                self.next_beat_time += phase_error * 0.15
            self.last_beat_wall_time = wall_time
            self.accepted_beats += 1
            rounded_bpm = round(self.bpm, 1) if self.bpm is not None else None
            should_log = rounded_bpm is not None and (
                self.last_logged_bpm is None or abs(rounded_bpm - self.last_logged_bpm) >= 1.0
            )
            if should_log:
                self.last_logged_bpm = rounded_bpm

        if should_log:
            log_event("USB BPM updated", category="music", bpm=rounded_bpm)

    def _blink_loop(self):
        """Render a steady beat grid with smooth audio-scaled pulses."""
        while self.active:
            with self.lock:
                beat_interval = self.beat_interval
                next_beat_time = self.next_beat_time
                last_beat_wall_time = self.last_beat_wall_time
                pulse_color = self.pulse_color
                pulse_started_at = self.visual_pulse_started_at
                pulse_intensity = self.visual_pulse_intensity

            if last_beat_wall_time is not None and time.time() - last_beat_wall_time > self.beat_timeout_seconds:
                self._reset_beat_lock()
                self.clear()
                time.sleep(0.02)
                continue

            if beat_interval is None or next_beat_time is None:
                time.sleep(0.01)
                continue

            now = time.time()
            beat_fired = False
            while next_beat_time is not None and now >= next_beat_time:
                beat_fired = True
                next_beat_time += beat_interval

            if beat_fired:
                pulse_started_at = now
                pulse_intensity = self._audio_intensity()
                with self.lock:
                    self.next_beat_time = next_beat_time
                    self.visual_pulse_started_at = pulse_started_at
                    self.visual_pulse_intensity = pulse_intensity

            brightness = self._fade_brightness(pulse_started_at, pulse_intensity, now)
            if brightness > 0:
                self._set_all(self._scale_color(pulse_color, brightness))
            else:
                self.clear()

            time.sleep(0.02)

    def _make_strip(self):
        return make_strip(self.num_leds, self.pin)

    def _startup_blink_test(self):
        print("LED startup blink test", flush=True)
        log_event("USB music LED startup blink test", category="music")
        for blink in range(3):
            print(f"startup blink {blink + 1}", flush=True)
            self._set_all(Color(255, 255, 255))
            time.sleep(0.12)
            self.clear()
            time.sleep(0.12)

    def _set_all(self, color):
        with self.strip_lock:
            for i in range(self.pixel_count()):
                self.strip.setPixelColor(i, color)
            self.strip.show()

    def _audio_intensity(self):
        with self.lock:
            level = self.last_audio_level
            reference = max(self.min_audio_level * 2.0, (self.music_level or self.min_audio_level) * 0.65)
        normalized = max(0.0, min(1.0, level / reference))
        return max(0.12, min(1.0, normalized * normalized))

    def _fade_brightness(self, pulse_started_at, pulse_intensity, now):
        if pulse_started_at is None:
            return 0.0
        age = now - pulse_started_at
        if age < 0 or age > self.fade_seconds:
            return 0.0
        fade = 1.0 - (age / self.fade_seconds)
        return max(0.0, min(1.0, pulse_intensity * fade * fade))

    def _scale_color(self, color, brightness):
        if isinstance(color, (tuple, list)):
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            return Color(int(r * brightness), int(g * brightness), int(b * brightness))
        else:
            value = int(color)
            high = int(((value >> 16) & 255) * brightness)
            mid = int(((value >> 8) & 255) * brightness)
            low = int((value & 255) * brightness)
            return (high << 16) | (mid << 8) | low

    def _reset_beat_lock(self):
        with self.lock:
            self.tracker = BeatGridTracker(min_bpm=self.min_bpm, max_bpm=self.max_bpm)
            self.bpm = None
            self.beat_interval = None
            self.next_beat_time = None
            self.last_beat_wall_time = None
            self.last_logged_bpm = None
            self.visual_pulse_started_at = None
            self.visual_pulse_intensity = 0.0

    def _start_audio_process(self):
        command = [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(self.sample_rate),
            "-t",
            "raw",
        ]
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _stop_audio_process(self):
        if self.process:
            self.process.terminate()
            self.process = None

    def _read_audio_chunk(self):
        bytes_to_read = self.chunk_size * 2
        raw_audio = self.process.stdout.read(bytes_to_read)
        if len(raw_audio) < bytes_to_read:
            return None
        return np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0


if __name__ == "__main__":
    controller = MusicController()
    try:
        controller.start()
        while controller.active:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()
