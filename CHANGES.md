# Multi-Pacer Configuration Changes

## Overview
The Flask backend and frontend have been completely overhauled to support multiple unique pacers instead of a single pacer configuration.

## Backend Changes (app.py)

### 1. **New pi_state Structure**
Changed from flat structure to nested pacer dictionary:

```python
# OLD STRUCTURE (single pacer):
pi_state = {
    "target_pace": 60,
    "rep_distance": 400,
    "lap_count": 0,
    "pace_type": "constant",
    "status": "idle",
    "last_update": "HH:MM:SS",
    "current_split": 0.0,
    "mode": "pacer"
}

# NEW STRUCTURE (multiple pacers):
pi_state = {
    "mode": "pacer",
    "status": "idle",
    "last_update": "HH:MM:SS",
    "pacers": {
        "Pacer 1": {
            "pacer_type": "constant",
            "rep_distance": 400,
            "lap_count": 1,
            "paces": [60],
            "current_split": 0.0,
            "running": False
        },
        "Pacer 2": {
            "pacer_type": "dynamic",
            "rep_distance": 400,
            "lap_count": 3,
            "paces": [60, 65, 70],
            "current_split": 0.0,
            "running": False
        }
    }
}
```

### 2. **Updated API Endpoints**

#### `/api/status` - Status Updates
- Now iterates through all pacers in `pi_state["pacers"]`
- Updates `current_split` for each running pacer individually
- Returns complete pacer configuration

#### `/api/control` - Legacy Control
- Maintains backward compatibility
- Updates first pacer if multiple exist
- Still supports mode and status changes

#### `/submit_pacers` - Configuration Submission
**CRITICAL CHANGE**: Now properly stores multiple pacers
- Validates all pacers before storing
- Creates individual entry for each pacer with all config
- Stores: pacer_name, pacer_type, rep_distance, lap_count, paces, current_split, running

### 3. **New Pacer Control Endpoints**

#### `/api/pacer/start/<pacer_name>` (POST)
- Starts a specific pacer by name
- Creates appropriate pacer instance based on type:
  - "constant" → ConstantPacerWithPacer
  - "constant_with_pacer" → ConstantPacerWithPacer
  - "dynamic" → DynamicPacer
- Maintains `pacer_instances` dict to track active pacer objects
- Sets `running: True` for the pacer
- Sets global `status: "running"`

#### `/api/pacer/stop/<pacer_name>` (POST)
- Stops a specific pacer by name
- Cleans up pacer instance
- Sets `running: False` for the pacer
- Sets global `status: "idle"` only if no other pacer is running

### 4. **Legacy Endpoints** (Backward Compatibility)
- `/start` - Delegates to `/api/pacer/start/<first_pacer_name>`
- `/stop` - Delegates to `/api/pacer/stop/<first_pacer_name>`

### 5. **Pacer Instance Management**
```python
pacer_instances = {}  # {"Pacer 1": <ConstantPacerWithPacer>, "Pacer 2": <DynamicPacer>}
```
- Tracks active pacer thread objects by name
- Allows independent start/stop of multiple pacers
- Cleaned up when pacer is stopped

## Frontend Changes (pacer_v3.html)

### 1. **startPacer() Function**
Now makes API call to `/api/pacer/start/<pacer_name>`:
- URL encodes pacer name for special characters
- Updates local pacer state on success
- Shows error messages on failure
- Only updates the specific pacer being started

### 2. **stopPacer() Function**
Now makes API call to `/api/pacer/stop/<pacer_name>`:
- URL encodes pacer name
- Updates local pacer state on success
- Cleans up pacer start times
- Shows error messages on failure
- Only updates the specific pacer being stopped

### 3. **Error Messaging**
Added `showErrorMessage()` function to display errors in red

## Data Flow

### Submit Configuration
1. User fills table with multiple pacers (Pacer 1, Pacer 2, etc.)
2. Each row has: name, type, paces, distance, lap count
3. Frontend sends to `/submit_pacers` endpoint
4. Backend validates all pacers
5. Backend stores each pacer in `pi_state["pacers"][pacer_name]`
6. Frontend receives success and populates status table

### Start Pacer
1. User clicks "Start" button for Pacer 1
2. Frontend calls `/api/pacer/start/Pacer%201`
3. Backend creates appropriate pacer instance
4. Backend calls `.start()` on the instance
5. Backend updates `pi_state["pacers"]["Pacer 1"]["running"] = True`
6. Frontend updates local state and button toggles to "Stop"

### Stop Pacer
1. User clicks "Stop" button for Pacer 1
2. Frontend calls `/api/pacer/stop/Pacer%201`
3. Backend stops the pacer instance
4. Backend updates `pi_state["pacers"]["Pacer 1"]["running"] = False`
5. If no other pacers running, sets global `status = "idle"`
6. Frontend updates local state and button toggles to "Start"

## Key Features
✅ Each pacer has independent start/stop buttons
✅ Each pacer tracks its own running time
✅ Each pacer stores unique configuration (type, paces, distance, lap count)
✅ Global status updates based on any running pacer
✅ Backward compatible with legacy /start and /stop endpoints
✅ Proper error handling for missing pacers
✅ Support for special characters in pacer names via URL encoding

## Testing Checklist
- [ ] Create 2+ pacers with different types
- [ ] Submit configuration - verify all stored in pi_state["pacers"]
- [ ] Click Start on Pacer 1 - verify only Pacer 1 runs
- [ ] Click Start on Pacer 2 - verify both run
- [ ] Click Stop on Pacer 1 - verify Pacer 1 stops, Pacer 2 continues
- [ ] Click Stop on Pacer 2 - verify global status becomes "idle"
- [ ] Check /api/status response - should show all pacers with running state
- [ ] Test error handling - try starting non-existent pacer
