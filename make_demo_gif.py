#!/usr/bin/env python
"""Render the water demo as a GIF for the slide deck.

    ./venv/bin/python make_demo_gif.py [outdir]

Builds the Water demo network, validates it, compiles the sampling program,
replays it frame by frame and encodes a GIF (plus an MP4 if ffmpeg is here).
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF

from environnets.core.models import Network
from environnets.core.presets import get_preset, instantiate
from environnets.core.recipe import Recipe, validate
from environnets.core.program import compile_program
from environnets.core.unit_types import plate_wells
from environnets.ui.animate import render_frames, encode_gif, encode_mp4


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/Desktop/environnets_demo")
    os.makedirs(out_dir, exist_ok=True)
    frame_dir = os.path.join(out_dir, "frames")

    app = QApplication(sys.argv)

    # 1. Build the demo network from the preset.
    preset_id = os.environ.get("ENV_PRESET", "bench")
    net = Network(network_id="water-demo", name="Water demo")
    units, conns = instantiate(get_preset(preset_id), 620, 380)
    net.units.extend(units)
    net.connections.extend(conns)

    # Bind to the reactors that are actually live on the leader.
    for u, unit_name in zip(
        [x for x in net.units if x.category == "reactor"],
        ["oliveirapioreactor01", "oliveirapioreactor05", "oliveirapioreactor06"],
    ):
        u.pioreactor_unit = unit_name

    # 2. A recipe with a short cadence, so the GIF shows several rounds.
    # Every vessel wired to a router port is a sampling source, harvest
    # pot included - read that off the drawing rather than hard-coding it.
    by_uid = {u.uid: u for u in net.units}
    router = next(u for u in net.units if u.category == "routing")
    port_map = {}
    for c in net.connections:
        if c.target_uid == router.uid and c.target_port is not None:
            port_map[by_uid[c.source_uid].label] = c.target_port
    nodes = sorted(port_map, key=lambda n: port_map[n])

    recipe = Recipe(
        run_id="ENV-DEMO-001",
        model="GEM + FBA",
        iteration=2,
        objective="integration demo (water)",
        nodes=nodes,
        d_per_h=[0.20] * len(nodes),
        cadence_min=[5] * len(nodes),
        draw_uL=500,
        vessel_volume_ml=20.0,
        run_hours=0.25,
    )

    result = validate(recipe, net)
    print("Validation:", "PASSED" if result.ok else "FAILED")
    for w in result.warnings:
        print("  warning:", w)
    for e in result.errors:
        print("  ERROR:", e)
    if not result.ok:
        return 1

    # 3. Compile the sampling program.
    plate = next(u for u in net.units if u.category == "plate")
    wells = plate_wells(plate.category, plate.type_id)
    steps = compile_program(recipe, port_map=port_map, wells=wells,
                            duration_min=recipe.run_hours * 60)
    print(f"Program: {len(steps)} steps")

    # 4. Record.
    print("Rendering frames...")
    frames = render_frames(net, steps, frame_dir, run_id=recipe.run_id,
                           width=1500, height=1000, hold=5, tail=16)
    print(f"  {len(frames)} frames")

    gif = os.path.join(out_dir, "environnets_water_demo.gif")
    print("Encoding GIF...")
    encode_gif(frame_dir, gif, fps=12, width=1150)
    print("  ", gif, f"({os.path.getsize(gif) / 1e6:.1f} MB)")

    mp4 = os.path.join(out_dir, "environnets_water_demo.mp4")
    if encode_mp4(frame_dir, mp4, fps=24):
        print("  ", mp4, f"({os.path.getsize(mp4) / 1e6:.1f} MB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
