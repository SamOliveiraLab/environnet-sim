"""NiceGUI sandbox: single-reactor bioreactor simulation in the browser.

Each browser session gets its own SimEngine. The sim runs server-side at a
fixed wall-clock cadence; updates push to the page via NiceGUI's WebSocket.
"""

from nicegui import ui

from environnets.core.simulation import SimEngine, SimConfig


PLOT_WINDOW = 600
TICK_HZ = 10


def _organism_config(name: str) -> SimConfig:
    return SimConfig.yeast() if name == "Yeast" else SimConfig.ecoli()


def _build_chart(title: str, color: str, y_name: str) -> ui.echart:
    return ui.echart({
        "title": {"text": title, "textStyle": {"fontSize": 12, "color": "#dcdce0"}},
        "grid": {"left": 50, "right": 16, "top": 36, "bottom": 30},
        "xAxis": {"type": "value", "name": "min", "nameGap": 18,
                  "axisLine": {"lineStyle": {"color": "#666"}}},
        "yAxis": {"type": "value", "name": y_name,
                  "axisLine": {"lineStyle": {"color": "#666"}},
                  "splitLine": {"lineStyle": {"color": "#2a2a30"}}},
        "tooltip": {"trigger": "axis"},
        "series": [{"type": "line", "showSymbol": False,
                    "lineStyle": {"color": color, "width": 2},
                    "data": []}],
        "backgroundColor": "transparent",
    }).style("height: 200px;")


