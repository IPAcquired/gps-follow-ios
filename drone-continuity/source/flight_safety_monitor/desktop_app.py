"""Native Tk desktop interface for Flight Safety Monitor."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
if getattr(sys, "frozen", False):
    ROOT = Path.home() / "Documents" / "Codex" / "2026-09-27" / "locate-and-fix-the-user-s"
    APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
sys.path.insert(0, str(APP_DIR))

import flight_guard as guard  # noqa: E402


class FlightSafetyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Flight Safety Monitor")
        self.geometry("1120x760")
        self.minsize(900, 620)
        self.configure(bg="#101820")
        self.output_dir = ROOT / "outputs" / "flight-safety-monitor"
        self.events = queue.Queue()
        self.monitor_stop = threading.Event()
        self.monitor_thread = None
        self.current_report = None
        self.current_proposal = None
        self.current_paths = {}
        self.live_events = []
        self._build_style()
        self._build_ui()
        self.after(120, self._drain_events)
        self._set_status("Ready — analysis and live monitoring are read-only", "good")
        self.after(250, self.check_model)

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#101820")
        style.configure("Card.TFrame", background="#17232d")
        style.configure("TLabel", background="#101820", foreground="#dce8ef", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#101820", foreground="white", font=("Segoe UI Semibold", 22))
        style.configure("Sub.TLabel", background="#101820", foreground="#9fb3c1", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#17232d", foreground="#dce8ef", font=("Segoe UI", 10))
        style.configure("Metric.TLabel", background="#17232d", foreground="white", font=("Segoe UI Semibold", 16))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(12, 8))
        style.configure("Accent.TButton", background="#1f8a70", foreground="white")
        style.map("Accent.TButton", background=[("active", "#26a98a")])
        style.configure("Danger.TButton", background="#a54242", foreground="white")
        style.map("Danger.TButton", background=[("active", "#c05252")])
        style.configure("TNotebook", background="#101820", borderwidth=0)
        style.configure("TNotebook.Tab", background="#17232d", foreground="#cbd9e2", padding=(14, 8))
        style.map("TNotebook.Tab", background=[("selected", "#244052")], foreground=[("selected", "white")])

    def _build_ui(self):
        header = ttk.Frame(self, padding=(20, 16, 20, 10))
        header.pack(fill="x")
        ttk.Label(header, text="Flight Safety Monitor", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Deterministic flight analysis with guarded, disarmed PID application", style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        self.status_var = tk.StringVar()
        self.status_label = tk.Label(self, textvariable=self.status_var, anchor="w", padx=18, pady=8, bg="#244052", fg="white", font=("Segoe UI Semibold", 10))
        self.status_label.pack(fill="x", padx=20, pady=(0, 10))

        controls = ttk.Frame(self, padding=(20, 0, 20, 10))
        controls.pack(fill="x")
        ttk.Button(controls, text="Analyze Latest Log", style="Accent.TButton", command=self.analyze_latest).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Choose BIN…", command=self.choose_log).pack(side="left", padx=(0, 8))
        self.live_button = ttk.Button(controls, text="Start Live Monitor", command=self.toggle_monitor)
        self.live_button.pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Read PID/Filter Snapshot", command=self.capture_baseline).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Open Reports", command=self.open_reports).pack(side="left")

        connection = ttk.Frame(controls)
        connection.pack(side="right")
        ttk.Label(connection, text="Port").grid(row=0, column=0, padx=(0, 5))
        self.port_var = tk.StringVar(value="COM8")
        ttk.Entry(connection, textvariable=self.port_var, width=9).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(connection, text="Baud").grid(row=0, column=2, padx=(0, 5))
        self.baud_var = tk.StringVar(value="115200")
        ttk.Entry(connection, textvariable=self.baud_var, width=10).grid(row=0, column=3)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.dashboard = ttk.Frame(self.notebook, padding=14)
        self.details = ttk.Frame(self.notebook, padding=14)
        self.proposal_tab = ttk.Frame(self.notebook, padding=14)
        self.live_tab = ttk.Frame(self.notebook, padding=14)
        self.settings_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.dashboard, text="Dashboard")
        self.notebook.add(self.details, text="Analysis")
        self.notebook.add(self.proposal_tab, text="PID Review")
        self.notebook.add(self.live_tab, text="Live Health")
        self.notebook.add(self.settings_tab, text="Local Model")
        self._build_dashboard()
        self._build_text_tabs()
        self._build_settings()

    def _build_dashboard(self):
        metrics = ttk.Frame(self.dashboard)
        metrics.pack(fill="x")
        self.metric_vars = {}
        for index, (key, title) in enumerate((("duration", "Flight duration"), ("roll", "Roll peak"), ("pitch", "Pitch peak"), ("vibe", "Vibration"), ("sat", "Motor saturation"))):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=14)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 6, 0))
            metrics.columnconfigure(index, weight=1)
            ttk.Label(card, text=title, style="Card.TLabel").pack(anchor="w")
            var = tk.StringVar(value="—")
            self.metric_vars[key] = var
            ttk.Label(card, textvariable=var, style="Metric.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(self.dashboard, text="Safety findings", font=("Segoe UI Semibold", 13)).pack(anchor="w", pady=(18, 6))
        self.findings = tk.Text(self.dashboard, height=17, wrap="word", bg="#17232d", fg="#dce8ef", insertbackground="white", relief="flat", padx=14, pady=12, font=("Segoe UI", 10))
        self.findings.pack(fill="both", expand=True)
        self.findings.insert("1.0", "Analyze a DataFlash BIN to populate the dashboard.\n")
        self.findings.configure(state="disabled")

    def _make_text(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", bg="#17232d", fg="#dce8ef", insertbackground="white", relief="flat", padx=14, pady=12, font=("Consolas", 9))
        bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        return text

    def _build_text_tabs(self):
        self.analysis_text = self._make_text(self.details)
        top = ttk.Frame(self.proposal_tab)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Confirmation token").pack(side="left")
        self.token_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.token_var, width=16).pack(side="left", padx=8)
        ttk.Button(top, text="Apply Reviewed Proposal", style="Danger.TButton", command=self.apply_current).pack(side="left")
        ttk.Label(top, text="Blocked while armed; backup and rollback are automatic.", style="Sub.TLabel").pack(side="left", padx=12)
        self.proposal_text = self._make_text(self.proposal_tab)
        live_top = ttk.Frame(self.live_tab)
        live_top.pack(fill="x", pady=(0, 8))
        self.bench_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(live_top, text="Bench mode: battery/radio intentionally disconnected", variable=self.bench_mode_var).pack(side="left")
        self.live_gate_var = tk.StringVar(value="NO-GO — live verification has not started")
        ttk.Label(live_top, textvariable=self.live_gate_var, style="Sub.TLabel").pack(side="right")
        self.live_text = self._make_text(self.live_tab)

    def _build_settings(self):
        card = ttk.Frame(self.settings_tab, style="Card.TFrame", padding=18)
        card.pack(fill="x")
        ttk.Label(card, text="Local Ollama advisory explanation", style="Metric.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(card, text="The model explains a completed deterministic report. It cannot arm, command, flash, write parameters, or control the aircraft.", style="Card.TLabel", wraplength=820).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 16))
        ttk.Label(card, text="Model", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        self.model_var = tk.StringVar(value=guard.DEFAULT_OLLAMA_MODEL)
        ttk.Entry(card, textvariable=self.model_var, width=38).grid(row=2, column=1, sticky="w", padx=10)
        ttk.Button(card, text="Check Local Model", command=self.check_model).grid(row=2, column=2, sticky="w")
        ttk.Label(card, text="Ollama URL", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        self.ollama_var = tk.StringVar(value=guard.DEFAULT_OLLAMA_URL)
        ttk.Entry(card, textvariable=self.ollama_var, width=38).grid(row=3, column=1, sticky="w", padx=10)
        self.model_status_var = tk.StringVar(value="Local model has not been checked yet.")
        self.model_status_label = tk.Label(card, textvariable=self.model_status_var, anchor="w", justify="left", padx=10, pady=8, bg="#244052", fg="white", font=("Segoe UI Semibold", 10), wraplength=820)
        self.model_status_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(16, 8))
        ttk.Label(card, text="Leave Model blank to use deterministic analysis only. If Ollama or the selected model is unavailable, analysis still completes with a deterministic explanation.", style="Card.TLabel", wraplength=820).grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        card.columnconfigure(1, weight=1)

    def _set_model_status(self, message, tone="neutral"):
        colors = {"good": "#1f6f5c", "bad": "#8e3b3b", "busy": "#765d23", "neutral": "#244052"}
        self.model_status_var.set(message)
        self.model_status_label.configure(bg=colors.get(tone, colors["neutral"]))

    def check_model(self):
        model = self.model_var.get().strip()
        endpoint = self.ollama_var.get().strip()
        if not model:
            self._set_model_status("Local model disabled; deterministic analysis will be used.", "neutral")
            return
        self._set_model_status(f"Checking {model} on local Ollama…", "busy")
        self._run(
            lambda: guard.ollama_model_status(endpoint, model),
            lambda result: self._set_model_status(
                result["message"],
                "good" if result["available"] and result["model_installed"] else "bad",
            ),
        )

    def _set_status(self, message, tone="neutral"):
        colors = {"good": "#1f6f5c", "bad": "#8e3b3b", "busy": "#765d23", "neutral": "#244052"}
        self.status_var.set(message)
        self.status_label.configure(bg=colors.get(tone, colors["neutral"]))

    def _run(self, function, success):
        def worker():
            try:
                result = function()
                self.events.put(("success", success, result))
            except Exception as error:
                self.events.put(("error", str(error), traceback.format_exc()))
        threading.Thread(target=worker, daemon=True).start()

    def _drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "success":
                    event[1](event[2])
                elif event[0] == "live":
                    self._append_live(event[1])
                elif event[0] == "monitor_done":
                    self.live_button.configure(text="Start Live Monitor")
                    self._set_status(f"Live recording saved: {event[1]}", "good")
                else:
                    self._set_status(event[1], "bad")
                    messagebox.showerror("Flight Safety Monitor", event[1])
        except queue.Empty:
            pass
        self.after(120, self._drain_events)

    def latest_log(self):
        logs = sorted((ROOT / "outputs").glob("*.bin"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not logs:
            raise RuntimeError("No DataFlash BIN files were found in the outputs folder")
        return logs[0]

    def analyze_latest(self):
        self.analyze(self.latest_log())

    def choose_log(self):
        selected = filedialog.askopenfilename(title="Choose ArduPilot DataFlash log", filetypes=[("DataFlash BIN", "*.bin"), ("All files", "*.*")], initialdir=str(ROOT / "outputs"))
        if selected:
            self.analyze(Path(selected))

    def analyze(self, path):
        self._set_status(f"Analyzing {path.name}…", "busy")
        model = self.model_var.get().strip()
        endpoint = self.ollama_var.get().strip()
        def job():
            report = guard.analyze_log(path)
            proposal = guard.make_proposal(report)
            explanation = None
            explanation_result = None
            if model:
                explanation_result = guard.ollama_explanation_result(report, proposal, model, endpoint)
                explanation = explanation_result["text"]
            paths = guard.write_outputs(report, proposal, self.output_dir, explanation)
            return report, proposal, paths, explanation_result
        self._run(job, self._analysis_done)

    def _analysis_done(self, result):
        report, proposal, paths, explanation_result = result
        self.current_report, self.current_proposal, self.current_paths = report, proposal, paths
        if explanation_result:
            tone = "good" if explanation_result["source"] == "ollama" else "neutral"
            self._set_model_status(explanation_result["message"], tone)
        flight = report.get("flight", {})
        self.metric_vars["duration"].set(f"{flight.get('duration_s', 0):.1f} s" if flight else "None")
        for axis in ("roll", "pitch"):
            osc = report.get("control", {}).get(axis, {}).get("oscillation", {})
            self.metric_vars[axis].set(f"{osc.get('peak_hz', 0):.1f} Hz" if osc.get("usable") else "No peak")
        max_vibe = max((item.get(key, {}).get("max", 0) for item in report.get("vibration", {}).values() for key in ("VibeX", "VibeY", "VibeZ")), default=0)
        self.metric_vars["vibe"].set(f"{max_vibe:.1f}")
        self.metric_vars["sat"].set(f"{report.get('motors', {}).get('saturation_fraction', 0)*100:.1f}%")
        choices = proposal.get("choices", {})
        findings = [
            f"SOURCE LOG: {Path(report.get('log', 'unknown')).name} | analyzed {report.get('created_local', 'unknown')} | SHA-256 {report.get('log_sha256', 'unknown')[:12]}…",
            "BEST CHOICE: " + choices.get("best_choice", {}).get("recommendation", proposal.get("decision", "")),
            "MOST EFFICIENT: " + choices.get("most_efficient", {}).get("recommendation", "Unavailable"),
        ]
        findings += [f"BLOCKER: {item}" for item in report.get("blockers", [])]
        findings += [f"WARNING: {item}" for item in report.get("warnings", [])]
        self._set_text(self.findings, "\n\n".join(findings))
        self._set_text(self.analysis_text, json.dumps(report, indent=2))
        self._set_text(self.proposal_text, json.dumps(proposal, indent=2))
        self.token_var.set("")
        tone = "bad" if proposal["status"] == "blocked" else "good"
        self._set_status(proposal["decision"], tone)
        self.notebook.select(self.dashboard)

    def _set_text(self, widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _append_live(self, item):
        self.live_events.append(item)
        if len(self.live_events) > 5000:
            self.live_events = self.live_events[-5000:]
        gate = guard.assess_live_readiness(self.live_events, self.bench_mode_var.get())
        self.live_gate_var.set(f"{gate['decision']} — {len(gate['blockers'])} blocker(s), {len(gate['limitations'])} bench limitation(s)")
        self.live_text.configure(state="normal")
        self.live_text.insert("end", f"{item['elapsed_s']:7.2f}s  {item['type']}\n")
        self.live_text.see("end")
        self.live_text.configure(state="disabled")

    def toggle_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_stop.set()
            self._set_status("Stopping live monitor…", "busy")
            return
        self.monitor_stop.clear()
        self.live_events = []
        self.live_gate_var.set("NO-GO — waiting for current telemetry")
        self.live_button.configure(text="Stop Live Monitor")
        self._set_text(self.live_text, "")
        self.notebook.select(self.live_tab)
        self._set_status("Live monitor is recording selected health telemetry; it does not write parameters", "good")
        def worker():
            try:
                path = guard.live_monitor(self.port_var.get().strip(), int(self.baud_var.get()), 86400, self.output_dir, self.monitor_stop, lambda item: self.events.put(("live", item)))
                self.events.put(("monitor_done", str(path)))
            except Exception as error:
                self.events.put(("error", str(error), traceback.format_exc()))
                self.events.put(("monitor_done", "monitor stopped after an error"))
        self.monitor_thread = threading.Thread(target=worker, daemon=True)
        self.monitor_thread.start()

    def apply_current(self):
        if not self.current_proposal or not self.current_paths.get("proposal"):
            messagebox.showinfo("Flight Safety Monitor", "Analyze a log before applying a proposal.")
            return
        token = self.token_var.get().strip().upper()
        if token != self.current_proposal.get("confirmation_token"):
            messagebox.showerror("Flight Safety Monitor", "The confirmation token does not match this proposal.")
            return
        if not messagebox.askyesno("Apply reviewed PID proposal", "Confirm the aircraft is disarmed and propellers are removed. The app will back up all parameters, apply only the reviewed PID reductions, verify read-back, and roll back on failure. Continue?"):
            return
        baseline = self.output_dir / "aircraft-baseline.json"
        if not baseline.exists():
            messagebox.showerror("Flight Safety Monitor", "Capture the full controller baseline before applying a proposal.")
            return
        self._set_status("Applying reviewed proposal with full-baseline, backup, and verification checks…", "busy")
        def job():
            return guard.apply_proposal(Path(self.current_paths["proposal"]), self.port_var.get().strip(), int(self.baud_var.get()), token, self.output_dir, baseline)
        self._run(job, lambda path: self._set_status(f"Proposal applied and verified; audit saved as {Path(path).name}", "good"))

    def capture_baseline(self):
        self._set_status("Reading every controller parameter for the aircraft baseline…", "busy")
        def job():
            return guard.capture_baseline(self.port_var.get().strip(), int(self.baud_var.get()), self.output_dir)
        def done(path):
            record = json.loads(Path(path).read_text(encoding="utf-8"))
            snapshot = guard.summarize_pid_filter_parameters(record.get("parameters", {}))
            display = {
                "source": str(path),
                "captured_local": record.get("created_local"),
                "parameter_count": record.get("parameter_count"),
                "purpose": "Read-only current PID/filter snapshot. Local AI does not continuously tune or control these values.",
                "pid_filter_snapshot": snapshot,
            }
            self._set_text(self.proposal_text, json.dumps(display, indent=2))
            self.notebook.select(self.proposal_tab)
            self._set_status(f"Read-only PID/filter snapshot saved: {Path(path).name}", "good")
        self._run(job, done)

    def open_reports(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self.output_dir)


if __name__ == "__main__":
    app = FlightSafetyApp()
    if "--flight-live" in sys.argv:
        app.bench_mode_var.set(False)
        app.after(1000, app.toggle_monitor)
    app.mainloop()
