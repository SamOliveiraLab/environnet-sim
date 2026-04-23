"""Setup wizard for building bioreactor networks.

Drop a bioreactor → wizard suggests what you need → pick components →
auto-layout with tubing → link each unit to real hardware → all green → done.
"""

import uuid
import math
from dataclasses import asdict
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QPainterPath,
)
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QScrollArea, QSizePolicy, QCheckBox,
    QSpinBox, QStackedWidget, QComboBox, QInputDialog, QMessageBox,
)

from environnets.core.models import Unit, Connection
from environnets.core.unit_types import (
    REACTOR_TYPES, PUMP_TYPES, SENSOR_TYPES,
    get_type, default_dims, list_types, get_port_pos, port_tangent,
)
from environnets.ui.cartoons import DRAW_FUNCTIONS, draw_status_glow
from environnets.ui.theme import (
    ACCENT, ACCENT_DIM, ACCENT_HOVER, TEXT_PRIMARY, TEXT_SECONDARY,
    TEXT_MUTED, BG_DARK, BG_PANEL, BG_CARD, BG_INPUT, BG_HOVER,
    BORDER, BORDER_HOVER, GREEN, RED, AMBER,
)


SETUP_TEMPLATES = {
    "pio_20ml": {
        "label": "Pioreactor 20 mL",
        "reservoirs": [
            {"type_id": "media_bottle", "role": "source", "label": "Media bottle"},
            {"type_id": "waste_bottle", "role": "drain", "label": "Waste bottle"},
        ],
        "suggested_pumps": [
            {"type_id": "peristaltic", "role": "media_in", "label": "Media pump (in)"},
            {"type_id": "peristaltic", "role": "waste_out", "label": "Waste pump (out)"},
        ],
        "builtin_sensors": ["od", "temperature"],
        "optional_sensors": [
            {"type_id": "ph", "label": "pH probe"},
            {"type_id": "co2", "label": "CO₂ sensor"},
            {"type_id": "dissolved_o2", "label": "Dissolved O₂"},
        ],
    },
    "pio_40ml": {
        "label": "Pioreactor 40 mL",
        "reservoirs": [
            {"type_id": "media_bottle", "role": "source", "label": "Media bottle"},
            {"type_id": "waste_bottle", "role": "drain", "label": "Waste bottle"},
        ],
        "suggested_pumps": [
            {"type_id": "peristaltic", "role": "media_in", "label": "Media pump (in)"},
            {"type_id": "peristaltic", "role": "waste_out", "label": "Waste pump (out)"},
        ],
        "builtin_sensors": ["od", "temperature"],
        "optional_sensors": [
            {"type_id": "ph", "label": "pH probe"},
            {"type_id": "co2", "label": "CO₂ sensor"},
            {"type_id": "dissolved_o2", "label": "Dissolved O₂"},
        ],
    },
    "stirred_tank": {
        "label": "Stirred tank",
        "reservoirs": [
            {"type_id": "media_bottle", "role": "source", "label": "Media bottle"},
            {"type_id": "waste_bottle", "role": "drain", "label": "Waste bottle"},
        ],
        "suggested_pumps": [
            {"type_id": "peristaltic", "role": "media_in", "label": "Media pump (in)"},
            {"type_id": "peristaltic", "role": "waste_out", "label": "Waste pump (out)"},
        ],
        "builtin_sensors": [],
        "optional_sensors": [
            {"type_id": "od", "label": "OD sensor"},
            {"type_id": "temperature", "label": "Temperature probe"},
            {"type_id": "ph", "label": "pH probe"},
            {"type_id": "co2", "label": "CO₂ sensor"},
            {"type_id": "dissolved_o2", "label": "Dissolved O₂"},
        ],
    },
    "microfluidic": {
        "label": "Microfluidic chamber",
        "reservoirs": [
            {"type_id": "media_bottle", "role": "source", "label": "Media bottle"},
            {"type_id": "waste_bottle", "role": "drain", "label": "Waste bottle"},
        ],
        "suggested_pumps": [
            {"type_id": "single_syringe", "role": "media_in", "label": "Syringe pump (in)"},
        ],
        "builtin_sensors": [],
        "optional_sensors": [
            {"type_id": "od", "label": "OD sensor"},
            {"type_id": "temperature", "label": "Temperature probe"},
            {"type_id": "ph", "label": "pH probe"},
        ],
    },
    "custom_vessel": {
        "label": "Custom vessel",
        "reservoirs": [
            {"type_id": "media_bottle", "role": "source", "label": "Media bottle"},
            {"type_id": "waste_bottle", "role": "drain", "label": "Waste bottle"},
        ],
        "suggested_pumps": [
            {"type_id": "peristaltic", "role": "media_in", "label": "Pump (in)"},
            {"type_id": "peristaltic", "role": "waste_out", "label": "Pump (out)"},
        ],
        "builtin_sensors": [],
        "optional_sensors": [
            {"type_id": "od", "label": "OD sensor"},
            {"type_id": "temperature", "label": "Temperature probe"},
            {"type_id": "ph", "label": "pH probe"},
            {"type_id": "co2", "label": "CO₂ sensor"},
            {"type_id": "dissolved_o2", "label": "Dissolved O₂"},
        ],
    },
}


