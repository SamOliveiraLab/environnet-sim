"""Experiment view: canvas + controls + simulation + live plots."""
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QDoubleSpinBox, QSpinBox, QComboBox, QSplitter,
    QSizePolicy, QCheckBox, QFileDialog,
)

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from environnets.core.experiments import Experiment, save_experiment
from environnets.core.simulation import SimEngine, SimConfig
from environnets.ui.canvas import NetworkCanvas
from environnets.ui.theme import (
    ACCENT, ACCENT_DIM, GREEN, RED, AMBER, BG_CARD, BG_PANEL, BG_DARK,
    BG_INPUT, BG_HOVER, BORDER, BORDER_HOVER, TEXT_PRIMARY, TEXT_SECONDARY,
    TEXT_MUTED,
)


if HAS_PYQTGRAPH:
    pg.setConfigOption("background", BG_DARK)
    pg.setConfigOption("foreground", TEXT_SECONDARY)


class ExperimentPanel(QWidget):
    def __init__(self, api, store, experiment: Experiment, network):
        super().__init__()
        self.api = api
        self.store = store
        self.experiment = experiment
        self._sim: SimEngine | None = None
        self._recording_frames: list = []
        self._recording = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QFrame()
        header.setStyleSheet(f"background:{BG_PANEL};border-bottom:1px solid {BORDER}")
        header.setMinimumHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 10, 20, 10)

        name = QLabel(experiment.name)
        name.setStyleSheet(f"font-size:15px;font-weight:500;color:{TEXT_PRIMARY}")
        name.setWordWrap(True)
        name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        desc = QLabel(experiment.description or "No description")
        desc.setStyleSheet(f"font-size:11px;color:{TEXT_MUTED}")
        desc.setWordWrap(True)
        desc.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        name_col.addWidget(name)
        name_col.addWidget(desc)
        name_wrap = QWidget()
        name_wrap.setLayout(name_col)
        name_wrap.setMinimumWidth(120)
        hl.addWidget(name_wrap, 1)

        self._time_label = QLabel("")
        self._time_label.setStyleSheet(f"font-size:11px;color:{TEXT_MUTED}")
        hl.addWidget(self._time_label)

        self._status_label = QLabel("Draft")
        self._status_label.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:11px;padding:4px 10px;"
            f"border:1px solid {BORDER};border-radius:4px"
        )
        hl.addWidget(self._status_label)

        self._sim_btn = QPushButton("Simulate")
        self._sim_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT_DIM};color:{TEXT_PRIMARY};border:1px solid {ACCENT_DIM};"
            f"border-radius:6px;padding:8px 14px;font-weight:500;font-size:12px}}"
            f"QPushButton:hover{{background:{ACCENT};color:#fff}}"
        )
        self._sim_btn.clicked.connect(self._toggle_sim)
        hl.addWidget(self._sim_btn)

        self._start_btn = QPushButton("Start experiment")
        self._start_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT_DIM};color:{TEXT_PRIMARY};border:1px solid {ACCENT_DIM};"
            f"border-radius:6px;padding:8px 14px;font-weight:500;font-size:12px}}"
            f"QPushButton:hover{{background:{ACCENT};color:#fff}}"
        )
        self._start_btn.clicked.connect(self._toggle_experiment)
        hl.addWidget(self._start_btn)

        self._gif_btn = QPushButton("REC")
        self._gif_btn.setFixedSize(40, 28)
        self._gif_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TEXT_MUTED};border:1px solid {BORDER};"
            f"border-radius:6px;font-size:10px;font-weight:600}}"
            f"QPushButton:hover{{color:{RED};border-color:{RED}}}"
        )
        self._gif_btn.clicked.connect(self._toggle_recording)
        hl.addWidget(self._gif_btn)

        root.addWidget(header)

        # Parameters strip
        params_bar = QFrame()
        params_bar.setFixedHeight(56)
        params_bar.setStyleSheet(
            f"QFrame{{background:{BG_CARD};border-bottom:1px solid {BORDER}}}"
            f"QLabel{{background:transparent;border:none}}"
        )
        pl = QHBoxLayout(params_bar)
        pl.setContentsMargins(20, 6, 20, 6)
        pl.setSpacing(18)

        self._mode = QComboBox()
        self._mode.addItems(["Manual", "Chemostat", "Turbidostat"])
        self._mode.setFixedWidth(120)
        self._mode.setFixedHeight(28)

        self._rpm = QSpinBox()
        self._rpm.setRange(0, 1500)
        self._rpm.setValue(int(experiment.parameters.get("rpm", 400)))
        self._rpm.setSuffix(" rpm")
        self._rpm.setFixedWidth(100)
        self._rpm.setFixedHeight(28)

        self._temp = QDoubleSpinBox()
        self._temp.setRange(15.0, 50.0)
        self._temp.setValue(float(experiment.parameters.get("temp", 30.0)))
        self._temp.setSuffix(" °C")
        self._temp.setFixedWidth(90)
        self._temp.setFixedHeight(28)

        self._vol = QDoubleSpinBox()
        self._vol.setRange(0.01, 10.0)
        self._vol.setValue(float(experiment.parameters.get("vol", 0.5)))
        self._vol.setSuffix(" mL")
        self._vol.setFixedWidth(90)
        self._vol.setFixedHeight(28)

        self._interval = QSpinBox()
        self._interval.setRange(1, 1440)
        self._interval.setValue(int(experiment.parameters.get("interval", 15)))
        self._interval.setSuffix(" min")
        self._interval.setFixedWidth(90)
        self._interval.setFixedHeight(28)

        self._speed = QSpinBox()
        self._speed.setRange(1, 500)
        self._speed.setValue(60)
        self._speed.setSuffix("x")
        self._speed.setFixedWidth(80)
        self._speed.setFixedHeight(28)
        self._speed.setToolTip("Simulation speed multiplier")

        for w, lbl in [(self._mode, "Mode"), (self._rpm, "Stir"),
                       (self._temp, "Temp"), (self._vol, "Dose"),
                       (self._interval, "Every"), (self._speed, "Speed")]:
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setContentsMargins(0, 0, 0, 0)
            l = QLabel(lbl)
            l.setStyleSheet(f"font-size:10px;color:{TEXT_SECONDARY};padding:0")
            col.addWidget(l)
            col.addWidget(w)
            pl.addLayout(col)

        pl.addStretch()
        root.addWidget(params_bar)

        # Canvas + Plots splitter
        self._main_splitter = QSplitter(Qt.Orientation.Vertical)

        self.canvas = NetworkCanvas(api, store)
        self.canvas.current_experiment_name = experiment.name
        if network:
            self.canvas.load_network(network)
        self._main_splitter.addWidget(self.canvas)

        # Plots panel
        self._plots_panel = QFrame()
        self._plots_panel.setStyleSheet(f"background:{BG_DARK};border-top:1px solid {BORDER}")
        plots_vl = QVBoxLayout(self._plots_panel)
        plots_vl.setContentsMargins(8, 4, 8, 4)
        plots_vl.setSpacing(4)

        if HAS_PYQTGRAPH:
            plots_row = QHBoxLayout()
            self._od_plot = pg.PlotWidget(title="OD")
            self._od_plot.showGrid(x=True, y=True, alpha=0.15)
            self._od_plot.setMinimumHeight(100)
            self._od_curve = self._od_plot.plot(pen=pg.mkPen("#7a9ec7", width=2))
            plots_row.addWidget(self._od_plot)

            self._temp_plot = pg.PlotWidget(title="Temperature (°C)")
            self._temp_plot.showGrid(x=True, y=True, alpha=0.15)
            self._temp_plot.setMinimumHeight(100)
            self._temp_curve = self._temp_plot.plot(pen=pg.mkPen("#c48a5a", width=2))
            plots_row.addWidget(self._temp_plot)

            self._gr_plot = pg.PlotWidget(title="Growth rate (1/h)")
            self._gr_plot.showGrid(x=True, y=True, alpha=0.15)
            self._gr_plot.setMinimumHeight(100)
            self._gr_curve = self._gr_plot.plot(pen=pg.mkPen("#8a7ab5", width=2))
            plots_row.addWidget(self._gr_plot)

            plots_vl.addLayout(plots_row)
        else:
            no_pg = QLabel("Install pyqtgraph for live plots: pip install pyqtgraph")
            no_pg.setStyleSheet(f"color:{TEXT_MUTED};font-size:11px;padding:12px")
            no_pg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            plots_vl.addWidget(no_pg)

        self._main_splitter.addWidget(self._plots_panel)
        self._main_splitter.setSizes([500, 180])
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 1)
        root.addWidget(self._main_splitter, 1)

        # Timers
        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._sim_tick)

        self._od_timer = QTimer(self)
        self._od_timer.timeout.connect(self._poll_telemetry)
        self._od_timer.start(10000)

        self._update_status_ui()

    # -- simulation --------------------------------------------------------

    def _toggle_sim(self):
        if self._sim and self._sim.running:
            self._stop_sim()
        else:
            self._start_sim()

    def _start_sim(self):
        if not self.canvas.network:
            return
        config = SimConfig.ecoli()
        config.time_scale = self._speed.value()
        self._sim = SimEngine(config)
        self._sim.start(
            rpm=self._rpm.value(),
            target_temp=self._temp.value(),
            mode=self._mode.currentText().lower(),
            dose_ml=self._vol.value(),
            dose_interval_min=self._interval.value(),
        )
        for u in self.canvas.network.units:
            if u.category in ("reactor", "pump"):
                u.status = "running"
        self.experiment.status = "running"
        self._sim_timer.start(33)
        self._update_status_ui()
        self._sim_btn.setText("Stop sim")

    def _stop_sim(self):
        if self._sim:
            self._sim.stop()
        self._sim_timer.stop()
        if self.canvas.network:
            for u in self.canvas.network.units:
                if u.category in ("reactor", "pump"):
                    u.status = "idle"
                u._sim_cells = None
                u._sim_reading = None
        self.experiment.status = "stopped"
        self._update_status_ui()
        self._sim_btn.setText("Simulate")

    def _sim_tick(self):
        if not self._sim or not self._sim.running:
            return
        self._sim.config.time_scale = self._speed.value()
        self._sim.step(0.033)
        s = self._sim.state

        if self.canvas.network:
            for u in self.canvas.network.units:
                if u.category == "reactor":
                    u.last_od = s.od
                    u.last_temp = s.temperature
                    u.last_gr = s.growth_rate
                    u._sim_cells = s.cells
                elif u.category == "sensor":
                    if u.type_id == "od":
                        u._sim_reading = s.od
                    elif u.type_id == "temperature":
                        u._sim_reading = s.temperature
                    elif u.type_id == "co2":
                        u._sim_reading = s.growth_rate * 10
                    elif u.type_id == "ph":
                        u._sim_reading = 7.0 - s.od * 0.3
                    elif u.type_id == "dissolved_o2":
                        u._sim_reading = max(0, 8.0 - s.od * 2)
                elif u.category == "reservoir":
                    if u.type_id == "media_bottle":
                        u._sim_reading = s.media_remaining_ml
                    elif u.type_id == "waste_bottle":
                        u._sim_reading = s.waste_collected_ml

        hours = self._sim.elapsed_hours
        self._time_label.setText(f"{hours:.1f}h ({hours/24:.1f}d)")

        if HAS_PYQTGRAPH and len(self._sim.history) > 1:
            ts, ods = self._sim.get_series("od")
            self._od_curve.setData(ts, ods)
            _, temps = self._sim.get_series("temperature")
            self._temp_curve.setData(ts, temps)
            _, grs = self._sim.get_series("growth_rate")
            self._gr_curve.setData(ts, grs)

        if self._recording:
            self._capture_frame()

    # -- recording (GIF) ---------------------------------------------------

    def _toggle_recording(self):
        if self._recording:
            self._stop_recording()
        else:
            self._recording = True
            self._recording_frames = []
            self._gif_btn.setText("STOP")
            self._gif_btn.setStyleSheet(
                f"QPushButton{{background:{RED};color:#fff;border:1px solid {RED};"
                f"border-radius:6px;font-size:10px;font-weight:600}}"
            )

    def _capture_frame(self):
        from PyQt6.QtGui import QPixmap
        cw = self.canvas._cw
        pm = QPixmap(cw.size())
        cw.render(pm)
        self._recording_frames.append(pm.toImage())
        if len(self._recording_frames) > 600:
            self._stop_recording()

    def _stop_recording(self):
        self._recording = False
        self._gif_btn.setText("REC")
        self._gif_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TEXT_MUTED};border:1px solid {BORDER};"
            f"border-radius:6px;font-size:10px;font-weight:600}}"
            f"QPushButton:hover{{color:{RED};border-color:{RED}}}"
        )
        if not self._recording_frames:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GIF", f"simulation_{int(time.time())}.gif", "GIF (*.gif)")
        if path:
            self._save_gif(path)
        self._recording_frames = []

    def _save_gif(self, path: str):
        try:
            from PIL import Image
            pil_frames = []
            for qimg in self._recording_frames:
                qimg = qimg.convertToFormat(qimg.Format.Format_RGBA8888)
                ptr = qimg.bits()
                ptr.setsize(qimg.sizeInBytes())
                img = Image.frombytes("RGBA", (qimg.width(), qimg.height()), bytes(ptr))
                img = img.convert("RGB").resize(
                    (qimg.width() // 2, qimg.height() // 2), Image.LANCZOS)
                pil_frames.append(img)
            if pil_frames:
                pil_frames[0].save(
                    path, save_all=True, append_images=pil_frames[1:],
                    duration=33, loop=0, optimize=True)
        except ImportError:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing dependency",
                "Install Pillow to save GIFs: pip install Pillow")

    # -- API-based experiment ----------------------------------------------

    def _poll_telemetry(self):
        if not self.canvas.network or self._sim:
            return
        try:
            od = self.api.get_od_readings(self.experiment.name)
            if not od or not od.get("series"):
                return
            latest = {}
            for idx, name_str in enumerate(od["series"]):
                unit_name = name_str.rsplit("-", 1)[0]
                data = od["data"][idx] if idx < len(od["data"]) else []
                if data:
                    latest[unit_name] = data[-1].get("y", 0.0)
            for u in self.canvas.network.units:
                if u.pioreactor_unit and u.pioreactor_unit in latest:
                    u.last_od = float(latest[u.pioreactor_unit])
        except Exception:
            pass

    def _toggle_experiment(self):
        if self.experiment.status != "running":
            self._start_experiment()
        else:
            self._stop_experiment()

    def _start_experiment(self):
        if not self.canvas.network:
            return
        reactors = [u for u in self.canvas.network.units
                    if u.category == "reactor" and u.pioreactor_unit]
        if not reactors:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No hardware",
                "Link at least one bioreactor to hardware before starting.\n"
                "Use 'Simulate' to run without hardware.")
            return

        exp_name = self.experiment.name
        for r in reactors:
            self.api.start_stirring(r.pioreactor_unit, exp_name, self._rpm.value())
            self.api.start_od_reading(r.pioreactor_unit, exp_name)
            self.api.start_growth_rate(r.pioreactor_unit, exp_name)
            self.api.start_temperature(r.pioreactor_unit, exp_name, self._temp.value())
            mode = self._mode.currentText()
            if mode == "Chemostat":
                self.api.start_chemostat(r.pioreactor_unit, exp_name,
                                         self._vol.value(), self._interval.value())
            elif mode == "Turbidostat":
                self.api.start_turbidostat(r.pioreactor_unit, exp_name,
                                            1.0, self._vol.value(), self._interval.value())
            r.status = "running"

        for u in self.canvas.network.units:
            if u.category == "pump" and u.pioreactor_unit:
                u.status = "running"

        self.experiment.status = "running"
        self.experiment.parameters = {
            "rpm": self._rpm.value(), "temp": self._temp.value(),
            "vol": self._vol.value(), "interval": self._interval.value(),
            "mode": self._mode.currentText(),
        }
        save_experiment(self.store, self.experiment)
        self.store.save_network(self.canvas.network)
        self._update_status_ui()

    def _stop_experiment(self):
        if not self.canvas.network:
            return
        exp_name = self.experiment.name
        for u in self.canvas.network.units:
            if u.pioreactor_unit:
                for job in ["dosing_automation", "growth_rate_calculating",
                            "od_reading", "temperature_automation", "stirring"]:
                    self.api.stop_job(u.pioreactor_unit, job, exp_name)
                u.status = "idle"
        self.experiment.status = "stopped"
        save_experiment(self.store, self.experiment)
        self.store.save_network(self.canvas.network)
        self._update_status_ui()

    def _update_status_ui(self):
        running = self.experiment.status == "running"
        if running:
            self._status_label.setText("Running")
            self._status_label.setStyleSheet(
                f"color:{GREEN};font-size:11px;padding:4px 10px;"
                f"border:1px solid {BORDER};border-radius:4px"
            )
            self._start_btn.setText("Stop experiment")
            self._start_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{RED};border:1px solid {BORDER};"
                f"border-radius:6px;padding:8px 14px;font-weight:500;font-size:12px}}"
                f"QPushButton:hover{{background:#2a1a1a;border-color:{RED}}}"
            )
        else:
            self._status_label.setText(self.experiment.status.capitalize())
            self._status_label.setStyleSheet(
                f"color:{TEXT_MUTED};font-size:11px;padding:4px 10px;"
                f"border:1px solid {BORDER};border-radius:4px"
            )
            self._start_btn.setText("Start experiment")
            self._start_btn.setStyleSheet(
                f"QPushButton{{background:{ACCENT_DIM};color:{TEXT_PRIMARY};border:1px solid {ACCENT_DIM};"
                f"border-radius:6px;padding:8px 14px;font-weight:500;font-size:12px}}"
                f"QPushButton:hover{{background:{ACCENT};color:#fff}}"
            )
