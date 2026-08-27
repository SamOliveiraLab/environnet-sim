"""Network canvas with drag-and-drop and animated cartoons."""

import copy
import math
import uuid
from dataclasses import asdict
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QMimeData, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPainterPath,
    QMouseEvent, QDrag, QPixmap, QKeySequence, QShortcut, QTransform,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QMenu, QInputDialog, QMessageBox,
    QScrollArea,
)

from environnets.core.models import Unit, Connection
from environnets.core.unit_types import (
    default_dims, list_types, get_type, get_port_pos, port_tangent,
    CATEGORY_ORDER, port_count, LINE_TYPES,
)
from environnets.core.presets import list_presets
from environnets.ui.cartoons import draw_unit, draw_status_glow
from environnets.ui.theme import (
    ACCENT, ACCENT_DIM, TEXT_SECONDARY, TEXT_MUTED, TEXT_PRIMARY,
    BG_CARD, BG_DARK, BG_PANEL, BG_INPUT, BG_HOVER, BORDER, BORDER_HOVER,
)

ZOOM_MIN = 0.25
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1


class CanvasWidget(QWidget):
    MAX_UNDO = 40

    def __init__(self, parent_canvas):
        super().__init__()
        self.parent_canvas = parent_canvas
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._dragging_unit = None
        self._drag_offset = QPointF(0, 0)
        self._hover_unit = None
        self._selected_unit = None
        self._selected_units: set = set()
        self._connecting_from = None
        self._mouse_pos = QPointF(0, 0)
        self._phase = 0.0
        self._grid = 20
        self._undo_stack: list[dict] = []
        # (source_uid, target_uid) pairs currently carrying liquid. None means
        # "not driven by playback"; fall back to device status.
        self._active_links: set | None = None
        # Lines the continuous process keeps busy (feeds, culture train):
        # they carry slow flow dots but stay dimmer than the active path.
        self._process_links: set | None = None

        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._panning = False
        self._pan_start = QPointF(0, 0)

        self._rubber_band = False
        self._rubber_start = QPointF(0, 0)
        self._rubber_end = QPointF(0, 0)

        self._multi_drag = False
        self._multi_drag_start = QPointF(0, 0)
        self._multi_drag_origins: dict = {}

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self):
        self._phase = (self._phase + 0.015) % 1.0
        self.update()

    @property
    def network(self):
        return self.parent_canvas.network

    def _screen_to_canvas(self, screen_pos: QPointF) -> QPointF:
        return QPointF(
            (screen_pos.x() - self._pan.x()) / self._zoom,
            (screen_pos.y() - self._pan.y()) / self._zoom,
        )

    def _canvas_to_screen(self, canvas_pos: QPointF) -> QPointF:
        return QPointF(
            canvas_pos.x() * self._zoom + self._pan.x(),
            canvas_pos.y() * self._zoom + self._pan.y(),
        )

    def set_zoom(self, z: float, anchor: QPointF = None):
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        canvas_pt = self._screen_to_canvas(anchor)
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, z))
        new_screen = self._canvas_to_screen(canvas_pt)
        self._pan += anchor - new_screen
        self.parent_canvas._update_zoom_label()

    def paintEvent(self, e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(self.rect(), QColor(BG_DARK))

            p.save()
            p.translate(self._pan)
            p.scale(self._zoom, self._zoom)

            g = self._grid
            visible = self._visible_canvas_rect()
            x0 = int(visible.left() / g) * g
            y0 = int(visible.top() / g) * g
            x1 = int(visible.right() / g + 1) * g
            y1 = int(visible.bottom() / g + 1) * g
            p.setPen(QPen(QColor(BORDER), 1.0 / self._zoom))
            for gx in range(x0, x1, g):
                for gy in range(y0, y1, g):
                    p.drawPoint(gx, gy)

            if not self.network:
                p.setPen(QPen(QColor(TEXT_MUTED)))
                p.setFont(QFont("Inter", 13))
                r = QRectF(0, 0, self.width() / self._zoom, self.height() / self._zoom)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                           "Drag units from the palette\nto build your bioreactor network")
                p.restore()
                return

            if self._connecting_from:
                u = self._connecting_from
                w, h = default_dims(u.category, u.type_id)
                p.setPen(QPen(QColor(ACCENT_DIM), 2.0 / self._zoom, Qt.PenStyle.DashLine))
                canvas_mouse = self._screen_to_canvas(self._mouse_pos)
                start = QPointF(u.x + w / 2, u.y + h * 0.06)
                p.drawLine(start, canvas_mouse)

            for u in self.network.units:
                draw_status_glow(p, u, self._phase)
                draw_unit(p, u, self._phase)

            # Tubing lies over the hardware, as it does on a real bench, and
            # so a line running past a device is never hidden behind it.
            for c in self.network.connections:
                self._draw_tubing(p, c)

            for c in self.network.connections:
                self._draw_port_badge(p, c)

            self._draw_port_dots(p)

            all_selected = self._selected_units | ({self._selected_unit} if self._selected_unit else set())
            for su in all_selected:
                if su and su in self.network.units:
                    sw, sh = default_dims(su.category, su.type_id)
                    p.setPen(QPen(QColor(ACCENT), 1.5 / self._zoom, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(QRectF(su.x - 6, su.y - 6, sw + 12, sh + 12), 8, 8)

            p.restore()

            if self._rubber_band:
                rb = QRectF(self._rubber_start, self._rubber_end).normalized()
                p.setPen(QPen(QColor(ACCENT), 1, Qt.PenStyle.DashLine))
                p.setBrush(QBrush(QColor(107, 138, 253, 30)))
                p.drawRect(rb)
        finally:
            p.end()

    def _visible_canvas_rect(self) -> QRectF:
        tl = self._screen_to_canvas(QPointF(0, 0))
        br = self._screen_to_canvas(QPointF(self.width(), self.height()))
        return QRectF(tl, br)

    @staticmethod
    def _rect_of(u):
        w, h = default_dims(u.category, u.type_id)
        return QRectF(u.x, u.y, w, h)

    def _draw_tubing(self, p, conn):
        src = next((u for u in self.network.units if u.uid == conn.source_uid), None)
        tgt = next((u for u in self.network.units if u.uid == conn.target_uid), None)
        if not src or not tgt:
            return

        # No tube between an arm and the plate it dispenses into - the needle
        # does that. Drawing one there reads as plumbing that does not exist.
        if {src.category, tgt.category} == {"sampling", "plate"}:
            return

        # Two units sitting on top of each other need no line; their spatial
        # relationship already says it, and a curve between them lassos.
        if self._rect_of(src).intersects(self._rect_of(tgt)):
            return

        path = self._connection_path(conn)
        if path is None:
            return

        # Colour the line by what it carries, so the graph reads as plumbing.
        spec = LINE_TYPES.get(conn.kind)
        core = QColor(spec["color"]) if spec else QColor(100, 105, 120)
        style = (Qt.PenStyle.DashLine
                 if spec and spec.get("dashed") else Qt.PenStyle.SolidLine)

        p.setBrush(Qt.BrushStyle.NoBrush)

        if style == Qt.PenStyle.DashLine:
            pen = QPen(core, 2.0)
            pen.setStyle(style)
            p.setPen(pen)
            p.drawPath(path)
        else:
            # Soft shadow cast onto whatever the tube lies across.
            shadow = QPen(QColor(0, 0, 0, 90), 9)
            shadow.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(shadow)
            p.save()
            p.translate(1.5, 2.0)
            p.drawPath(path)
            p.restore()

            # Dark wall, translucent bore, then a specular line along the top:
            # reads as a soft tube rather than a drawn stroke.
            wall = QPen(QColor(22, 24, 30), 7.5)
            wall.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(wall)
            p.drawPath(path)

            bore = QPen(QColor(core.red(), core.green(), core.blue(), 150), 5.0)
            bore.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(bore)
            p.drawPath(path)

            gloss = QPen(QColor(255, 255, 255, 60), 1.6)
            gloss.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(gloss)
            p.save()
            p.translate(-0.6, -1.6)
            p.drawPath(path)
            p.restore()

        # Only the path carrying liquid right now animates. When an explicit
        # active set is supplied (playback), it is authoritative - otherwise
        # fall back to device status.
        if self._active_links is not None:
            flowing = (conn.source_uid, conn.target_uid) in self._active_links
        else:
            flowing = src.status == "running" or tgt.status == "running"

        if flowing:
            # brighten the live line so the route reads at a glance
            glow = QPen(QColor(core.red(), core.green(), core.blue(), 70), 8)
            p.setPen(glow)
            p.drawPath(path)
            lit = QPen(core.lighter(145), 3.4)
            p.setPen(lit)
            p.drawPath(path)

            p.setBrush(QBrush(core.lighter(160)))
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(4):
                t = (self._phase * 1.2 + i / 4) % 1.0
                pt = path.pointAtPercent(t)
                p.drawEllipse(pt, 3.2, 3.2)

        elif (self._process_links is not None
              and (conn.source_uid, conn.target_uid) in self._process_links):
            # The continuous process: quiet metabolite traffic, slower and
            # dimmer than the sampling path so the active route still leads.
            p.setBrush(QBrush(QColor(core.red(), core.green(),
                                     core.blue(), 165)))
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                t = (self._phase * 0.5 + i / 3) % 1.0
                pt = path.pointAtPercent(t)
                p.drawEllipse(pt, 2.3, 2.3)

    def _connection_path(self, conn):
        """Recompute a connection's curve, or None if an end is missing."""
        src = next((u for u in self.network.units if u.uid == conn.source_uid), None)
        tgt = next((u for u in self.network.units if u.uid == conn.target_uid), None)
        if not src or not tgt:
            return None
        sx, sy = get_port_pos(src, "source", tgt, conn.source_port, conn.kind)
        tx, ty = get_port_pos(tgt, "target", src, conn.target_port, conn.kind)

        # Sample lines into a selector are routed like a cable tray: straight
        # drop, a horizontal lane of their own, straight into the port.
        lane_y = self._sample_lane_y(conn, tgt)
        if lane_y is not None:
            return self._tray_path(src, sx, sy, tx, ty, lane_y)

        # Ends stacked vertically: fall straight, no wave.
        if abs(tx - sx) < 6 and abs(ty - sy) > 30:
            path = QPainterPath()
            path.moveTo(sx, sy)
            path.cubicTo(sx, sy + (ty - sy) * 0.35,
                         tx, ty - (ty - sy) * 0.35, tx, ty)
            return path

        # Ends at the same height (the culture run between caps and their
        # transfer pumps): one uniform shallow sag, the same on every span,
        # instead of a wave shaped by whatever the tangents happen to be.
        if conn.kind in ("culture", "waste") and abs(ty - sy) < 24 \
                and abs(tx - sx) > 40:
            droop = max(sy, ty) + 15
            path = QPainterPath()
            path.moveTo(sx, sy)
            path.cubicTo(sx + (tx - sx) * 0.32, droop,
                         sx + (tx - sx) * 0.68, droop, tx, ty)
            return path

        sdx, sdy = port_tangent(src, sx, sy, conn.kind)
        tdx, tdy = port_tangent(tgt, tx, ty, conn.kind)
        dist = math.sqrt((tx - sx) ** 2 + (ty - sy) ** 2)
        ext = min(90, max(30.0, dist * 0.42))
        path = QPainterPath()
        path.moveTo(sx, sy)
        path.cubicTo(sx + sdx * ext, sy + sdy * ext,
                     tx + tdx * ext, ty + tdy * ext, tx, ty)
        return path

    def _sample_lane_y(self, conn, tgt):
        """The horizontal lane a router-bound sample line runs along.

        Every sample line into the selector gets its own lane, stacked
        above the inlets. Lines approaching from the left take the low
        lanes in port order; lines from the right stack above them in
        reverse port order - that ordering is what keeps every drop clear
        of every other line's lane.
        """
        if (conn.kind != "sample" or tgt.category != "routing"
                or not conn.target_port):
            return None
        left, right = [], []
        for c in self.network.connections:
            if (c.kind != "sample" or c.target_uid != tgt.uid
                    or not c.target_port):
                continue
            s = next((u for u in self.network.units
                      if u.uid == c.source_uid), None)
            if s is None:
                continue
            sxx, _ = get_port_pos(s, "source", tgt, c.source_port, c.kind)
            txx, _ = get_port_pos(tgt, "target", s, c.target_port, c.kind)
            (left if sxx <= txx else right).append((c.target_port, c))
        order = ([c for _, c in sorted(left, key=lambda t: t[0])]
                 + [c for _, c in sorted(right, key=lambda t: -t[0])])
        for lane, c in enumerate(order):
            if c is conn:
                return tgt.y - 24 - lane * 13
        return None

    @staticmethod
    def _tray_path(src, sx, sy, tx, ty, lane_y):
        """Orthogonal tube run with rounded corners: drop, lane, drop."""
        r = 14.0
        path = QPainterPath()
        path.moveTo(sx, sy)
        if src.category == "reactor":
            # Out of the cap, over the vial rim, then down the front of
            # the housing - the way the real tube hangs.
            drop_x = sx + (26.0 if tx >= sx else -26.0)
            path.cubicTo(sx, sy - 20, drop_x, sy - 20, drop_x, sy + 8)
        elif src.category == "reservoir":
            # Out of the cap, over the shoulder, down the side of the
            # bottle - never through it.
            bw = default_dims(src.category, src.type_id)[0]
            sgn = 1.0 if tx >= sx else -1.0
            drop_x = sx + sgn * (bw * 0.5 + 10.0)
            path.cubicTo(sx, sy - 26, drop_x, sy - 26, drop_x, sy + 16)
        else:
            drop_x = sx
        if abs(drop_x - tx) < 2 * r + 2:
            # Already above its port: one straight fall, gently correcting.
            path.cubicTo(drop_x, lane_y, tx, lane_y, tx, ty)
            return path
        sgn = 1.0 if tx > drop_x else -1.0
        path.lineTo(drop_x, lane_y - r)
        path.quadTo(drop_x, lane_y, drop_x + sgn * r, lane_y)
        path.lineTo(tx - sgn * r, lane_y)
        path.quadTo(tx, lane_y, tx, lane_y + r)
        path.lineTo(tx, ty)
        return path

    def _draw_port_badge(self, p, conn):
        """Numbered badge showing which router port a line claims."""
        if conn.target_port is None:
            return
        path = self._connection_path(conn)
        if path is None:
            return

        spec = LINE_TYPES.get(conn.kind)
        core = QColor(spec["color"]) if spec else QColor(120, 128, 145)

        # On the corner where the line turns down into its port; falls back
        # to a point near the inlet for free-form curves.
        src = next((u for u in self.network.units
                    if u.uid == conn.source_uid), None)
        tgt = next((u for u in self.network.units
                    if u.uid == conn.target_uid), None)
        lane_y = self._sample_lane_y(conn, tgt) if tgt else None
        if lane_y is not None and src is not None:
            tx, _ = get_port_pos(tgt, "target", src, conn.target_port,
                                 conn.kind)
            mid = QPointF(tx, lane_y)
        else:
            mid = path.pointAtPercent(0.80)
        r = 13.0
        p.setBrush(QBrush(QColor(20, 20, 25)))
        p.setPen(QPen(core, 2.0))
        p.drawEllipse(mid, r, r)
        p.setPen(QPen(QColor(238, 240, 246)))
        f = QFont("Inter", 11)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(mid.x() - r, mid.y() - r, r * 2, r * 2),
                   Qt.AlignmentFlag.AlignCenter, str(conn.target_port))

    def _draw_port_dots(self, p):
        if not self.network:
            return
        connected_ports: list[tuple[float, float]] = []
        for c in self.network.connections:
            src = next((u for u in self.network.units if u.uid == c.source_uid), None)
            tgt = next((u for u in self.network.units if u.uid == c.target_uid), None)
            if src and tgt:
                # The arm-plate pair draws no tube, so no dots either.
                if {src.category, tgt.category} == {"sampling", "plate"}:
                    continue
                connected_ports.append(
                    get_port_pos(src, "source", tgt, c.source_port, c.kind))
                connected_ports.append(
                    get_port_pos(tgt, "target", src, c.target_port, c.kind))
        dot_r = 4.0 / self._zoom
        inner_r = 2.0 / self._zoom
        pen_w = 1.5 / self._zoom
        for px, py in connected_ports:
            p.setPen(QPen(QColor(80, 90, 110), pen_w))
            p.setBrush(QBrush(QColor(140, 160, 190)))
            p.drawEllipse(QPointF(px, py), dot_r, dot_r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(200, 210, 230, 120)))
            p.drawEllipse(QPointF(px, py), inner_r, inner_r)

    def _drop_preset(self, preset_id: str, canvas_pos):
        """Place a full assembly, then select it so it can be moved as one."""
        from environnets.core.presets import get_preset, instantiate

        preset = get_preset(preset_id)
        if not preset:
            return

        existing = {u.label for u in self.network.units if u.label}
        units, connections = instantiate(
            preset, canvas_pos.x(), canvas_pos.y(), existing)

        self._push_undo()
        self.network.units.extend(units)
        self.network.connections.extend(connections)

        # Leave the whole assembly selected so it can be dragged into place.
        self._selected_unit = None
        self._selected_units = set(units)

        self._save()
        self.update()

    def _infer_kind(self, src, tgt) -> str:
        """Pick the line type from what is being joined.

        Saves classifying every line by hand; it stays changeable from the
        right-click menu.
        """
        s, t = src.category, tgt.category
        if s == "sensor" or t == "sensor":
            return "data"
        if t == "reservoir" and (tgt.type_id or "").startswith("waste"):
            return "waste"
        if s == "reservoir":
            return "media"
        if t in ("routing", "sampling", "plate") or s in ("routing", "sampling"):
            return "sample"
        if s == "reactor" and t == "reactor":
            return "culture"
        return "media" if t == "reactor" else "sample"

    def _next_free_port(self, router):
        """Lowest unclaimed port on a multi-port device."""
        total = port_count(router.category, router.type_id)
        if not total:
            return None
        taken = {
            c.target_port for c in self.network.connections
            if c.target_uid == router.uid and c.target_port is not None
        }
        for p in range(1, total + 1):
            if p not in taken:
                return p
        return None

    def _make_connection(self, src, tgt):
        """Build a connection, typing the line and claiming a port if needed."""
        kind = self._infer_kind(src, tgt)
        target_port = None
        if tgt.category == "routing":
            target_port = self._next_free_port(tgt)
            if target_port is None:
                QMessageBox.warning(
                    self, "Router full",
                    f"All {port_count(tgt.category, tgt.type_id)} ports on "
                    f"{tgt.label or tgt.uid} are already claimed.",
                )
        return Connection(source_uid=src.uid, target_uid=tgt.uid,
                          kind=kind, target_port=target_port)

    def _unit_at(self, pos):
        if not self.network:
            return None
        for u in reversed(self.network.units):
            w, h = default_dims(u.category, u.type_id)
            if QRectF(u.x, u.y, w, h).contains(pos):
                return u
        return None

    def mousePressEvent(self, e):
        screen_pos = e.position()
        canvas_pos = self._screen_to_canvas(screen_pos)

        if e.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = screen_pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        u = self._unit_at(canvas_pos)
        if e.button() == Qt.MouseButton.LeftButton:
            if u and self._connecting_from and u != self._connecting_from:
                self._push_undo()
                self.network.connections.append(
                    self._make_connection(self._connecting_from, u))
                self._connecting_from = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self._save()
                return

            shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)

            if u:
                if shift:
                    if u in self._selected_units:
                        self._selected_units.discard(u)
                    else:
                        self._selected_units.add(u)
                    self._selected_unit = None
                elif u in self._selected_units and len(self._selected_units) > 1:
                    pass
                else:
                    if not (u in self._selected_units):
                        self._selected_units.clear()
                    self._selected_unit = u
                    self._selected_units.add(u)

                if self._selected_units:
                    self._multi_drag = True
                    self._multi_drag_start = canvas_pos
                    self._multi_drag_origins = {
                        id(su): QPointF(su.x, su.y) for su in self._selected_units
                    }
                else:
                    self._dragging_unit = u
                    self._drag_offset = QPointF(canvas_pos.x() - u.x, canvas_pos.y() - u.y)
            else:
                if self._connecting_from:
                    self._connecting_from = None
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                elif not shift:
                    self._selected_unit = None
                    self._selected_units.clear()
                self._rubber_band = True
                self._rubber_start = screen_pos
                self._rubber_end = screen_pos

        elif e.button() == Qt.MouseButton.RightButton:
            if u:
                self._selected_unit = u
                if u not in self._selected_units:
                    self._selected_units.clear()
                    self._selected_units.add(u)
                self._show_menu(u, e.globalPosition().toPoint())
            else:
                self._show_canvas_menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        self._mouse_pos = e.position()
        canvas_pos = self._screen_to_canvas(e.position())

        if self._panning:
            delta = e.position() - self._pan_start
            self._pan += delta
            self._pan_start = e.position()
            return

        if self._rubber_band:
            self._rubber_end = e.position()
            rb_screen = QRectF(self._rubber_start, self._rubber_end).normalized()
            tl = self._screen_to_canvas(rb_screen.topLeft())
            br = self._screen_to_canvas(rb_screen.bottomRight())
            rb_canvas = QRectF(tl, br).normalized()
            self._selected_units.clear()
            self._selected_unit = None
            if self.network:
                for u in self.network.units:
                    w, h = default_dims(u.category, u.type_id)
                    if rb_canvas.intersects(QRectF(u.x, u.y, w, h)):
                        self._selected_units.add(u)
            return

        if self._multi_drag:
            dx = canvas_pos.x() - self._multi_drag_start.x()
            dy = canvas_pos.y() - self._multi_drag_start.y()
            for su in self._selected_units:
                orig = self._multi_drag_origins.get(id(su))
                if orig:
                    su.x = orig.x() + dx
                    su.y = orig.y() + dy
            return

        if self._dragging_unit:
            self._dragging_unit.x = canvas_pos.x() - self._drag_offset.x()
            self._dragging_unit.y = canvas_pos.y() - self._drag_offset.y()
        else:
            self._hover_unit = self._unit_at(canvas_pos)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if self._rubber_band:
            self._rubber_band = False
            return

        if self._multi_drag:
            dx = self._screen_to_canvas(e.position()).x() - self._multi_drag_start.x()
            dy = self._screen_to_canvas(e.position()).y() - self._multi_drag_start.y()
            if abs(dx) > 2 or abs(dy) > 2:
                self._push_undo()
            g = self._grid
            for su in self._selected_units:
                su.x = round(su.x / g) * g
                su.y = round(su.y / g) * g
            self._multi_drag = False
            self._multi_drag_origins.clear()
            self._save()
            return

        if self._dragging_unit:
            g = self._grid
            new_x = round(self._dragging_unit.x / g) * g
            new_y = round(self._dragging_unit.y / g) * g
            old_x = self._drag_offset.x()
            old_y = self._drag_offset.y()
            if new_x != old_x or new_y != old_y:
                self._push_undo()
            self._dragging_unit.x = new_x
            self._dragging_unit.y = new_y
            self._dragging_unit = None
            self._save()

    def wheelEvent(self, e: QWheelEvent):
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1 + (ZOOM_STEP if delta > 0 else -ZOOM_STEP)
        self.set_zoom(self._zoom * factor, anchor=e.position())

    def mouseDoubleClickEvent(self, e):
        canvas_pos = self._screen_to_canvas(e.position())
        u = self._unit_at(canvas_pos)
        if u:
            self.parent_canvas.open_unit_detail(u)

    def _menu_style(self):
        return (
            f"QMenu{{background:{BG_CARD};border:1px solid {BORDER};border-radius:6px;padding:4px}}"
            f"QMenu::item{{padding:6px 20px;border-radius:4px;color:{TEXT_SECONDARY}}}"
            f"QMenu::item:selected{{background:{BG_HOVER};color:{TEXT_PRIMARY}}}"
            f"QMenu::separator{{height:1px;background:{BORDER};margin:4px 8px}}"
        )

    def _show_menu(self, u, pos):
        m = QMenu(self)
        m.setStyleSheet(self._menu_style())
        a_link = m.addAction("Link to hardware...")
        a_conn = m.addAction("Connect to...")
        a_ren = m.addAction("Rename")

        # Show removable connections for this unit
        conn_actions = []
        if self.network:
            unit_conns = [c for c in self.network.connections
                         if c.source_uid == u.uid or c.target_uid == u.uid]
            if unit_conns:
                m.addSeparator()
                for c in unit_conns:
                    other_uid = c.target_uid if c.source_uid == u.uid else c.source_uid
                    other = next((x for x in self.network.units if x.uid == other_uid), None)
                    other_label = other.label if other else "?"
                    direction = "\u2192" if c.source_uid == u.uid else "\u2190"
                    port = f"  [port {c.target_port}]" if c.target_port else ""
                    a = m.addAction(
                        f"Disconnect {direction} {other_label}{port}")
                    conn_actions.append((a, c))

        # Reassign a router port.
        port_actions = []
        if self.network:
            routed = [
                c for c in self.network.connections
                if (c.source_uid == u.uid or c.target_uid == u.uid)
                and c.target_port is not None
            ]
            if routed:
                m.addSeparator()
                for c in routed:
                    a = m.addAction(f"Change port (currently {c.target_port})...")
                    port_actions.append((a, c))

        m.addSeparator()
        a_del = m.addAction("Remove from canvas")
        choice = m.exec(pos)
        if not choice:
            return
        if choice == a_del:
            self._push_undo()
            self.network.units.remove(u)
            self.network.connections = [
                x for x in self.network.connections
                if x.source_uid != u.uid and x.target_uid != u.uid
            ]
            self._selected_unit = None
            self._save()
        elif choice == a_conn:
            self._connecting_from = u
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif choice == a_ren:
            self._push_undo()
            t, ok = QInputDialog.getText(self, "Rename", "Label:", text=u.label)
            if ok and t.strip():
                u.label = t.strip()
                self._save()
        elif choice == a_link:
            self.parent_canvas.link_hardware(u)
        else:
            for a, c in conn_actions:
                if choice == a:
                    self._push_undo()
                    self.network.connections.remove(c)
                    self._save()
                    return
            for a, c in port_actions:
                if choice != a:
                    continue
                router = next(
                    (x for x in self.network.units if x.uid == c.target_uid), None)
                total = port_count(router.category, router.type_id) if router else 8
                port, ok = QInputDialog.getInt(
                    self, "Router port",
                    f"Port for this line (1-{total}):",
                    value=c.target_port or 1, min=1, max=total)
                if ok:
                    clash = next(
                        (x for x in self.network.connections
                         if x is not c and x.target_uid == c.target_uid
                         and x.target_port == port), None)
                    if clash:
                        QMessageBox.warning(
                            self, "Port in use",
                            f"Port {port} is already claimed by another line.")
                    else:
                        self._push_undo()
                        c.target_port = port
                        self._save()
                return

    def _show_canvas_menu(self, pos):
        m = QMenu(self)
        m.setStyleSheet(self._menu_style())
        a_undo = None
        if self._undo_stack:
            a_undo = m.addAction("Undo")
        a_arrange = None
        if self.network and self.network.units:
            a_arrange = m.addAction("Auto-arrange")
        if not a_undo and not a_arrange:
            return
        choice = m.exec(pos)
        if choice and choice == a_undo:
            self._undo()
        elif choice and choice == a_arrange:
            self._auto_arrange()

    def _auto_arrange(self):
        if not self.network or not self.network.units:
            return
        from environnets.ui.setup_wizard import auto_layout
        reactors = [u for u in self.network.units if u.category == "reactor"]
        if not reactors:
            return
        self._push_undo()
        for reactor in reactors:
            pumps_in, pumps_out, sensors, res_in, res_out = [], [], [], [], []
            for c in self.network.connections:
                other_uid = None
                if c.target_uid == reactor.uid:
                    other_uid = c.source_uid
                    other = next((u for u in self.network.units if u.uid == other_uid), None)
                    if not other:
                        continue
                    if other.category == "pump":
                        pumps_in.append(other)
                    elif other.category == "sensor":
                        sensors.append(other)
                    elif other.category == "reservoir":
                        res_in.append(other)
                elif c.source_uid == reactor.uid:
                    other_uid = c.target_uid
                    other = next((u for u in self.network.units if u.uid == other_uid), None)
                    if not other:
                        continue
                    if other.category == "pump":
                        pumps_out.append(other)
                    elif other.category == "reservoir":
                        res_out.append(other)
            for p in pumps_in:
                for c in self.network.connections:
                    if c.target_uid == p.uid:
                        src = next((u for u in self.network.units if u.uid == c.source_uid), None)
                        if src and src.category == "reservoir" and src not in res_in:
                            res_in.append(src)
            for p in pumps_out:
                for c in self.network.connections:
                    if c.source_uid == p.uid:
                        tgt = next((u for u in self.network.units if u.uid == c.target_uid), None)
                        if tgt and tgt.category == "reservoir" and tgt not in res_out:
                            res_out.append(tgt)
            auto_layout(reactor, pumps_in, pumps_out, sensors, res_in, res_out)
        self._save()

    def _push_undo(self):
        if not self.network:
            return
        snapshot = {
            "units": [asdict(u) for u in self.network.units],
            "connections": [asdict(c) for c in self.network.connections],
        }
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self.MAX_UNDO:
            self._undo_stack.pop(0)

    def _undo(self):
        if not self._undo_stack or not self.network:
            return
        snapshot = self._undo_stack.pop()
        self.network.units = [Unit(**u) for u in snapshot["units"]]
        self.network.connections = [Connection(**c) for c in snapshot["connections"]]
        self.parent_canvas.store.save_network(self.network)

    def _delete_selected(self):
        if not self.network:
            return
        to_delete = set(self._selected_units)
        if self._selected_unit:
            to_delete.add(self._selected_unit)
        if not to_delete:
            return
        self._push_undo()
        del_uids = {u.uid for u in to_delete}
        self.network.units = [u for u in self.network.units if u.uid not in del_uids]
        self.network.connections = [
            c for c in self.network.connections
            if c.source_uid not in del_uids and c.target_uid not in del_uids
        ]
        self._selected_unit = None
        self._selected_units.clear()
        self._save()

    def _select_all(self):
        if self.network:
            self._selected_units = set(self.network.units)
            self._selected_unit = None

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Undo):
            self._undo()
            return
        if e.matches(QKeySequence.StandardKey.SelectAll):
            self._select_all()
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
            return
        if e.key() == Qt.Key.Key_Escape:
            if self._connecting_from:
                self._connecting_from = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self._selected_unit = None
            self._selected_units.clear()
            return
        if e.key() == Qt.Key.Key_Equal and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.set_zoom(self._zoom + ZOOM_STEP)
            return
        if e.key() == Qt.Key.Key_Minus and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.set_zoom(self._zoom - ZOOM_STEP)
            return
        if e.key() == Qt.Key.Key_0 and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.set_zoom(1.0)
            self._pan = QPointF(0, 0)
            return
        super().keyPressEvent(e)

    def _save(self):
        if self.network:
            self.parent_canvas.store.save_network(self.network)

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        if not self.network:
            return
        data = e.mimeData().text()
        try:
            cat, tid = data.split(":", 1)
        except ValueError:
            return

        canvas_pos = self._screen_to_canvas(e.position())

        # A preset drops a whole wired assembly rather than one unit.
        if cat == "preset":
            self._drop_preset(tid, canvas_pos)
            e.acceptProposedAction()
            return

        defn = get_type(cat, tid)
        if not defn:
            return

        if cat == "reactor":
            from environnets.ui.setup_wizard import SetupChoiceDialog, SetupWizard
            choice_dlg = SetupChoiceDialog(tid, parent=self)
            if choice_dlg.exec() != choice_dlg.DialogCode.Accepted:
                return

            if choice_dlg.choice == SetupChoiceDialog.BUILD_UP:
                wizard = SetupWizard(tid, api=self.parent_canvas.api, parent=self)
                if wizard.exec() == wizard.DialogCode.Accepted and wizard.result_units:
                    self._push_undo()
                    ox = canvas_pos.x() - 200
                    oy = canvas_pos.y() - 150
                    for u in wizard.result_units:
                        u.x += ox
                        u.y += oy
                        self.network.units.append(u)
                    self.network.connections.extend(wizard.result_connections)
                    self._save()
                e.acceptProposedAction()
                return

        w, h = default_dims(cat, tid)
        u = Unit(
            uid=f"u-{uuid.uuid4().hex[:6]}",
            kind=cat,
            label=defn["label"],
            x=canvas_pos.x() - w / 2,
            y=canvas_pos.y() - h / 2,
            category=cat,
            type_id=tid,
        )
        self._push_undo()
        self.network.units.append(u)
        self._selected_unit = u
        self._save()
        e.acceptProposedAction()


