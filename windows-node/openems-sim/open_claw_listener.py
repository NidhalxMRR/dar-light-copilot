#!/usr/bin/env python3
"""Listener for the EMS simulator.

Supports:
- JSONL telemetry (preferred): ems_telemetry.jsonl
- OpenEMS-like text log: openems_simulation.log

Alerts:
- JSONL: status==ALARM or anomalies.*==true
- Text: any line containing " ERROR "

This script is an example of what an OpenClaw skill would do (tail + detect anomalies).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time


RE_ERROR = re.compile(r"\sERROR\s")


def follow(path: str, sleep_s: float = 0.2):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(sleep_s)
                continue
            yield line


def try_json(line: str):
    try:
        return json.loads(line)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    args = ap.parse_args()

    print(f"Listening: {args.file}")

    for raw in follow(args.file):
        line = raw.strip()
        if not line:
            continue

        evt = try_json(line)
        if isinstance(evt, dict):
            status = evt.get("status")
            anomalies = evt.get("anomalies") or {}
            if status == "ALARM" or any(bool(v) for v in anomalies.values()):
                on = [k for k, v in anomalies.items() if v]
                print(
                    f"[{evt.get('ts')}] ALARM seq={evt.get('seq')} on={on} "
                    f"dc_bus_v={evt.get('dc_bus_v')} inv_temp={evt.get('inverter_temp_c')} h2_bar={evt.get('h2_tank_bar')}"
                )
            continue

        # text log mode
        if RE_ERROR.search(line):
            # redacted: we print the line (it is simulated), but in real use you could strip values.
            print(f"[TEXT] ALERT: {line}")


if __name__ == "__main__":
    main()
