#!/usr/bin/env python3
"""Lossless real-time shipper (Windows) for EMS *text* log.

- Tails openems_simulation.log
- Assigns a monotonically increasing seq
- Stores events in a local SQLite spool until ACKed by VPS
- Sends events over a TCP tunnel (recommended: SSH -L)

Protocol:
- Client sends one JSON per line: {seq, ts, kind, site, line}
- Server replies: {"ack": <seq>} one per line

Usage (Windows):
  python ems_shipper_text.py --file "C:\\Users\\xfive\\Desktop\\EMS simulator\\openems_simulation.log" --host 127.0.0.1 --port 9010

Keep an SSH tunnel open:
  ssh -N -L 9010:127.0.0.1:9010 ubuntu@149.202.63.227
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import socket
from datetime import datetime, timezone


def iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        create table if not exists spool (
          seq integer primary key,
          ts text not null,
          line text not null,
          sent integer not null default 0
        )
        """
    )
    conn.commit()
    return conn


def tail_lines(path: str, sleep_s: float = 0.2):
    while not os.path.exists(path):
        time.sleep(0.5)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(sleep_s)
                continue
            yield line.strip("\r\n")


def connect(host: str, port: int, timeout_s: float = 5.0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    s.connect((host, port))
    s.settimeout(None)
    return s


def send_line(sock: socket.socket, obj: dict) -> None:
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sock.sendall(data)


def recv_line(sock: socket.socket) -> str:
    buf = bytearray()
    while True:
        ch = sock.recv(1)
        if not ch:
            raise ConnectionError("socket closed")
        if ch == b"\n":
            return buf.decode("utf-8", errors="replace")
        buf.extend(ch)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="openems_simulation.log")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9010)
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "ems_spool_text.db"))
    ap.add_argument("--site", default="demo-site")
    args = ap.parse_args()

    conn = ensure_db(args.db)
    row = conn.execute("select coalesce(max(seq), 0) from spool").fetchone()
    seq = int(row[0] or 0)

    print(f"[shipper-text] tail={args.file}")
    print(f"[shipper-text] spool={args.db}")
    print(f"[shipper-text] target={args.host}:{args.port} (tunnel)")

    sock = None

    def ensure_conn():
        nonlocal sock
        while sock is None:
            try:
                sock = connect(args.host, args.port)
                print("[shipper-text] connected")
            except Exception as e:
                print(f"[shipper-text] connect failed: {e}; retrying...")
                time.sleep(1.0)

    tail = tail_lines(args.file)
    last_flush = 0.0

    while True:
        line = next(tail)
        if not line:
            continue

        seq += 1
        conn.execute("insert or replace into spool(seq, ts, line, sent) values(?,?,?,0)", (seq, iso_utc(), line))
        conn.commit()

        if time.time() - last_flush < 0.1:
            continue
        last_flush = time.time()

        ensure_conn()

        cur = conn.execute("select seq, ts, line from spool where sent=0 order by seq asc limit 200")
        batch = cur.fetchall()
        if not batch:
            continue

        try:
            for s_seq, s_ts, s_line in batch:
                send_line(
                    sock,
                    {
                        "seq": s_seq,
                        "ts": s_ts,
                        "kind": "ems_text",
                        "site": args.site,
                        "line": s_line,
                    },
                )
                ack_raw = recv_line(sock)
                ack = json.loads(ack_raw)
                if ack.get("ack") != s_seq:
                    raise RuntimeError(f"bad ack: got {ack} expected {s_seq}")
                conn.execute("update spool set sent=1 where seq=?", (s_seq,))
            conn.commit()
        except Exception as e:
            print(f"[shipper-text] send/ack failed: {e}; reconnecting")
            try:
                sock.close()
            except Exception:
                pass
            sock = None
            time.sleep(0.5)


if __name__ == "__main__":
    main()
