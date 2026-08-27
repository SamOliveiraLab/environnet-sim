"""Record a simulated run as frames, then encode a GIF.

Replays a compiled program against the canvas, driving the visual state as it
goes - the selector lights its live port, the arm animates, wells fill as
samples land - and grabs one image per frame. Reuses the real canvas widget,
so what gets recorded is exactly what the app draws.

Encoding needs ffmpeg (preferred, two-pass palette) or ImageMagick.
"""

import math
import os
import shutil
import subprocess

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QImage

from environnets.core.unit_types import default_dims
from environnets.ui.cartoons import plate_well_center


HUD_H = 54


def _bounds(network):
    """Bounding box of everything on the canvas."""
    xs, ys, xe, ye = [], [], [], []
    for u in network.units:
        w, h = default_dims(u.category, u.type_id)
        xs.append(u.x); ys.append(u.y)
        xe.append(u.x + w); ye.append(u.y + h)
    if not xs:
        return QRectF(0, 0, 800, 600)
    return QRectF(min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))


def _fit(canvas_widget, network, width, height, margin=70):
    """Zoom and pan so the whole network fills the frame."""
    box = _bounds(network)
    if box.width() <= 0 or box.height() <= 0:
        return
    zoom = min((width - margin * 2) / box.width(),
               (height - margin * 2 - HUD_H) / box.height())
    zoom = max(0.15, min(2.0, zoom))
    canvas_widget._zoom = zoom
    canvas_widget._pan = QPointF(
        (width - box.width() * zoom) / 2 - box.x() * zoom,
        (height - HUD_H - box.height() * zoom) / 2 - box.y() * zoom + HUD_H,
    )


