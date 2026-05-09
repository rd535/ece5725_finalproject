from flask import Flask, render_template, jsonify, request, g
import time
import json
import csv
import io
from pathlib import Path
from functools import wraps
from threading import Lock
from pacer.event_log import get_events, log_event
from pacer.state import NewPacerManager
from pacer.pacer_pattern import Color, NewConstantPacer, NewDynamicPacer
from pacer.settings_store import led_count_from_settings, load_settings, save_settings
from lighting.lighting_manager import LightingManagerV2
from lighting.lighting_patterns import pattern_metadata
from performance_logger import get_performance_logger

app = Flask(__name__)

pacer = None
pacer_instances = {}  # Dict to store pacer instances by name: {"Pacer 1": <pacer_object>, ...}
app_settings = load_settings()
web_pacer_manager = NewPacerManager(num_leds=led_count_from_settings(app_settings), pin=app_settings["led_strip"]["pin"])
web_lighting_manager = None
DEFAULT_PACER_COLOR = "#00ff00"
pacer_state_lock = Lock()


@app.context_processor
def static_versions():
    css_path = Path(app.static_folder) / "pacer_style.css"
    css_version = int(css_path.stat().st_mtime) if css_path.exists() else int(time.time())
    return {"css_version": css_version}

# API request timing
@app.before_request
def start_timer():
    g.start = time.perf_counter()

@app.after_request
def log_request_time(response):
    if hasattr(g, 'start'):
        duration = time.perf_counter() - g.start
        latency_ms = round(duration * 1000, 2)
        
        perf_logger = get_performance_logger()
        perf_logger.log_api_performance(
            endpoint=request.endpoint or "unknown",
            method=request.method,
            latency_ms=latency_ms,
            status_code=response.status_code
        )
    return response

# Shared State for down and upload
# New structure with per-pacer configurations
pi_state = {
    "mode": "pacer",
    "status": "idle",
    "last_update": time.strftime("%H:%M:%S"),
    "pacers": {},  # Format: { "Pacer Name": { "pacer_type", "rep_distance", "lap_count", "paces", "current_split", "running" } }
    }
for saved_pacer in app_settings.get("active_pacers", []):
    pi_state["pacers"][saved_pacer["pacer_name"]] = {
        "pacer_type": saved_pacer.get("pacer_type", "constant"),
        "rep_distance": saved_pacer.get("rep_distance", 400),
        "lap_count": saved_pacer.get("lap_count", 1),
        "paces": saved_pacer.get("paces", []),
        "color": saved_pacer.get("color", DEFAULT_PACER_COLOR),
        "current_split": 0.0,
        "running": False,
        "finished": False,
    }


def hex_to_rgb(color_hex):
    # remove whitspace
    color_hex = (color_hex or DEFAULT_PACER_COLOR).strip()
    # will have #FF0000 value as example
    if color_hex.startswith("#"):
        color_hex = color_hex[1:]
    if len(color_hex) != 6:
        raise ValueError(f"Invalid color: #{color_hex}")
    return tuple(int(color_hex[i:i + 2], 16) for i in (0, 2, 4))

def hex_to_color(color_hex):
    # print("Converting color hex:", color_hex)
    r, g, b = hex_to_rgb(color_hex)
    order = app_settings["led_strip"].get("color_order", "RGB").upper()
    # print("Color order from settings:", order)
    values = {"R": r, "G": g, "B": b}
    # print("Color values before reordering:", values)
    return Color(values[order[0]], values[order[1]], values[order[2]])

def pacer_dict_to_list():
    return [
        {
            "pacer_name": name,
            "pacer_type": config.get("pacer_type", "constant"),
            "rep_distance": config.get("rep_distance", 400),
            "lap_count": config.get("lap_count", 1),
            "paces": config.get("paces", []),
            "color": config.get("color", DEFAULT_PACER_COLOR),
        }
        for name, config in pi_state["pacers"].items()
    ]

