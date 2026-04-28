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

app = Flask(__name__)

pacer = None
pacer_instances = {}  # Dict to store pacer instances by name: {"Pacer 1": <pacer_object>, ...}
web_pacer_manager = NewPacerManager()
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

# Legacy fields for backward compatibility (will be removed)
legacy_state = {
    "target_pace": 60,
    "rep_distance": 400,
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
    return Color(r, g, b)

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

# Browser sends data to the Pi
@app.route("/api/control", methods=["POST"])
def control():
    data = request.get_json()

    if not data:
        log_event("Control request missing JSON", level="ERROR", category="api")
        return jsonify({"ok": False, "error": "No JSON recieved"}), 400

    # Update global status
    if "status" in data:
        pi_state["status"] = data["status"]
        log_event("System status updated", category="settings", status=data["status"])

    if "mode" in data:
        pi_state["mode"] = data["mode"]
        log_event("Mode updated", category="settings", mode=data["mode"])

    # Legacy support: target_pace and rep_distance (updates first pacer if it exists)
    if "target_pace" in data and pi_state["pacers"]:
        first_pacer = list(pi_state["pacers"].keys())[0]
        if first_pacer in pi_state["pacers"]:
            pi_state["pacers"][first_pacer]["paces"] = [data["target_pace"]]
            log_event("Target pace updated", category="settings", pacer_name=first_pacer, pace=data["target_pace"])

    if "rep_distance" in data and pi_state["pacers"]:
        first_pacer = list(pi_state["pacers"].keys())[0]
        if first_pacer in pi_state["pacers"]:
            pi_state["pacers"][first_pacer]["rep_distance"] = data["rep_distance"]
            log_event("Rep distance updated", category="settings", pacer_name=first_pacer, rep_distance=data["rep_distance"])

    pi_state["last_update"] = time.strftime("%H:%M:%S")

    return jsonify({"ok": True, "state" : pi_state})

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
    log_event("Pacer settings saved", category="settings", pacer_count=len(pacers))

    return jsonify({
        "ok": True,
        "message": "Pacers received successfully",
        "pacers": pacers,
        "state": pi_state
    })


# @app.route('/hello/<name>')
# def hello(name):
#     return render_template('page.html', name=name)

# # Testing color from the web interface
# from color_test import set_color_all
# @app.route('/set_color', methods=['POST'])
# def set_color():
#     data = request.json
#     r, g, b = data['r'], data['g'], data['b']
#     set_color_all(r, g, b)
#     return "OK"

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

# Legacy endpoints for backward compatibility
@app.route('/start', methods=['POST'])
def start():
    """Legacy endpoint - starts the first pacer"""
    log_event("Legacy start command received", category="pacer")
    if not pi_state["pacers"]:
        log_event("Legacy start rejected: no pacers configured", level="ERROR", category="pacer")
        return jsonify({"ok": False, "error": "No pacers configured"}), 400

    first_pacer_name = list(pi_state["pacers"].keys())[0]
    return pacer_start(first_pacer_name)

@app.route('/stop', methods=['POST'])
def stop():
    """Legacy endpoint - stops the first pacer"""
    log_event("Legacy stop command received", category="pacer")
    if not pi_state["pacers"]:
        log_event("Legacy stop rejected: no pacers configured", level="ERROR", category="pacer")
        return jsonify({"ok": False, "error": "No pacers configured"}), 400

    first_pacer_name = list(pi_state["pacers"].keys())[0]
    return pacer_stop(first_pacer_name)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    