def _render_cartoon(category: str, type_id: str, status: str = "idle", size: int = 80) -> QPixmap:
    w, h = default_dims(category, type_id)
    scale = min(size / w, size / h) * 0.85
    pw, ph = int(w * scale) + 20, int(h * scale) + 20
    pm = QPixmap(pw, ph)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    dummy = Unit(uid="preview", kind=category, category=category, type_id=type_id, status=status,
                 x=10, y=10)
    fn = DRAW_FUNCTIONS.get((category, type_id))
    if fn:
        fn(p, 10, 10, w * scale, h * scale, dummy, 0.0)
    p.end()
    return pm


class ComponentCard(QFrame):
    _card_id = 0

    def __init__(self, category: str, type_id: str, label: str,
                 description: str = "", checked: bool = True,
                 builtin: bool = False, parent=None):
        super().__init__(parent)
        self.category = category
        self.type_id = type_id
        self.is_builtin = builtin
        ComponentCard._card_id += 1
        obj_name = f"compCard{ComponentCard._card_id}"
        self.setObjectName(obj_name)
        self.setStyleSheet(
            f"#{obj_name}{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:8px;padding:8px}}"
            f"#{obj_name}:hover{{border-color:{BORDER_HOVER}}}"
            f"#{obj_name} QLabel{{border:none;background:transparent}}"
            f"#{obj_name} QCheckBox{{background:transparent;border:none}}"
        )
        self.setFixedHeight(72)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        icon_label = QLabel()
        pm = _render_cartoon(category, type_id, size=52)
        icon_label.setPixmap(pm)
        icon_label.setFixedSize(56, 56)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(label)
        name.setStyleSheet(f"font-size:12px;font-weight:500;color:{TEXT_PRIMARY}")
        text_col.addWidget(name)
        if description:
            desc = QLabel(description)
            desc.setStyleSheet(f"font-size:10px;color:{TEXT_MUTED}")
            desc.setWordWrap(True)
            text_col.addWidget(desc)
        elif builtin:
            tag = QLabel("Built-in")
            tag.setStyleSheet(f"font-size:10px;color:{GREEN}")
            text_col.addWidget(tag)
        layout.addLayout(text_col, 1)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        if builtin:
            self.checkbox.setChecked(True)
            self.checkbox.setEnabled(False)
        self.checkbox.setStyleSheet(
            f"QCheckBox::indicator{{width:18px;height:18px;border-radius:4px;"
            f"border:1px solid {BORDER};background:{BG_INPUT}}}"
            f"QCheckBox::indicator:checked{{background:{ACCENT};border-color:{ACCENT}}}"
            f"QCheckBox::indicator:disabled{{background:{ACCENT_DIM};border-color:{ACCENT_DIM}}}"
        )
        layout.addWidget(self.checkbox)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()