def normalize_pacer_list(raw_pacers):
    if isinstance(raw_pacers, str):
        try:
            return normalize_pacer_list(json.loads(raw_pacers))
        except json.JSONDecodeError:
            return []
    if isinstance(raw_pacers, list):
        rows = raw_pacers
    elif isinstance(raw_pacers, dict) and "pacers" in raw_pacers:
        return normalize_pacer_list(raw_pacers["pacers"])
    elif isinstance(raw_pacers, dict):
        rows = []
        for pacer_name, config in raw_pacers.items():
            if isinstance(config, dict):
                row = dict(config)
                row.setdefault("pacer_name", pacer_name)
                rows.append(row)
            else:
                rows.append({
                    "pacer_name": pacer_name,
                    "pacer_type": "constant",
                    "rep_distance": 400,
                    "lap_count": 1,
                    "paces": [config],
                    "color": DEFAULT_PACER_COLOR,
                })
    else:
        rows = []

    normalized = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        paces = row.get("paces", [])
        if paces in (None, ""):
            paces = row.get("pace_list", row.get("pace", []))
        if not isinstance(paces, list):
            paces = [paces]

        normalized.append({
            "pacer_name": row.get("pacer_name") or row.get("name") or f"Pacer {index + 1}",
            "pacer_type": row.get("pacer_type") or row.get("type") or "constant",
            "rep_distance": row.get("rep_distance") or row.get("distance") or row.get("interval") or 400,
            "lap_count": row.get("lap_count") or row.get("lapCount") or row.get("laps") or len(paces) or 1,
            "paces": paces,
            "color": row.get("color", DEFAULT_PACER_COLOR),
        })

    return normalized

def save_active_pacers():
    app_settings["active_pacers"] = pacer_dict_to_list()
    save_settings(app_settings)

def clean_presets():
    presets = app_settings.setdefault("presets", {})
    invalid_names = [name for name, preset in presets.items() if preset is None]
    for name in invalid_names:
        presets.pop(name, None)

    if invalid_names:
        save_settings(app_settings)
        log_event("Removed invalid saved preset entries", category="settings", presets=invalid_names)

    return presets

def create_lighting_manager():
    return LightingManagerV2(
        num_leds=led_count_from_settings(app_settings),
        pin=app_settings["led_strip"]["pin"],
        color_order=app_settings["led_strip"].get("color_order", "RGB"),
        strip=web_pacer_manager.strip,
    )

def ensure_lighting_manager():
    global web_lighting_manager
    if web_lighting_manager is None:
        web_lighting_manager = create_lighting_manager()
    return web_lighting_manager

def stop_lighting_manager(destroy=False):
    global web_lighting_manager
    if web_lighting_manager is None:
        return
    web_lighting_manager.stop()
    if destroy:
        web_lighting_manager = None

def stop_pacer_runtime(clear_strip=True):
    for config in pi_state["pacers"].values():
        config["running"] = False
        config["finished"] = False
        config["current_split"] = 0.0
    pacer_instances.clear()
    web_pacer_manager.stop()
    pacer_thread = getattr(web_pacer_manager, "thread", None)
    if pacer_thread and pacer_thread.is_alive():
        pacer_thread.join(timeout=1.0)
    web_pacer_manager.clear_pacers()
    if clear_strip:
        web_pacer_manager.clear()
    pi_state["status"] = "idle"