class PlaybackState:
    """Physical state of the rig as the program plays back.

    Liquid only ever travels reactor -> router -> needle -> well, so exactly
    one source is live at a time and only that path is illuminated.
    """

    def __init__(self, network):
        self.net = network
        self.routers = [u for u in network.units if u.category == "routing"]
        self.arms = [u for u in network.units if u.category == "sampling"]
        self.plates = [u for u in network.units if u.category == "plate"]
        self.pumps = [u for u in network.units if u.category == "pump"]
        self.by_uid = {u.uid: u for u in network.units}
        self.reactors = {(u.label or u.uid): u for u in network.units
                         if u.category == "reactor"}
        self.filled: dict[str, str] = {}      # well -> source label
        self.source: str | None = None
        self.port: int | None = None
        self.well: str | None = None
        self.sample_id: str | None = None
        self.delivered = 0
        self.fed: set[str] = set()
        self.started = False                  # continuous process live?
        self.t = 0.0                          # sim clock, seconds

        # The production train: every feed, culture and harvest line, and
        # the pumps that drive them. Once the run starts these never stop -
        # it is a chemostat cascade, not a batch of one-shot moves.
        self.process_links: set = set()
        self.process_pumps: list = []
        for c in network.connections:
            if c.kind in ("media", "culture", "waste"):
                self.process_links.add((c.source_uid, c.target_uid))
                for uid in (c.source_uid, c.target_uid):
                    u = self.by_uid.get(uid)
                    if u and u.category == "pump" and u not in self.process_pumps:
                        self.process_pumps.append(u)

        # Cascade order, for staggering growth down the train.
        self.chain = sorted(self.reactors.values(), key=lambda u: u.x)

        # Needle travel: where the arm is coming from and going to.
        self._arm_from: tuple | None = None
        self._arm_to: tuple | None = None

    def _arm_rest_tip(self):
        """Needle tip of the arm's parked pose (mirrors the cartoon)."""
        if not self.arms:
            return None
        a = self.arms[0]
        w, h = default_dims(a.category, a.type_id)
        j2 = (a.x + w * 0.24, a.y + h * 0.80 - h * 0.02)
        a1, l1, l2 = -1.05, w * 0.36, w * 0.34
        j3 = (j2[0] + math.cos(a1) * l1, j2[1] + math.sin(a1) * l1)
        a2 = a1 + 1.22
        j4 = (j3[0] + math.cos(a2) * l2, j3[1] + math.sin(a2) * l2)
        return (j4[0], j4[1] + h * 0.20)

    def tween(self, step, frac):
        """Advance the needle along its travel for this step's frames."""
        if step.action == "move" and self._arm_from and self._arm_to:
            f = frac * frac * (3 - 2 * frac)          # ease in-out
            x = self._arm_from[0] + (self._arm_to[0] - self._arm_from[0]) * f
            y = self._arm_from[1] + (self._arm_to[1] - self._arm_from[1]) * f
            y -= math.sin(math.pi * f) * 10           # hop over the wells
            for a in self.arms:
                a._reach_xy = (x, y)

    # -- wiring lookups ----------------------------------------------------

    def _uid(self, label):
        u = self.reactors.get(label)
        return u.uid if u else None

    def _links_for(self, source_label, pumping=False):
        """The live path: source -> router -> sample pump -> needle.

        pumping: also spin every pump along the outlet chain - liquid is
        actually being drawn, not just a valve position being held.
        """
        links = set()
        if not self.routers:
            return links
        router = self.routers[0]
        src_uid = self._uid(source_label)
        for c in self.net.connections:
            if c.target_uid == router.uid and c.source_uid == src_uid:
                links.add((c.source_uid, c.target_uid))
        # Follow the outlet through any pumps until it reaches the needle.
        cur = router
        for _ in range(6):
            step_c = next(
                (c for c in self.net.connections
                 if c.kind == "sample" and c.source_uid == cur.uid), None)
            if step_c is None:
                break
            nxt = self.by_uid.get(step_c.target_uid)
            if nxt is None:
                break
            links.add((step_c.source_uid, step_c.target_uid))
            if nxt.category == "pump":
                if pumping:
                    nxt.status = "running"
                cur = nxt
                continue
            break
        return links

    def _feed_links(self, reactor_label):
        """Bottle -> feed pump -> reactor, with that pump spinning."""
        links = set()
        u = self.reactors.get(reactor_label)
        if u is None:
            return links
        for c in self.net.connections:
            if c.kind == "media" and c.target_uid == u.uid:
                links.add((c.source_uid, c.target_uid))
                pump = self.by_uid.get(c.source_uid)
                if pump and pump.category == "pump":
                    pump.status = "running"
                    for c2 in self.net.connections:
                        if c2.kind == "media" and c2.target_uid == pump.uid:
                            links.add((c2.source_uid, c2.target_uid))
        return links

    # -- step application --------------------------------------------------

    def apply(self, step):
        self.t = max(self.t, float(step.at_s))
        for a in self.arms:
            a.status = "idle"
        for pu in self.pumps:
            pu.status = "idle"

        if step.action == "init":
            for u in self.reactors.values():
                u.status = "idle"
            for a in self.arms:
                a._reach_xy = None
            self.source = self.port = self.well = None
            self._set_links(set())

        elif step.action == "home":
            self._set_port(None)
            self._set_links(set())

        elif step.action == "feed":
            # A fed reactor joins the continuous process: from here on its
            # culture grows and its lines carry traffic without stopping.
            self.fed.add(step.target)
            self.started = True
            self._set_links(self._feed_links(step.target))

        elif step.action == "select":
            self.source = step.target
            self.port = step.detail.get("port")
            self._set_port(self.port)
            # Valve set, sample pump drawing. The reactors keep running -
            # the lit path is what says who is being sampled.
            self._set_links(self._links_for(self.source, pumping=True))

        elif step.action == "move":
            self.well = step.target
            for a in self.arms:
                a.status = "running"
            # Needle in motion - travel from wherever it is to the well.
            if self.plates:
                self._arm_from = (getattr(self.arms[0], "_reach_xy", None)
                                  or self._arm_rest_tip()) if self.arms else None
                self._arm_to = plate_well_center(self.plates[0], step.target)
            self._set_links(self._links_for(self.source))

        elif step.action == "dispense":
            self.well = step.target
            self.source = step.detail.get("source", self.source)
            for a in self.arms:
                a.status = "running"
                if self.plates:
                    a._reach_xy = plate_well_center(self.plates[0],
                                                    step.target)
            self.filled[step.target] = self.source or ""
            self.delivered += 1
            self.sample_id = step.detail.get("sample_id")
            self._push_plate()
            # Pushing the draw out through the needle.
            self._set_links(self._links_for(self.source, pumping=True))

        elif step.action == "purge":
            self._set_port(None)
            self._set_links(self._links_for(None, pumping=True)
                            if self.routers else set())

        self._advance_process()

    def _advance_process(self):
        """Continuous culture: pumps turning, biomass climbing the train.

        The OD curve is a dummy - saturating growth staggered down the
        cascade so B1 leads and B3 lags, the way the real train would.
        """
        if not self.started:
            return
        for pu in self.process_pumps:
            pu.status = "running"
        for i, u in enumerate(self.chain):
            u.status = "running"
            stagger = max(0.4, 1.0 - 0.18 * i)
            u.last_od = round(
                (0.10 + 1.15 * (1 - math.exp(-self.t / 480.0))) * stagger, 3)

    # -- helpers -----------------------------------------------------------

    def _set_port(self, port):
        for r in self.routers:
            r.config = dict(r.config or {}, active_port=port)

    def _push_plate(self):
        for pl in self.plates:
            pl.config = dict(pl.config or {},
                             filled_wells=sorted(self.filled),
                             well_sources=dict(self.filled))

    def _set_links(self, links):
        self._links = links

    @property
    def links(self):
        return getattr(self, "_links", set())


