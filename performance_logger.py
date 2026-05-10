"""CSV-based performance logging for pacer, lighting, and music systems."""

import csv
import threading
import time
from pathlib import Path


class PerformanceLogger:
    """Logs performance metrics to CSV files for analysis and trending."""

    def __init__(self, log_dir="performance_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.lock = threading.Lock()
        
        # Define CSV files for each system
        self.files = {
            'pacer': self.log_dir / 'pacer_performance.csv',
            'pacer_control': self.log_dir / 'pacer_control_performance.csv',
            'lighting': self.log_dir / 'lighting_performance.csv',
            'lighting_control': self.log_dir / 'lighting_control_performance.csv',
            'music_audio': self.log_dir / 'music_audio_performance.csv',
            'music_beat': self.log_dir / 'music_beat_performance.csv',
            'music_bpm': self.log_dir / 'music_bpm.csv',
            'api': self.log_dir / 'api_performance.csv'
        }

    def log_pacer_performance(self, frame_interval_ms, frame_jitter_ms, collect_ms, render_ms, lock_wait_ms, total_ms):
        """Log pacer frame timing metrics."""
        data = {
            'timestamp': time.time(),
            'frame_interval_ms': round(frame_interval_ms, 2),
            'frame_jitter_ms': round(frame_jitter_ms, 2),
            'collect_ms': round(collect_ms, 2),
            'render_ms': round(render_ms, 2),
            'lock_wait_ms': round(lock_wait_ms, 2),
            'total_ms': round(total_ms, 2)
        }
        self._write_csv('pacer', data)

    def log_pacer_control_performance(self, action, latency_ms, pacer_name=None, pacer_type=None, pace=None, distance=None):
        """Log pacer start/stop control latency."""
        data = {
            'timestamp': time.time(),
            'action': action,
            'latency_ms': round(latency_ms, 2),
            'pacer_name': pacer_name,
            'pacer_type': pacer_type,
            'pace': pace,
            'distance': distance
        }
        self._write_csv('pacer_control', data)

    def log_lighting_performance(self, frame_interval_ms, frame_jitter_ms, frame_gen_ms, render_ms, 
                                  lock_wait_ms, total_frame_ms):
        """Log lighting frame timing metrics."""
        data = {
            'timestamp': time.time(),
            'frame_interval_ms': round(frame_interval_ms, 2),
            'frame_jitter_ms': round(frame_jitter_ms, 2),
            'frame_gen_ms': round(frame_gen_ms, 2),
            'render_ms': round(render_ms, 2),
            'lock_wait_ms': round(lock_wait_ms, 2),
            'total_frame_ms': round(total_frame_ms, 2)
        }
        self._write_csv('lighting', data)

    def log_lighting_control_performance(self, action, latency_ms, pattern=None, colors=None, speed=None):
        """Log lighting start/stop control latency."""
        data = {
            'timestamp': time.time(),
            'action': action,
            'latency_ms': round(latency_ms, 2),
            'pattern': pattern,
            'colors': str(colors) if colors is not None else None,
            'speed': speed
        }
        self._write_csv('lighting_control', data)

    def log_music_audio_performance(self, avg_chunk_proc_ms, avg_audio_read_ms, chunk_duration_ms, realtime_ratio):
        """Log music audio processing metrics."""
        data = {
            'timestamp': time.time(),
            'avg_chunk_proc_ms': round(avg_chunk_proc_ms, 2),
            'avg_audio_read_ms': round(avg_audio_read_ms, 2),
            'chunk_duration_ms': round(chunk_duration_ms, 2),
            'realtime_ratio': round(realtime_ratio, 2)
        }
        self._write_csv('music_audio', data)

    def log_music_beat_performance(self, avg_beat_detect_ms, beats_detected, avg_audio_to_led_ms, avg_blink_delay_ms):
        """Log music beat detection metrics."""
        data = {
            'timestamp': time.time(),
            'avg_beat_detect_ms': round(avg_beat_detect_ms, 2),
            'beats_detected': beats_detected,
            'avg_audio_to_led_ms': round(avg_audio_to_led_ms, 2),
            'avg_blink_delay_ms': round(avg_blink_delay_ms, 2)
        }
        self._write_csv('music_beat', data)

    def log_music_bpm_average(self, current_bpm, average_bpm, beat_count):
        """Log average detected BPM over time to CSV."""
        data = {
            'timestamp': time.time(),
            'current_bpm': round(current_bpm, 1) if current_bpm is not None else None,
            'average_bpm': round(average_bpm, 1) if average_bpm is not None else None,
            'beat_count': beat_count
        }
        self._write_csv('music_bpm', data)

    def log_api_performance(self, endpoint, method, latency_ms, status_code):
        """Log API endpoint response times."""
        data = {
            'timestamp': time.time(),
            'endpoint': endpoint,
            'method': method,
            'latency_ms': round(latency_ms, 2),
            'status_code': status_code
        }
        self._write_csv('api', data)

    def _write_csv(self, metric_type, data):
        """Thread-safe CSV write operation."""
        with self.lock:
            file_path = self.files[metric_type]
            file_exists = file_path.exists()
            
            try:
                with open(file_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=data.keys())
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(data)
            except Exception as e:
                print(f"Error writing to {metric_type} CSV: {e}", flush=True)


# Global logger instance
_perf_logger = None


def get_performance_logger():
    """Get or create the global performance logger instance."""
    global _perf_logger
    if _perf_logger is None:
        _perf_logger = PerformanceLogger()
    return _perf_logger
