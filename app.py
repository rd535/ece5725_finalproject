from flask import Flask, render_template, jsonify, request
import time
import json
import csv
import io
from functools import wraps
from threading import Lock
from pacer.event_log import get_events, log_event
from pacer.state import NewPacerManager
from pacer.pacer_pattern import Color, NewConstantPacer, NewDynamicPacer
from pacer.settings_store import led_count_from_settings, load_settings, save_settings

app = Flask(__name__)

pacer = None
pacer_instances = {}  # Dict to store pacer instances by name: {"Pacer 1": <pacer_object>, ...}
app_settings = load_settings()
web_pacer_manager = NewPacerManager(num_leds=led_count_from_settings(app_settings), pin=app_settings["led_strip"]["pin"])
DEFAULT_PACER_COLOR = "#00ff00"
pacer_state_lock = Lock()

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
    r, g, b = hex_to_rgb(color_hex)
    order = app_settings["led_strip"].get("color_order", "RGB").upper()
    values = {"R": r, "G": g, "B": b}
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

def save_active_pacers():
    app_settings["active_pacers"] = pacer_dict_to_list()
    save_settings(app_settings)

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

# File upload endpoint for JSON and CSV files
@app.route("/api/upload", methods=["POST"])
def upload_file():
    try:
        if 'file' not in request.files:
            log_event("Upload rejected: no file provided", level="ERROR", category="upload")
            return jsonify({"ok": False, "error": "No file provided"}), 400

        file = request.files['file']

        if file.filename == '':
            log_event("Upload rejected: no file selected", level="ERROR", category="upload")
            return jsonify({"ok": False, "error": "No file selected"}), 400

        # Check file extension
        filename = file.filename.lower()
        if not (filename.endswith('.json') or filename.endswith('.csv')):
            log_event("Upload rejected: invalid file type", level="ERROR", category="upload", filename=file.filename)
            return jsonify({"ok": False, "error": "Invalid file type. Only JSON and CSV are supported"}), 400

        # Read file content
        content = file.read().decode('utf-8')

        # Parse based on file type
        if filename.endswith('.json'):
            data = json.loads(content)
        else:  # CSV
            lines = content.strip().split('\n')
            if len(lines) < 2:
                log_event("Upload rejected: malformed CSV", level="ERROR", category="upload", filename=file.filename)
                return jsonify({"ok": False, "error": "CSV file must have headers and at least one data row"}), 400

            # Parse CSV
            reader = csv.DictReader(io.StringIO(content))
            data = next(reader)
            # Convert numeric strings to numbers where applicable
            if 'target_pace' in data:
                data['target_pace'] = float(data['target_pace'])
            if 'rep_distance' in data:
                data['rep_distance'] = float(data['rep_distance'])

        # Update pi_state with values from file
        if "target_pace" in data:
            pi_state["target_pace"] = float(data["target_pace"])

        if "rep_distance" in data:
            pi_state["rep_distance"] = float(data["rep_distance"])

        pi_state["last_update"] = time.strftime("%H:%M:%S")
        log_event("File uploaded and parsed", category="upload", filename=file.filename)

        return jsonify({
            "ok": True,
            "message": f"File {file.filename} uploaded and parsed successfully",
            "state": pi_state
        })

    except json.JSONDecodeError as e:
        log_event("Upload rejected: invalid JSON", level="ERROR", category="upload", error=str(e))
        return jsonify({"ok": False, "error": f"Invalid JSON format: {str(e)}"}), 400
    except Exception as e:
        log_event("Upload failed", level="ERROR", category="upload", error=str(e))
        return jsonify({"ok": False, "error": f"Error processing file: {str(e)}"}), 500

# Mode selection endpoint
@app.route("/api/mode", methods=["POST"])
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

    pi_state["mode"] = mode
    pi_state["last_update"] = time.strftime("%H:%M:%S")
    log_event("Mode selected", category="settings", mode=mode)

    return jsonify({"ok": True, "mode": mode, "state": pi_state})

