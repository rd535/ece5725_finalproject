import json
from copy import deepcopy
from pathlib import Path
from threading import Lock


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SETTINGS_FILE = DATA_DIR / "app_settings.json"

DEFAULT_SETTINGS = {
    "led_strip": {
        "strip_length_m": 5.0,
        "leds_per_meter": 60,
        "pin": 12,
        "color_order": "GRB",
    },
    "presets": {},
    "active_pacers": [],
}

_lock = Lock()


def load_settings():
    with _lock:
        if not SETTINGS_FILE.exists():
            DATA_DIR.mkdir(exist_ok=True)
            with SETTINGS_FILE.open("w", encoding="utf-8") as file:
                json.dump(DEFAULT_SETTINGS, file, indent=2)
            return deepcopy(DEFAULT_SETTINGS)

        with SETTINGS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        merged = deepcopy(DEFAULT_SETTINGS)
        merged.update(data)
        merged["led_strip"].update(data.get("led_strip", {}))
        merged["presets"] = data.get("presets", {})
        merged["active_pacers"] = data.get("active_pacers", [])
        return merged


def save_settings(settings):
    with _lock:
        DATA_DIR.mkdir(exist_ok=True)
        with SETTINGS_FILE.open("w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)


def led_count_from_settings(settings):
    led_strip = settings["led_strip"]
    return max(1, int(round(float(led_strip["strip_length_m"]) * float(led_strip["leds_per_meter"]))))
