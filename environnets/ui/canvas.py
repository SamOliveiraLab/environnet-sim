"""Network canvas with drag-and-drop and animated cartoons."""

import copy
import uuid
from dataclasses import asdict
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QMimeData, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPainterPath,
    QMouseEvent, QDrag, QPixmap, QKeySequence, QShortcut,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QMenu, QInputDialog, QMessageBox,
)

from environnets.core.models import Unit, Connection
from environnets.core.unit_types import default_dims, list_types, get_type
from environnets.ui.cartoons import draw_unit, draw_status_glow
from environnets.ui.theme import (
    ACCENT, ACCENT_DIM, TEXT_SECONDARY, TEXT_MUTED, TEXT_PRIMARY,
    BG_CARD, BG_DARK, BG_PANEL, BG_INPUT, BG_HOVER, BORDER, BORDER_HOVER,
)


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
        self._connecting_from = None
        self._mouse_pos = QPointF(0, 0)
        self._phase = 0.0
        self._grid = 20
        self._undo_stack: list[dict] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _tick(self):
        self._phase = (self._phase + 0.015) % 1.0
        self.update()

    @property
    def network(self):
        return self.parent_canvas.network

    def paintEvent(self, e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(self.rect(), QColor(BG_DARK))

            p.setPen(QPen(QColor(BORDER), 1))
            for x in range(0, self.width(), self._grid):
                for y in range(0, self.height(), self._grid):
                    p.drawPoint(x, y)

            if not self.network:
                p.setPen(QPen(QColor(TEXT_MUTED)))
                p.setFont(QFont("Inter", 13))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                           "Drag units from the palette\nto build your bioreactor network")
                return

            for c in self.network.connections:
                self._draw_tubing(p, c)

            if self._connecting_from:
                u = self._connecting_from
                w, h = default_dims(u.category, u.type_id)
                p.setPen(QPen(QColor(ACCENT_DIM), 2, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(u.x + w / 2, u.y + h / 2), self._mouse_pos)

            for u in self.network.units:
                draw_status_glow(p, u, self._phase)
                draw_unit(p, u, self._phase)

            if self._selected_unit and self._selected_unit in self.network.units:
                su = self._selected_unit
                sw, sh = default_dims(su.category, su.type_id)
                p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(su.x - 6, su.y - 6, sw + 12, sh + 12), 8, 8)
        finally:
            p.end()

    def _draw_tubing(self, p, conn):
        src = next((u for u in self.network.units if u.uid == conn.source_uid), None)
        tgt = next((u for u in self.network.units if u.uid == conn.target_uid), None)
        if not src or not tgt:
            return
        sw, sh = default_dims(src.category, src.type_id)
        tw, th = default_dims(tgt.category, tgt.type_id)
        sx, sy = src.x + sw / 2, src.y + sh / 2
        tx, ty = tgt.x + tw / 2, tgt.y + th / 2

        path = QPainterPath()
        path.moveTo(sx, sy)
        mx = (sx + tx) / 2
        path.cubicTo(mx, sy, mx, ty, tx, ty)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(30, 30, 38), 7))
        p.drawPath(path)
        p.setPen(QPen(QColor(100, 105, 120), 3))
        p.drawPath(path)
        p.setPen(QPen(QColor(140, 150, 170, 100), 1))
        p.drawPath(path)

        if src.status == "running" or tgt.status == "running":
            p.setBrush(QBrush(QColor(140, 165, 210)))
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(3):
                t = (self._phase + i / 3) % 1.0
                pt = path.pointAtPercent(t)
                p.drawEllipse(pt, 3, 3)

    def _unit_at(self, pos):
        if not self.network:
            return None
        for u in reversed(self.network.units):
            w, h = default_dims(u.category, u.type_id)
            if QRectF(u.x, u.y, w, h).contains(pos):
                return u
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        u = self._unit_at(pos)
        if e.button() == Qt.MouseButton.LeftButton:
            if u and self._connecting_from and u != self._connecting_from:
                self._push_undo()
                self.network.connections.append(
                    Connection(source_uid=self._connecting_from.uid, target_uid=u.uid))
                self._connecting_from = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self._save()
                return
            self._selected_unit = u
            if u:
                self._dragging_unit = u
                self._drag_offset = QPointF(pos.x() - u.x, pos.y() - u.y)
            elif self._connecting_from:
                self._connecting_from = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif e.button() == Qt.MouseButton.RightButton:
            if u:
                self._selected_unit = u
                self._show_menu(u, e.globalPosition().toPoint())
            else:
                self._show_canvas_menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        self._mouse_pos = e.position()
        if self._dragging_unit:
            self._dragging_unit.x = e.position().x() - self._drag_offset.x()
            self._dragging_unit.y = e.position().y() - self._drag_offset.y()
        else:
            self._hover_unit = self._unit_at(e.position())

    def mouseReleaseEvent(self, e):
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

    def mouseDoubleClickEvent(self, e):
        u = self._unit_at(e.position())
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
                    a = m.addAction(f"Disconnect {direction} {other_label}")
                    conn_actions.append((a, c))

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
                    break

    def _show_canvas_menu(self, pos):
        if not self._undo_stack:
            return
        m = QMenu(self)
        m.setStyleSheet(self._menu_style())
        a_undo = m.addAction("Undo")
        if m.exec(pos) == a_undo:
            self._undo()

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
        if not self._selected_unit or not self.network:
            return
        u = self._selected_unit
        self._push_undo()
        self.network.units.remove(u)
        self.network.connections = [
            x for x in self.network.connections
            if x.source_uid != u.uid and x.target_uid != u.uid
        ]
        self._selected_unit = None
        self._save()

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Undo):
            self._undo()
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
            return
        if e.key() == Qt.Key.Key_Escape:
            if self._connecting_from:
                self._connecting_from = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self._selected_unit = None
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
        defn = get_type(cat, tid)
        if not defn:
            return
        pos = e.position()
        w, h = default_dims(cat, tid)
        u = Unit(
            uid=f"u-{uuid.uuid4().hex[:6]}",
            kind=cat,
            label=defn["label"],
            x=pos.x() - w / 2,
            y=pos.y() - h / 2,
            category=cat,
            type_id=tid,
        )
        self._push_undo()
        self.network.units.append(u)
        self._selected_unit = u
        self._save()
        e.acceptProposedAction()


