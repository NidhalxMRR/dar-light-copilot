#!/usr/bin/env python3
"""EMS ingest server (VPS) — TCP line protocol with ACK.

- Listens on 127.0.0.1:9010 (keep private; use SSH tunnel from PC)
- For each received JSON event (one per line), immediately replies {"ack": seq}
- Classifies alarms and sends Telegram alerts (via VPS OpenClaw)

Run as systemd service.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass

OPENCLAW_BIN = "/home/ubuntu/.local/share/pnpm/openclaw"
TELEGRAM_TARGET = "6072002251"


@dataclass
class RateLimit:
    last_sent: float = 0.0
    cooldown_s: float = 5.0
    last_fingerprint: str = ""


RL = RateLimit()


def fingerprint(evt: dict) -> str:
    # stable-ish dedupe key
    try:
        payload = evt.get("payload") or {}
        anomalies = payload.get("anomalies") or {}
        on = ",".join(sorted([k for k, v in anomalies.items() if v]))
        status = payload.get("status")
        return f"{status}|{on}"
    except Exception:
        return ""


def classify(evt: dict) -> str | None:
    payload = evt.get("payload") or {}
    status = payload.get("status")
    anomalies = payload.get("anomalies") or {}
    if status == "ALARM" or any(bool(v) for v in anomalies.values()):
        on = [k for k, v in anomalies.items() if v]
        return ",".join(on) if on else "ALARM"
    return None


def send_telegram(msg: str) -> None:
    import subprocess

    subprocess.run(
        [OPENCLAW_BIN, "message", "send", "--channel", "telegram", "--target", TELEGRAM_TARGET, "--message", msg],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def handle_client(conn: socket.socket, addr):
    buf = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line:
                    continue
                try:
                    evt = json.loads(line.decode("utf-8", errors="replace"))
                except Exception:
                    continue

                seq = evt.get("seq")
                # ACK immediately
                conn.sendall((json.dumps({"ack": seq}) + "\n").encode("utf-8"))

                tag = classify(evt)
                if not tag:
                    continue

                fp = fingerprint(evt)
                now = time.time()
                if fp and fp == RL.last_fingerprint and now - RL.last_sent < RL.cooldown_s:
                    continue
                if now - RL.last_sent < RL.cooldown_s:
                    continue

                payload = evt.get("payload") or {}
                msg = (
                    f"[EMS ALERT] site={evt.get('site')} seq={seq} tag={tag} "
                    f"dc_bus_v={payload.get('dc_bus_v')} inv_temp={payload.get('inverter_temp_c')} h2_bar={payload.get('h2_tank_bar')}"
                )
                send_telegram(msg)
                RL.last_sent = now
                RL.last_fingerprint = fp
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    host = "127.0.0.1"
    port = 9010
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(5)
    print(f"EMS ingest listening on {host}:{port}")
    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
