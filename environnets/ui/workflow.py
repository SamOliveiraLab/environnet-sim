"""DESIGN -> VALIDATE -> SIMULATE -> DEPLOY.

The bar across the top of the canvas. Each stage gates the next: you cannot
simulate a recipe that failed validation, and you cannot deploy one you have
not simulated. That gating is the safety boundary between the model layer and
the hardware, made visible.
"""

import json
import os
import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
    QFileDialog, QDialog, QTextEdit, QDialogButtonBox, QMessageBox,
)

from environnets.core.recipe import Recipe, validate
from environnets.core.program import compile_program, run_program, schedule_slip
from environnets.core.devices import (
    SelectorAdapter, RobotAdapter, SimSelectorDriver, SimRobotDriver, Ack,
)
from environnets.core.events import write_results
from environnets.core.unit_types import plate_wells
from environnets.core.preflight import build_report, build_package, expected_log
from environnets.ui.theme import (
    ACCENT, GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BG_PANEL, BORDER, BORDER_HOVER,
)

STAGES = ["DESIGN", "VALIDATE", "SIMULATE", "DEPLOY"]


class _SimReactor:
    """Stands in for a reactor while nothing is bound to hardware."""

    kind = "simulated"

    def __init__(self, name):
        self.name = name

    def connect(self):
        return Ack(True, "simulated")

    def set_dilution_rate(self, per_h, interval_min=15.0):
        return Ack(True, f"simulated D = {per_h:.3f}/h")

    def stop(self):
        return Ack(True, "stopped")


class LogDialog(QDialog):
    """Shows a run's audit trail."""

    def __init__(self, title, body, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 560)
        lay = QVBoxLayout(self)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(body)
        view.setStyleSheet(
            f"background:{BG_CARD};color:{TEXT_SECONDARY};border:1px solid {BORDER};"
            f"font-family:'SF Mono',Menlo,monospace;font-size:11px"
        )
        lay.addWidget(view)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)


