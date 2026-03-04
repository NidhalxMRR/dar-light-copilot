#!/usr/bin/env python3
"""OpenEMS-style Green Energy Simulator (Solar + Hydrogen) + Tkinter UI.

- Generates near-realistic telemetry every N seconds.
- Writes JSONL logs (one JSON object per line) to a file.
- Allows toggling anomaly states (high/low voltage, overtemp, comms loss, etc.).
- Designed for OpenClaw integration: a listener can tail the JSONL file and detect anomalies.

Security: logs avoid secrets; only simulated telemetry.
"""

from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AnomalyFlags:
    hv_dc_bus: bool = False
    lv_dc_bus: bool = False
    inverter_overtemp: bool = False
    electrolyzer_overpressure: bool = False
    comms_loss: bool = False


@dataclass
class Telemetry:
    ts: str
    seq: int
    site: str

    # Solar
    irradiance_w_m2: float
    pv_kw: float

    # Battery
    soc_pct: float
    batt_kw: float  # +charge, -discharge

    # DC Bus / Inverter
    dc_bus_v: float
    inverter_temp_c: float

    # Loads
    load_kw: float

    # Hydrogen chain
    electrolyzer_kw: float
    h2_rate_nl_min: float
    h2_tank_bar: float

    # Health
    status: str  # OK | WARN | ALARM
    anomalies: dict