class PresetItem(QPushButton):
    """Drag this to drop an entire wired assembly."""

    def __init__(self, preset):
        super().__init__(f"  {preset.label}")
        self.preset = preset
        self.setFixedHeight(38)
        self.setToolTip(f"{preset.description}\n\n{preset.summary}")
        self.setStyleSheet(
            f"QPushButton{{text-align:left;padding:6px 10px;"
            f"border:1px solid {ACCENT_DIM};border-radius:6px;font-size:11px;"
            f"font-weight:600;color:#ffffff;background:{BG_CARD}}}"
            f"QPushButton:hover{{border-color:{ACCENT};background:{BG_HOVER}}}"
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            d = QDrag(self)
            mime = QMimeData()
            mime.setText(f"preset:{self.preset.preset_id}")
            d.setMimeData(mime)
            pm = QPixmap(self.size())
            pm.fill(QColor(107, 138, 253, 80))
            d.setPixmap(pm)
            d.exec(Qt.DropAction.CopyAction)


class PaletteItem(QPushButton):
    def __init__(self, category, type_id, defn):
        super().__init__(f"  {defn['label']}")
        self.category = category
        self.type_id = type_id
        self.setFixedHeight(32)
        self.setStyleSheet(
            f"QPushButton{{text-align:left;padding:6px 10px;border:1px solid {BORDER};"
            f"border-radius:6px;font-size:11px;font-weight:500;"
            f"color:#ffffff;background:{BG_CARD}}}"
            f"QPushButton:hover{{border-color:{ACCENT_DIM};color:#ffffff;"
            f"background:{BG_HOVER}}}"
        )
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            d = QDrag(self)
            mime = QMimeData()
            mime.setText(f"{self.category}:{self.type_id}")
            d.setMimeData(mime)
            pm = QPixmap(self.size())
            pm.fill(QColor(107, 138, 253, 50))
            d.setPixmap(pm)
            d.exec(Qt.DropAction.CopyAction)


class UnitPalette(QFrame):
    def __init__(self, canvas_widget):
        super().__init__()
        self.canvas_widget = canvas_widget
        self.setMinimumWidth(170)
        self.setMaximumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background:{BG_PANEL};border-right:1px solid {BORDER}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea{{background:transparent;border:none}}"
            f"QScrollBar:vertical{{background:{BG_PANEL};width:5px;border-radius:2px}}"
            f"QScrollBar::handle:vertical{{background:{BORDER_HOVER};border-radius:2px;min-height:30px}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0}}"
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(4)

        def header(text):
            hdr = QLabel(text)
            hdr.setStyleSheet(
                f"font-size:10px;font-weight:600;color:#ffffff;padding-top:8px;"
                f"padding-bottom:2px;text-transform:uppercase;letter-spacing:0.5px"
            )
            layout.addWidget(hdr)

        # Complete setups first - the fastest way onto a working canvas.
        header("Setups")
        for preset in list_presets():
            layout.addWidget(PresetItem(preset))
        sub = QLabel("Drops a full wired setup.")
        sub.setStyleSheet(f"font-size:9px;color:{TEXT_MUTED};padding-bottom:2px")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        for cat_label, cat_key in CATEGORY_ORDER:
            header(cat_label)
            for tid, defn in list_types(cat_key):
                layout.addWidget(PaletteItem(cat_key, tid, defn))

        layout.addStretch()
        hint = QLabel("Drag units onto the canvas.\nDraw a box to select multiple.\nRight-click for options.")
        hint.setStyleSheet(f"font-size:9px;color:{TEXT_MUTED};padding-top:6px")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll.setWidget(content)
        outer.addWidget(scroll)


class NetworkCanvas(QWidget):
    def __init__(self, api, store):
        super().__init__()
        self.api = api
        self.store = store
        self.network = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._cw = CanvasWidget(self)
        self._palette = UnitPalette(self._cw)
        layout.addWidget(self._palette)

        canvas_col = QVBoxLayout()
        canvas_col.setContentsMargins(0, 0, 0, 0)
        canvas_col.setSpacing(0)
        canvas_col.addWidget(self._cw, 1)

        zoom_bar = QFrame()
        zoom_bar.setFixedHeight(28)
        zoom_bar.setStyleSheet(
            f"QFrame{{background:{BG_PANEL};border-top:1px solid {BORDER}}}"
            f"QLabel{{border:none;background:transparent}}"
        )
        zl = QHBoxLayout(zoom_bar)
        zl.setContentsMargins(8, 0, 8, 0)
        zl.setSpacing(6)

        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedSize(22, 22)
        zoom_out_btn.setStyleSheet(
            f"QPushButton{{font-size:14px;padding:0;border-radius:4px;"
            f"border:1px solid {BORDER};background:{BG_CARD};color:{TEXT_SECONDARY}}}"
            f"QPushButton:hover{{background:{BG_HOVER};color:{TEXT_PRIMARY}}}"
        )
        zoom_out_btn.clicked.connect(lambda: self._cw.set_zoom(self._cw._zoom - ZOOM_STEP))
        zl.addWidget(zoom_out_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet(f"font-size:10px;color:{TEXT_MUTED}")
        zl.addWidget(self._zoom_label)

        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(22, 22)
        zoom_in_btn.setStyleSheet(
            f"QPushButton{{font-size:14px;padding:0;border-radius:4px;"
            f"border:1px solid {BORDER};background:{BG_CARD};color:{TEXT_SECONDARY}}}"
            f"QPushButton:hover{{background:{BG_HOVER};color:{TEXT_PRIMARY}}}"
        )
        zoom_in_btn.clicked.connect(lambda: self._cw.set_zoom(self._cw._zoom + ZOOM_STEP))
        zl.addWidget(zoom_in_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.setFixedHeight(22)
        reset_btn.setStyleSheet(
            f"QPushButton{{font-size:10px;padding:0 8px;border-radius:4px;"
            f"border:1px solid {BORDER};background:{BG_CARD};color:{TEXT_MUTED}}}"
            f"QPushButton:hover{{background:{BG_HOVER};color:{TEXT_PRIMARY}}}"
        )
        reset_btn.clicked.connect(self._reset_zoom)
        zl.addWidget(reset_btn)

        zl.addStretch()

        hint = QLabel("Scroll to zoom  ·  Middle-click to pan  ·  Shift+click for multi-select")
        hint.setStyleSheet(f"font-size:10px;color:{TEXT_MUTED}")
        zl.addWidget(hint)

        canvas_col.addWidget(zoom_bar)
        layout.addLayout(canvas_col, 1)

    def _update_zoom_label(self):
        pct = int(self._cw._zoom * 100)
        self._zoom_label.setText(f"{pct}%")

    def _reset_zoom(self):
        self._cw._zoom = 1.0
        self._cw._pan = QPointF(0, 0)
        self._update_zoom_label()

    def load_network(self, net):
        self.network = net
        self._cw.update()

    def open_unit_detail(self, unit):
        if not unit.pioreactor_unit:
            QMessageBox.information(self, "Not linked",
                "Right-click > Link to hardware first.")
            return
        from environnets.ui.unit_detail import UnitDetailDialog
        exp_name = getattr(self, "current_experiment_name", "Demo experiment")
        dlg = UnitDetailDialog(self.api, exp_name, unit, self)
        dlg.exec()

    def link_hardware(self, unit):
        workers = self.api.get_workers() or []
        active = [w for w in workers if w.get("is_active")]
        already_linked = set()
        if self.network:
            already_linked = {u.pioreactor_unit for u in self.network.units if u.pioreactor_unit}
        items = []
        for w in active:
            name = w["pioreactor_unit"]
            tag = " (in use)" if name in already_linked and name != unit.pioreactor_unit else ""
            items.append(f"{name}{tag}")
        if unit.pioreactor_unit:
            items.insert(0, f"[Unlink] {unit.pioreactor_unit}")
        if not items:
            QMessageBox.warning(self, "No hardware",
                "No active workers found.\nCheck your Pioreactor connection.")
            return
        choice, ok = QInputDialog.getItem(
            self, "Link to hardware",
            f"Assign \"{unit.label}\" to a Pioreactor worker:", items, 0, False)
        if not ok or not choice:
            return
        if choice.startswith("[Unlink]"):
            unit.pioreactor_unit = ""
            unit.status = "disconnected"
        else:
            name = choice.replace(" (in use)", "")
            unit.pioreactor_unit = name
            unit.status = "idle"
        self.store.save_network(self.network)