def with_pacer_lock(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with pacer_state_lock:
            return func(*args, **kwargs)
    return wrapper

def sync_pacer_runtime_state():
    """Mirror completed/stopped pacer threads into pi_state for the browser."""
    for pacer_name, pacer_instance in list(pacer_instances.items()):
        pacer_config = pi_state["pacers"].get(pacer_name)
        if pacer_config is None:
            pacer_instances.pop(pacer_name, None)
            continue

        thread = getattr(pacer_instance, "thread", None)
        is_active = bool(getattr(pacer_instance, "active", False))
        is_alive = bool(thread and thread.is_alive())

        if pacer_config.get("running") and not is_active and not is_alive:
            pacer_config["running"] = False
            pacer_config["finished"] = True
            pacer_config["current_split"] = 0.0
            pacer_instances.pop(pacer_name, None)
            web_pacer_manager.remove_pacer_by_name(pacer_name)
            log_event("Pacer finished", category="pacer", pacer_name=pacer_name)

    pi_state["status"] = (
        "running"
        if any(p.get("running", False) for p in pi_state["pacers"].values())
        else "idle"
    )

# Browser reads current Pi data
@app.route("/api/status")
@with_pacer_lock
def status():
    sync_pacer_runtime_state()

    # Update timestamp
    pi_state["last_update"] = time.strftime("%H:%M:%S")

    # Update current_split for running pacers (legacy behavior)
    if pi_state["status"] == "running" and pi_state["pacers"]:
        for pacer_name in pi_state["pacers"]:
            if pi_state["pacers"][pacer_name].get("running"):
                current = pi_state["pacers"][pacer_name].get("current_split", 0)
                pi_state["pacers"][pacer_name]["current_split"] = current + 0.25
    else:
        # Reset splits when not running
        for pacer_name in pi_state["pacers"]:
            pi_state["pacers"][pacer_name]["current_split"] = 0.0

    return jsonify(pi_state)

# Mode selection endpoint
@app.route("/api/mode", methods=["POST"])
@with_pacer_lock
def set_mode():
    data = request.get_json()

    if not data or "mode" not in data:
        log_event("Mode request rejected: mode not specified", level="ERROR", category="api")
        return jsonify({"ok": False, "error": "Mode not specified"}), 400

    valid_modes = ["pacer", "music", "lighting"]
    mode = data["mode"]

    if mode not in valid_modes:
        log_event("Mode request rejected: invalid mode", level="ERROR", category="api", mode=mode)
        return jsonify({"ok": False, "error": f"Invalid mode. Must be one of: {', '.join(valid_modes)}"}), 400

    if mode != "pacer":
        stop_pacer_runtime()

    if mode == "lighting":
        ensure_lighting_manager().start()
    else:
        stop_lighting_manager(destroy=True)

    pi_state["mode"] = mode
    pi_state["last_update"] = time.strftime("%H:%M:%S")
    log_event("Mode selected", category="settings", mode=mode)

    return jsonify({"ok": True, "mode": mode, "state": pi_state})

# HTML front end
@app.route('/')
def index():
    return render_template('pacer_v3.html')

@app.route("/api/logs")
def logs():
    limit = request.args.get("limit", 100)
    return jsonify({"ok": True, "logs": get_events(limit)})

@app.route("/api/app-settings", methods=["GET"])
def get_app_settings():
    clean_presets()
    return jsonify({
        "ok": True,
        "settings": app_settings,
        "led_count": led_count_from_settings(app_settings),
    })

@app.route("/api/led-settings", methods=["POST"])
@with_pacer_lock
def save_led_settings():
    data = request.get_json() or {}

    try:
        strip_length_m = float(data.get("strip_length_m"))
        leds_per_meter = float(data.get("leds_per_meter"))
        pin = int(data.get("pin", 12))
        color_order = data.get("color_order", "RGB").upper()
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "LED settings must include numeric strip length, LED/m, and pin."}), 400

    if strip_length_m <= 0 or leds_per_meter <= 0:
        return jsonify({"ok": False, "error": "Strip length and LED/m must be greater than 0."}), 400

    if color_order not in {"RGB", "RBG", "GRB", "GBR", "BRG", "BGR"}:
        return jsonify({"ok": False, "error": "Color order must be one of RGB, RBG, GRB, GBR, BRG, BGR."}), 400

    app_settings["led_strip"] = {
        "strip_length_m": strip_length_m,
        "leds_per_meter": leds_per_meter,
        "pin": pin,
        "color_order": color_order,
    }
    save_settings(app_settings)

    pacer_instances.clear()
    for config in pi_state["pacers"].values():
        config["running"] = False
    pi_state["status"] = "idle"
    web_pacer_manager.configure_strip(num_leds=led_count_from_settings(app_settings), pin=pin)
    if web_lighting_manager is not None:
        web_lighting_manager.configure_strip(
            num_leds=led_count_from_settings(app_settings),
            pin=pin,
            color_order=color_order,
            strip=web_pacer_manager.strip,
        )
    log_event("LED settings saved", category="settings", led_count=led_count_from_settings(app_settings), color_order=color_order)

    return jsonify({"ok": True, "settings": app_settings, "led_count": led_count_from_settings(app_settings)})