class PumpTypeCard(QFrame):
    _card_id = 0

    def __init__(self, pump_info: dict, parent=None):
        super().__init__(parent)
        self.pump_info = pump_info
        self.type_id = pump_info["type_id"]
        self.role = pump_info["role"]
        PumpTypeCard._card_id += 1
        obj_name = f"pumpCard{PumpTypeCard._card_id}"
        self.setObjectName(obj_name)
        self.setStyleSheet(
            f"#{obj_name}{{background:{BG_CARD};border:1px solid {BORDER};"
            f"border-radius:8px;padding:8px}}"
            f"#{obj_name}:hover{{border-color:{BORDER_HOVER}}}"
            f"#{obj_name} QLabel{{border:none;background:transparent}}"
            f"#{obj_name} QCheckBox{{background:transparent;border:none}}"
        )
        self.setFixedHeight(80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        icon_label = QLabel()
        pm = _render_cartoon("pump", self.type_id, size=56)
        icon_label.setPixmap(pm)
        icon_label.setFixedSize(60, 60)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(pump_info["label"])
        name.setStyleSheet(f"font-size:12px;font-weight:500;color:{TEXT_PRIMARY}")
        text_col.addWidget(name)

        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        type_lbl = QLabel("Type:")
        type_lbl.setStyleSheet(f"font-size:10px;color:{TEXT_MUTED}")
        type_row.addWidget(type_lbl)
        self.type_combo = QComboBox()
        self.type_combo.setFixedHeight(24)
        self.type_combo.setStyleSheet(f"font-size:10px;padding:2px 6px")
        for tid, defn in list_types("pump"):
            self.type_combo.addItem(defn["label"], tid)
        idx = self.type_combo.findData(self.type_id)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        type_row.addWidget(self.type_combo, 1)
        text_col.addLayout(type_row)

        layout.addLayout(text_col, 1)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.setStyleSheet(
            f"QCheckBox::indicator{{width:18px;height:18px;border-radius:4px;"
            f"border:1px solid {BORDER};background:{BG_INPUT}}}"
            f"QCheckBox::indicator:checked{{background:{ACCENT};border-color:{ACCENT}}}"
        )
        layout.addWidget(self.checkbox)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def get_type_id(self) -> str:
        return self.type_combo.currentData() or self.type_id


class PreviewWidget(QWidget):
    """Shows a mini-preview of the auto-layout before committing."""

    def __init__(self, units: list[Unit], connections: list[Connection], parent=None):
        super().__init__(parent)
        self.units = units
        self.connections = connections
        self._phase = 0.0
        self.setMinimumSize(400, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self):
        self._phase = (self._phase + 0.015) % 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(self.rect(), QColor(BG_DARK))

            p.setPen(QPen(QColor(BORDER), 1))
            grid = 20
            for gx in range(0, self.width(), grid):
                for gy in range(0, self.height(), grid):
                    p.drawPoint(gx, gy)

            for c in self.connections:
                self._draw_tubing(p, c)
            for u in self.units:
                draw_status_glow(p, u, self._phase)
                fn = DRAW_FUNCTIONS.get((u.category, u.type_id))
                if fn:
                    w, h = default_dims(u.category, u.type_id)
                    fn(p, u.x, u.y, w, h, u, self._phase)
            self._draw_port_dots(p)
        finally:
            p.end()

    def _draw_port_dots(self, p):
        connected_ports: list[tuple[float, float]] = []
        for c in self.connections:
            src = next((u for u in self.units if u.uid == c.source_uid), None)
            tgt = next((u for u in self.units if u.uid == c.target_uid), None)
            if src and tgt:
                connected_ports.append(get_port_pos(src, "source", tgt))
                connected_ports.append(get_port_pos(tgt, "target", src))
        for px, py in connected_ports:
            p.setPen(QPen(QColor(80, 90, 110), 1.5))
            p.setBrush(QBrush(QColor(140, 160, 190)))
            p.drawEllipse(QPointF(px, py), 4, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(200, 210, 230, 120)))
            p.drawEllipse(QPointF(px, py), 2, 2)

    def _draw_tubing(self, p, conn):
        src = next((u for u in self.units if u.uid == conn.source_uid), None)
        tgt = next((u for u in self.units if u.uid == conn.target_uid), None)
        if not src or not tgt:
            return

        sx, sy = get_port_pos(src, "source", tgt)
        tx, ty = get_port_pos(tgt, "target", src)

        sdx, sdy = port_tangent(src, sx, sy)
        tdx, tdy = port_tangent(tgt, tx, ty)
        dist = math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2)
        ext = min(80, dist * 0.4)

        path = QPainterPath()
        path.moveTo(sx, sy)
        path.cubicTo(sx + sdx * ext, sy + sdy * ext,
                     tx + tdx * ext, ty + tdy * ext, tx, ty)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(30, 30, 38), 7))
        p.drawPath(path)
        p.setPen(QPen(QColor(100, 105, 120), 3))
        p.drawPath(path)
        p.setPen(QPen(QColor(140, 150, 170, 100), 1))
        p.drawPath(path)

        p.setBrush(QBrush(QColor(140, 165, 210)))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            t = (self._phase + i / 3) % 1.0
            pt = path.pointAtPercent(t)
            p.drawEllipse(pt, 3, 3)

    def update_layout(self, units, connections):
        self.units = units
        self.connections = connections
        self.update()


