from flask import Flask, render_template, jsonify, request
import time
import json
import csv
import io

app = Flask(__name__)

pacer = None

# Shared State for down and upload
pi_state = {
    "target_pace": 60,
    "rep_distance": 400,
    "status" : "idle",
    "last_update": time.strftime("%H:%M:%S"),
    "current_split" : 0.0,
    "mode": "pacer"
    }

# Browser reads current Pi data
@app.route("/api/status")
def status():
    if pi_state["status"] == "running":
        pi_state["current_split"] += 0.25
    else:
        pi_state["current_split"] = 0.0
    pi_state["last_update"] = time.strftime("%H:%M:%S")
    return jsonify(pi_state)

# Browser sends data to the Pi
@app.route("/api/control", methods=["POST"])
def control():
    data = request.get_json()

    if not data:
        return jsonify({"ok": False, "error": "No JSON recieved"}), 400

    if "target_pace" in data:
        pi_state["target_pace"] = data["target_pace"]

    if "rep_distance" in data:
        pi_state["rep_distance"] = data["rep_distance"]

    if "status" in data:
        pi_state["status"] = data["status"]

    if "mode" in data:
        pi_state["mode"] = data["mode"]

    pi_state["last_update"] = time.strftime("%H:%M:%S")

    return jsonify({"ok": True, "state" : pi_state})

    # can trigger pi from here
    # start_led_controller(pi_state["target_pace"])

# File upload endpoint for JSON and CSV files
@app.route("/api/upload", methods=["POST"])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"ok": False, "error": "No file provided"}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({"ok": False, "error": "No file selected"}), 400

        # Check file extension
        filename = file.filename.lower()
        if not (filename.endswith('.json') or filename.endswith('.csv')):
            return jsonify({"ok": False, "error": "Invalid file type. Only JSON and CSV are supported"}), 400

        # Read file content
        content = file.read().decode('utf-8')

        # Parse based on file type
        if filename.endswith('.json'):
            data = json.loads(content)
        else:  # CSV
            lines = content.strip().split('\n')
            if len(lines) < 2:
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

        return jsonify({
            "ok": True,
            "message": f"File {file.filename} uploaded and parsed successfully",
            "state": pi_state
        })

    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"Invalid JSON format: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error processing file: {str(e)}"}), 500

# Mode selection endpoint
@app.route("/api/mode", methods=["POST"])
def set_mode():
    data = request.get_json()

    if not data or "mode" not in data:
        return jsonify({"ok": False, "error": "Mode not specified"}), 400

    valid_modes = ["pacer", "music", "lighting"]
    mode = data["mode"]

    if mode not in valid_modes:
        return jsonify({"ok": False, "error": f"Invalid mode. Must be one of: {', '.join(valid_modes)}"}), 400

    pi_state["mode"] = mode
    pi_state["last_update"] = time.strftime("%H:%M:%S")

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

@app.route("/submit_pacers", methods=["POST"])
def submit_pacers():
    data = request.get_json()

    pacers = data.get("pacers", [])

    for i, row in enumerate(pacers):
        pacer_name = row.get("pacer_name")
        pacer_type = row.get("pacer_type", "dynamic")
        distance = row.get("distance")
        paces = row.get("paces", [])

        # Validation
        if not pacer_name or distance is None:
            return jsonify({"error": f"Row {i + 1}: Missing pacer name or distance"}), 400

        if pacer_type == "dynamic" and (not paces or len(paces) == 0):
            return jsonify({"error": f"Row {i + 1}: Dynamic pacer requires at least one pace"}), 400

        if pacer_type in ["constant", "constant_with_pacer"] and (not paces or len(paces) == 0):
            return jsonify({"error": f"Row {i + 1}: {pacer_type} pacer requires a pace value"}), 400

    print(f"Received pacer configuration: {pacers}")

    return jsonify({
        "ok": True,
        "message": "Pacers received successfully",
        "pacers": pacers
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

# For single pace testing
from pacer.state import manager
from pacer.controller import start_pacer, stop_pacer
from pacer.pacer_pattern import ConstantPacerWithPacer, DynamicPacer

@app.route('/start', methods=['POST'])
def start():
    print("Received start command")
    # basic testing, no manager
    global pacer 

    if pacer is None or not pacer.active:
        pacer = ConstantPacerWithPacer(
            pace=pi_state["target_pace"],
            rep_distance=pi_state["rep_distance"]
        )
        pacer.start()
    print("Finished start command")
    return jsonify({"ok": True, "status": "running"})

    # start_pacer()

@app.route('/stop', methods=['POST'])
def stop():
    # basic testing, no manager
    global pacer

    if pacer is not None:
        pacer.active = False

    return jsonify({"ok": True, "status": "stopped"})

    # stop_pacer()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    
