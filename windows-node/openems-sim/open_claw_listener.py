#!/usr/bin/env python3
"""Example OpenClaw-side listener for the EMS simulator JSONL.

This is a lightweight tailer that:
- follows a JSONL file
- prints alarm events and anomalies
- can be replaced by an OpenClaw skill/tool later

Run:
  python open_claw_listener.py --file "C:\\Users\\xfive\\Desktop\\ems_sim\\ems_telemetry.jsonl"

No secret values are printed.
"""

from __future__ import annotations

import argparse
import json
import os
import time


def follow(path: str, sleep_s: float = 0.2):
    with open(path, "r", encoding="utf-8") as f:
        # seek to end
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(sleep_s)
                continue
            yield line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    args = ap.parse_args()

    print(f"Listening: {args.file}")
    for line in follow(args.file):
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue

        status = evt.get("status")
        anomalies = evt.get("anomalies") or {}
        if status == "ALARM" or any(bool(v) for v in anomalies.values()):
            # Redacted: print only keys, not any potential secret values
            on = [k for k, v in anomalies.items() if v]
            print(f"[{evt.get('ts')}] ALARM seq={evt.get('seq')} on={on} dc_bus_v={evt.get('dc_bus_v')} inv_temp={evt.get('inverter_temp_c')} h2_bar={evt.get('h2_tank_bar')}")


if __name__ == "__main__":
    main()