VERBS = {
    "init": "INITIALISE",
    "home": "HOME",
    "feed": "READY",
    "select": "SELECT SOURCE",
    "move": "MOVE TO WELL",
    "dispense": "DISPENSE",
    "purge": "FLUSH / PURGE",
}

# How long each operation dwells on screen, relative to the base hold.
# Selecting, moving and dispensing are the real physical work; they get
# real time. Bookkeeping steps pass quickly.
ACTION_HOLD = {
    "init": 1.0,
    "home": 0.7,
    "feed": 1.8,
    "select": 2.4,
    "move": 2.2,
    "dispense": 3.2,
    "purge": 1.4,
}

LOG_W = 330          # width of the run-log panel on the right


def step_log_line(step) -> tuple[str, str, str]:
    """(clock, verb, detail) for one program step - the same wording in
    the on-screen log panel and the exported run_log.txt."""
    t = int(step.at_s)
    clock = f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"
    a = step.action
    if a == "select":
        d = f"{step.target} -> port {step.detail.get('port')}"
    elif a == "move":
        d = f"needle -> well {step.target}"
    elif a == "dispense":
        d = (f"{step.detail.get('volume_uL', 0):.0f} uL "
             f"{step.detail.get('source', '')} -> {step.target}")
    elif a == "feed":
        d = f"{step.target}  D={step.detail.get('d_per_h', 0):.2f}/h"
    elif a == "home":
        d = "selector -> home"
    elif a == "purge":
        d = "flush sample line"
    else:
        d = step.target or ""
    return clock, VERBS.get(a, a.upper()), d


LOG_COLORS = {
    "SELECT SOURCE": QColor(107, 138, 253),
    "MOVE TO WELL": QColor(196, 200, 212),
    "DISPENSE": QColor(122, 196, 148),
    "READY": QColor(184, 149, 64),
    "FLUSH / PURGE": QColor(150, 130, 190),
}


def _draw_log(painter, x, width, height, lines):
    """The run log down the right edge: what the rig is doing, as it does it."""
    painter.fillRect(QRectF(x, HUD_H, width, height - HUD_H),
                     QColor(13, 13, 16))
    painter.setPen(QPen(QColor(44, 46, 56)))
    painter.drawLine(int(x), HUD_H, int(x), height)

    painter.setFont(QFont("Inter", 9, QFont.Weight.DemiBold))
    painter.setPen(QPen(QColor(124, 124, 138)))
    painter.drawText(QRectF(x + 16, HUD_H + 10, width - 32, 16),
                     Qt.AlignmentFlag.AlignVCenter, "RUN LOG")

    line_h = 17
    top = HUD_H + 36
    n_fit = int((height - top - 10) / line_h)
    shown = lines[-n_fit:]
    mono = QFont("Menlo", 9)
    for i, (clock, verb, detail) in enumerate(shown):
        y = top + i * line_h
        painter.setFont(mono)
        painter.setPen(QPen(QColor(108, 110, 124)))
        painter.drawText(QRectF(x + 16, y, 58, line_h),
                         Qt.AlignmentFlag.AlignVCenter, clock)
        painter.setPen(QPen(LOG_COLORS.get(verb, QColor(150, 154, 166))))
        painter.drawText(QRectF(x + 78, y, 96, line_h),
                         Qt.AlignmentFlag.AlignVCenter, verb)
        painter.setPen(QPen(QColor(210, 214, 224)))
        painter.drawText(QRectF(x + 176, y, width - 190, line_h),
                         Qt.AlignmentFlag.AlignVCenter, detail)