def _build_page():
    ui.dark_mode().enable()
    ui.add_head_html("""
    <style>
        body { background: #18181c; }
        .stat-row { font-size: 13px; color: #c0c0c8; }
        .stat-val { color: #fff; font-weight: 500; }
    </style>
    """)

    sim = SimEngine(SimConfig.ecoli())
    state = {"speed": 60.0}

    with ui.header().classes("items-center").style("background: #1f1f24; border-bottom: 1px solid #2a2a30"):
        ui.label("EnvironNets Sandbox").style("font-size: 18px; font-weight: 500; color: #fff")
        ui.label("· single-reactor simulation").style("font-size: 12px; color: #7c7c8a")
        ui.space()
        time_label = ui.label("0.0 h").style("font-size: 12px; color: #7c7c8a")

    with ui.row().classes("w-full no-wrap").style("padding: 12px"):

        # ---------- Controls panel ----------
        with ui.column().style("width: 280px; min-width: 260px;"):
            with ui.card().tight().style("background: #1f1f24; border: 1px solid #2a2a30; padding: 14px"):
                ui.label("Setup").style("font-size: 11px; color: #7c7c8a; letter-spacing: 0.5px")
                organism = ui.select(["E. coli", "Yeast"], value="E. coli", label="Organism").classes("w-full")
                mode = ui.select(["Manual", "Chemostat", "Turbidostat"], value="Chemostat", label="Mode").classes("w-full")

                ui.label("Stir (RPM)").classes("q-mt-sm").style("font-size: 11px; color: #7c7c8a")
                rpm = ui.slider(min=0, max=1500, value=400, step=50).props("label-always color=primary")

                ui.label("Target temperature (°C)").classes("q-mt-sm").style("font-size: 11px; color: #7c7c8a")
                temp = ui.slider(min=15, max=50, value=37, step=0.5).props("label-always color=orange")

                with ui.row().classes("w-full no-wrap q-mt-sm"):
                    dose = ui.number(label="Dose (mL)", value=0.5, format="%.2f", min=0.01, max=10, step=0.1).classes("w-1/2")
                    interval = ui.number(label="Every (min)", value=15, min=1, max=1440, step=1).classes("w-1/2")

                ui.label("Sim speed (x real time)").classes("q-mt-sm").style("font-size: 11px; color: #7c7c8a")
                speed = ui.slider(min=1, max=300, value=60, step=1).props("label-always")

            with ui.row().classes("w-full no-wrap q-mt-sm"):
                play_btn = ui.button("Play").props("color=primary").classes("w-1/2")
                reset_btn = ui.button("Reset").props("flat color=grey").classes("w-1/2")

            # Stats card
            with ui.card().tight().classes("q-mt-sm").style("background: #1f1f24; border: 1px solid #2a2a30; padding: 14px"):
                ui.label("Live state").style("font-size: 11px; color: #7c7c8a; letter-spacing: 0.5px")
                stats = {}
                for key, label in [("od", "OD"), ("gr", "Growth rate (1/h)"),
                                   ("temp", "Temperature (°C)"),
                                   ("media", "Media remaining (mL)"),
                                   ("waste", "Waste collected (mL)")]:
                    with ui.row().classes("stat-row no-wrap items-center q-py-xs"):
                        ui.label(label)
                        ui.space()
                        stats[key] = ui.label("—").classes("stat-val")

        # ---------- Plots column ----------
        with ui.column().classes("col"):
            od_chart = _build_chart("Optical density", "#7a9ec7", "OD")
            gr_chart = _build_chart("Growth rate", "#8a7ab5", "1/h")
            temp_chart = _build_chart("Temperature", "#c48a5a", "°C")

    # ---------- Wiring ----------
    def reset_sim():
        nonlocal sim
        sim.stop()
        sim = SimEngine(_organism_config(organism.value))
        for chart in (od_chart, gr_chart, temp_chart):
            chart.options["series"][0]["data"] = []
            chart.update()
        for k in stats:
            stats[k].text = "—"
        time_label.text = "0.0 h"
        play_btn.text = "Play"
        play_btn.props("color=primary")

    def toggle_play():
        if sim.running:
            sim.stop()
            play_btn.text = "Play"
            play_btn.props("color=primary")
        else:
            sim.config = _organism_config(organism.value)
            sim.config.time_scale = float(speed.value)
            sim.start(
                rpm=int(rpm.value),
                target_temp=float(temp.value),
                mode=mode.value.lower(),
                dose_ml=float(dose.value),
                dose_interval_min=float(interval.value),
            )
            play_btn.text = "Stop"
            play_btn.props("color=red")

    play_btn.on("click", toggle_play)
    reset_btn.on("click", reset_sim)

    # Live updates from controls while running
    def push_params():
        if not sim.running:
            return
        sim.state.target_temp = float(temp.value)
        sim.state.rpm = int(rpm.value)
        sim.state.dose_volume_ml = float(dose.value)
        sim.state.dose_interval_min = float(interval.value)
        sim.config.time_scale = float(speed.value)
        sim.mode = mode.value.lower()

    for w in (rpm, temp, mode, dose, interval, speed):
        w.on("update:model-value", push_params)

    def tick():
        if not sim.running:
            return
        sim.step(1.0 / TICK_HZ)
        s = sim.state

        ts = [h["t"] for h in sim.history[-PLOT_WINDOW:]]
        od_chart.options["series"][0]["data"] = list(zip(ts, [h["od"] for h in sim.history[-PLOT_WINDOW:]]))
        gr_chart.options["series"][0]["data"] = list(zip(ts, [h["growth_rate"] for h in sim.history[-PLOT_WINDOW:]]))
        temp_chart.options["series"][0]["data"] = list(zip(ts, [h["temperature"] for h in sim.history[-PLOT_WINDOW:]]))
        for chart in (od_chart, gr_chart, temp_chart):
            chart.update()

        stats["od"].text = f"{s.od:.3f}"
        stats["gr"].text = f"{s.growth_rate:.3f}"
        stats["temp"].text = f"{s.temperature:.2f}"
        stats["media"].text = f"{s.media_remaining_ml:.1f}"
        stats["waste"].text = f"{s.waste_collected_ml:.1f}"
        time_label.text = f"{sim.elapsed_hours:.2f} h"

    ui.timer(1.0 / TICK_HZ, tick)


def build():
    @ui.page("/")
    def index():
        _build_page()

    @ui.page("/healthz")
    def healthz():
        ui.label("ok")
