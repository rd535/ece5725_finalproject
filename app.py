from flask import Flask, render_template, jsonify, request
import time

app = Flask(__name__)

# Shared State for down and upload
pi_state = {
    "target_pace": 60,
    "rep_distance": 400,
    "status" : "idle",
    "last_update": time.strftime("%H:%M:%S"),
    "current_split" : 0.0
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
    
    pi_state["last_update"] = time.strftime("%H:%M:%S")
    
    return jsonify({"ok": True, "state" : pi_state})
    
    # can trigger pi from here
    # start_led_controller(pi_state["target_pace"])
    
# HTML front end
@app.route('/')
def index():
    #return 'Hello world'
    #return render_template('index.html')
    
    ## BASIC, REQUIRES REFRESH
    # current_time = time.strftime("%H:%M:%S")
    # lap_count = 7
    # return render_template('pacer_basic.html', current_time=current_time, lap_count=lap_count)
    
    ## ADVANCED, SCRIPTED REFRESH
    return render_template('pacer_v2.html')




@app.route('/hello/<name>')
def hello(name):
    return render_template('page.html', name=name)

# Testing color from the web interface
from color_test import set_color_all
@app.route('/set_color', methods=['POST'])
def set_color():
    data = request.json
    r, g, b = data['r'], data['g'], data['b']
    set_color_all(r, g, b)
    return "OK"

# For single pace testing
from pacer.state import manager
from pacer.controller import start_pacer, stop_pacer

@app.route('/start', methods=['POST'])
def start():
    start_pacer()
    return "OK"

def stop():
    stop_pacer()
    return "OK"

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    
