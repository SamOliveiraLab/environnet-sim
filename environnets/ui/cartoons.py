"""Cartoon drawing for canvas units.

Each function draws a recognizable illustration of a piece of hardware
using QPainter primitives. No image files, all vector.

Functions receive: painter, x, y, w, h, unit, phase (0..1 for animations).
"""

import math
from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath, QLinearGradient, QFont

GLASS = QColor(160, 185, 210, 50)
LIQUID = QColor(70, 140, 170, 130)
METAL = QColor(120, 128, 145)
METAL_DARK = QColor(50, 55, 70)
BODY = QColor(35, 38, 50)
TUBE = QColor(170, 178, 195, 160)
CELL = QColor(110, 185, 140, 200)
ACCENT_C = QColor(107, 138, 253)
WARNING = QColor(184, 149, 64)


def _text(p: QPainter, x: float, y: float, w: float, text: str, size: int = 10, color=QColor(200, 200, 210)):
    p.setPen(QPen(color))
    f = QFont("Inter", size, QFont.Weight.Medium)
    p.setFont(f)
    p.drawText(QRectF(x, y, w, 18), Qt.AlignmentFlag.AlignCenter, text)


# -- REACTORS --------------------------------------------------------------

def draw_pio_vial(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Pioreactor: black housing with a glass vial poking out the top,
    liquid inside, stir bar spinning at the bottom, tiny cells floating."""
    # Housing (black box around the vial)
    housing = QRectF(x + w * 0.15, y + h * 0.35, w * 0.7, h * 0.55)
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    path = QPainterPath()
    path.addRoundedRect(housing, 6, 6)
    p.drawPath(path)

    # Little LED dot on housing
    led_r = 2.5
    led_color = ACCENT_C if unit.status == "running" else QColor(60, 68, 85)
    p.setBrush(QBrush(led_color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(x + w * 0.22, y + h * 0.45), led_r, led_r)
    p.drawEllipse(QPointF(x + w * 0.78, y + h * 0.45), led_r, led_r)

    # Glass vial sticking out top
    vial_x = x + w * 0.32
    vial_y = y + h * 0.1
    vial_w = w * 0.36
    vial_h = h * 0.5
    vial_rect = QRectF(vial_x, vial_y, vial_w, vial_h)
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1))
    p.drawRoundedRect(vial_rect, 4, 4)

    # Liquid fill — color shifts with OD (turbidity), animated wave surface
    od = getattr(unit, "last_od", 0.0) or 0.0
    liquid_h = vial_h * 0.7
    liquid_top = vial_y + vial_h - liquid_h
    turbidity = min(1.0, od / 2.0)
    liq_r = int(70 + turbidity * 80)
    liq_g = int(140 - turbidity * 40)
    liq_b = int(170 - turbidity * 60)
    liq_a = int(130 + turbidity * 80)
    liq_color = QColor(liq_r, liq_g, liq_b, liq_a)

    lx = vial_x + 1
    lw = vial_w - 2
    lb = vial_y + vial_h - 2

    if unit.status == "running":
        wave_amp = 1.5 + turbidity * 1.0
        wave_path = QPainterPath()
        wave_path.moveTo(lx, lb)
        wave_path.lineTo(lx, liquid_top)
        steps = 12
        for i in range(steps + 1):
            frac = i / steps
            wx = lx + frac * lw
            wy = liquid_top + wave_amp * math.sin(phase * 2 * math.pi * 3 + frac * math.pi * 4)
            if i == 0:
                wave_path.lineTo(wx, wy)
            else:
                wave_path.lineTo(wx, wy)
        wave_path.lineTo(lx + lw, lb)
        wave_path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(liq_color))
        p.drawPath(wave_path)
        hi_color = QColor(liq_r + 30, liq_g + 20, liq_b + 10, 40)
        hi_rect = QRectF(lx + lw * 0.15, liquid_top + 2, lw * 0.3, liquid_h * 0.4)
        p.setBrush(QBrush(hi_color))
        p.drawRoundedRect(hi_rect, 3, 3)
    else:
        liquid_rect = QRectF(lx, liquid_top, lw, liquid_h - 2)
        p.setBrush(QBrush(liq_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(liquid_rect, 2, 2)

    # Cells floating — use sim cells if available, else derive from OD
    sim_cells = getattr(unit, "_sim_cells", None)
    if sim_cells and unit.status == "running":
        p.setBrush(QBrush(CELL))
        p.setPen(Qt.PenStyle.NoPen)
        for c in sim_cells:
            cx = vial_x + c["x"] * vial_w
            cy = liquid_top + (c["y"] - 0.25) / 0.65 * liquid_h
            r = 1.2 * c.get("size", 1.0)
            p.drawEllipse(QPointF(cx, cy), r, r * 0.8)
    elif unit.status in ("running", "idle") and od > 0.05:
        cell_count = int(min(40, od * 18))
        p.setBrush(QBrush(CELL))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(cell_count):
            cx = vial_x + 4 + ((i * 7 + phase * 20) % (vial_w - 8))
            cy = liquid_top + 6 + ((i * 11 + phase * 15) % (liquid_h - 12))
            p.drawEllipse(QPointF(cx, cy), 1.5, 1.2)

    # OD reading overlay
    if unit.status == "running" and od > 0:
        od_text = f"OD {od:.2f}"
        p.setPen(QPen(QColor(200, 220, 255, 200)))
        f = QFont("Inter", 7, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(vial_x, vial_y + 2, vial_w, 12),
                   Qt.AlignmentFlag.AlignCenter, od_text)

    # Stir bar (spinning ellipse at bottom of liquid)
    sb_cx = vial_x + vial_w / 2
    sb_cy = vial_y + vial_h - 8
    angle = phase * 2 * math.pi if unit.status == "running" else 0
    p.save()
    p.translate(sb_cx, sb_cy)
    p.rotate(math.degrees(angle))
    p.setBrush(QBrush(QColor(255, 255, 255)))
    p.setPen(QPen(METAL, 0.5))
    p.drawRoundedRect(QRectF(-vial_w * 0.3, -1.5, vial_w * 0.6, 3), 1.5, 1.5)
    p.restore()

    # Label
    _text(p, x, y + h - 16, w, unit.label or "Bioreactor", 10)


def draw_microfluidic(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Microfluidic chamber: a rectangle with inlet/outlet channels and wavy channels inside."""
    body = QRectF(x + 10, y + 20, w - 20, h - 40)
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.5))
    p.drawRoundedRect(body, 4, 4)

    # Inlet/outlet ports
    p.setBrush(QBrush(METAL_DARK))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(x + 10, y + h / 2), 4, 4)
    p.drawEllipse(QPointF(x + w - 10, y + h / 2), 4, 4)

    # Internal serpentine channel
    p.setPen(QPen(LIQUID, 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(x + 14, y + h / 2)
    for i in range(4):
        cx = x + 14 + (i + 1) * (w - 28) / 5
        cy = y + h / 2 + (15 if i % 2 == 0 else -15)
        path.quadTo(cx - 10, cy, cx, y + h / 2)
    path.lineTo(x + w - 14, y + h / 2)
    p.drawPath(path)

    _text(p, x, y + h - 18, w, unit.label or "Microfluidic", 10)


def draw_stirred_tank(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Larger stirred tank: tall cylinder with impeller inside."""
    tank = QRectF(x + w * 0.2, y + 15, w * 0.6, h - 35)
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.5))
    p.drawRoundedRect(tank, 8, 8)

    # Liquid
    liq = QRectF(tank.x() + 2, tank.y() + tank.height() * 0.35, tank.width() - 4, tank.height() * 0.63)
    p.setBrush(QBrush(LIQUID))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(liq)

    # Impeller shaft from top
    p.setPen(QPen(METAL, 2))
    shaft_x = tank.x() + tank.width() / 2
    p.drawLine(QPointF(shaft_x, tank.y()), QPointF(shaft_x, tank.y() + tank.height() * 0.7))

    # Impeller blades (rotating)
    angle = phase * 2 * math.pi if unit.status == "running" else 0
    p.save()
    p.translate(shaft_x, tank.y() + tank.height() * 0.7)
    p.rotate(math.degrees(angle))
    p.setBrush(QBrush(METAL))
    p.drawRect(QRectF(-tank.width() * 0.35, -1.5, tank.width() * 0.7, 3))
    p.restore()

    _text(p, x, y + h - 16, w, unit.label or "Stirred tank", 10)


# -- PUMPS -----------------------------------------------------------------

def draw_peristaltic(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Peristaltic pump: round rotor with 3 rollers, tube wrapping around it."""
    cx = x + w / 2
    cy = y + h * 0.45
    radius = min(w, h) * 0.3

    # Housing
    housing = QRectF(x + 8, y + 10, w - 16, h - 30)
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(housing, 6, 6)

    # Tube wrapping around rotor
    tube_r = radius + 8
    p.setPen(QPen(TUBE, 4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(cx - tube_r, cy - tube_r, tube_r * 2, tube_r * 2), 30 * 16, 300 * 16)

    # Tube tails
    p.drawLine(QPointF(cx - tube_r * 0.87, cy + tube_r * 0.5), QPointF(cx - tube_r - 4, cy + tube_r * 0.5 + 6))
    p.drawLine(QPointF(cx + tube_r * 0.87, cy + tube_r * 0.5), QPointF(cx + tube_r + 4, cy + tube_r * 0.5 + 6))

    # Rotor circle
    p.setBrush(QBrush(METAL))
    p.setPen(QPen(METAL_DARK, 1))
    p.drawEllipse(QPointF(cx, cy), radius, radius)

    # Rollers (3 small circles, rotating)
    angle = phase * 2 * math.pi if unit.status == "running" else 0
    for i in range(3):
        a = angle + i * (2 * math.pi / 3)
        rx = cx + radius * 0.7 * math.cos(a)
        ry = cy + radius * 0.7 * math.sin(a)
        p.setBrush(QBrush(QColor(220, 220, 230)))
        p.drawEllipse(QPointF(rx, ry), 3, 3)

    # Center pin
    p.setBrush(QBrush(METAL_DARK))
    p.drawEllipse(QPointF(cx, cy), 2, 2)

    _text(p, x, y + h - 16, w, unit.label or "Peristaltic", 9)


def draw_syringe(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float, dual: bool = False):
    """Syringe pump: one or two horizontal syringes with plungers."""
    n = 2 if dual else 1
    syr_h = (h - 30) / n - 4
    for i in range(n):
        sy = y + 10 + i * (syr_h + 6)
        # Barrel
        barrel = QRectF(x + 20, sy, w - 40, syr_h)
        p.setBrush(QBrush(GLASS))
        p.setPen(QPen(METAL, 1.2))
        p.drawRect(barrel)

        # Plunger (moves with phase)
        plunge_offset = (w - 50) * (0.5 + 0.3 * math.sin(phase * 2 * math.pi + i * math.pi))
        if unit.status != "running":
            plunge_offset = (w - 50) * 0.5
        plunger = QRectF(x + 20 + plunge_offset, sy + 2, 6, syr_h - 4)
        p.setBrush(QBrush(METAL_DARK))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(plunger)

        # Liquid in barrel (ahead of plunger)
        liq = QRectF(x + 20 + plunge_offset + 6, sy + 3, w - 40 - plunge_offset - 8, syr_h - 6)
        p.setBrush(QBrush(LIQUID))
        p.drawRect(liq)

        # Nozzle
        p.setBrush(QBrush(METAL))
        p.drawRect(QRectF(x + w - 20, sy + syr_h / 2 - 1.5, 8, 3))

        # Plunger handle
        p.setBrush(QBrush(METAL_DARK))
        p.drawRect(QRectF(x + 12, sy + syr_h / 2 - 4, 8, 8))

    _text(p, x, y + h - 16, w, unit.label or ("Dual syringe" if dual else "Syringe"), 9)


def draw_dual_syringe(p, x, y, w, h, unit, phase):
    draw_syringe(p, x, y, w, h, unit, phase, dual=True)


def draw_diaphragm(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Diaphragm pump: dome chamber that pulses."""
    cx = x + w / 2
    cy = y + h * 0.5
    pulse = 1.0 + 0.1 * math.sin(phase * 2 * math.pi) if unit.status == "running" else 1.0

    # Body
    body = QRectF(x + 10, y + 15, w - 20, h - 35)
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(body, 6, 6)

    # Dome
    dome_w = (w - 30) * pulse
    dome_h = 25 * pulse
    dome = QRectF(cx - dome_w / 2, cy - dome_h / 2, dome_w, dome_h)
    p.setBrush(QBrush(QColor(100, 120, 150)))
    p.setPen(QPen(METAL, 1))
    p.drawEllipse(dome)

    # Inlet/outlet
    p.setPen(QPen(TUBE, 3))
    p.drawLine(QPointF(x + 4, cy), QPointF(x + 14, cy))
    p.drawLine(QPointF(x + w - 4, cy), QPointF(x + w - 14, cy))

    _text(p, x, y + h - 16, w, unit.label or "Diaphragm", 9)


def draw_custom_pump(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    body = QRectF(x + 8, y + 10, w - 16, h - 30)
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(body, 6, 6)
    # Arrow showing flow
    p.setPen(QPen(ACCENT_C, 2.5))
    cy = y + h * 0.45
    p.drawLine(QPointF(x + 20, cy), QPointF(x + w - 20, cy))
    p.drawLine(QPointF(x + w - 24, cy - 4), QPointF(x + w - 20, cy))
    p.drawLine(QPointF(x + w - 24, cy + 4), QPointF(x + w - 20, cy))
    _text(p, x, y + h - 16, w, unit.label or "Pump", 9)


# -- SENSORS ---------------------------------------------------------------

def draw_probe(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float, color=ACCENT_C):
    """Generic probe: body with display face and a dipstick."""
    # Body
    body = QRectF(x + w * 0.2, y + 10, w * 0.6, h * 0.45)
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(body, 4, 4)

    # Display face
    face = QRectF(body.x() + 4, body.y() + 4, body.width() - 8, body.height() * 0.55)
    p.setBrush(QBrush(QColor(30, 45, 35) if unit.status == "running" else QColor(20, 25, 35)))
    p.setPen(QPen(METAL, 0.5))
    p.drawRoundedRect(face, 2, 2)

    # Reading display
    reading = getattr(unit, "_sim_reading", None)
    if reading is not None:
        p.setPen(QPen(QColor(120, 220, 160), 1))
        f = QFont("Inter", 7, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(face, Qt.AlignmentFlag.AlignCenter, f"{reading:.1f}")
    elif unit.status == "running":
        p.setPen(QPen(color, 1.2))
        nx = face.x() + face.width() / 2
        ny = face.y() + face.height() - 2
        ang = math.radians(-45 + 90 * (0.5 + 0.3 * math.sin(phase * 2 * math.pi)))
        p.drawLine(QPointF(nx, ny), QPointF(nx + 10 * math.cos(ang), ny + 10 * math.sin(ang)))

    # Probe shaft dipping down
    p.setPen(QPen(METAL, 2.5))
    shaft_x = x + w / 2
    p.drawLine(QPointF(shaft_x, body.y() + body.height()), QPointF(shaft_x, y + h - 22))
    # Probe tip
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(shaft_x, y + h - 22), 3, 3)

    _text(p, x, y + h - 16, w, unit.label or "Sensor", 9)


def draw_od(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(100, 220, 140))
def draw_temp(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(240, 120, 80))
def draw_ph(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(180, 120, 220))
def draw_co2(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(80, 180, 240))
def draw_do2(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(0, 200, 180))
def draw_spec(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(255, 200, 80))
def draw_custom_sensor(p, x, y, w, h, u, ph): draw_probe(p, x, y, w, h, u, ph, QColor(180, 180, 200))


# -- RESERVOIRS ------------------------------------------------------------

def draw_media_bottle(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Media bottle: tall bottle with cap, filled with clear/blue media."""
    # Bottle neck
    neck_w = w * 0.22
    neck_h = h * 0.12
    neck_x = x + w / 2 - neck_w / 2
    neck_y = y + 8
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.2))
    p.drawRect(QRectF(neck_x, neck_y, neck_w, neck_h))

    # Cap
    cap_w = neck_w + 6
    p.setBrush(QBrush(METAL_DARK))
    p.setPen(QPen(METAL, 0.8))
    p.drawRoundedRect(QRectF(x + w / 2 - cap_w / 2, y + 4, cap_w, 8), 2, 2)

    # Bottle body (wider, rounded bottom)
    body_y = neck_y + neck_h
    body_h = h - neck_h - 28
    body = QRectF(x + w * 0.15, body_y, w * 0.7, body_h)
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.2))

    path = QPainterPath()
    path.moveTo(neck_x, body_y)
    path.lineTo(x + w * 0.15, body_y + body_h * 0.15)
    path.lineTo(x + w * 0.15, body_y + body_h)
    path.quadTo(x + w * 0.15, body_y + body_h + 6, x + w * 0.22, body_y + body_h + 6)
    path.lineTo(x + w * 0.78, body_y + body_h + 6)
    path.quadTo(x + w * 0.85, body_y + body_h + 6, x + w * 0.85, body_y + body_h)
    path.lineTo(x + w * 0.85, body_y + body_h * 0.15)
    path.lineTo(neck_x + neck_w, body_y)
    path.closeSubpath()
    p.drawPath(path)

    # Liquid fill — level tracks sim reading (media remaining)
    reading = getattr(unit, "_sim_reading", None)
    max_vol = 500.0
    fill_frac = max(0.02, min(0.92, (reading / max_vol) if reading is not None else 0.75))
    fill_h = body_h * fill_frac
    fill_y = body_y + body_h - fill_h + 4
    liq = QRectF(x + w * 0.17, fill_y, w * 0.66, fill_h)
    p.setBrush(QBrush(QColor(80, 150, 200, 120)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(liq, 2, 2)

    # Animated drips rising through neck when running
    if unit.status == "running" and reading is not None and reading < max_vol:
        drop_color = QColor(80, 150, 200, 200)
        p.setPen(Qt.PenStyle.NoPen)
        drop_x = x + w / 2
        neck_top = neck_y
        neck_bot = neck_y + neck_h
        for i in range(3):
            drop_t = (phase * 3 + i * 0.33) % 1.0
            drop_y = neck_bot - drop_t * (neck_h + 14)
            r = 3.0 * (1.0 - drop_t * 0.3)
            p.setBrush(QBrush(drop_color))
            p.drawEllipse(QPointF(drop_x + (i - 1) * 3, drop_y), r, r * 1.3)

    _text(p, x, y + h - 16, w, unit.label or "Media", 9)


def draw_waste_bottle(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Waste bottle: same shape as media but with murky brownish liquid."""
    neck_w = w * 0.22
    neck_h = h * 0.12
    neck_x = x + w / 2 - neck_w / 2
    neck_y = y + 8
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.2))
    p.drawRect(QRectF(neck_x, neck_y, neck_w, neck_h))

    cap_w = neck_w + 6
    p.setBrush(QBrush(METAL_DARK))
    p.setPen(QPen(METAL, 0.8))
    p.drawRoundedRect(QRectF(x + w / 2 - cap_w / 2, y + 4, cap_w, 8), 2, 2)

    body_y = neck_y + neck_h
    body_h = h - neck_h - 28

    path = QPainterPath()
    path.moveTo(neck_x, body_y)
    path.lineTo(x + w * 0.15, body_y + body_h * 0.15)
    path.lineTo(x + w * 0.15, body_y + body_h)
    path.quadTo(x + w * 0.15, body_y + body_h + 6, x + w * 0.22, body_y + body_h + 6)
    path.lineTo(x + w * 0.78, body_y + body_h + 6)
    path.quadTo(x + w * 0.85, body_y + body_h + 6, x + w * 0.85, body_y + body_h)
    path.lineTo(x + w * 0.85, body_y + body_h * 0.15)
    path.lineTo(neck_x + neck_w, body_y)
    path.closeSubpath()
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.2))
    p.drawPath(path)

    # Waste liquid — level tracks sim reading (waste collected)
    reading = getattr(unit, "_sim_reading", None)
    max_vol = 500.0
    fill_frac = max(0.02, min(0.92, (reading / max_vol) if reading is not None else 0.05))
    fill_h = body_h * fill_frac
    fill_y = body_y + body_h - fill_h + 4
    liq = QRectF(x + w * 0.17, fill_y, w * 0.66, fill_h)
    p.setBrush(QBrush(QColor(140, 110, 70, 130)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(liq, 2, 2)

    # Animated drips falling into the bottle when running
    if unit.status == "running" and reading is not None and reading > 0:
        drop_color = QColor(160, 120, 75, 200)
        p.setPen(Qt.PenStyle.NoPen)
        drop_x = x + w / 2
        neck_bottom = neck_y + neck_h
        drop_zone = fill_y - neck_bottom
        if drop_zone > 6:
            for i in range(3):
                drop_t = (phase * 3 + i * 0.33) % 1.0
                drop_y = neck_bottom + 4 + drop_t * (drop_zone - 8)
                r = 3.5 * (1.0 - drop_t * 0.4)
                p.setBrush(QBrush(drop_color))
                p.drawEllipse(QPointF(drop_x + (i - 1) * 5, drop_y), r, r * 1.4)
            # Splash ring at liquid surface
            splash_t = (phase * 3) % 1.0
            if splash_t > 0.8:
                splash_r = 6 + (splash_t - 0.8) * 40
                splash_a = int(120 * (1.0 - (splash_t - 0.8) * 5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(160, 120, 75, splash_a), 1.5))
                p.drawEllipse(QPointF(drop_x, fill_y), splash_r, splash_r * 0.3)

    _text(p, x, y + h - 16, w, unit.label or "Waste", 9)


def draw_reagent_bottle(p: QPainter, x: float, y: float, w: float, h: float, unit, phase: float):
    """Reagent bottle: smaller bottle with colored liquid."""
    neck_w = w * 0.24
    neck_h = h * 0.1
    neck_x = x + w / 2 - neck_w / 2
    neck_y = y + 8
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.2))
    p.drawRect(QRectF(neck_x, neck_y, neck_w, neck_h))

    cap_w = neck_w + 4
    p.setBrush(QBrush(QColor(180, 60, 60)))
    p.setPen(QPen(METAL, 0.8))
    p.drawRoundedRect(QRectF(x + w / 2 - cap_w / 2, y + 4, cap_w, 7), 2, 2)

    body_y = neck_y + neck_h
    body_h = h - neck_h - 24
    body = QRectF(x + w * 0.18, body_y, w * 0.64, body_h)
    p.setBrush(QBrush(GLASS))
    p.setPen(QPen(METAL, 1.2))
    p.drawRoundedRect(body, 4, 4)

    # Colored reagent (green/yellow)
    fill_h = body_h * 0.6
    fill_y = body_y + body_h - fill_h - 1
    liq = QRectF(x + w * 0.2, fill_y, w * 0.6, fill_h)
    p.setBrush(QBrush(QColor(120, 190, 90, 130)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(liq, 2, 2)

    _text(p, x, y + h - 14, w, unit.label or "Reagent", 9)


# -- registry --------------------------------------------------------------

# -- routing ---------------------------------------------------------------

def draw_selector(p: QPainter, x, y, w, h, unit, phase):
    """8-port rotary selector. The live port lights up; the rest sit dark."""
    ports = get_type(unit.category, unit.type_id).get("ports", 8)
    active = (unit.config or {}).get("active_port")

    # contact shadow so the manifold sits on the bench
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 80)))
    p.drawEllipse(QRectF(x + w * 0.04, y + h * 0.70, w * 0.92, h * 0.10))

    body = QRectF(x, y + h * 0.22, w, h * 0.52)
    grad = QLinearGradient(x, body.top(), x, body.bottom())
    grad.setColorAt(0.0, QColor(52, 57, 70))
    grad.setColorAt(1.0, QColor(30, 33, 42))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(body, 6, 6)

    slot_w = w / ports
    for i in range(1, ports + 1):
        cx = x + slot_w * (i - 0.5)
        lit = (active == i)

        # compression fitting on top of each inlet
        p.setBrush(QBrush(QColor(150, 158, 175)))
        p.setPen(QPen(METAL_DARK, 1))
        p.drawRoundedRect(
            QRectF(cx - slot_w * 0.16, y, slot_w * 0.32, h * 0.07), 1.5, 1.5)

        top = QRectF(cx - slot_w * 0.32, y + h * 0.05,
                     slot_w * 0.64, h * 0.19)
        p.setBrush(QBrush(METAL if not lit else ACCENT_C))
        p.setPen(QPen(METAL_DARK, 1))
        p.drawRoundedRect(top, 2, 2)

        p.setBrush(QBrush(ACCENT_C if lit else QColor(70, 76, 92)))
        p.setPen(QPen(METAL_DARK, 1))
        p.drawEllipse(QPointF(cx, y + h * 0.40), 4.2, 4.2)

        if lit:
            glow = QColor(ACCENT_C)
            glow.setAlpha(70 + int(50 * math.sin(phase * 2 * math.pi)))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, y + h * 0.40), 8.5, 8.5)

        p.setPen(QPen(QColor(150, 156, 172)))
        f = QFont("Inter", 6)
        p.setFont(f)
        p.drawText(QRectF(cx - slot_w * 0.5, y + h * 0.055, slot_w, h * 0.16),
                   Qt.AlignmentFlag.AlignCenter, str(i))

        # terminal block under each port
        p.setBrush(QBrush(QColor(64, 116, 84)))
        p.setPen(QPen(METAL_DARK, 1))
        p.drawRect(QRectF(cx - slot_w * 0.26, y + h * 0.60, slot_w * 0.52, h * 0.11))

    # common outlet
    p.setBrush(QBrush(METAL))
    p.setPen(QPen(METAL_DARK, 1.2))
    p.drawRoundedRect(QRectF(x + w - 6, y + h * 0.38, 12, h * 0.16), 3, 3)

    _text(p, x, y + h * 0.80, w, unit.label or "Selector", 9)


def draw_crossbar(p: QPainter, x, y, w, h, unit, phase):
    """Solenoid crossbar: a grid of independently addressed valves."""
    rows, cols = 3, 6
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(QRectF(x, y + h * 0.12, w, h * 0.62), 6, 6)

    open_cells = (unit.config or {}).get("open_cells") or []
    cw_, ch_ = w / (cols + 1), (h * 0.62) / (rows + 1)
    for r in range(rows):
        for c in range(cols):
            cx = x + cw_ * (c + 1)
            cy = y + h * 0.12 + ch_ * (r + 1)
            lit = [r, c] in open_cells or (r, c) in open_cells
            p.setBrush(QBrush(ACCENT_C if lit else QColor(66, 72, 88)))
            p.setPen(QPen(METAL_DARK, 1))
            p.drawEllipse(QPointF(cx, cy), 4.0, 4.0)

    _text(p, x, y + h * 0.80, w, unit.label or "Crossbar", 9)


def draw_solenoid(p: QPainter, x, y, w, h, unit, phase):
    """Single two-way valve."""
    is_open = bool((unit.config or {}).get("open"))
    p.setBrush(QBrush(BODY))
    p.setPen(QPen(METAL_DARK, 1.5))
    p.drawRoundedRect(QRectF(x + w * 0.15, y + h * 0.20, w * 0.7, h * 0.45), 4, 4)

    p.setBrush(QBrush(QColor(64, 116, 84)))
    p.setPen(QPen(METAL_DARK, 1))
    p.drawRect(QRectF(x + w * 0.32, y + h * 0.63, w * 0.36, h * 0.10))

    p.setBrush(QBrush(ACCENT_C if is_open else QColor(70, 76, 92)))
    p.setPen(QPen(METAL_DARK, 1))
    p.drawEllipse(QPointF(x + w * 0.5, y + h * 0.40), 5.5, 5.5)

    _text(p, x, y + h * 0.78, w, unit.label or "Valve", 9)


# -- sampling --------------------------------------------------------------

SHELL = QColor(232, 234, 239)        # moulded white housing
SHELL_EDGE = QColor(146, 152, 166)
JOINT_BAND = QColor(58, 63, 76)      # dark collar between segments
TOOL = QColor(72, 168, 190)


def _link(p, a: QPointF, b: QPointF, width: float):
    """One arm segment: dark edge, white shell, specular highlight."""
    edge = QPen(QColor(38, 42, 52), width + 2.5)
    edge.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(edge)
    p.drawLine(a, b)

    shell = QPen(SHELL, width)
    shell.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(shell)
    p.drawLine(a, b)

    # highlight runs along the upper edge of the segment
    dx, dy = b.x() - a.x(), b.y() - a.y()
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln, dx / ln
    off = width * 0.24
    hl = QPen(QColor(255, 255, 255, 150), width * 0.24)
    hl.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(hl)
    p.drawLine(QPointF(a.x() + nx * off, a.y() + ny * off),
               QPointF(b.x() + nx * off, b.y() + ny * off))


def _joint(p, c: QPointF, r: float):
    """Joint housing: dark collar with a lighter cap and a pivot dot."""
    p.setPen(QPen(QColor(38, 42, 52), 1.6))
    p.setBrush(QBrush(JOINT_BAND))
    p.drawEllipse(c, r, r)
    p.setBrush(QBrush(SHELL))
    p.setPen(QPen(SHELL_EDGE, 1.0))
    p.drawEllipse(c, r * 0.62, r * 0.62)
    p.setBrush(QBrush(QColor(120, 128, 145)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(c, r * 0.2, r * 0.2)


def draw_robot_arm(p: QPainter, x, y, w, h, unit, phase):
    """Six-axis bench arm, myCobot proportions, tool pointing down."""
    running = unit.status == "running"
    swing = math.sin(phase * 2 * math.pi) * 0.11 if running else 0.0

    bx = x + w * 0.24
    by = y + h * 0.80

    # contact shadow, so it sits on the bench rather than floating
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 90)))
    p.drawEllipse(QPointF(bx, by + h * 0.15), w * 0.20, h * 0.035)

    # base plate + rotating column (J1)
    p.setBrush(QBrush(QColor(46, 50, 62)))
    p.setPen(QPen(QColor(30, 33, 42), 1.5))
    p.drawRoundedRect(QRectF(bx - w * 0.17, by + h * 0.06, w * 0.34, h * 0.10),
                      3, 3)
    p.setBrush(QBrush(SHELL))
    p.setPen(QPen(SHELL_EDGE, 1.4))
    p.drawRoundedRect(QRectF(bx - w * 0.11, by - h * 0.02, w * 0.22, h * 0.10),
                      4, 4)
    p.setBrush(QBrush(JOINT_BAND))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(bx - w * 0.11, by + h * 0.045, w * 0.22, h * 0.018))

    # shoulder (J2) -> elbow (J3) -> wrist (J4)
    l1 = w * 0.36
    l2 = w * 0.34
    j2 = QPointF(bx, by - h * 0.02)

    target = getattr(unit, "_reach_xy", None)
    if target is not None:
        # Two-link IK, elbow up: put the wrist one needle-length above the
        # goal so the needle tip lands exactly on it.
        gx, gy = target[0], target[1] - h * 0.20
        ddx, ddy = gx - j2.x(), gy - j2.y()
        d = max(abs(l1 - l2) + 2.0,
                min(l1 + l2 - 1.0, math.hypot(ddx, ddy)))
        base_a = math.atan2(ddy, ddx)
        cos_a = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
        a1 = base_a - math.acos(max(-1.0, min(1.0, cos_a)))
        j3 = QPointF(j2.x() + math.cos(a1) * l1, j2.y() + math.sin(a1) * l1)
        a2 = math.atan2(gy - j3.y(), gx - j3.x())
        j4 = QPointF(j3.x() + math.cos(a2) * l2, j3.y() + math.sin(a2) * l2)
    else:
        a1 = -1.05 + swing
        j3 = QPointF(j2.x() + math.cos(a1) * l1, j2.y() + math.sin(a1) * l1)
        a2 = a1 + 1.22 - swing * 0.55
        j4 = QPointF(j3.x() + math.cos(a2) * l2, j3.y() + math.sin(a2) * l2)

    _link(p, j2, j3, w * 0.085)
    _link(p, j3, j4, w * 0.072)
    _joint(p, j2, w * 0.062)
    _joint(p, j3, w * 0.052)
    _joint(p, j4, w * 0.042)

    # wrist roll block (J5/J6) and the tool it carries
    p.setBrush(QBrush(SHELL))
    p.setPen(QPen(SHELL_EDGE, 1.2))
    p.drawRoundedRect(QRectF(j4.x() - w * 0.035, j4.y() + h * 0.01,
                             w * 0.07, h * 0.055), 3, 3)
    p.setBrush(QBrush(TOOL))
    p.setPen(QPen(QColor(38, 42, 52), 1.2))
    p.drawRoundedRect(QRectF(j4.x() - w * 0.028, j4.y() + h * 0.06,
                             w * 0.056, h * 0.06), 2.5, 2.5)

    # needle
    npen = QPen(QColor(206, 96, 96), 2.2)
    npen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(npen)
    tip = QPointF(j4.x(), j4.y() + h * 0.20)
    p.drawLine(QPointF(j4.x(), j4.y() + h * 0.115), tip)

    # cable loop from the base up the first link
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(52, 57, 70), 2.0))
    cable = QPainterPath()
    cable.moveTo(bx - w * 0.10, by + h * 0.03)
    cable.cubicTo(bx - w * 0.24, by - h * 0.06,
                  j3.x() - w * 0.20, j3.y() + h * 0.10,
                  j3.x() - w * 0.04, j3.y() + h * 0.02)
    p.drawPath(cable)

    if running:
        d = (phase * 2) % 1.0
        drop = QColor(130, 190, 228, max(0, int(235 * (1 - d))))
        p.setBrush(QBrush(drop))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(tip.x(), tip.y() + 3 + d * h * 0.10),
                      w * 0.019, h * 0.024)

    # Label under the base, where the machine actually stands.
    _text(p, x - w * 0.20, y + h * 0.99, w, unit.label or "Arm", 9)


def draw_needle(p: QPainter, x, y, w, h, unit, phase):
    """Fixed sampling needle."""
    p.setBrush(QBrush(METAL))
    p.setPen(QPen(METAL_DARK, 1.2))
    p.drawRoundedRect(QRectF(x + w * 0.34, y + h * 0.14, w * 0.32, h * 0.36), 3, 3)
    pen = QPen(QColor(200, 90, 90), 2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(x + w * 0.5, y + h * 0.50),
               QPointF(x + w * 0.5, y + h * 0.80))
    _text(p, x, y + h * 0.84, w, unit.label or "Needle", 9)


# -- plates ----------------------------------------------------------------

def plate_well_center(unit, well: str) -> tuple[float, float]:
    """Canvas position of one well's centre - the same grid draw_plate
    lays out, so the needle and the drawing always agree."""
    from environnets.core.unit_types import default_dims
    w, h = default_dims(unit.category, unit.type_id)
    t = get_type(unit.category, unit.type_id)
    rows, cols = t.get("rows", 3), t.get("cols", 3)
    rr = ord(well[0]) - ord("A")
    cc = int(well[1:]) - 1
    top = unit.y + h * 0.08
    body_h = h * 0.76
    padx = w * 0.09
    pady = body_h * 0.16
    gw = (w - padx * 2) / cols
    gh = (body_h - pady * 1.4) / rows
    return (unit.x + padx + gw * (cc + 0.5),
            top + pady * 0.85 + gh * (rr + 0.5))


def draw_plate(p: QPainter, x, y, w, h, unit, phase):
    """Well plate: skirted body, chamfered A1 corner, wells that fill."""
    t = get_type(unit.category, unit.type_id)
    rows, cols = t.get("rows", 3), t.get("cols", 3)
    cfg = unit.config or {}
    filled = set(cfg.get("filled_wells") or [])
    sources = cfg.get("well_sources") or {}

    top = y + h * 0.08
    body_h = h * 0.76

    # contact shadow
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 80)))
    p.drawEllipse(QRectF(x + w * 0.06, top + body_h - h * 0.03,
                         w * 0.88, h * 0.07))

    # skirt, then deck, with the A1 corner cut like real labware
    p.setBrush(QBrush(QColor(196, 205, 220, 40)))
    p.setPen(QPen(QColor(150, 160, 180, 120), 1.4))
    p.drawRoundedRect(QRectF(x, top, w, body_h), 5, 5)

    chamfer = min(w, body_h) * 0.14
    deck = QPainterPath()
    dx0, dy0 = x + w * 0.035, top + body_h * 0.06
    dx1, dy1 = x + w * 0.965, top + body_h * 0.94
    deck.moveTo(dx0 + chamfer, dy0)
    deck.lineTo(dx1, dy0)
    deck.lineTo(dx1, dy1)
    deck.lineTo(dx0, dy1)
    deck.lineTo(dx0, dy0 + chamfer)
    deck.closeSubpath()
    p.setBrush(QBrush(QColor(228, 234, 244, 26)))
    p.setPen(QPen(QColor(170, 180, 200, 90), 1.0))
    p.drawPath(deck)

    padx = w * 0.09
    pady = body_h * 0.16
    gw = (w - padx * 2) / cols
    gh = (body_h - pady * 1.4) / rows
    r = min(gw, gh) * 0.35

    for rr in range(rows):
        for cc in range(cols):
            cx = x + padx + gw * (cc + 0.5)
            cy = top + pady * 0.85 + gh * (rr + 0.5)
            name = f"{chr(ord('A') + rr)}{cc + 1}"

            # well bore
            p.setBrush(QBrush(QColor(16, 18, 24, 200)))
            p.setPen(QPen(QColor(126, 136, 156, 120), 1.0))
            p.drawEllipse(QPointF(cx, cy), r, r)

            if name in filled:
                p.setBrush(QBrush(QColor(104, 172, 212, 225)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(cx, cy), r * 0.82, r * 0.82)
                # meniscus glint
                p.setBrush(QBrush(QColor(220, 240, 255, 130)))
                p.drawEllipse(QPointF(cx - r * 0.24, cy - r * 0.3),
                              r * 0.20, r * 0.14)
                # which reactor this well came from
                src = sources.get(name)
                if src and r > 7:
                    p.setPen(QPen(QColor(12, 20, 30)))
                    f = QFont("Inter", max(6, int(r * 0.52)))
                    f.setBold(True)
                    p.setFont(f)
                    p.drawText(QRectF(cx - r, cy - r, r * 2, r * 2),
                               Qt.AlignmentFlag.AlignCenter, src)

    _text(p, x, y + h * 0.90, w, unit.label or "Plate", 9)


def get_type(cat, tid):
    from environnets.core.unit_types import get_type as _gt
    return _gt(cat, tid)


DRAW_FUNCTIONS = {
    # routing
    ("routing", "selector_8"):     draw_selector,
    ("routing", "crossbar_8"):     draw_crossbar,
    ("routing", "solenoid_valve"): draw_solenoid,
    # sampling
    ("sampling", "robot_arm"):     draw_robot_arm,
    ("sampling", "sample_needle"): draw_needle,
    # plates
    ("plate", "plate_3x3"):        draw_plate,
    ("plate", "plate_96"):         draw_plate,
    # reactors
    ("reactor", "pio_20ml"):     draw_pio_vial,
    ("reactor", "pio_40ml"):     draw_pio_vial,
    ("reactor", "stirred_tank"): draw_stirred_tank,
    ("reactor", "microfluidic"): draw_microfluidic,
    ("reactor", "custom_vessel"): draw_pio_vial,
    # pumps
    ("pump", "peristaltic"):    draw_peristaltic,
    ("pump", "dual_syringe"):   draw_dual_syringe,
    ("pump", "single_syringe"): draw_syringe,
    ("pump", "diaphragm"):      draw_diaphragm,
    ("pump", "custom_pump"):    draw_custom_pump,
    # reservoirs
    ("reservoir", "media_bottle"):  draw_media_bottle,
    ("reservoir", "waste_bottle"):  draw_waste_bottle,
    ("reservoir", "reagent_bottle"): draw_reagent_bottle,
    # sensors
    ("sensor", "od"):            draw_od,
    ("sensor", "temperature"):   draw_temp,
    ("sensor", "ph"):            draw_ph,
    ("sensor", "co2"):           draw_co2,
    ("sensor", "dissolved_o2"):  draw_do2,
    ("sensor", "spectrometer"):  draw_spec,
    ("sensor", "custom_sensor"): draw_custom_sensor,
}


def draw_unit(painter: QPainter, unit, phase: float = 0.0):
    """Dispatch to the right cartoon function based on category + type_id."""
    cat = getattr(unit, "category", "reactor")
    tid = getattr(unit, "type_id", "pio_20ml")
    fn = DRAW_FUNCTIONS.get((cat, tid), draw_pio_vial)
    from environnets.core.unit_types import default_dims
    w, h = default_dims(cat, tid)
    fn(painter, unit.x, unit.y, w, h, unit, phase)


def draw_status_glow(painter: QPainter, unit, phase: float):
    """Small status lamp on the device.

    A box drawn round every unit makes the canvas read as a diagram of boxes
    rather than equipment sitting on a bench, so the state shows as a lamp.
    """
    cat = getattr(unit, "category", "reactor")
    if cat in ("reservoir", "pump"):
        return
    from environnets.core.unit_types import default_dims
    tid = getattr(unit, "type_id", "pio_20ml")
    w, h = default_dims(cat, tid)

    colours = {
        "disconnected": QColor(168, 76, 76),
        "idle":         QColor(176, 142, 62),
        "running":      QColor(96, 156, 214),
        "connected":    QColor(96, 156, 214),
    }
    c = colours.get(unit.status, QColor(168, 76, 76))
    # Sit the lamp on the device body, not the corner of an invisible box.
    if cat == "reactor":
        cx, cy = unit.x + w * 0.24, unit.y + h * 0.42
    elif cat == "routing":
        cx, cy = unit.x + w * 0.055, unit.y + h * 0.47
    elif cat == "sampling":
        cx, cy = unit.x + w * 0.24, unit.y + h * 0.90
    elif cat == "plate":
        cx, cy = unit.x + w * 0.94, unit.y + h * 0.16
    else:
        cx, cy = unit.x + 7, unit.y + 7

    if unit.status == "running":
        halo = QColor(c)
        halo.setAlpha(60 + int(60 * abs(math.sin(phase * 2 * math.pi))))
        painter.setBrush(QBrush(halo))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 8.5, 8.5)

    painter.setBrush(QBrush(c))
    painter.setPen(QPen(QColor(18, 20, 26), 1.2))
    painter.drawEllipse(QPointF(cx, cy), 3.8, 3.8)