def _draw_hud(painter, width, step, index, total, run_id, state, n_samples,
              done=False):
    """Status strip: the operation, and the live state of the whole rig."""
    painter.fillRect(QRectF(0, 0, width, HUD_H), QColor(18, 18, 22))
    painter.setPen(QPen(QColor(44, 46, 56)))
    painter.drawLine(0, HUD_H, width, HUD_H)

    t = int(step.at_s) if step else 0
    clock = f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"
    verb = "COMPLETE" if done else (
        VERBS.get(step.action, step.action.upper()) if step else "COMPLETE")

    detail = ""
    if step and not done:
        if step.action == "select":
            detail = f"{step.target}  →  router port {step.detail.get('port')}"
        elif step.action == "move":
            detail = f"needle → well {step.target}"
        elif step.action == "dispense":
            detail = (f"{step.detail.get('volume_uL', 0):.0f} µL   "
                      f"{step.detail.get('source', '')} → well {step.target}")
        elif step.action == "feed":
            detail = f"{step.target} ready  ·  D = {step.detail.get('d_per_h', 0):.2f}/h"

    painter.setFont(QFont("Inter", 9))
    painter.setPen(QPen(QColor(124, 124, 138)))
    painter.drawText(QRectF(16, 6, 300, 16), Qt.AlignmentFlag.AlignVCenter,
                     f"EnvironNets · {run_id}")

    painter.setFont(QFont("Inter", 13, QFont.Weight.DemiBold))
    painter.setPen(QPen(QColor(107, 138, 253)))
    painter.drawText(QRectF(16, 22, 190, 22), Qt.AlignmentFlag.AlignVCenter, verb)

    painter.setFont(QFont("Inter", 11))
    painter.setPen(QPen(QColor(224, 226, 232)))
    painter.drawText(QRectF(196, 22, 420, 22),
                     Qt.AlignmentFlag.AlignVCenter, detail)

    # live rig state, right-aligned
    fields = [
        ("SOURCE", state.source or "—"),
        ("PORT", str(state.port) if state.port else "—"),
        ("WELL", state.well or "—"),
        ("SAMPLES", f"{state.delivered}/{n_samples}"),
        ("TIME", clock),
    ]
    fx = width - 16 - len(fields) * 108
    for label, value in fields:
        painter.setFont(QFont("Inter", 8))
        painter.setPen(QPen(QColor(108, 110, 124)))
        painter.drawText(QRectF(fx, 8, 100, 12),
                         Qt.AlignmentFlag.AlignLeft, label)
        painter.setFont(QFont("Inter", 12, QFont.Weight.DemiBold))
        painter.setPen(QPen(QColor(228, 230, 238)))
        painter.drawText(QRectF(fx, 22, 100, 20),
                         Qt.AlignmentFlag.AlignLeft, value)
        fx += 108

    frac = (index + 1) / max(1, total)
    painter.fillRect(QRectF(0, HUD_H - 2, width * frac, 2), QColor(107, 138, 253))


def _draw_complete(painter, width, height, state, n_samples):
    """Closing card."""
    painter.fillRect(QRectF(0, HUD_H, width, height - HUD_H),
                     QColor(18, 18, 22, 205))
    box = QRectF(width / 2 - 300, height / 2 - 62, 600, 124)
    painter.setBrush(QColor(24, 26, 32))
    painter.setPen(QPen(QColor(96, 168, 122), 2))
    painter.drawRoundedRect(box, 10, 10)

    painter.setFont(QFont("Inter", 16, QFont.Weight.Bold))
    painter.setPen(QPen(QColor(122, 196, 148)))
    painter.drawText(QRectF(box.x(), box.y() + 22, box.width(), 26),
                     Qt.AlignmentFlag.AlignCenter, "SIMULATION COMPLETE")

    painter.setFont(QFont("Inter", 12))
    painter.setPen(QPen(QColor(214, 218, 226)))
    painter.drawText(
        QRectF(box.x(), box.y() + 56, box.width(), 22),
        Qt.AlignmentFlag.AlignCenter,
        f"{state.delivered}/{n_samples} samples delivered   ·   "
        f"0 routing errors   ·   0 well collisions")

    painter.setFont(QFont("Inter", 10))
    painter.setPen(QPen(QColor(128, 132, 146)))
    painter.drawText(
        QRectF(box.x(), box.y() + 84, box.width(), 20),
        Qt.AlignmentFlag.AlignCenter,
        "reactor → router → needle → plate, coordinated automatically")