class Simulator:
    def __init__(self, site: str, out_path: Path, interval_s: float = 1.0):
        self.site = site
        self.out_path = out_path
        self.interval_s = interval_s

        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        # state
        self.seq = 0
        self.flags = AnomalyFlags()
        self.soc = 55.0
        self.h2_bar = 120.0
        self.inv_temp = 42.0

        # pseudo-day profile phase (seconds)
        self._t0 = time.time()

    def set_out_path(self, p: Path) -> None:
        with self._lock:
            self.out_path = p

    def set_interval(self, s: float) -> None:
        with self._lock:
            self.interval_s = s

    def set_flag(self, name: str, value: bool) -> None:
        with self._lock:
            setattr(self.flags, name, value)

    def snapshot_flags(self) -> AnomalyFlags:
        with self._lock:
            return AnomalyFlags(**asdict(self.flags))

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _run(self) -> None:
        # Ensure directory exists
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            with self._lock:
                if not self._running:
                    break
                interval = self.interval_s
                out_path = self.out_path
            telem = self._tick()
            self._append_jsonl(out_path, telem)
            time.sleep(max(0.05, interval))

    def _append_jsonl(self, path: Path, telem: Telemetry) -> None:
        line = json.dumps(asdict(telem), separators=(",", ":"), ensure_ascii=False)
        # atomic-ish append
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _tick(self) -> Telemetry:
        self.seq += 1
        t = time.time() - self._t0

        flags = self.snapshot_flags()

        # Daylight curve (0..1), approx 24h period scaled down for demo.
        # Use a ~4 minute "day" so the demo looks alive.
        day_period = 240.0
        phase = (t % day_period) / day_period
        sun = max(0.0, math.sin(math.pi * phase))  # 0 at night, 1 at noon

        # irradiance with weather noise
        cloud = 0.85 + 0.25 * random.random()
        irradiance = 1000.0 * sun * cloud

        pv_kw = max(0.0, (irradiance / 1000.0) * 45.0)  # 45kW array
        pv_kw *= (0.97 + 0.06 * random.random())

        # Base load fluctuates
        load_kw = 18.0 + 6.0 * random.random() + (3.0 * math.sin(2 * math.pi * (t / 30.0)))
        load_kw = max(8.0, load_kw)

        # Control policy (simple):
        # - Use PV to feed loads
        # - Excess PV charges battery then runs electrolyzer
        # - Deficit discharges battery
        net_kw = pv_kw - load_kw

        batt_kw = 0.0
        electrolyzer_kw = 0.0

        # battery charge/discharge limits
        max_chg = 15.0
        max_dis = 15.0

        if net_kw > 0:
            # charge battery if not full
            if self.soc < 95.0:
                batt_kw = min(max_chg, net_kw)
                net_kw -= batt_kw
                self.soc = min(100.0, self.soc + 0.03 * batt_kw)  # quick demo dynamics
            # run electrolyzer with remaining
            electrolyzer_kw = min(20.0, net_kw)
        else:
            # discharge battery if not empty
            if self.soc > 10.0:
                batt_kw = -min(max_dis, abs(net_kw))
                self.soc = max(0.0, self.soc - 0.04 * abs(batt_kw))

        # Hydrogen production (rough):
        # 1 kW -> ~0.45 NL/min (demo scaling)
        h2_rate = max(0.0, electrolyzer_kw * (0.42 + 0.08 * random.random()))
        # Tank pressure rises with production, leaks slowly
        self.h2_bar = max(20.0, min(350.0, self.h2_bar + 0.02 * h2_rate - 0.03))

        # Inverter temperature tracks power + ambient drift
        ambient = 26.0 + 2.0 * math.sin(2 * math.pi * (t / 120.0))
        power_through = abs(load_kw) + abs(batt_kw) + abs(electrolyzer_kw)
        self.inv_temp = 0.92 * self.inv_temp + 0.08 * (ambient + 0.7 * power_through)

        # DC bus voltage nominal 760V
        dc_bus = 760.0 + random.uniform(-4.0, 4.0)

        # Apply anomalies
        anomalies = asdict(flags)
        status = "OK"
        if flags.comms_loss:
            status = "ALARM"
        if flags.hv_dc_bus:
            dc_bus = 920.0 + random.uniform(-10, 10)
            status = "ALARM"
        if flags.lv_dc_bus:
            dc_bus = 520.0 + random.uniform(-10, 10)
            status = "ALARM"
        if flags.inverter_overtemp:
            self.inv_temp = max(self.inv_temp, 98.0 + random.uniform(-1, 3))
            status = "ALARM"
        if flags.electrolyzer_overpressure:
            self.h2_bar = max(self.h2_bar, 330.0 + random.uniform(-2, 6))
            status = "ALARM"

        # For comms loss, we still log but add clear field
        if flags.comms_loss:
            anomalies["comms_loss"] = True

        return Telemetry(
            ts=iso_utc_now(),
            seq=self.seq,
            site=self.site,
            irradiance_w_m2=round(irradiance, 1),
            pv_kw=round(pv_kw, 2),
            soc_pct=round(self.soc, 2),
            batt_kw=round(batt_kw, 2),
            dc_bus_v=round(dc_bus, 1),
            inverter_temp_c=round(self.inv_temp, 1),
            load_kw=round(load_kw, 2),
            electrolyzer_kw=round(electrolyzer_kw, 2),
            h2_rate_nl_min=round(h2_rate, 2),
            h2_tank_bar=round(self.h2_bar, 1),
            status=status,
            anomalies=anomalies,
        )


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Green Energy EMS Simulator (Solar + H2) — OpenClaw")
        self.geometry("860x520")

        default_path = Path.home() / "Desktop" / "ems_sim" / "ems_telemetry.jsonl"
        self.sim = Simulator(site="demo-site", out_path=default_path, interval_s=1.0)

        self._build_ui()
        self._ui_tick()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Output JSONL file:").pack(side="left")
        self.path_var = tk.StringVar(value=str(self.sim.out_path))
        entry = ttk.Entry(top, textvariable=self.path_var, width=70)
        entry.pack(side="left", padx=8)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="x", **pad)

        ttk.Label(mid, text="Site:").pack(side="left")
        self.site_var = tk.StringVar(value=self.sim.site)
        ttk.Entry(mid, textvariable=self.site_var, width=18).pack(side="left", padx=8)

        ttk.Label(mid, text="Interval (s):").pack(side="left")
        self.int_var = tk.DoubleVar(value=self.sim.interval_s)
        ttk.Spinbox(mid, from_=0.2, to=10.0, increment=0.2, textvariable=self.int_var, width=6).pack(side="left", padx=8)

        self.run_btn = ttk.Button(mid, text="Start", command=self._toggle_run)
        self.run_btn.pack(side="left", padx=8)

        ttk.Button(mid, text="Write one sample line", command=self._write_one).pack(side="left")

        sep = ttk.Separator(self)
        sep.pack(fill="x", padx=10, pady=5)

        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True, padx=10, pady=8)

        # Anomaly toggles
        left = ttk.LabelFrame(grid, text="Anomaly toggles (click to ALARM / click again to NORMAL)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=2)
        grid.rowconfigure(0, weight=1)

        self.flag_vars: dict[str, tk.BooleanVar] = {}
        for name, label in [
            ("hv_dc_bus", "High DC Bus Voltage"),
            ("lv_dc_bus", "Low DC Bus Voltage"),
            ("inverter_overtemp", "Inverter Over-Temp"),
            ("electrolyzer_overpressure", "Electrolyzer Over-Pressure"),
            ("comms_loss", "Comms Loss"),
        ]:
            v = tk.BooleanVar(value=False)
            self.flag_vars[name] = v
            cb = ttk.Checkbutton(left, text=label, variable=v, command=lambda n=name: self._on_flag(n))
            cb.pack(anchor="w", padx=10, pady=6)

        # Live telemetry
        right = ttk.LabelFrame(grid, text="Live preview (approx-realistic solar + hydrogen telemetry)")
        right.grid(row=0, column=1, sticky="nsew")

        self.preview = tk.Text(right, height=20, width=60)
        self.preview.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview.configure(state="disabled")

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(bottom, text="Integration: tail the JSONL file and trigger alerts on status=ALARM or anomalies.*=true").pack(anchor="w")

    def _browse(self):
        p = filedialog.asksaveasfilename(
            title="Select output JSONL path",
            initialfile="ems_telemetry.jsonl",
            defaultextension=".jsonl",
            filetypes=[("JSONL", "*.jsonl"), ("All files", "*.*")],
        )
        if p:
            self.path_var.set(p)
            self.sim.set_out_path(Path(p))

    def _toggle_run(self):
        if self.run_btn["text"] == "Start":
            # apply settings
            self.sim.site = self.site_var.get().strip() or "demo-site"
            try:
                self.sim.set_interval(float(self.int_var.get()))
            except Exception:
                messagebox.showerror("Invalid interval", "Interval must be a number")
                return
            self.sim.set_out_path(Path(self.path_var.get()))
            self.sim.start()
            self.run_btn.configure(text="Stop")
        else:
            self.sim.stop()
            self.run_btn.configure(text="Start")

    def _write_one(self):
        self.sim.site = self.site_var.get().strip() or "demo-site"
        self.sim.set_out_path(Path(self.path_var.get()))
        t = self.sim._tick()
        self.sim._append_jsonl(self.sim.out_path, t)
        messagebox.showinfo("Wrote", "Wrote one JSONL line")

    def _on_flag(self, name: str):
        self.sim.set_flag(name, bool(self.flag_vars[name].get()))

    def _ui_tick(self):
        # show a preview of the next telemetry line (without writing)
        t = self.sim._tick()
        # roll back seq increment side-effect for preview: keep UI smooth
        self.sim.seq -= 1

        s = json.dumps(asdict(t), indent=2, ensure_ascii=False)
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("end", s)
        self.preview.configure(state="disabled")

        self.after(700, self._ui_tick)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