def auto_layout(reactor: Unit, pumps_in: list[Unit], pumps_out: list[Unit],
                sensors: list[Unit], reservoirs_in: list[Unit] = None,
                reservoirs_out: list[Unit] = None,
                canvas_w: int = 800, canvas_h: int = 500) -> list[Connection]:
    """Horizontal flow chain: bottles at edges, pumps flanking reactor, sensors below."""
    reservoirs_in = reservoirs_in or []
    reservoirs_out = reservoirs_out or []
    g = 20
    sensor_gap = 40

    rw, rh = default_dims(reactor.category, reactor.type_id)

    chain = list(reservoirs_in) + list(pumps_in) + [reactor] + list(pumps_out) + list(reservoirs_out)
    widths = [default_dims(u.category, u.type_id)[0] for u in chain]
    heights = [default_dims(u.category, u.type_id)[1] for u in chain]
    total_w = sum(widths)
    n_gaps = max(len(widths) - 1, 1)
    gap = max(30, (canvas_w - total_w - 40) / n_gaps)

    center_y = max(heights) / 2 + 20

    x = 20.0
    for u, w, h in zip(chain, widths, heights):
        u.x = round(x / g) * g
        u.y = round((center_y - h / 2) / g) * g
        x += w + gap

    connections = []

    for res in reservoirs_in:
        target = pumps_in[0] if pumps_in else reactor
        connections.append(Connection(source_uid=res.uid, target_uid=target.uid, kind="flow"))
    for pump in pumps_in:
        connections.append(Connection(source_uid=pump.uid, target_uid=reactor.uid, kind="flow"))
    for pump in pumps_out:
        connections.append(Connection(source_uid=reactor.uid, target_uid=pump.uid, kind="flow"))
    for res in reservoirs_out:
        source = pumps_out[-1] if pumps_out else reactor
        connections.append(Connection(source_uid=source.uid, target_uid=res.uid, kind="flow"))

    sensor_y = reactor.y + rh + sensor_gap
    total_sw = sum(default_dims(s.category, s.type_id)[0] + 30 for s in sensors) - (30 if sensors else 0)
    sx = reactor.x + rw / 2 - total_sw / 2
    for sensor in sensors:
        sw, sh = default_dims(sensor.category, sensor.type_id)
        sensor.x = round(sx / g) * g
        sensor.y = round(sensor_y / g) * g
        sx += sw + 30
        connections.append(Connection(source_uid=sensor.uid, target_uid=reactor.uid, kind="data"))

    return connections


