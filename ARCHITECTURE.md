# Multi-Pacer System Architecture

## Data Structure Hierarchy

```
pi_state (global state)
├── mode: "pacer"
├── status: "idle" or "running"
├── last_update: "HH:MM:SS"
└── pacers: (dictionary keyed by pacer name)
    ├── "Pacer 1"
    │   ├── pacer_type: "constant" | "constant_with_pacer" | "dynamic"
    │   ├── rep_distance: 400 (meters)
    │   ├── lap_count: 3 (number of laps)
    │   ├── paces: [60, 65, 70] (array of BPM values)
    │   ├── current_split: 0.0 (distance covered in current run)
    │   └── running: false (is this pacer currently active)
    │
    ├── "Pacer 2"
    │   ├── pacer_type: "dynamic"
    │   ├── rep_distance: 500
    │   ├── lap_count: 2
    │   ├── paces: [70, 75]
    │   ├── current_split: 0.0
    │   └── running: false
    │
    └── ... (more pacers)

pacer_instances (runtime object tracking)
├── "Pacer 1": <ConstantPacerWithPacer object>
├── "Pacer 2": <DynamicPacer object>
└── ... (only contains running pacers)
```

## API Endpoint Mapping

```
Configuration Management:
  POST /submit_pacers
    Input:  { pacers: [ { pacer_name, pacer_type, rep_distance, lap_count, paces }, ... ] }
    Output: { ok: true, pacers: [...], state: pi_state }
    Effect: Validates and stores all pacers in pi_state["pacers"]

Status Monitoring:
  GET /api/status
    Output: { mode, status, last_update, pacers: { ... } }
    Effect: Updates current_split for running pacers

Control & Configuration:
  POST /api/control
    Input:  { status?, mode?, target_pace?, rep_distance? }
    Output: { ok: true, state: pi_state }
    Effect: Updates global state (legacy support)

  POST /api/mode
    Input:  { mode: "pacer" | "music" | "lighting" }
    Output: { ok: true, mode: "...", state: pi_state }
    Effect: Changes mode

Individual Pacer Control:
  POST /api/pacer/start/<pacer_name>
    Parameters: name in URL
    Output: { ok: true, message: "...", pacer_name: "...", pacer_type: "..." }
    Effect: Creates and starts pacer instance
            Sets pacers[name].running = true
            Sets status = "running"

  POST /api/pacer/stop/<pacer_name>
    Parameters: name in URL
    Output: { ok: true, message: "...", pacer_name: "..." }
    Effect: Stops pacer instance and cleans up
            Sets pacers[name].running = false
            Sets status = "idle" if no pacers running

Legacy Endpoints (Backward Compatible):
  POST /start        → Calls /api/pacer/start/<first_pacer_name>
  POST /stop         → Calls /api/pacer/stop/<first_pacer_name>
```

## Frontend State Management

```
pacerState (JavaScript object)
├── "Pacer 1": { type: "constant", pace: 60, lapCount: 1, status: "idle" }
├── "Pacer 2": { type: "dynamic", pace: 65, lapCount: 3, status: "running" }
└── ...

pacerStartTimes (JavaScript object - tracks elapsed time)
├── "Pacer 1": <timestamp when started or undefined>
├── "Pacer 2": <timestamp when started>
└── ...
```

## Control Flow Diagrams

### Submit Configuration
```
User fills table → Click "Submit"
  ↓
Frontend validates all rows
  ↓
POST /submit_pacers with pacer array
  ↓
Backend validates all pacers
  ├─ Check required fields
  ├─ Check type-specific requirements
  └─ If any fail: return 400 error
  ↓
Backend stores in pi_state["pacers"]
  ├─ Pacer 1 config
  ├─ Pacer 2 config
  └─ ...
  ↓
Frontend receives success
  ↓
updateStatusTable() populates status display
```

### Start Multiple Pacers
```
User clicks Start for Pacer 1
  ↓
POST /api/pacer/start/Pacer1
  ↓
Backend instantiates appropriate pacer class
  ├─ Calls .start() to begin in thread
  └─ Stores in pacer_instances["Pacer1"]
  ↓
Backend updates pi_state:
  ├─ pacers["Pacer1"].running = true
  └─ status = "running"
  ↓
Frontend updates button to "Stop"
  ↓
User clicks Start for Pacer 2
  ↓
POST /api/pacer/start/Pacer2
  ↓
Same process, now Pacer1 and Pacer2 both running
  └─ Global status still "running"
```

### Stop One Pacer
```
User clicks Stop on Pacer 1
  ↓
POST /api/pacer/stop/Pacer1
  ↓
Backend:
  ├─ Finds pacer_instances["Pacer1"]
  ├─ Sets .active = false (thread stops)
  ├─ Deletes from pacer_instances
  ├─ Sets pacers["Pacer1"].running = false
  └─ Checks: are ANY pacers running?
     ├─ Yes → status stays "running"
     └─ No → status = "idle"
  ↓
Frontend updates button to "Start"
```

## URL Encoding for Special Characters

Pacer names with spaces or special characters are URL encoded:
```
"Pacer 1" → "Pacer%201"
"Test (Pacer)" → "Test%20%28Pacer%29"
```

JavaScript handles encoding:
```javascript
fetch(`/api/pacer/start/${encodeURIComponent(pacerName)}`)
```

Flask automatically decodes the route parameter to the original name.

## Error Handling

### Missing Pacer
```
User tries to start non-existent "Pacer X"
  ↓
POST /api/pacer/start/PacerX
  ↓
Backend checks: "Pacer X" in pi_state["pacers"]?
  └─ No → return 404 { ok: false, error: "Pacer 'Pacer X' not found" }
  ↓
Frontend catches error and displays error message
```

### Invalid Pacer Configuration
```
User submits row with missing lap_count
  ↓
Backend validation loop:
  └─ Detects missing field
  ↓
Return 400 { ok: false, error: "Row 2: Missing required fields" }
  ↓
Frontend displays error in red
```

## Performance Considerations

- Multiple pacer threads run independently
- Each pacer has its own stack (no interference)
- Status updates happen every 1000ms (1 second)
- Time display updates every 250ms for smooth animation
- No shared locks needed (Flask GIL protection sufficient for now)