@app.route("/api/lighting/patterns", methods=["GET"])
def lighting_patterns():
    return jsonify({"ok": True, "patterns": pattern_metadata()})

@app.route("/api/lighting/status", methods=["GET"])
def lighting_status():
    if web_lighting_manager is None:
        return jsonify({"ok": True, "lighting": {"active": False, "running": False, "pattern": None, "started_at": None}})
    return jsonify({"ok": True, "lighting": web_lighting_manager.status()})

@app.route("/api/lighting/start", methods=["POST"])
@with_pacer_lock
def lighting_start():
    data = request.get_json() or {}
    pattern_name = data.get("pattern")
    colors = data.get("colors", [])
    speed = data.get("speed", 1.0)

    if not pattern_name:
        return jsonify({"ok": False, "error": "Lighting pattern is required."}), 400

    try:
        color_objects = [hex_to_rgb(color) for color in colors]
        stop_pacer_runtime()
        manager = ensure_lighting_manager()
        manager.start()
        manager.start_pattern(pattern_name, color_objects, speed=speed)
        pi_state["mode"] = "lighting"
        pi_state["last_update"] = time.strftime("%H:%M:%S")
    except ValueError as exc:
        log_event("Lighting start rejected", level="ERROR", category="lighting", pattern=pattern_name, error=str(exc))
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        log_event("Lighting start failed", level="ERROR", category="lighting", pattern=pattern_name, error=repr(exc))
        return jsonify({"ok": False, "error": f"Failed to start lighting pattern: {exc}"}), 500

    return jsonify({"ok": True, "lighting": manager.status()})

@app.route("/api/lighting/stop", methods=["POST"])
@with_pacer_lock
def lighting_stop():
    if web_lighting_manager is not None:
        web_lighting_manager.stop_pattern()
    pi_state["last_update"] = time.strftime("%H:%M:%S")
    if web_lighting_manager is None:
        return jsonify({"ok": True, "lighting": {"active": False, "running": False, "pattern": None, "started_at": None}})
    return jsonify({"ok": True, "lighting": web_lighting_manager.status()})

@app.route("/api/presets", methods=["GET"])
def list_presets():
    return jsonify({"ok": True, "presets": clean_presets()})

@app.route("/api/presets/<preset_name>", methods=["GET"])
def load_preset(preset_name):
    preset = clean_presets().get(preset_name)
    if preset is None:
        log_event("Preset load rejected: not found", level="ERROR", category="settings", preset=preset_name)
        return jsonify({"ok": False, "error": f"Preset '{preset_name}' not found"}), 404
    pacers = normalize_pacer_list(preset)
    log_event("Preset loaded", category="settings", preset=preset_name, pacer_count=len(pacers))
    return jsonify({"ok": True, "name": preset_name, "pacers": pacers})

@app.route("/api/presets/<preset_name>", methods=["POST"])
@with_pacer_lock
def save_preset(preset_name):
    data = request.get_json() or {}
    pacers = normalize_pacer_list(data.get("pacers", pacer_dict_to_list()))
    presets = clean_presets()

    presets[preset_name] = pacers
    save_settings(app_settings)
    log_event("Preset saved", category="settings", preset=preset_name, pacer_count=len(pacers))
    return jsonify({"ok": True, "presets": presets})

@app.route("/api/presets/<preset_name>", methods=["DELETE"])
@with_pacer_lock
def delete_preset(preset_name):
    presets = clean_presets()
    if preset_name not in presets:
        log_event("Preset delete rejected: not found", level="ERROR", category="settings", preset=preset_name)
        return jsonify({"ok": False, "error": f"Preset '{preset_name}' not found"}), 404

    presets.pop(preset_name)
    save_settings(app_settings)
    log_event("Preset deleted", category="settings", preset=preset_name)
    return jsonify({"ok": True, "presets": presets, "deleted_preset": preset_name})

