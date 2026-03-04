# EMS Real-time Alert Pipeline (Lossless)

Goal: stream EMS anomalies from a Windows PC in real time with **no data loss**, and alert via Telegram.

## Components

### VPS (receiver + aggregator)
- Service: `ems-ingest.service`
- Listens on: `127.0.0.1:9010` (loopback only)
- Receives JSON line events, replies with `{"ack": seq}`
- Classifies alarm types:
  - `HIGH_VOLTAGE`
  - `LOW_VOLTAGE`
  - `H2_LEAK`
  - `INVERTER_OVERHEAT`
  - fallback: `ALARM` when a line contains ` ERROR `
- Sends Telegram alerts (via VPS OpenClaw Telegram plugin)

### Windows (shipper)
- Script: `windows-node/openems-sim/ems_shipper_text.py`
- Tails: `openems_simulation.log`
- Stores events in a local SQLite spool until ACKed by the VPS
- Reconnects and replays unsent events after tunnel drops

## Transport (secure)
Use an SSH tunnel so the VPS listener stays private:

```bat
ssh -N -L 9010:127.0.0.1:9010 ubuntu@149.202.63.227
```

## Runbook (3 terminals)

1) Tunnel (CMD)
```bat
ssh -N -L 9010:127.0.0.1:9010 ubuntu@149.202.63.227
```

2) Simulator (PowerShell)
```powershell
cd "C:\Users\xfive\Desktop\EMS simulator"
python openems_simulator.py
```

3) Shipper (PowerShell)
```powershell
cd "C:\Users\xfive\Desktop\EMS simulator"
python ems_shipper_text.py --file "C:\Users\xfive\Desktop\EMS simulator\openems_simulation.log" --host 127.0.0.1 --port 9010 --site "mrR-ems"
```

## Notes
- This is lossless at the event level because every event requires ACK before it is marked sent.
- If you later switch to JSONL telemetry, use `ems_shipper.py` and the same receiver.