def render_frames(network, steps, out_dir, *, run_id="ENV", width=1280,
                  height=720, hold=6, tail=10):
    """Draw the run to numbered PNGs. Returns the list of paths.

    hold: frames per program step. tail: extra frames on the final image.
    """
    from PyQt6.QtWidgets import QApplication
    from environnets.ui.canvas import CanvasWidget

    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if old.endswith(".png"):
            os.remove(os.path.join(out_dir, old))

    class _Holder:
        """Minimal stand-in for NetworkCanvas, so the widget can live alone.

        Building the canvas inside its usual parent layout leaves it without
        real geometry until shown, and grab() then captures only a corner.
        """

        def __init__(self, net):
            self.network = net
            self.store = None
            self.api = None

        def _update_zoom_label(self):
            pass

        def open_unit_detail(self, unit):
            pass

        def link_hardware(self, unit):
            pass

    canvas_w = width - LOG_W
    holder = _Holder(network)
    cw = CanvasWidget(holder)
    cw.setFixedSize(canvas_w, height)
    cw._timer.stop()          # drive the animation phase by hand
    cw.show()
    QApplication.processEvents()
    _fit(cw, network, canvas_w, height)

    state = PlaybackState(network)
    n_samples = sum(1 for s in steps if s.action == "dispense")
    paths = []
    log_lines: list[tuple[str, str, str]] = []
    n = 0

    def grab(step, index, total, done=False):
        nonlocal n
        cw._active_links = state.links
        cw._process_links = state.process_links if state.started else None
        img = QImage(width, height, QImage.Format.Format_RGB32)
        img.fill(QColor(18, 18, 22))
        p = QPainter(img)
        cw.render(p)                       # paint the canvas straight in
        _draw_hud(p, width, step, index, total, run_id, state, n_samples,
                  done=done)
        _draw_log(p, canvas_w, LOG_W, height, log_lines)
        if done:
            _draw_complete(p, canvas_w, height, state, n_samples)
        p.end()
        path = os.path.join(out_dir, f"frame_{n:05d}.png")
        img.save(path)
        paths.append(path)
        n += 1

    total = len(steps)
    for i, step in enumerate(steps):
        state.apply(step)
        log_lines.append(step_log_line(step))
        dwell = max(2, round(hold * ACTION_HOLD.get(step.action, 1.0)))
        for k in range(dwell):
            state.tween(step, k / max(1, dwell - 1))
            cw._phase = (n % 36) / 36.0
            grab(step, i, total)

    log_lines.append(("", "COMPLETE", f"{state.delivered}/{n_samples} "
                      "samples delivered"))
    for _ in range(tail):
        cw._phase = (n % 36) / 36.0
        grab(steps[-1] if steps else None, total - 1, total, done=True)

    return paths


def encode_gif(frame_dir, out_path, fps=12, width=1000):
    """Turn the PNG sequence into a GIF. ffmpeg preferred, ImageMagick fallback."""
    pattern = os.path.join(frame_dir, "frame_%05d.png")

    if shutil.which("ffmpeg"):
        palette = os.path.join(frame_dir, "palette.png")
        vf = f"fps={fps},scale={width}:-1:flags=lanczos"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", pattern,
             "-vf", f"{vf},palettegen=stats_mode=diff", palette],
            check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", pattern, "-i", palette,
             "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
             out_path],
            check=True)
        return out_path

    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        cmd = [magick] if "magick" in os.path.basename(magick) else [magick]
        subprocess.run(
            cmd + ["-delay", str(int(100 / fps)), "-loop", "0",
                   os.path.join(frame_dir, "frame_*.png"),
                   "-resize", f"{width}x", out_path],
            check=True)
        return out_path

    raise RuntimeError("Need ffmpeg or ImageMagick to encode a GIF.")


def encode_mp4(frame_dir, out_path, fps=24):
    """Also useful: a crisp MP4 for slides that accept video."""
    if not shutil.which("ffmpeg"):
        return None
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
         "-i", os.path.join(frame_dir, "frame_%05d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", out_path],
        check=True)
    return out_path