class SetupWizard(QDialog):
    def __init__(self, reactor_type_id: str, api=None, parent=None):
        super().__init__(parent)
        self.reactor_type_id = reactor_type_id
        self.api = api
        self.setWindowTitle("Set up bioreactor network")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(
            f"QDialog{{background:{BG_DARK}}}"
        )

        self.template = SETUP_TEMPLATES.get(reactor_type_id, SETUP_TEMPLATES["pio_20ml"])
        self.result_units: list[Unit] = []
        self.result_connections: list[Connection] = []

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        header = QLabel(f"  Build your network")
        header.setStyleSheet(
            f"font-size:16px;font-weight:600;color:{TEXT_PRIMARY};"
            f"padding:16px 20px 8px 20px;background:{BG_PANEL}"
        )
        main_layout.addWidget(header)

        self._subtitle = QLabel(f"  Starting with: {self.template['label']}")
        self._subtitle.setStyleSheet(
            f"font-size:12px;color:{TEXT_SECONDARY};padding:0 20px 12px 20px;background:{BG_PANEL}"
        )
        main_layout.addWidget(self._subtitle)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{BORDER}")
        main_layout.addWidget(sep)

        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        self._build_step_pumps()
        self._build_step_sensors()
        self._build_step_count()
        self._build_step_preview()

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background:{BORDER}")
        main_layout.addWidget(sep2)

        nav = QHBoxLayout()
        nav.setContentsMargins(16, 12, 16, 12)

        self._step_label = QLabel("Step 1 of 4")
        self._step_label.setStyleSheet(f"font-size:11px;color:{TEXT_MUTED}")
        nav.addWidget(self._step_label)

        nav.addStretch()

        self._back_btn = QPushButton("Back")
        self._back_btn.clicked.connect(self._go_back)
        self._back_btn.setVisible(False)
        nav.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next")
        self._next_btn.setProperty("class", "primary")
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)

        main_layout.addLayout(nav)

    def _build_step_pumps(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Pumps")
        title.setStyleSheet(f"font-size:14px;font-weight:500;color:{TEXT_PRIMARY}")
        layout.addWidget(title)

        hint = QLabel("Your bioreactor needs pumps to flow media in and waste out.\nSelect and configure what you need.")
        hint.setStyleSheet(f"font-size:11px;color:{TEXT_SECONDARY}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._pump_cards: list[PumpTypeCard] = []
        for pump_info in self.template["suggested_pumps"]:
            card = PumpTypeCard(pump_info)
            self._pump_cards.append(card)
            layout.addWidget(card)

        layout.addStretch()
        self._stack.addWidget(page)

    def _build_step_sensors(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Sensors")
        title.setStyleSheet(f"font-size:14px;font-weight:500;color:{TEXT_PRIMARY}")
        layout.addWidget(title)

        hint = QLabel("Check which sensors to include.\nBuilt-in sensors are already part of your reactor.")
        hint.setStyleSheet(f"font-size:11px;color:{TEXT_SECONDARY}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:transparent;border:none")
        scroll_w = QWidget()
        scroll_layout = QVBoxLayout(scroll_w)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(6)

        self._sensor_cards: list[ComponentCard] = []

        for sid in self.template["builtin_sensors"]:
            defn = get_type("sensor", sid)
            if defn:
                card = ComponentCard("sensor", sid, defn["label"], builtin=True)
                self._sensor_cards.append(card)
                scroll_layout.addWidget(card)

        for sinfo in self.template["optional_sensors"]:
            defn = get_type("sensor", sinfo["type_id"])
            if defn:
                card = ComponentCard("sensor", sinfo["type_id"], sinfo["label"],
                                     description=defn.get("description", ""), checked=False)
                self._sensor_cards.append(card)
                scroll_layout.addWidget(card)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_w)
        layout.addWidget(scroll, 1)
        self._stack.addWidget(page)

    def _build_step_count(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("How many reactors?")
        title.setStyleSheet(f"font-size:14px;font-weight:500;color:{TEXT_PRIMARY}")
        layout.addWidget(title)

        hint = QLabel("Each reactor gets its own set of pumps and sensors.\nStart with 1 if you're just getting going.")
        hint.setStyleSheet(f"font-size:11px;color:{TEXT_SECONDARY}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        count_row = QHBoxLayout()
        count_row.setSpacing(12)

        icon_label = QLabel()
        pm = _render_cartoon("reactor", self.reactor_type_id, size=80)
        icon_label.setPixmap(pm)
        icon_label.setFixedSize(90, 90)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_row.addWidget(icon_label)

        self._reactor_count = QSpinBox()
        self._reactor_count.setRange(1, 12)
        self._reactor_count.setValue(1)
        self._reactor_count.setFixedSize(80, 36)
        self._reactor_count.setStyleSheet(f"font-size:16px;font-weight:600")
        count_row.addWidget(self._reactor_count)

        times_label = QLabel(f"×  {self.template['label']}")
        times_label.setStyleSheet(f"font-size:13px;color:{TEXT_SECONDARY}")
        count_row.addWidget(times_label)
        count_row.addStretch()

        layout.addLayout(count_row)
        layout.addStretch()
        self._stack.addWidget(page)

    def _build_step_preview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Preview your network")
        title.setStyleSheet(f"font-size:14px;font-weight:500;color:{TEXT_PRIMARY}")
        layout.addWidget(title)

        hint = QLabel("This is how your network will look. You can rearrange everything after.")
        hint.setStyleSheet(f"font-size:11px;color:{TEXT_SECONDARY}")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._preview = PreviewWidget([], [])
        self._preview.setStyleSheet(f"border:1px solid {BORDER};border-radius:8px")
        layout.addWidget(self._preview, 1)

        summary_frame = QFrame()
        summary_frame.setStyleSheet(
            f"QFrame{{background:{BG_CARD};border:1px solid {BORDER};border-radius:6px;padding:10px}}"
        )
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setSpacing(4)
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet(f"font-size:11px;color:{TEXT_SECONDARY};border:none;background:transparent")
        self._summary_label.setWordWrap(True)
        summary_layout.addWidget(self._summary_label)
        layout.addWidget(summary_frame)

        self._stack.addWidget(page)

    def _go_back(self):
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._update_nav()

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx < 3:
            if idx == 2:
                self._generate_layout()
            self._stack.setCurrentIndex(idx + 1)
            self._update_nav()
        else:
            self.accept()

    def _update_nav(self):
        idx = self._stack.currentIndex()
        self._step_label.setText(f"Step {idx + 1} of 4")
        self._back_btn.setVisible(idx > 0)
        if idx == 3:
            self._next_btn.setText("Build it")
        else:
            self._next_btn.setText("Next")

        subtitles = [
            f"Starting with: {self.template['label']}",
            "Choose your sensors",
            "Set the number of reactors",
            "Review and build",
        ]
        self._subtitle.setText(f"  {subtitles[idx]}")

    def _generate_layout(self):
        count = self._reactor_count.value()
        all_units: list[Unit] = []
        all_connections: list[Connection] = []

        selected_pumps = [c for c in self._pump_cards if c.is_selected()]
        selected_sensors = [c for c in self._sensor_cards if c.is_selected()]
        template_reservoirs = self.template.get("reservoirs", [])

        for ri in range(count):
            reactor_defn = get_type("reactor", self.reactor_type_id)
            reactor = Unit(
                uid=f"u-{uuid.uuid4().hex[:6]}",
                kind="reactor",
                label=f"{reactor_defn.get('label', 'Reactor')} {ri + 1}" if count > 1
                      else reactor_defn.get("label", "Reactor"),
                category="reactor",
                type_id=self.reactor_type_id,
                status="disconnected",
            )

            pumps_in = []
            pumps_out = []
            for pc in selected_pumps:
                tid = pc.get_type_id()
                pump = Unit(
                    uid=f"u-{uuid.uuid4().hex[:6]}",
                    kind="pump",
                    label=f"{pc.pump_info['label']}" + (f" {ri + 1}" if count > 1 else ""),
                    category="pump",
                    type_id=tid,
                    status="disconnected",
                )
                if pc.role == "media_in":
                    pumps_in.append(pump)
                else:
                    pumps_out.append(pump)

            reservoirs_in = []
            reservoirs_out = []
            for rinfo in template_reservoirs:
                res_defn = get_type("reservoir", rinfo["type_id"])
                if not res_defn:
                    continue
                res = Unit(
                    uid=f"u-{uuid.uuid4().hex[:6]}",
                    kind="reservoir",
                    label=rinfo["label"] + (f" {ri + 1}" if count > 1 else ""),
                    category="reservoir",
                    type_id=rinfo["type_id"],
                    status="disconnected",
                )
                if rinfo["role"] == "source":
                    reservoirs_in.append(res)
                else:
                    reservoirs_out.append(res)

            sensors = []
            for sc in selected_sensors:
                sensor_defn = get_type("sensor", sc.type_id)
                sensor = Unit(
                    uid=f"u-{uuid.uuid4().hex[:6]}",
                    kind="sensor",
                    label=sensor_defn.get("label", "Sensor") + (f" {ri + 1}" if count > 1 else ""),
                    category="sensor",
                    type_id=sc.type_id,
                    status="disconnected",
                )
                sensors.append(sensor)

            offset_x = ri * 840
            canvas_w = 800
            canvas_h = max(460, 300 + len(sensors) * 50)
            conns = auto_layout(reactor, pumps_in, pumps_out, sensors,
                                reservoirs_in, reservoirs_out, canvas_w, canvas_h)

            for unit in [reactor] + pumps_in + pumps_out + reservoirs_in + reservoirs_out + sensors:
                unit.x += offset_x

            all_units.append(reactor)
            all_units.extend(reservoirs_in)
            all_units.extend(pumps_in)
            all_units.extend(pumps_out)
            all_units.extend(reservoirs_out)
            all_units.extend(sensors)
            all_connections.extend(conns)

        if count > 1:
            for i in range(count - 1):
                reactors = [u for u in all_units if u.category == "reactor"]
                if i + 1 < len(reactors):
                    all_connections.append(Connection(
                        source_uid=reactors[i].uid,
                        target_uid=reactors[i + 1].uid,
                        kind="flow",
                    ))

        self.result_units = all_units
        self.result_connections = all_connections

        self._preview.update_layout(all_units, all_connections)

        n_reactors = sum(1 for u in all_units if u.category == "reactor")
        n_pumps = sum(1 for u in all_units if u.category == "pump")
        n_sensors = sum(1 for u in all_units if u.category == "sensor")
        n_reservoirs = sum(1 for u in all_units if u.category == "reservoir")
        self._summary_label.setText(
            f"{n_reactors} reactor(s)  ·  {n_pumps} pump(s)  ·  "
            f"{n_reservoirs} reservoir(s)  ·  {n_sensors} sensor(s)  ·  "
            f"{len(all_connections)} connection(s)\n"
            f"All units will start disconnected (red). Link each to hardware to go green."
        )


class SetupChoiceDialog(QDialog):
    """First dialog: 'Build up' or 'Manual drag'."""
    BUILD_UP = "buildup"
    MANUAL = "manual"

    def __init__(self, reactor_type_id: str, parent=None):
        super().__init__(parent)
        self.reactor_type_id = reactor_type_id
        self.choice = self.MANUAL
        self.setWindowTitle("How do you want to set up?")
        self.setFixedSize(460, 320)
        self.setStyleSheet(f"QDialog{{background:{BG_DARK}}}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        reactor_defn = get_type("reactor", reactor_type_id)
        title = QLabel(f"Setting up: {reactor_defn.get('label', 'Reactor')}")
        title.setStyleSheet(f"font-size:16px;font-weight:600;color:{TEXT_PRIMARY}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        icon_label = QLabel()
        pm = _render_cartoon("reactor", reactor_type_id, size=90)
        icon_label.setPixmap(pm)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        hint = QLabel("Choose how to build your network")
        hint.setStyleSheet(f"font-size:12px;color:{TEXT_SECONDARY}")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        build_btn = QPushButton("Build up\nGuided setup with suggestions")
        build_btn.setFixedHeight(60)
        build_btn.setProperty("class", "primary")
        build_btn.setStyleSheet(
            build_btn.styleSheet() +
            f"QPushButton{{text-align:center;font-size:12px;padding:8px 16px}}"
        )
        build_btn.clicked.connect(lambda: self._pick(self.BUILD_UP))
        btn_row.addWidget(build_btn, 1)

        manual_btn = QPushButton("Manual drag\nDrag each piece yourself")
        manual_btn.setFixedHeight(60)
        manual_btn.setStyleSheet(
            manual_btn.styleSheet() +
            f"QPushButton{{text-align:center;font-size:12px;padding:8px 16px}}"
        )
        manual_btn.clicked.connect(lambda: self._pick(self.MANUAL))
        btn_row.addWidget(manual_btn, 1)

        layout.addLayout(btn_row)

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()