@app.route("/api/pacer/start_all", methods=["POST"])
@with_pacer_lock
def pacer_start_all():
    started = []
    for pacer_name in list(pi_state["pacers"].keys()):
        response = pacer_start.__wrapped__(pacer_name)
        if isinstance(response, tuple):
            return response
        started.append(pacer_name)

    log_event("All pacers started", category="pacer", pacers=started)
    return jsonify({"ok": True, "started": started})

@app.route("/api/pacer/stop_all", methods=["POST"])
@with_pacer_lock
def pacer_stop_all():
    stopped = []
    for pacer_name in list(pi_state["pacers"].keys()):
        response = pacer_stop.__wrapped__(pacer_name)
        if isinstance(response, tuple):
            return response
        stopped.append(pacer_name)

    log_event("All pacers stopped", category="pacer", pacers=stopped)
    return jsonify({"ok": True, "stopped": stopped})

@app.route("/submit_pacers", methods=["POST"])
@with_pacer_lock
def submit_pacers():
    data = request.get_json() or {}
    pacers = normalize_pacer_list(data.get("pacers", []))

    # Validate all pacers first
    for i, row in enumerate(pacers):
        pacer_name = row.get("pacer_name")
        pacer_type = row.get("pacer_type", "constant")
        distance = row.get("rep_distance")
        lap_count = row.get("lap_count")
        paces = row.get("paces", [])
        color = row.get("color", DEFAULT_PACER_COLOR)

        # Validation
        if not pacer_name or distance is None or lap_count is None:
            log_event("Pacer settings rejected: missing required fields", level="ERROR", category="settings", row=i + 1)
            return jsonify({"ok": False, "error": f"Row {i + 1}: Missing required fields"}), 400

        if pacer_type == "dynamic" and (not paces or len(paces) == 0):
            log_event("Pacer settings rejected: dynamic pacer missing pace", level="ERROR", category="settings", row=i + 1)
            return jsonify({"ok": False, "error": f"Row {i + 1}: Dynamic pacer requires at least one pace"}), 400

        if pacer_type in ["constant", "constant_with_pacer"] and (not paces or len(paces) == 0):
            log_event("Pacer settings rejected: pacer missing pace", level="ERROR", category="settings", row=i + 1, pacer_type=pacer_type)
            return jsonify({"ok": False, "error": f"Row {i + 1}: {pacer_type} pacer requires a pace value"}), 400

        try:
            hex_to_rgb(color)
        except ValueError as exc:
            log_event("Pacer settings rejected: invalid color", level="ERROR", category="settings", row=i + 1, color=color)
            return jsonify({"ok": False, "error": f"Row {i + 1}: {exc}"}), 400

    # All validation passed, store pacers in pi_state, clear old dict
    stop_lighting_manager(destroy=True)
    pi_state["pacers"] = {}
    pacer_instances.clear()
    web_pacer_manager.stop()
    web_pacer_manager.clear_pacers()

    for row in pacers:
        pacer_name = row.get("pacer_name")
        pacer_type = row.get("pacer_type", "constant")
        distance = row.get("rep_distance")
        lap_count = row.get("lap_count")
        paces = row.get("paces", [])
        color = row.get("color", DEFAULT_PACER_COLOR)

        # Store pacer configuration
        pi_state["pacers"][pacer_name] = {
            "pacer_type": pacer_type,
            "rep_distance": distance,
            "lap_count": lap_count,
            "paces": paces,
            "color": color,
            "current_split": 0.0,
            "running": False,
            "finished": False
        }

    pi_state["last_update"] = time.strftime("%H:%M:%S")
    app_settings["active_pacers"] = pacer_dict_to_list()
    save_settings(app_settings)
    log_event("Pacer settings saved", category="settings", pacer_count=len(pacers), active_pacers_saved=len(app_settings["active_pacers"]))

    return jsonify({
        "ok": True,
        "message": "Pacers received successfully",
        "pacers": pacers,
        "state": pi_state,
        "active_pacers": app_settings["active_pacers"]
    })