class WorkflowBar(QFrame):
    """Stage buttons plus the status line underneath them."""

    stage_changed = pyqtSignal(str)
    show_report = pyqtSignal()

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.recipe: Recipe | None = None
        self.validation = None
        self.last_run = None
        self.last_steps = []
        self.last_port_map = {}
        self.report = None

        self.setStyleSheet(
            f"background:{BG_PANEL};border-bottom:1px solid {BORDER}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)

        self._buttons = {}
        for i, stage in enumerate(STAGES):
            if i:
                arrow = QLabel("→")
                arrow.setStyleSheet(f"color:{TEXT_MUTED};font-size:13px")
                row.addWidget(arrow)
            btn = QPushButton(stage)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, s=stage: self._run_stage(s))
            self._buttons[stage] = btn
            row.addWidget(btn)

        row.addSpacing(16)
        self.import_btn = QPushButton("Import model proposal")
        self.import_btn.setFixedHeight(30)
        self.import_btn.clicked.connect(self._import_proposal)
        row.addWidget(self.import_btn)

        self.report_btn = QPushButton("Simulation report")
        self.report_btn.setFixedHeight(30)
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self.show_report.emit)
        row.addWidget(self.report_btn)

        self.log_btn = QPushButton("View log")
        self.log_btn.setFixedHeight(30)
        self.log_btn.setEnabled(False)
        self.log_btn.clicked.connect(self._show_log)
        row.addWidget(self.log_btn)

        row.addStretch()
        outer.addLayout(row)

        self.status = QLabel("Draw a network, then run VALIDATE.")
        self.status.setStyleSheet(f"font-size:11px;color:{TEXT_MUTED}")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        self._stage_state = {s: "idle" for s in STAGES}
        self._stage_state["DESIGN"] = "ok"
        self._restyle()

    # -- styling -----------------------------------------------------------

    def _restyle(self):
        for stage, btn in self._buttons.items():
            state = self._stage_state[stage]
            colour = {"ok": GREEN, "fail": RED, "busy": ACCENT}.get(state, None)
            border = colour or BORDER
            text = colour or TEXT_SECONDARY
            btn.setStyleSheet(
                f"QPushButton{{background:{BG_CARD};color:{text};"
                f"border:1px solid {border};border-radius:6px;padding:4px 14px;"
                f"font-size:11px;font-weight:600;letter-spacing:0.6px}}"
                f"QPushButton:hover{{border-color:{BORDER_HOVER};color:{TEXT_PRIMARY}}}"
                f"QPushButton:disabled{{color:{TEXT_MUTED};border-color:{BORDER}}}"
            )

    def _set(self, stage, state, message, error=False):
        self._stage_state[stage] = state
        self._restyle()
        self.status.setText(message)
        self.status.setStyleSheet(
            f"font-size:11px;color:{RED if error else TEXT_MUTED}")

    # -- topology read off the canvas --------------------------------------

    def _network(self):
        return getattr(self.canvas, "network", None)

    def _topology(self, net):
        """Router ports per reactor, and the ordered pool of empty wells."""
        by_uid = {u.uid: u for u in net.units}

        def name(u):
            return u.label or u.uid

        port_map, well_map = {}, {}
        routers = [u for u in net.units if u.category == "routing"]
        if routers:
            router = routers[0]
            for c in net.connections:
                if c.target_uid == router.uid and c.target_port is not None:
                    src = by_uid.get(c.source_uid)
                    if src is not None and src.category == "reactor":
                        port_map[name(src)] = c.target_port

        plates = [u for u in net.units if u.category == "plate"]
        wells = []
        for p in plates:
            wells.extend(plate_wells(p.category, p.type_id))

        return port_map, wells

    def _ensure_recipe(self, net):
        if self.recipe is None:
            self.recipe = Recipe.from_network(net, run_id=f"ENV-{net.name[:12]}")
            if not self.recipe.cadence_min:
                self.recipe.cadence_min = [20.0] * max(1, len(self.recipe.nodes))
            if not any(self.recipe.d_per_h):
                self.recipe.d_per_h = [0.2] * len(self.recipe.nodes)
            self.recipe.run_hours = 1.0
        return self.recipe

    # -- stages ------------------------------------------------------------

    def _run_stage(self, stage):
        net = self._network()
        if net is None:
            self._set(stage, "fail", "No network selected.", error=True)
            return
        if stage == "DESIGN":
            self.recipe = None
            self.validation = None
            self.last_run = None
            for s in STAGES[1:]:
                self._stage_state[s] = "idle"
            self._set("DESIGN", "ok", "Design mode. Edit the canvas freely.")
        elif stage == "VALIDATE":
            self._validate(net)
        elif stage == "SIMULATE":
            self._simulate(net)
        elif stage == "DEPLOY":
            self._deploy(net)
        self.stage_changed.emit(stage)

    def _validate(self, net):
        recipe = self._ensure_recipe(net)
        self.validation = validate(recipe, net)
        n_err = len(self.validation.errors)
        n_warn = len(self.validation.warnings)
        if self.validation.ok:
            msg = f"Validation passed" + (f" with {n_warn} warning(s)." if n_warn else ".")
            self._set("VALIDATE", "ok", msg)
        else:
            first = self.validation.errors[0]
            self._set("VALIDATE", "fail",
                      f"Validation failed ({n_err}): {first}", error=True)
            self._stage_state["SIMULATE"] = "idle"
            self._stage_state["DEPLOY"] = "idle"
            self._restyle()

    def _simulate(self, net):
        if self.validation is None or not self.validation.ok:
            self._set("SIMULATE", "fail",
                      "Run VALIDATE first - a rejected recipe cannot be simulated.",
                      error=True)
            return
        recipe = self.recipe
        port_map, wells = self._topology(net)
        if not port_map:
            self._set("SIMULATE", "fail",
                      "No reactor is connected to a router port, so nothing "
                      "can be sampled.", error=True)
            return

        steps = compile_program(recipe, port_map=port_map, wells=wells,
                                duration_min=recipe.run_hours * 60)
        reactors = {n: _SimReactor(n) for n in port_map}
        run = run_program(
            steps, recipe, reactors=reactors,
            selector=SelectorAdapter(driver=SimSelectorDriver()),
            robot=RobotAdapter(driver=SimRobotDriver(), plate_wells=wells),
            mode="simulated",
        )
        self.last_run = run
        self.last_steps = steps
        self.last_port_map = port_map
        self.log_btn.setEnabled(True)

        # The simulator's real output: a pre-deployment report.
        self.report = build_report(
            recipe, net, steps, run, port_map, wells,
            validation=self.validation)
        self.report_btn.setEnabled(True)

        ok = sum(1 for s in run.samples if s.status == "complete")
        slip = schedule_slip(steps)
        msg = (f"Simulated {ok}/{len(run.samples)} samples over "
               f"{recipe.run_hours:g} h. {self.report.verdict}"
               f" — {self.report.failed} error(s), {self.report.warned} warning(s).")
        if slip:
            worst = max(w for _, w in slip)
            msg += (f" {len(slip)} draw(s) delayed up to {worst:.0f} s.")
        self._set("SIMULATE", "fail" if (run.aborted or not self.report.passed)
                  else "ok", msg, error=run.aborted or not self.report.passed)

        self.show_report.emit()

    def _deploy(self, net):
        if self.report is None:
            self._set("DEPLOY", "fail",
                      "Simulate before deploying.", error=True)
            return
        if not self.report.passed:
            self._set("DEPLOY", "fail",
                      f"{self.report.verdict}: {self.report.failed} check(s) "
                      f"failed. Fix them before deploying.", error=True)
            return
        return self.export_package(net, deploy=True)

    def export_package(self, net=None, deploy=False):
        """Write the validated experiment package."""
        net = net or self._network()
        if net is None or self.report is None:
            return
        recipe = self.recipe
        default = os.path.expanduser(
            f"~/{recipe.run_id or 'experiment'}_experiment.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export experiment package", default, "JSON (*.json)")
        if not path:
            self._set("DEPLOY", "idle", "Export cancelled.")
            return

        package = build_package(recipe, net, self.last_steps, self.report,
                                self.last_port_map)
        with open(path, "w") as fh:
            json.dump(package, fh, indent=2)

        base = os.path.dirname(path)
        results_path = os.path.join(
            base, f"results_{recipe.run_id or 'run'}.json")
        write_results(results_path, run_id=recipe.run_id,
                      recipe=recipe.to_proposal(), log=self.last_run.log,
                      samples=self.last_run.samples, mode="simulated")

        log_path = os.path.join(base, f"expected_{recipe.run_id or 'run'}.log")
        with open(log_path, "w") as fh:
            fh.write(expected_log(self.last_steps, recipe.run_id))

        self._set("DEPLOY", "ok",
                  f"{'Deployed' if deploy else 'Exported'}: "
                  f"{os.path.basename(path)}, "
                  f"{os.path.basename(results_path)}, "
                  f"{os.path.basename(log_path)}.")

    # -- proposal import ---------------------------------------------------

    def _import_proposal(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import model proposal", os.path.expanduser("~"),
            "JSON (*.json)")
        if not path:
            return
        try:
            with open(path) as fh:
                data = json.load(fh)
            self.recipe = Recipe.from_proposal(data)
        except Exception as exc:
            QMessageBox.warning(self, "Could not read proposal", str(exc))
            return
        self.validation = None
        self.last_run = None
        for s in STAGES[1:]:
            self._stage_state[s] = "idle"
        self._set("DESIGN", "ok",
                  f"Loaded {os.path.basename(path)}: {self.recipe.model or 'recipe'} "
                  f"iteration {self.recipe.iteration}, nodes "
                  f"{', '.join(self.recipe.nodes)}. Not deployed - run VALIDATE.")

    def _show_log(self):
        if self.last_run is None:
            return
        body = self.last_run.log.text()
        counts = self.last_run.log.counts()
        header = (f"Run {self.recipe.run_id}  ({self.last_run.mode})\n"
                  f"{counts['commands']} commands, {counts['acks']} acks, "
                  f"{counts['nacks']} nacks, "
                  f"{counts['unacknowledged']} unacknowledged\n"
                  + "-" * 72 + "\n")
        LogDialog("Execution log", header + body, self).exec()
