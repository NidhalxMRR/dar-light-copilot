# OpenEMS Green Energy Simulator (Solar + Hydrogen) — Tkinter

Purpose: generate near-realistic telemetry logs and inject anomalies to test OpenClaw detection.

## Files
- `openems_simulator.py` — Tkinter UI that writes JSONL telemetry and toggles anomalies.
- `open_claw_listener.py` — example tailing listener (prints alarms).

## Run (Windows)
```powershell
python openems_simulator.py
```

Default output:
- `~/Desktop/ems_sim/ems_telemetry.jsonl`

## Log format
JSONL (one JSON object per line). Example keys:
- `status`: `OK` or `ALARM`
- `anomalies`: object of boolean flags (e.g. `hv_dc_bus`, `comms_loss`)
- solar/battery/hydrogen metrics (pv_kw, soc_pct, dc_bus_v, h2_tank_bar, ...)

## How OpenClaw should integrate (MVP)
- Tail the JSONL file.
- Trigger an alert when `status == "ALARM"` or any `anomalies.* == true`.
- Optionally keep a rolling window and detect trends.

## Notes
- For demos, the simulator compresses the “day/night” cycle into ~4 minutes so the graphs/data visibly change.