class PaletteItem(QPushButton):
    def __init__(self, category, type_id, defn):
        super().__init__(f"  {defn['label']}")
        self.category = category
        self.type_id = type_id
        self.setStyleSheet(
            f"QPushButton{{text-align:left;padding:8px 12px;border:1px solid {BORDER};"
            f"border-radius:6px;font-size:11px;color:{TEXT_SECONDARY};background:{BG_CARD}}}"
            f"QPushButton:hover{{border-color:{BORDER_HOVER};color:{TEXT_PRIMARY};background:{BG_HOVER}}}"
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
        self.setMinimumWidth(160)
        self.setMaximumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(f"background:{BG_PANEL};border-right:1px solid {BORDER}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(5)

        for cat_label, cat_key in [("Reactors", "reactor"), ("Pumps", "pump"), ("Sensors", "sensor")]:
            hdr = QLabel(cat_label)
            hdr.setStyleSheet(
                f"font-size:11px;font-weight:500;color:{TEXT_SECONDARY};padding-top:8px;padding-bottom:2px"
            )
            layout.addWidget(hdr)
            for tid, defn in list_types(cat_key):
                layout.addWidget(PaletteItem(cat_key, tid, defn))

        layout.addStretch()
        hint = QLabel("Drag units onto\nthe canvas.\n\nRight-click for\noptions.")
        hint.setStyleSheet(f"font-size:10px;color:{TEXT_MUTED};padding-top:8px")
        hint.setWordWrap(True)
        layout.addWidget(hint)


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
        layout.addWidget(self._cw, 1)

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
        active = [w["pioreactor_unit"] for w in workers if w.get("is_active")]
        if not active:
            QMessageBox.warning(self, "No hardware", "No active workers found. Check your connection.")
            return
        choice, ok = QInputDialog.getItem(
            self, "Link to hardware", "Assign this unit to:", active, 0, False
        )
        if ok and choice:
            unit.pioreactor_unit = choice
            unit.status = "idle"
            self.store.save_network(self.network)