@app.route('/api/pacer/start/<pacer_name>', methods=['POST'])
@with_pacer_lock
def pacer_start(pacer_name):
    """Start a specific pacer by name"""
    stop_lighting_manager(destroy=True)

    if pacer_name not in pi_state["pacers"]:
        log_event("Start rejected: pacer not found", level="ERROR", category="pacer", pacer_name=pacer_name)
        return jsonify({"ok": False, "error": f"Pacer '{pacer_name}' not found"}), 404

    pacer_config = pi_state["pacers"][pacer_name]
    pacer_type = pacer_config.get("pacer_type", "constant")
    pace = pacer_config["paces"][0] if pacer_config["paces"] else 60
    distance = pacer_config.get("rep_distance", 400)
    lap_count = pacer_config.get("lap_count", 4)
    color_hex = pacer_config.get("color", DEFAULT_PACER_COLOR)

    try:
        existing_pacer = pacer_instances.get(pacer_name)
        if existing_pacer:
            web_pacer_manager.remove_pacer_by_name(pacer_name)
            log_event("Restarting existing pacer instance", category="pacer", pacer_name=pacer_name)

        color = hex_to_color(color_hex)

        if pacer_type == "dynamic":
            pacer_instances[pacer_name] = NewDynamicPacer(
                pace=pacer_config["paces"],
                rep_distance=distance,
                lap_count=lap_count,
                color=color,
            )
        else:
            pacer_instances[pacer_name] = NewConstantPacer(
                pace=pace,
                rep_distance=distance,
                lap_count=lap_count,
                color=color,
            )

        pacer_instance = pacer_instances[pacer_name]
        pacer_instance.name = pacer_name
        pacer_instance.num_leds = web_pacer_manager.num_leds
        pacer_instance.start()
        web_pacer_manager.add_pacer(pacer_instance, log=False)
        web_pacer_manager.start(log=False)
        web_pacer_manager.render_active_frame()
        pi_state["pacers"][pacer_name]["running"] = True
        pi_state["pacers"][pacer_name]["finished"] = False
        pi_state["status"] = "running"
        pi_state["last_update"] = time.strftime("%H:%M:%S")
        log_event("Pacer started", category="pacer", pacer_name=pacer_name, pacer_type=pacer_type, pace=pace, distance=distance)

        return jsonify({
            "ok": True,
            "message": f"Pacer '{pacer_name}' started",
            "pacer_name": pacer_name,
            "pacer_type": pacer_type
        })

    except Exception as e:
        log_event("Failed to start pacer", level="ERROR", category="pacer", pacer_name=pacer_name, error=str(e))
        return jsonify({
            "ok": False,
            "error": f"Failed to start pacer: {str(e)}"
        }), 500

@app.route('/api/pacer/stop/<pacer_name>', methods=['POST'])
@with_pacer_lock
def pacer_stop(pacer_name):
    """Stop a specific pacer by name"""
    if pacer_name not in pi_state["pacers"]:
        log_event("Stop rejected: pacer not found", level="ERROR", category="pacer", pacer_name=pacer_name)
        return jsonify({"ok": False, "error": f"Pacer '{pacer_name}' not found"}), 404

    if pacer_name in pacer_instances and pacer_instances[pacer_name]:
        web_pacer_manager.remove_pacer_by_name(pacer_name)
        del pacer_instances[pacer_name]

    pi_state["pacers"][pacer_name]["running"] = False
    pi_state["pacers"][pacer_name]["finished"] = False
    pi_state["pacers"][pacer_name]["current_split"] = 0.0

    # Check if any pacer is still running
    any_running = any(p.get("running", False) for p in pi_state["pacers"].values())
    if not any_running:
        pi_state["status"] = "idle"
        web_pacer_manager.stop()

    pi_state["last_update"] = time.strftime("%H:%M:%S")
    log_event("Pacer stopped", category="pacer", pacer_name=pacer_name)

    return jsonify({
        "ok": True,
        "message": f"Pacer '{pacer_name}' stopped",
        "pacer_name": pacer_name
    })

import socket

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except:
        ip = "No IP"
    finally:
        s.close()
    return ip

if __name__ == '__main__':
    print("Actual IP:", get_ip())
    app.run(debug=True, host='0.0.0.0', port=5000)
    