# HTML front end
@app.route('/')
def index():
    #return 'Hello world'
    #return render_template('index.html')

    ## BASIC, REQUIRES REFRESH
    # current_time = time.strftime("%H:%M:%S")
    # lap_count = 7
    # return render_template('pacer_basic.html', current_time=current_time, lap_count=lap_count)

    ## ADVANCED, SCRIPTED REFRESH - UPGRADED VERSION
    return render_template('pacer_v3.html')

@app.route("/api/logs")
def logs():
    limit = request.args.get("limit", 100)
    return jsonify({"ok": True, "logs": get_events(limit)})

@app.route("/api/app-settings", methods=["GET"])
def get_app_settings():
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
    log_event("LED settings saved", category="settings", led_count=led_count_from_settings(app_settings), color_order=color_order)

    return jsonify({"ok": True, "settings": app_settings, "led_count": led_count_from_settings(app_settings)})

@app.route("/api/presets", methods=["GET"])
def list_presets():
    return jsonify({"ok": True, "presets": app_settings.get("presets", {})})

@app.route("/api/presets/<preset_name>", methods=["GET"])
def load_preset(preset_name):
    preset = app_settings.get("presets", {}).get(preset_name)
    if preset is None:
        return jsonify({"ok": False, "error": f"Preset '{preset_name}' not found"}), 404
    return jsonify({"ok": True, "name": preset_name, "pacers": preset})

@app.route("/api/presets/<preset_name>", methods=["POST"])
@with_pacer_lock
def save_preset(preset_name):
    data = request.get_json() or {}
    pacers = data.get("pacers", pacer_dict_to_list())
    presets = app_settings.setdefault("presets", {})
    if preset_name not in presets and len(presets) >= 3:
        return jsonify({"ok": False, "error": "Only 3 presets can be saved. Reuse an existing preset name to overwrite it."}), 400

    presets[preset_name] = pacers
    save_settings(app_settings)
    log_event("Preset saved", category="settings", preset=preset_name, pacer_count=len(pacers))
    return jsonify({"ok": True, "presets": presets})

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

@app.route("/submit_pacers", methods=["POST"])
@with_pacer_lock
def submit_pacers():
    data = request.get_json()
    pacers = data.get("pacers", [])

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
    save_active_pacers()
    log_event("Pacer settings saved", category="settings", pacer_count=len(pacers))

    return jsonify({
        "ok": True,
        "message": "Pacers received successfully",
        "pacers": pacers,
        "state": pi_state
    })

@app.route('/api/pacer/start/<pacer_name>', methods=['POST'])
@with_pacer_lock
def pacer_start(pacer_name):
    """Start a specific pacer by name"""
    if pacer_name not in pi_state["pacers"]:
        log_event("Start rejected: pacer not found", level="ERROR", category="pacer", pacer_name=pacer_name)
        return jsonify({"ok": False, "error": f"Pacer '{pacer_name}' not found"}), 404

    pacer_config = pi_state["pacers"][pacer_name]
    pacer_type = pacer_config.get("pacer_type", "constant")
    pace = pacer_config["paces"][0] if pacer_config["paces"] else 60
    distance = pacer_config.get("rep_distance", 400)
    lap_count = pacer_config.get("lap_count", 4)
    color_hex = pacer_config.get("color", DEFAULT_PACER_COLOR)

    log_event("Starting pacer request", category="pacer", pacer_name=pacer_name, pacer_type=pacer_type, pace=pace, distance=distance)

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

        pacer_instances[pacer_name].name = pacer_name
        web_pacer_manager.add_pacer(pacer_instances[pacer_name])
        web_pacer_manager.start()
        pacer_instances[pacer_name].start()
        pi_state["pacers"][pacer_name]["running"] = True
        pi_state["pacers"][pacer_name]["finished"] = False
        pi_state["status"] = "running"
        pi_state["last_update"] = time.strftime("%H:%M:%S")
        log_event("Pacer started", category="pacer", pacer_name=pacer_name, pacer_type=pacer_type)

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    
