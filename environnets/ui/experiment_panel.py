"""Experiment view: canvas + inline controls."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QDoubleSpinBox, QSpinBox, QComboBox, QScrollArea,
    QSizePolicy,
)
from environnets.core.experiments import Experiment, save_experiment
from environnets.ui.canvas import NetworkCanvas
from environnets.ui.theme import (
    ACCENT, ACCENT_DIM, GREEN, RED, AMBER, BG_CARD, BG_PANEL, BG_HOVER,
    BORDER, BORDER_HOVER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
)


class ExperimentPanel(QWidget):
    def __init__(self, api, store, experiment: Experiment, network):
        super().__init__()
        self.api = api
        self.store = store
        self.experiment = experiment

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

        self._status_label = QLabel("Draft")
        self._status_label.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:11px;padding:4px 10px;"
            f"border:1px solid {BORDER};border-radius:4px"
        )
        hl.addWidget(self._status_label)

        self._start_btn = QPushButton("Start experiment")
        self._start_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT_DIM};color:{TEXT_PRIMARY};border:1px solid {ACCENT_DIM};"
            f"border-radius:6px;padding:8px 18px;font-weight:500;font-size:12px}}"
            f"QPushButton:hover{{background:{ACCENT};color:#fff}}"
        )
        self._start_btn.clicked.connect(self._toggle_experiment)
        hl.addWidget(self._start_btn)

        root.addWidget(header)

        # Parameters strip — scroll horizontally on narrow screens (small MacBooks)
        params_scroll = QScrollArea()
        params_scroll.setFrameShape(QFrame.Shape.NoFrame)
        params_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        params_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        params_scroll.setWidgetResizable(False)
        params_scroll.setFixedHeight(62)
        params_scroll.setStyleSheet(f"QScrollArea{{background:{BG_CARD};border-bottom:1px solid {BORDER}}}")

        params_inner = QWidget()
        params_inner.setStyleSheet(f"background:{BG_CARD}")
        pl = QHBoxLayout(params_inner)
        pl.setContentsMargins(20, 8, 20, 8)
        pl.setSpacing(12)

        self._mode = QComboBox()
        self._mode.addItems(["Manual", "Chemostat", "Turbidostat"])
        self._mode.setMinimumWidth(108)

        self._rpm = QSpinBox()
        self._rpm.setRange(0, 1500)
        self._rpm.setValue(int(experiment.parameters.get("rpm", 400)))
        self._rpm.setSuffix(" rpm")
        self._rpm.setMinimumWidth(88)

        self._temp = QDoubleSpinBox()
        self._temp.setRange(15.0, 50.0)
        self._temp.setValue(float(experiment.parameters.get("temp", 30.0)))
        self._temp.setSuffix(" C")
        self._temp.setMinimumWidth(78)

        self._vol = QDoubleSpinBox()
        self._vol.setRange(0.01, 10.0)
        self._vol.setValue(float(experiment.parameters.get("vol", 0.5)))
        self._vol.setSuffix(" mL")
        self._vol.setMinimumWidth(78)

        self._interval = QSpinBox()
        self._interval.setRange(1, 1440)
        self._interval.setValue(int(experiment.parameters.get("interval", 15)))
        self._interval.setSuffix(" min")
        self._interval.setMinimumWidth(88)

        for w, lbl in [(self._mode, "Mode"), (self._rpm, "Stir"),
                       (self._temp, "Temp"), (self._vol, "Dose"), (self._interval, "Every")]:
            col = QVBoxLayout()
            col.setSpacing(1)
            l = QLabel(lbl)
            l.setStyleSheet(f"font-size:10px;color:{TEXT_SECONDARY}")
            col.addWidget(l)
            col.addWidget(w)
            wrap = QWidget()
            wrap.setLayout(col)
            pl.addWidget(wrap)

        pl.addStretch()
        params_inner.setMinimumWidth(720)
        params_scroll.setWidget(params_inner)
        root.addWidget(params_scroll)

        # Canvas
        self.canvas = NetworkCanvas(api, store)
        self.canvas.current_experiment_name = experiment.name
        if network:
            self.canvas.load_network(network)
        root.addWidget(self.canvas, 1)

        self._od_timer = QTimer(self)
        self._od_timer.timeout.connect(self._poll_telemetry)
        self._od_timer.start(10000)

    def _poll_telemetry(self):
        if not self.canvas.network:
            return
        try:
            od = self.api.get_od_readings(self.experiment.name)
            if not od or not od.get("series"):
                return
            latest = {}
            for idx, name in enumerate(od["series"]):
                unit_name = name.rsplit("-", 1)[0]
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
                "Link at least one bioreactor to hardware before starting.")
            return

        exp_name = self.experiment.name
        for r in reactors:
            self.api.start_stirring(r.pioreactor_unit, exp_name, self._rpm.value())
            self.api.start_od_reading(r.pioreactor_unit, exp_name)
            self.api.start_growth_rate(r.pioreactor_unit, exp_name)
            self.api.start_temperature(r.pioreactor_unit, exp_name, self._temp.value())
            if self._mode.currentText() == "Chemostat":
                self.api.start_chemostat(r.pioreactor_unit, exp_name,
                                         self._vol.value(), self._interval.value())
            r.status = "running"

        # Mark linked pumps as running so cartoons animate
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
        if self.experiment.status == "running":
            self._status_label.setText("Running")
            self._status_label.setStyleSheet(
                f"color:{GREEN};font-size:11px;padding:4px 10px;"
                f"border:1px solid {BORDER};border-radius:4px"
            )
            self._start_btn.setText("Stop experiment")
            self._start_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{RED};border:1px solid {BORDER};"
                f"border-radius:6px;padding:8px 18px;font-weight:500;font-size:12px}}"
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
                f"border-radius:6px;padding:8px 18px;font-weight:500;font-size:12px}}"
                f"QPushButton:hover{{background:{ACCENT};color:#fff}}"
            )
