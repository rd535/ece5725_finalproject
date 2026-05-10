#!/usr/bin/env python3
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import aubio
import numpy as np
from rpi_ws281x import Color, PixelStrip, ws

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pacer.event_log import log_event
from performance_logger import get_performance_logger


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
            tempo_gain = 0.13
        else:
            phase_window = min(0.12, self.interval * 0.28)
            phase_gain = 0.35
            tempo_gain = 0.08

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

        if abs(new_bpm - current_bpm) < max(12.0, current_bpm * 0.14):
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

        if current_bpm is not None and abs(new_bpm - current_bpm) < max(9.0, current_bpm * 0.09):
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

        if self.bpm is None and self.min_bpm <= raw_bpm < 125:
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
        if raw_bpm >= 200:
            slow_candidates = [item for item in candidates if 70 <= item[0] <= 115]
            if slow_candidates:
                return min(slow_candidates, key=lambda item: abs(item[0] - 90.0))[1]

        return min(candidates, key=lambda item: abs(item[0] - 110.0))[1]

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
        self.strip = strip

        self.process = None
        self.audio_thread = None
        self.blink_thread = None
        self.active = False

        self.lock = threading.Lock()
        self.tracker = BeatGridTracker(min_bpm=min_bpm, max_bpm=max_bpm)
        self.bpm = None
        self.beat_interval = None
        self.next_beat_time = None
        self.last_sound_time = None
        self.music_level = None
        self.last_logged_bpm = None
        self.started_time = None
        self.high_bpm_count = 0
        self.half_time_threshold = 140

        # Performance metrics
        self.chunk_processing_times = deque(maxlen=100)
        self.audio_read_times = deque(maxlen=100)
        self.beat_detection_latencies = deque(maxlen=100)
        self.blink_scheduling_delays = deque(maxlen=100)
        self.audio_to_led_latencies = deque(maxlen=100)
        self.bpm_history = deque(maxlen=100)
        self.beat_count = 0
        self.missed_beats = 0
        self.false_beats = 0
        self.last_beat_time = None

    def start(self):
        """Start audio tracking and LED blinking."""
        if self.active:
            return

        if self.strip is None:
            self.strip = self._make_strip()
        self.clear()
        self._startup_blink_test()

        self.process = self._start_audio_process()
        self.last_sound_time = time.time()
        self.started_time = self.last_sound_time
        self.active = True

        # Reset performance stats on start
        self.reset_performance_stats()

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

    def configure_strip(self, num_leds=None, pin=None, strip=None):
        """Configure the LED strip for the music controller."""
        self.stop()
        with self.lock:
            if num_leds is not None:
                self.num_leds = num_leds
            if pin is not None:
                self.pin = pin
            if strip is not None:
                self.strip = strip
        log_event("Music controller strip configured", category="music", num_leds=self.num_leds, pin=self.pin)

    def stop(self):
        """Stop audio capture and turn the LEDs off."""
        self.active = False

        current_thread = threading.current_thread()
        if self.audio_thread and self.audio_thread.is_alive() and self.audio_thread is not current_thread:
            self.audio_thread.join(timeout=1.0)
        if self.blink_thread and self.blink_thread.is_alive() and self.blink_thread is not current_thread:
            self.blink_thread.join(timeout=1.0)

        self._stop_audio_process()
        self.clear()
        log_event("USB music controller stopped", category="music")

    def clear(self):
        if not self.strip:
            return
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0, 0, 0, 0))
        self.strip.show()

    def _track_audio(self):
        """Read USB mic audio once, correcting the beat grid from strong onsets."""
        onset = aubio.onset("default", self.chunk_size * 2, self.chunk_size, self.sample_rate)
        onset.set_silence(-70)
        onset.set_threshold(0.12)

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
                chunk_start = time.perf_counter()
                
                # Measure audio read time
                audio_read_start = time.perf_counter()
                samples = self._read_audio_chunk()
                audio_read_end = time.perf_counter()
                self.audio_read_times.append(audio_read_end - audio_read_start)
                
                if samples is None:
                    continue

                audio_time += len(samples) / self.sample_rate
                centered = samples - np.mean(samples)
                level = float(np.std(centered))
                now = time.time()

                self._update_sound_state(level, now)
                if self._music_stopped(level, now):
                    return

                if self.bpm is not None and self.last_logged_bpm is not None:
                    if not self.last_sound_time or now - self.last_sound_time >= self.silence_seconds:
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
                            
                            # Measure beat detection latency
                            beat_detect_start = time.perf_counter()
                            accepted = self.tracker.update(candidate_time)
                            beat_detect_end = time.perf_counter()
                            
                            if accepted:
                                self.last_sound_time = now
                                detection_latency = beat_detect_end - beat_detect_start
                                self.beat_detection_latencies.append(detection_latency)
                                self.beat_count += 1
                                
                                # Measure end-to-end audio-to-LED latency
                                audio_to_led_start = time.perf_counter()
                                self._accept_tracked_beat(now)
                                audio_to_led_end = time.perf_counter()
                                self.audio_to_led_latencies.append(audio_to_led_end - audio_to_led_start)

                before_previous_level = previous_level
                previous_level = level
                previous_time = audio_time
                previous_aubio_onset = aubio_onset
                
                # Record total chunk processing time
                chunk_end = time.perf_counter()
                self.chunk_processing_times.append(chunk_end - chunk_start)
                
                # Log performance metrics periodically
                self._log_music_performance_metrics()
                
        except Exception as exc:
            self.active = False
            self.clear()
            log_event("USB music controller crashed", level="ERROR", category="music", error=repr(exc))
            raise

    def _log_music_performance_metrics(self):
        """Log music performance metrics every 10 seconds."""
        now = time.time()
        if not hasattr(self, '_last_music_metrics_log'):
            self._last_music_metrics_log = now
            return
        
        if now - self._last_music_metrics_log < 10.0:
            return
        
        self._last_music_metrics_log = now
        perf_logger = get_performance_logger()
        
        if len(self.chunk_processing_times) >= 5:
            avg_chunk_proc = sum(self.chunk_processing_times) / len(self.chunk_processing_times)
            avg_audio_read = sum(self.audio_read_times) / len(self.audio_read_times)
            
            chunk_duration = self.chunk_size / self.sample_rate  # Expected chunk time
            
            perf_logger.log_music_audio_performance(
                avg_chunk_proc_ms=avg_chunk_proc * 1000,
                avg_audio_read_ms=avg_audio_read * 1000,
                chunk_duration_ms=chunk_duration * 1000,
                realtime_ratio=avg_chunk_proc / chunk_duration
            )
        
        if len(self.beat_detection_latencies) >= 3:
            avg_beat_detect = sum(self.beat_detection_latencies) / len(self.beat_detection_latencies)
            avg_audio_to_led = (sum(self.audio_to_led_latencies) / len(self.audio_to_led_latencies) * 1000) if self.audio_to_led_latencies else 0
            avg_blink_delay = (sum(self.blink_scheduling_delays) / len(self.blink_scheduling_delays) * 1000) if self.blink_scheduling_delays else 0
            
            perf_logger.log_music_beat_performance(
                avg_beat_detect_ms=avg_beat_detect * 1000,
                beats_detected=self.beat_count,
                avg_audio_to_led_ms=avg_audio_to_led,
                avg_blink_delay_ms=avg_blink_delay
            )

    def _update_sound_state(self, level, now):
        if self.music_level is None and level >= self.min_audio_level:
            self.music_level = level
        elif self.music_level is not None and level > self.music_level:
            self.music_level = self.music_level * 0.90 + level * 0.10

        silence_level = self._silence_level()
        if self.bpm is None and level >= silence_level:
            self.last_sound_time = now

    def _music_stopped(self, level, now):
        silence_level = self._silence_level()
        if level >= silence_level:
            return False

        if self.started_time and now - self.started_time < self.silence_seconds + 3.0:
            return False

        if self.last_sound_time and now - self.last_sound_time < self.silence_seconds:
            return False

        log_event(
            "USB music stopped; turning lights off",
            category="music",
            audio_level=round(level, 6),
            silence_level=round(silence_level, 6),
        )
        self.active = False
        self.clear()
        return True

    def _silence_level(self):
        if self.music_level is None:
            return self.min_audio_level
        return max(self.min_audio_level, self.music_level * 0.30)

    def _display_interval(self, bpm, interval):
        if bpm is not None and bpm >= self.half_time_threshold:
            return interval * 2.0
        return interval

    def _accept_tracked_beat(self, wall_time):
        with self.lock:
            self.bpm = self.tracker.bpm
            self.beat_interval = self._display_interval(self.bpm, self.tracker.interval)
            self.next_beat_time = time.perf_counter()  # Use monotonic clock for scheduling
            rounded_bpm = round(self.bpm, 1) if self.bpm is not None else None
            should_log = rounded_bpm is not None and (
                self.last_logged_bpm is None or abs(rounded_bpm - self.last_logged_bpm) >= 1.0
            )
            if should_log:
                self.last_logged_bpm = rounded_bpm
            
            # Capture BPM value inside lock for safe access
            current_bpm = self.bpm
            beat_count = self.beat_count

        if should_log:
            log_event("USB BPM updated", category="music", bpm=rounded_bpm)

        # Track rolling BPM history and write average BPM to CSV.
        if current_bpm is not None:
            self.bpm_history.append(current_bpm)
            average_bpm = sum(self.bpm_history) / len(self.bpm_history)
            try:
                perf_logger = get_performance_logger()
                perf_logger.log_music_bpm_average(
                    current_bpm=rounded_bpm,
                    average_bpm=average_bpm,
                    beat_count=beat_count,
                )
            except Exception as exc:
                # Log CSV write errors but don't block beat updates
                log_event("Error writing BPM to CSV", level="ERROR", category="music", error=repr(exc))

    def _blink_loop(self):
        """Flash white at the current beat grid."""
        while self.active:
            with self.lock:
                beat_interval = self.beat_interval
                next_beat_time = self.next_beat_time

            if beat_interval is None or next_beat_time is None:
                time.sleep(0.01)
                continue

            now = time.perf_counter()  # Use monotonic clock
            if now < next_beat_time:
                time.sleep(min(0.01, next_beat_time - now))
                continue

            # Measure blink scheduling delay (how late we are)
            scheduled_time = next_beat_time
            actual_blink_time = time.perf_counter()
            blink_delay = actual_blink_time - scheduled_time
            self.blink_scheduling_delays.append(blink_delay)

            self._set_all(Color(255, 255, 255))
            time.sleep(self.pulse_seconds)
            self.clear()

            with self.lock:
                while self.next_beat_time is not None and self.next_beat_time <= time.perf_counter():
                    self.next_beat_time += self.beat_interval or beat_interval

    def _make_strip(self):
        strip = PixelStrip(
            self.num_leds,
            self.pin,
            800000,
            10,
            False,
            24,
            0,
            ws.SK6812_STRIP_GRBW,
        )
        strip.begin()
        return strip

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
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, color)
        self.strip.show()

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

    def _read_audio_chunk(self):
        """Read one raw audio chunk from the arecord subprocess."""
        if not self.process or self.process.stdout is None:
            return None

        bytes_needed = self.chunk_size * 2
        raw_bytes = bytearray()

        while len(raw_bytes) < bytes_needed:
            chunk = self.process.stdout.read(bytes_needed - len(raw_bytes))
            if not chunk:
                return None
            raw_bytes.extend(chunk)

        try:
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            return samples
        except Exception as exc:
            log_event("Failed to decode audio chunk", level="ERROR", category="music", error=repr(exc))
            return None

    def _stop_audio_process(self):
        if self.process:
            self.process.terminate()
            self.process = None

    def get_performance_stats(self):
        """Get current performance statistics."""
        stats = {
            "beats_detected": self.beat_count,
            "current_bpm": round(self.bpm, 1) if self.bpm else None,
        }
        
        if len(self.chunk_processing_times) >= 3:
            stats["audio_performance"] = {
                "avg_chunk_proc_ms": round(sum(self.chunk_processing_times) / len(self.chunk_processing_times) * 1000, 2),
                "avg_audio_read_ms": round(sum(self.audio_read_times) / len(self.audio_read_times) * 1000, 2),
                "chunk_duration_ms": round(self.chunk_size / self.sample_rate * 1000, 2),
                "realtime_ratio": round((sum(self.chunk_processing_times) / len(self.chunk_processing_times)) / (self.chunk_size / self.sample_rate), 2),
                "samples": len(self.chunk_processing_times)
            }
        
        if len(self.beat_detection_latencies) >= 2:
            stats["beat_performance"] = {
                "avg_beat_detect_ms": round(sum(self.beat_detection_latencies) / len(self.beat_detection_latencies) * 1000, 2),
                "avg_audio_to_led_ms": round(sum(self.audio_to_led_latencies) / len(self.audio_to_led_latencies) * 1000, 2) if self.audio_to_led_latencies else 0,
                "avg_blink_delay_ms": round(sum(self.blink_scheduling_delays) / len(self.blink_scheduling_delays) * 1000, 2) if self.blink_scheduling_delays else 0,
                "samples": len(self.beat_detection_latencies)
            }
        
        return stats

    def reset_performance_stats(self):
        """Reset all performance statistics."""
        self.chunk_processing_times.clear()
        self.audio_read_times.clear()
        self.beat_detection_latencies.clear()
        self.blink_scheduling_delays.clear()
        self.audio_to_led_latencies.clear()
        self.bpm_history.clear()
        self.beat_count = 0
        self.missed_beats = 0
        self.false_beats = 0
        self.last_beat_time = None


if __name__ == "__main__":
    controller = MusicController()
    try:
        controller.start()
        while controller.active:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()
