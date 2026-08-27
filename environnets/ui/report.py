"""The simulator's final screen: a validated experiment package.

Reads as a preflight sheet, not a drawing. Status bar, plate preview with the
sample that will land in each well, routing table, hardware map, per-node
parameters, the checklist, and the expected log - then Export and Deploy.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QTabWidget, QSizePolicy,
)

from environnets.core.preflight import OK, WARN, FAIL, expected_log
from environnets.ui.theme import (
    ACCENT, ACCENT_DIM, GREEN, RED, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    BG_CARD, BG_PANEL, BG_DARK, BORDER, BORDER_HOVER,
)

AMBER = "#b89540"
MONO = "'SF Mono', Menlo, monospace"


def _state_colour(state):
    return {OK: GREEN, WARN: AMBER, FAIL: RED}.get(state, TEXT_MUTED)


class Card(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:8px}}")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(14, 12, 14, 12)
        self.v.setSpacing(8)
        if title:
            lab = QLabel(title.upper())
            lab.setStyleSheet(
                f"font-size:10px;font-weight:700;color:{TEXT_MUTED};"
                f"letter-spacing:1px;border:none")
            self.v.addWidget(lab)


class PlatePreview(QWidget):
    """Grid of wells; filled ones name the sample that will land there."""

    well_clicked = pyqtSignal(str)

    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.report = report
        lay = QGridLayout(self)
        lay.setSpacing(4)
        wells = report.well_map()

        for c in range(report.plate_cols):
            h = QLabel(str(c + 1))
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h.setStyleSheet(f"color:{TEXT_MUTED};font-size:10px;border:none")
            lay.addWidget(h, 0, c + 1)

        for r in range(report.plate_rows):
            rl = QLabel(chr(ord("A") + r))
            rl.setStyleSheet(f"color:{TEXT_MUTED};font-size:10px;border:none")
            lay.addWidget(rl, r + 1, 0)
            for c in range(report.plate_cols):
                name = f"{chr(ord('A') + r)}{c + 1}"
                s = wells.get(name)
                btn = QPushButton(s.source if s else "")
                btn.setFixedSize(58, 40)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                if s:
                    btn.setStyleSheet(
                        f"QPushButton{{background:rgba(110,175,210,55);"
                        f"border:1px solid {ACCENT};border-radius:6px;"
                        f"color:{TEXT_PRIMARY};font-size:11px;font-weight:600}}"
                        f"QPushButton:hover{{background:rgba(110,175,210,95)}}")
                    btn.setToolTip(
                        f"{s.sample_id}\nSource: {s.source}\n"
                        f"Router port: {s.port}\nVolume: {s.volume_uL:g} uL\n"
                        f"Scheduled: {int(s.at_s)//60:02d}:{int(s.at_s)%60:02d}")
                else:
                    btn.setStyleSheet(
                        f"QPushButton{{background:{BG_DARK};border:1px dashed "
                        f"{BORDER};border-radius:6px;color:{TEXT_MUTED};"
                        f"font-size:9px}}")
                    btn.setText("unused")
                btn.clicked.connect(lambda _, n=name: self.well_clicked.emit(n))
                lay.addWidget(btn, r + 1, c + 1)


def _table(headers, rows, colour_col=None):
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    t.setStyleSheet(
        f"QTableWidget{{background:transparent;border:none;gridline-color:{BORDER};"
        f"color:{TEXT_SECONDARY};font-size:11px}}"
        f"QHeaderView::section{{background:{BG_PANEL};color:{TEXT_MUTED};"
        f"border:none;border-bottom:1px solid {BORDER};padding:5px;"
        f"font-size:10px;font-weight:600}}")
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            if colour_col is not None and c == colour_col:
                col = {"Valid": GREEN, "Mapped": GREEN,
                       "Unused": TEXT_MUTED, "Unmapped": AMBER}.get(str(val))
                if col:
                    from PyQt6.QtGui import QColor
                    it.setForeground(QColor(col))
            t.setItem(r, c, it)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setFixedHeight(min(300, 30 + 26 * max(1, len(rows))))
    return t


class ReportView(QWidget):
    """The full pre-deployment report."""

    export_requested = pyqtSignal()
    deploy_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(self, report, steps, parent=None):
        super().__init__(parent)
        self.report = report
        self.steps = steps
        self.setStyleSheet(f"background:{BG_DARK}")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._status_bar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent}")
        body = QWidget()
        body.setStyleSheet("background:transparent")
        v = QVBoxLayout(body)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(14)

        # top row: plate + summary
        top = QHBoxLayout()
        top.setSpacing(14)

        plate_card = Card(f"Planned plate  ·  {report.plate_label or 'plate'}")
        self.plate = PlatePreview(report)
        plate_card.v.addWidget(self.plate)
        self.well_detail = QLabel("Click a well for its sample record.")
        self.well_detail.setStyleSheet(
            f"color:{TEXT_MUTED};font-size:11px;border:none;font-family:{MONO}")
        self.well_detail.setWordWrap(True)
        plate_card.v.addWidget(self.well_detail)
        self.plate.well_clicked.connect(self._show_well)
        top.addWidget(plate_card, 1)

        top.addWidget(self._summary_card(), 1)
        v.addLayout(top)

        # tabs: checklist / routing / hardware / parameters / sequence / log
        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {BORDER};border-radius:8px;"
            f"background:{BG_CARD}}}"
            f"QTabBar::tab{{background:transparent;color:{TEXT_MUTED};"
            f"padding:7px 14px;font-size:11px;border:none}}"
            f"QTabBar::tab:selected{{color:{TEXT_PRIMARY};"
            f"border-bottom:2px solid {ACCENT}}}")
        tabs.addTab(self._checklist_tab(), "Pre-deployment check")
        tabs.addTab(self._routing_tab(), "Routing")
        tabs.addTab(self._hardware_tab(), "Hardware")
        tabs.addTab(self._parameters_tab(), "Parameters")
        tabs.addTab(self._sequence_tab(), "Sequence")
        tabs.addTab(self._log_tab(), "Expected log")
        v.addWidget(tabs, 1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(self._action_bar())

    # -- pieces ------------------------------------------------------------

    def _status_bar(self):
        r = self.report
        bar = QFrame()
        ok = r.passed
        bar.setStyleSheet(
            f"background:{BG_PANEL};border-bottom:2px solid "
            f"{GREEN if ok else RED}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(26)

        def field(label, value, colour=TEXT_PRIMARY, big=False):
            w = QWidget()
            w.setStyleSheet("border:none;background:transparent")
            c = QVBoxLayout(w)
            c.setContentsMargins(0, 0, 0, 0)
            c.setSpacing(1)
            l1 = QLabel(label.upper())
            l1.setStyleSheet(
                f"font-size:9px;color:{TEXT_MUTED};letter-spacing:1px;border:none")
            l2 = QLabel(value)
            l2.setStyleSheet(
                f"font-size:{15 if big else 12}px;color:{colour};"
                f"font-weight:{700 if big else 500};border:none")
            c.addWidget(l1)
            c.addWidget(l2)
            return w

        h.addWidget(field("Experiment", r.run_id, TEXT_PRIMARY, big=True))
        h.addWidget(field("Mode", r.mode))
        h.addWidget(field("Status",
                          "VALIDATED" if ok else "REJECTED",
                          GREEN if ok else RED, big=True))
        h.addWidget(field("Hardware", self._hw_summary()))
        h.addWidget(field("Estimated duration", r.duration_hms))
        h.addWidget(field("Warnings", str(r.warned),
                          AMBER if r.warned else TEXT_SECONDARY))
        h.addWidget(field("Ready to deploy", "YES" if ok else "NO",
                          GREEN if ok else RED, big=True))
        h.addStretch()
        return bar

    def _hw_summary(self):
        n = {"reactor": 0, "routing": 0, "sampling": 0, "plate": 0}
        for b in self.report.bindings:
            k = b.kind.lower()
            if "selector" in k or "crossbar" in k or "valve" in k:
                n["routing"] += 1
            elif "arm" in k or "needle" in k:
                n["sampling"] += 1
            elif "plate" in k or "well" in k:
                n["plate"] += 1
            else:
                n["reactor"] += 1
        return (f"{n['reactor']} reactors · {n['routing']} router · "
                f"{n['sampling']} robot · {n['plate']} plate")

    def _summary_card(self):
        r = self.report
        card = Card("Simulation result")
        grid = QGridLayout()
        grid.setSpacing(6)
        rows = [
            ("Duration", r.duration_hms),
            ("Samples", str(r.counts.get("samples", 0))),
            ("Router actions", str(r.counts.get("router_actions", 0))),
            ("Robot moves", str(r.counts.get("robot_moves", 0))),
            ("Program steps", str(r.counts.get("steps", 0))),
            ("Warnings", str(r.warned)),
            ("Errors", str(r.failed)),
        ]
        for i, (k, val) in enumerate(rows):
            a = QLabel(k)
            a.setStyleSheet(f"color:{TEXT_MUTED};font-size:11px;border:none")
            b = QLabel(val)
            colour = RED if (k == "Errors" and r.failed) else (
                AMBER if (k == "Warnings" and r.warned) else TEXT_PRIMARY)
            b.setStyleSheet(
                f"color:{colour};font-size:12px;font-weight:600;border:none;"
                f"font-family:{MONO}")
            grid.addWidget(a, i, 0)
            grid.addWidget(b, i, 1, Qt.AlignmentFlag.AlignRight)
        card.v.addLayout(grid)

        verdict = QLabel(r.verdict)
        verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        verdict.setStyleSheet(
            f"color:{GREEN if r.passed else RED};font-size:14px;font-weight:700;"
            f"letter-spacing:1px;border:1px solid "
            f"{GREEN if r.passed else RED};border-radius:6px;padding:8px")
        card.v.addWidget(verdict)
        return card

    def _checklist_tab(self):
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet("border:none;background:transparent")
        inner = QWidget()
        inner.setStyleSheet("background:transparent")
        v = QVBoxLayout(inner)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(12)

        for g in self.report.groups:
            head = QLabel(g.name.upper())
            head.setStyleSheet(
                f"font-size:10px;font-weight:700;color:{TEXT_SECONDARY};"
                f"letter-spacing:1px")
            v.addWidget(head)
            for c in g.checks:
                row = QHBoxLayout()
                row.setSpacing(8)
                mark = QLabel({"pass": "✓", "warn": "!", "fail": "✕"}[c.state])
                mark.setFixedWidth(14)
                mark.setStyleSheet(
                    f"color:{_state_colour(c.state)};font-size:12px;font-weight:700")
                lab = QLabel(c.label)
                lab.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:11px")
                det = QLabel(c.detail)
                det.setStyleSheet(f"color:{TEXT_MUTED};font-size:10px")
                det.setWordWrap(True)
                row.addWidget(mark)
                row.addWidget(lab)
                row.addStretch()
                row.addWidget(det, 2)
                v.addLayout(row)
        v.addStretch()
        w.setWidget(inner)
        return w

    def _routing_tab(self):
        rows = [(r.port, r.source or "—", r.destination, r.state)
                for r in self.report.routes]
        w = QWidget()
        w.setStyleSheet("background:transparent")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        note = QLabel("One route is held at a time; the selector serialises "
                      "sampling.")
        note.setStyleSheet(f"color:{TEXT_MUTED};font-size:10px")
        v.addWidget(note)
        v.addWidget(_table(["Port", "Source", "Destination", "State"], rows,
                           colour_col=3))
        v.addStretch()
        return w

    def _hardware_tab(self):
        rows = [(b.sim_object, b.kind, b.physical_device, b.status)
                for b in self.report.bindings]
        w = QWidget()
        w.setStyleSheet("background:transparent")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        note = QLabel("EnvironNets addresses every reactor the same way, "
                      "whatever it is underneath.")
        note.setStyleSheet(f"color:{TEXT_MUTED};font-size:10px")
        v.addWidget(note)
        v.addWidget(_table(["SIM object", "Type", "Physical device", "Status"],
                           rows, colour_col=3))
        v.addStretch()
        return w

    def _parameters_tab(self):
        rows = []
        for node, p in self.report.parameters.items():
            rows.append((
                node, p["reactor"], p["contents"],
                f"{p['sample_volume_uL']:g} uL", p["sample_count"],
                p["router_port"], ", ".join(p["destinations"]) or "—",
            ))
        w = QWidget()
        w.setStyleSheet("background:transparent")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(_table(
            ["Node", "Reactor", "Contents", "Sample vol", "Count",
             "Port", "Destinations"], rows))
        v.addStretch()
        return w

    def _sequence_tab(self):
        rows = []
        for i, s in enumerate(self.steps, start=1):
            t = int(s.at_s)
            verb = {"init": "Initialize experiment", "home": "Home selector",
                    "feed": "Start feed", "select": "Set router",
                    "move": "Move arm", "dispense": "Dispense sample",
                    "purge": "Flush / reset line"}.get(s.action, s.action)
            device = {"select": "Router", "move": "Robot", "dispense": "Robot",
                      "purge": "Router", "feed": "Reactor",
                      "home": "Router", "init": "Controller"}.get(s.action, "—")
            detail = ""
            if s.action == "select":
                detail = f"{s.target} → port {s.detail.get('port')}"
            elif s.action == "move":
                detail = f"well {s.target}"
            elif s.action == "dispense":
                detail = f"{s.detail.get('volume_uL'):.0f} uL → {s.target}"
            elif s.action == "feed":
                detail = f"{s.target}  D = {s.detail.get('d_per_h', 0):.2f}/h"
            rows.append((i, f"{t//60:02d}:{t%60:02d}", verb, device, detail))
        w = QWidget()
        w.setStyleSheet("background:transparent")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        tbl = _table(["#", "Time", "Action", "Device", "Detail"], rows)
        tbl.setFixedHeight(340)
        v.addWidget(tbl)
        return w

    def _log_tab(self):
        w = QWidget()
        w.setStyleSheet("background:transparent")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        note = QLabel("What the run should produce. The dashboard writes the "
                      "same lines tagged [RUN], so the two can be compared.")
        note.setStyleSheet(f"color:{TEXT_MUTED};font-size:10px")
        v.addWidget(note)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(expected_log(self.steps, self.report.run_id))
        te.setStyleSheet(
            f"background:{BG_DARK};color:{TEXT_SECONDARY};border:1px solid "
            f"{BORDER};border-radius:6px;font-family:{MONO};font-size:11px")
        v.addWidget(te)
        return w

    def _action_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            f"background:{BG_PANEL};border-top:1px solid {BORDER}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(10)

        back = QPushButton("← Back to canvas")
        back.setStyleSheet(
            f"QPushButton{{background:transparent;color:{TEXT_MUTED};"
            f"border:1px solid {BORDER};border-radius:6px;padding:7px 14px;"
            f"font-size:11px}}"
            f"QPushButton:hover{{color:{TEXT_PRIMARY};border-color:{BORDER_HOVER}}}")
        back.clicked.connect(self.back_requested.emit)
        h.addWidget(back)
        h.addStretch()

        exp = QPushButton("Export package")
        exp.setStyleSheet(
            f"QPushButton{{background:{BG_CARD};color:{TEXT_PRIMARY};"
            f"border:1px solid {BORDER_HOVER};border-radius:6px;"
            f"padding:7px 18px;font-size:11px;font-weight:600}}"
            f"QPushButton:hover{{border-color:{ACCENT}}}")
        exp.clicked.connect(self.export_requested.emit)
        h.addWidget(exp)

        dep = QPushButton("DEPLOY EXPERIMENT")
        ok = self.report.passed
        dep.setEnabled(ok)
        dep.setStyleSheet(
            f"QPushButton{{background:{'#1e3a2a' if ok else BG_CARD};"
            f"color:{GREEN if ok else TEXT_MUTED};"
            f"border:1px solid {GREEN if ok else BORDER};border-radius:6px;"
            f"padding:7px 22px;font-size:11px;font-weight:700;letter-spacing:0.6px}}"
            f"QPushButton:hover{{background:#265036}}"
            f"QPushButton:disabled{{color:{TEXT_MUTED}}}")
        dep.clicked.connect(self.deploy_requested.emit)
        h.addWidget(dep)
        return bar

    # -- interaction -------------------------------------------------------

    def _show_well(self, name):
        s = self.report.well_map().get(name)
        if not s:
            self.well_detail.setText(f"{name} — unused")
            return
        t = int(s.at_s)
        self.well_detail.setText(
            f"Sample ID:  {s.sample_id}\n"
            f"Source:     {s.source}\n"
            f"Router port:{s.port}\n"
            f"Volume:     {s.volume_uL:g} uL\n"
            f"Scheduled:  {t//60:02d}:{t%60:02d}")
