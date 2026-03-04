#!/usr/bin/env python3
"""Green Energy EMS Simulator (Solar + Hydrogen) — Tkinter.

MVP goals:
- Generate *near-realistic* EMS telemetry (solar + battery + electrolyzer + H2 tank).
- Write machine-friendly **JSONL** for OpenClaw (best for anomaly detection).
- Optionally also write a human-friendly **OpenEMS-like text log**.
- UI buttons toggle anomalies ON/OFF (HV/LV/Overtemp/H2 leak/Comms loss).

Outputs are safe-by-default (no secrets).

Recommended integration:
- OpenClaw tails the JSONL file and alerts when status==ALARM or anomalies.*==true.
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
from tkinter.scrolledtext import ScrolledText


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def openems_ts() -> str:
    # OpenEMS-ish timestamp format: 2026-03-04T12:00:00,123
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S,%f")[:-3]


@dataclass
class AnomalyFlags:
    hv_dc_bus: bool = False
    lv_dc_bus: bool = False
    inverter_overtemp: bool = False
    h2_leak: bool = False
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
    status: str  # OK | ALARM
    anomalies: dict


class Simulator:
    def __init__(self, site: str, jsonl_path: Path, interval_s: float = 1.0):
        self.site = site
        self.jsonl_path = jsonl_path
        self.interval_s = interval_s

        # Optional human log
        self.write_text_log = True
        self.text_log_path = jsonl_path.with_suffix(".log")

        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        # state
        self.seq = 0
        self.flags = AnomalyFlags()
        self.soc = 65.0
        self.h2_bar = 250.0
        self.inv_temp = 40.0

        # pseudo-day profile phase (seconds)
        self._t0 = time.time()

        # hook for UI preview
        self.on_emit = None  # type: ignore

    def set_paths(self, jsonl_path: Path, text_log_path: Path | None = None) -> None:
        with self._lock:
            self.jsonl_path = jsonl_path
            if text_log_path is not None:
                self.text_log_path = text_log_path

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
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.text_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Write a startup marker (text log)
        if self.write_text_log:
            self._append_text(self.text_log_path, f"{openems_ts()} [system  ] INFO  [component.AbstractOpenemsComponent] Green Energy System Initialized\n")

        while True:
            with self._lock:
                if not self._running:
                    break
                interval = self.interval_s
                jsonl_path = self.jsonl_path
                text_log_path = self.text_log_path
                write_text = self.write_text_log

            telem, text_lines = self._tick_with_logs()
            self._append_jsonl(jsonl_path, telem)
            if write_text:
                for ln in text_lines:
                    self._append_text(text_log_path, ln)

            if self.on_emit:
                try:
                    self.on_emit(telem, text_lines)
                except Exception:
                    pass

            time.sleep(max(0.05, interval))

    def _append_jsonl(self, path: Path, telem: Telemetry) -> None:
        line = json.dumps(asdict(telem), separators=(",", ":"), ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _append_text(self, path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()

    def _tick_with_logs(self) -> tuple[Telemetry, list[str]]:
        self.seq += 1
        t = time.time() - self._t0

        flags = self.snapshot_flags()

        # Fast demo day/night cycle (~4 minutes)
        day_period = 240.0
        phase = (t % day_period) / day_period
        sun = max(0.0, math.sin(math.pi * phase))

        cloud = 0.85 + 0.25 * random.random()
        irradiance = 1000.0 * sun * cloud

        pv_kw = max(0.0, (irradiance / 1000.0) * 45.0)
        pv_kw *= (0.97 + 0.06 * random.random())

        load_kw = 18.0 + 6.0 * random.random() + (3.0 * math.sin(2 * math.pi * (t / 30.0)))
        load_kw = max(8.0, load_kw)

        net_kw = pv_kw - load_kw

        batt_kw = 0.0
        electrolyzer_kw = 0.0

        max_chg = 15.0
        max_dis = 15.0

        if net_kw > 0:
            if self.soc < 95.0:
                batt_kw = min(max_chg, net_kw)
                net_kw -= batt_kw
                self.soc = min(100.0, self.soc + 0.03 * batt_kw)
            electrolyzer_kw = min(20.0, net_kw)
        else:
            if self.soc > 10.0:
                batt_kw = -min(max_dis, abs(net_kw))
                self.soc = max(0.0, self.soc - 0.04 * abs(batt_kw))

        h2_rate = max(0.0, electrolyzer_kw * (0.42 + 0.08 * random.random()))
        self.h2_bar = max(20.0, min(350.0, self.h2_bar + 0.02 * h2_rate - 0.03))

        ambient = 26.0 + 2.0 * math.sin(2 * math.pi * (t / 120.0))
        power_through = abs(load_kw) + abs(batt_kw) + abs(electrolyzer_kw)
        self.inv_temp = 0.92 * self.inv_temp + 0.08 * (ambient + 0.7 * power_through)

        dc_bus = 760.0 + random.uniform(-4.0, 4.0)

        anomalies = asdict(flags)
        status = "OK"
        text_lines: list[str] = []

        def err(component: str, msg: str) -> None:
            text_lines.append(f"{openems_ts()} [{component:<8}] ERROR [e.modbus.api.task.AbstractTask] {msg}\n")

        # Inject anomalies
        if flags.hv_dc_bus:
            dc_bus = 880.0 + random.uniform(-10, 10)
            status = "ALARM"
            err("ess0", f"Critical High Voltage on DC Bus: {dc_bus:.1f}V (Limit: 850V)")

        if flags.lv_dc_bus:
            dc_bus = 330.0 + random.uniform(-10, 10)
            status = "ALARM"
            err("ess0", f"Battery Under-Voltage: {dc_bus:.1f}V - Emergency Shutdown Imminent")

        if flags.inverter_overtemp:
            self.inv_temp = max(self.inv_temp, 95.0 + random.uniform(-1, 8))
            status = "ALARM"
            err("pv_inv1", f"Inverter Temperature Critical: {self.inv_temp:.1f}°C - Derating Power Output")

        if flags.h2_leak:
            self.h2_bar = max(5.0, self.h2_bar - 2.5)
            status = "ALARM"
            err("h2_ctrl", f"Pressure Drop Detected in Storage Tank: {self.h2_bar:.1f} bar - Potential Leak!")

        if flags.electrolyzer_overpressure:
            self.h2_bar = max(self.h2_bar, 335.0 + random.uniform(-2, 6))
            status = "ALARM"
            err("h2_ctrl", f"Electrolyzer Over-Pressure: {self.h2_bar:.1f} bar - Safety Vent Required")

        if flags.comms_loss:
            status = "ALARM"
            err("comms", "Comms Loss: Modbus timeout / stale telemetry")

        # Normal heartbeat
        if not text_lines and (self.seq % 5 == 0):
            text_lines.append(
                f"{openems_ts()} [system  ] INFO  [e.modbus.api.task.AbstractTask] Solar: {pv_kw:.1f}kW | SoC: {self.soc:.1f}% | H2: {h2_rate:.2f}NL/min | Tank: {self.h2_bar:.1f}bar\n"
            )

        telem = Telemetry(
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

        return telem, text_lines


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OpenEMS Green Energy Simulator (Solar + H2) — OpenClaw")
        self.geometry("980x720")

        default_dir = Path.home() / "Desktop" / "ems_sim"
        self.jsonl_path = default_dir / "ems_telemetry.jsonl"
        self.text_path = default_dir / "openems_simulation.log"

        self.sim = Simulator(site="demo-site", jsonl_path=self.jsonl_path, interval_s=1.0)
        self.sim.text_log_path = self.text_path
        self.sim.write_text_log = True
        self.sim.on_emit = self._on_emit

        self._build_ui()
        self._update_preview_loop()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(header, text="Simulateur EMS — Solaire + Hydrogène", font=("Helvetica", 14, "bold")).pack(side="left")

        paths = ttk.LabelFrame(self, text="Fichiers de logs")
        paths.pack(fill="x", padx=10, pady=6)

        self.jsonl_var = tk.StringVar(value=str(self.jsonl_path))
        self.text_var = tk.StringVar(value=str(self.text_path))

        row1 = ttk.Frame(paths)
        row1.pack(fill="x", padx=10, pady=6)
        ttk.Label(row1, text="JSONL (OpenClaw):").pack(side="left")
        ttk.Entry(row1, textvariable=self.jsonl_var, width=78).pack(side="left", padx=8)
        ttk.Button(row1, text="Browse…", command=self._browse_jsonl).pack(side="left")

        row2 = ttk.Frame(paths)
        row2.pack(fill="x", padx=10, pady=6)
        self.text_enable = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="Also write OpenEMS-like text log", variable=self.text_enable, command=self._apply_text_enable).pack(side="left")
        ttk.Label(row2, text="Text log:").pack(side="left", padx=(20, 0))
        ttk.Entry(row2, textvariable=self.text_var, width=62).pack(side="left", padx=8)
        ttk.Button(row2, text="Browse…", command=self._browse_text).pack(side="left")

        ctrl = ttk.LabelFrame(self, text="Contrôles")
        ctrl.pack(fill="x", padx=10, pady=6)

        ttk.Label(ctrl, text="Site:").pack(side="left", padx=8)
        self.site_var = tk.StringVar(value=self.sim.site)
        ttk.Entry(ctrl, textvariable=self.site_var, width=18).pack(side="left")

        ttk.Label(ctrl, text="Interval (s):").pack(side="left", padx=(20, 8))
        self.int_var = tk.DoubleVar(value=self.sim.interval_s)
        ttk.Spinbox(ctrl, from_=0.2, to=10.0, increment=0.2, textvariable=self.int_var, width=6).pack(side="left")

        self.start_btn = ttk.Button(ctrl, text="Démarrer Simulation", command=self._toggle)
        self.start_btn.pack(side="left", padx=12)

        ttk.Button(ctrl, text="Write one sample", command=self._write_one).pack(side="left")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=6)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # Dashboard
        dash = ttk.LabelFrame(body, text="Tableau de bord (valeurs réalistes)")
        dash.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))

        self.dash_labels = {}
        metrics = [
            ("Irradiance", "irradiance_w_m2", "W/m²"),
            ("PV", "pv_kw", "kW"),
            ("SoC", "soc_pct", "%"),
            ("DC bus", "dc_bus_v", "V"),
            ("Inv temp", "inverter_temp_c", "°C"),
            ("Load", "load_kw", "kW"),
            ("Electrolyzer", "electrolyzer_kw", "kW"),
            ("H2 tank", "h2_tank_bar", "bar"),
        ]
        for i, (name, key, unit) in enumerate(metrics):
            r = i // 2
            c = (i % 2)
            frm = ttk.Frame(dash)
            frm.grid(row=r, column=c, padx=12, pady=8, sticky="w")
            ttk.Label(frm, text=name, font=("Helvetica", 9, "bold")).pack(anchor="w")
            lbl = ttk.Label(frm, text=f"0 {unit}", font=("Consolas", 11), foreground="#2b6cb0")
            lbl.pack(anchor="w")
            self.dash_labels[key] = (lbl, unit)

        # Anomalies
        an = ttk.LabelFrame(body, text="Injection d'anomalies (clic = ALARM / re-clic = NORMAL)")
        an.grid(row=0, column=1, sticky="nsew", pady=(0, 10))

        self.anomaly_buttons: dict[str, ttk.Button] = {}
        self.active_anomaly = None

        btns = [
            ("Haute Tension (HV)", "hv_dc_bus"),
            ("Basse Tension (LV)", "lv_dc_bus"),
            ("Fuite Hydrogène", "h2_leak"),
            ("Surchauffe Onduleur", "inverter_overtemp"),
            ("Surpression Electrolyseur", "electrolyzer_overpressure"),
            ("Perte Comms", "comms_loss"),
        ]

        for text, code in btns:
            b = ttk.Button(an, text=text, command=lambda c=code: self._toggle_anomaly(c))
            b.pack(fill="x", padx=10, pady=6)
            self.anomaly_buttons[code] = b

        # Logs
        logs = ttk.LabelFrame(body, text="Flux logs (OpenEMS-like text log)")
        logs.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.log_area = ScrolledText(logs, height=14, state="disabled", bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10))
        self.log_area.pack(fill="both", expand=True, padx=8, pady=8)

        self.status_var = tk.StringVar(value="Système prêt")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill="x", padx=10, pady=(0, 8))

    def _browse_jsonl(self):
        p = filedialog.asksaveasfilename(title="Select JSONL output", defaultextension=".jsonl", filetypes=[("JSONL", "*.jsonl"), ("All", "*.*")])
        if p:
            self.jsonl_var.set(p)

    def _browse_text(self):
        p = filedialog.asksaveasfilename(title="Select text log output", defaultextension=".log", filetypes=[("LOG", "*.log"), ("All", "*.*")])
        if p:
            self.text_var.set(p)

    def _apply_text_enable(self):
        self.sim.write_text_log = bool(self.text_enable.get())

    def _toggle(self):
        if self.start_btn["text"].startswith("Démarrer"):
            self.sim.site = self.site_var.get().strip() or "demo-site"
            try:
                self.sim.set_interval(float(self.int_var.get()))
            except Exception:
                messagebox.showerror("Invalid interval", "Interval must be a number")
                return

            self.sim.set_paths(Path(self.jsonl_var.get()), Path(self.text_var.get()))
            self.sim.write_text_log = bool(self.text_enable.get())
            self.sim.start()
            self.start_btn.configure(text="Arrêter Simulation")
            self.status_var.set("Simulation en cours")
        else:
            self.sim.stop()
            self.start_btn.configure(text="Démarrer Simulation")
            self.status_var.set("Système à l'arrêt")

    def _write_one(self):
        self.sim.site = self.site_var.get().strip() or "demo-site"
        self.sim.set_paths(Path(self.jsonl_var.get()), Path(self.text_var.get()))
        telem, lines = self.sim._tick_with_logs()
        self.sim.seq -= 1
        self.sim._append_jsonl(self.sim.jsonl_path, telem)
        if self.sim.write_text_log:
            for ln in lines:
                self.sim._append_text(self.sim.text_log_path, ln)
                self._append_ui_log(ln)
        messagebox.showinfo("Wrote", "Wrote one telemetry sample")

    def _toggle_anomaly(self, code: str):
        # toggle one at a time for clean demos
        if self.active_anomaly == code:
            self.active_anomaly = None
            # clear all flags
            for k in self.anomaly_buttons.keys():
                self.sim.set_flag(k, False)
            self.status_var.set("Retour à la normale")
        else:
            self.active_anomaly = code
            for k in self.anomaly_buttons.keys():
                self.sim.set_flag(k, k == code)
            self.status_var.set(f"ALERTE ACTIVE: {code}")

        # Update button text styling
        for k, b in self.anomaly_buttons.items():
            if self.active_anomaly == k:
                b.configure(text=f"!!! {k.upper()} !!!")
            else:
                # restore label
                # (quick mapping)
                pass

    def _append_ui_log(self, line: str):
        self.log_area.configure(state="normal")
        self.log_area.insert("end", line)
        self.log_area.see("end")
        # keep ~800 lines
        try:
            if int(self.log_area.index("end-1c").split(".")[0]) > 800:
                self.log_area.delete("1.0", "2.0")
        except Exception:
            pass
        self.log_area.configure(state="disabled")

    def _on_emit(self, telem: Telemetry, text_lines: list[str]):
        # UI thread safe: schedule
        def _do():
            # dashboard
            for key, (lbl, unit) in self.dash_labels.items():
                v = getattr(telem, key)
                lbl.configure(text=f"{v} {unit}")
            # status
            if telem.status == "ALARM":
                self.status_var.set("ALARM — anomalies active")
            # logs
            for ln in text_lines:
                self._append_ui_log(ln)

        self.after(0, _do)

    def _update_preview_loop(self):
        # nothing heavy here; dashboard updates come from on_emit
        self.after(1000, self._update_preview_loop)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
