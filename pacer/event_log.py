from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock


LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIR / "pacer_events.log"
MAX_EVENTS = 500
MAX_LOG_FILE_LINES = 200

# fixed size in-memory event log with thread safety
_events = deque(maxlen=MAX_EVENTS)

# prevent race conditions for reading/writing log events
_lock = Lock()


def log_event(message, level="INFO", category="system", **details):
    timestamp = datetime.now().isoformat(timespec="seconds")
    entry = {
        "timestamp": timestamp,
        "level": level.upper(),
        "category": category,
        "message": message,
        "details": details,
    }

    detail_text = ""
    if details:
        detail_text = " " + " ".join(f"{key}={value}" for key, value in details.items())

    line = f"[{timestamp}] [{entry['level']}] [{category}] {message}{detail_text}"

    with _lock:
        # store in memory log
        _events.append(entry)
        try:
            # keep newest persisted entries at the top and cap file length
            LOG_DIR.mkdir(exist_ok=True)
            existing_lines = []
            if LOG_FILE.exists():
                existing_lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            LOG_FILE.write_text(
                "\n".join([line] + existing_lines[:MAX_LOG_FILE_LINES - 1]) + "\n",
                encoding="utf-8",
            )
        except PermissionError:
            pass

    print(line, flush=True)
    return entry

# API to retrieve recent events for display in web interface
def get_events(limit=100):
    with _lock:
        events = list(_events)

    if limit is None:
        return events

    return events[-int(limit):]
