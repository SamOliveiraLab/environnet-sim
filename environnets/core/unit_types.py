"""Unit type catalog.

Defines every kind of hardware unit the canvas can draw:
reactors, pumps, sensors. Each entry has display metadata,
canvas dimensions, and a config schema for its detail panel.
"""

# Category > type_id > definition

REACTOR_TYPES = {
    "pio_20ml": {
        "label": "Pioreactor 20ml",
        "description": "Pioreactor with 20ml glass vial, standard heterogeneity setup.",
        "width": 140,
        "height": 170,
        "config_fields": ["hostname"],
    },
    "pio_40ml": {
        "label": "Pioreactor 40ml",
        "description": "Pioreactor with 40ml vial for larger cultures.",
        "width": 150,
        "height": 180,
        "config_fields": ["hostname"],
    },
    "stirred_tank": {
        "label": "Stirred tank",
        "description": "Larger scale stirred tank bioreactor.",
        "width": 160,
        "height": 200,
        "config_fields": ["hostname", "volume_ml"],
    },
    "microfluidic": {
        "label": "Microfluidic chamber",
        "description": "For biofilm and single cell work.",
        "width": 170,
        "height": 120,
        "config_fields": ["chamber_id"],
    },
    "custom_vessel": {
        "label": "Custom vessel",
        "description": "Generic container, user-defined.",
        "width": 140,
        "height": 160,
        "config_fields": ["label"],
    },
}

PUMP_TYPES = {
    "peristaltic": {
        "label": "Peristaltic pump",
        "description": "Rotor and roller squeeze tubing. Default Pioreactor pump.",
        "width": 92,
        "height": 84,
        "config_fields": ["pwm_channel", "direction", "calibration_ml_per_s"],
        "api_job": {"in": "add_media", "out": "remove_waste"},
    },
    "dual_syringe": {
        "label": "Dual syringe pump",
        "description": "Two syringes, one pushes while other pulls. Handles both directions.",
        "width": 116,
        "height": 76,
        "config_fields": ["gpio_step", "gpio_dir", "syringe_volume_ml"],
        "api_job": None,  # custom firmware
    },
    "single_syringe": {
        "label": "Single syringe pump",
        "description": "One syringe plunger. Precise for small volumes.",
        "width": 100,
        "height": 70,
        "config_fields": ["gpio_step", "gpio_dir", "syringe_volume_ml"],
        "api_job": None,
    },
    "diaphragm": {
        "label": "Diaphragm pump",
        "description": "Pulsing dome chamber. Good for air or thick liquids.",
        "width": 92,
        "height": 76,
        "config_fields": ["pwm_channel", "pulse_hz"],
        "api_job": None,
    },
    "custom_pump": {
        "label": "Custom pump",
        "description": "Generic pump block, user-defined control.",
        "width": 84,
        "height": 70,
        "config_fields": ["gpio_pin", "label"],
        "api_job": None,
    },
}

SENSOR_TYPES = {
    "od": {
        "label": "OD sensor",
        "description": "Optical density. Built into the Pioreactor.",
        "width": 90,
        "height": 100,
        "config_fields": ["channel"],
    },
    "temperature": {
        "label": "Temperature probe",
        "description": "Measures culture temperature.",
        "width": 90,
        "height": 100,
        "config_fields": ["channel"],
    },
    "ph": {
        "label": "pH probe",
        "description": "Measures culture pH.",
        "width": 90,
        "height": 110,
        "config_fields": ["i2c_address"],
    },
    "co2": {
        "label": "CO2 sensor",
        "description": "Dissolved CO2 in headspace.",
        "width": 100,
        "height": 100,
        "config_fields": ["i2c_address"],
    },
    "spectrometer": {
        "label": "Spectrometer",
        "description": "Color and absorbance across wavelengths.",
        "width": 120,
        "height": 100,
        "config_fields": ["usb_port"],
    },
    "dissolved_o2": {
        "label": "Dissolved O2",
        "description": "Dissolved oxygen in culture.",
        "width": 90,
        "height": 110,
        "config_fields": ["i2c_address"],
    },
    "custom_sensor": {
        "label": "Custom sensor",
        "description": "Generic analog sensor input.",
        "width": 90,
        "height": 90,
        "config_fields": ["adc_channel", "label"],
    },
}

RESERVOIR_TYPES = {
    "media_bottle": {
        "label": "Media bottle",
        "description": "Reservoir holding fresh growth media. Feeds into the media pump.",
        "width": 100,
        "height": 140,
        "config_fields": ["volume_ml", "media_type"],
    },
    "waste_bottle": {
        "label": "Waste bottle",
        "description": "Collects effluent/waste from the bioreactor.",
        "width": 100,
        "height": 140,
        "config_fields": ["volume_ml"],
    },
    "reagent_bottle": {
        "label": "Reagent bottle",
        "description": "Holds inducer, antibiotic, or other reagent for dosing.",
        "width": 90,
        "height": 120,
        "config_fields": ["volume_ml", "reagent_name"],
    },
}

ROUTING_TYPES = {
    "selector_8": {
        "label": "8-port selector",
        "description": (
            "Rotary selector, 8 inlets to 1 outlet. One path at a time, so it "
            "selects which reactor is sampled - it cannot hold a continuous "
            "reactor-to-reactor cascade open."
        ),
        "width": 190,
        "height": 90,
        "ports": 8,
        "simultaneous_routes": 1,
        "config_fields": ["serial_port", "home_position"],
    },
    "solenoid_valve": {
        "label": "Solenoid valve",
        "description": "Single two-way valve, open or closed, on one GPIO line.",
        "width": 90,
        "height": 80,
        "ports": 1,
        "simultaneous_routes": 1,
        "config_fields": ["gpio_pin"],
    },
    "crossbar_8": {
        "label": "Solenoid crossbar",
        "description": (
            "Independently addressed valves. Multiple routes can be held open "
            "at once, which is what a continuous cascade needs."
        ),
        "width": 200,
        "height": 120,
        "ports": 8,
        "simultaneous_routes": 8,
        "config_fields": ["i2c_address", "channels"],
    },
}

SAMPLING_TYPES = {
    "robot_arm": {
        "label": "Robotic arm",
        "description": "myCobot-class arm carrying the sampling needle.",
        "width": 150,
        "height": 150,
        "config_fields": ["serial_port", "home_pose", "draw_uL"],
    },
    "sample_needle": {
        "label": "Sampling needle",
        "description": "Fixed needle at the end of the sample line.",
        "width": 80,
        "height": 100,
        "config_fields": ["dead_volume_uL"],
    },
}

PLATE_TYPES = {
    "plate_3x3": {
        "label": "3x3 demo plate",
        "description": "Nine-well demo sampling fixture. Not the final architecture.",
        "width": 130,
        "height": 130,
        "rows": 3,
        "cols": 3,
        "config_fields": ["plate_id"],
    },
    "plate_96": {
        "label": "96-well plate",
        "description": "Standard 8x12 plate, one per reactor per the deck's strategy.",
        "width": 190,
        "height": 130,
        "rows": 8,
        "cols": 12,
        "config_fields": ["plate_id"],
    },
}

CATEGORY_MAP = {
    "reactor": REACTOR_TYPES,
    "pump": PUMP_TYPES,
    "sensor": SENSOR_TYPES,
    "reservoir": RESERVOIR_TYPES,
    "routing": ROUTING_TYPES,
    "sampling": SAMPLING_TYPES,
    "plate": PLATE_TYPES,
}

# Palette order, used by the canvas.
CATEGORY_ORDER = [
    ("Reactors", "reactor"),
    ("Reservoirs", "reservoir"),
    ("Pumps", "pump"),
    ("Sensors", "sensor"),
    ("Routing", "routing"),
    ("Sampling", "sampling"),
    ("Plates", "plate"),
]

# -- typed connections -----------------------------------------------------
#
# A line means something. LINE_RULES declares which source category may feed
# which target category on each line type, so the canvas can refuse a
# connection that makes no physical sense (media bottle -> OD sensor).

LINE_TYPES = {
    "media":   {"label": "Media / feed", "color": "#5a8ac4", "dashed": False},
    "culture": {"label": "Culture transfer", "color": "#c48a5a", "dashed": False},
    "sample":  {"label": "Sample line", "color": "#8a7ab5", "dashed": False},
    "waste":   {"label": "Waste", "color": "#7c7c8a", "dashed": False},
    "data":    {"label": "Data / control", "color": "#5aa88a", "dashed": True},
}

# line kind -> {allowed source categories} -> {allowed target categories}
LINE_RULES = {
    "media": ({"reservoir", "pump"}, {"pump", "reactor"}),
    "culture": ({"reactor", "pump", "routing"}, {"reactor", "pump", "routing"}),
    # A harvest pot is a legitimate sampling source, and the sample pump sits
    # between the selector outlet and the needle.
    "sample": ({"reactor", "reservoir", "routing", "sampling", "pump"},
               {"routing", "sampling", "plate", "pump"}),
    "waste": ({"reactor", "pump", "routing"}, {"pump", "reservoir"}),
    "data": ({"sensor", "reactor", "routing", "sampling", "pump"},
             {"sensor", "reactor", "routing", "sampling", "pump"}),
}

# Legacy networks stored kind="flow"; treat it as unchecked rather than invalid.
LEGACY_KINDS = {"flow", "control"}


def line_allowed(kind: str, source_category: str, target_category: str) -> bool:
    """True if this line type may join these two categories."""
    if kind in LEGACY_KINDS:
        return True
    rule = LINE_RULES.get(kind)
    if not rule:
        return False
    sources, targets = rule
    return source_category in sources and target_category in targets


def port_count(category: str, type_id: str) -> int:
    """Number of addressable ports on a device, 0 if it has none."""
    return get_type(category, type_id).get("ports", 0)


def plate_wells(category: str, type_id: str) -> list[str]:
    """Well names for a plate, row-major: A1, A2, ... """
    t = get_type(category, type_id)
    rows, cols = t.get("rows", 0), t.get("cols", 0)
    return [
        f"{chr(ord('A') + r)}{c + 1}"
        for r in range(rows)
        for c in range(cols)
    ]


def get_type(category: str, type_id: str) -> dict:
    """Look up a unit type definition by category and id."""
    return CATEGORY_MAP.get(category, {}).get(type_id, {})


def list_types(category: str) -> list:
    """Return all types in a category as (id, definition) tuples."""
    return list(CATEGORY_MAP.get(category, {}).items())


def default_dims(category: str, type_id: str) -> tuple[int, int]:
    t = get_type(category, type_id)
    return (t.get("width", 120), t.get("height", 100))


def get_port_pos(unit, role: str, other_unit=None, port: int | None = None,
                 kind: str | None = None) -> tuple[float, float]:
    """Return canvas (x, y) for the connection port on a unit.

    role: 'source' — use an outward port; 'target' — use an inward port.
    other_unit: the unit on the other end, used to pick the best side.
    port: for multi-port devices, which numbered port this line uses.
    kind: what the line carries; lets a unit keep one dedicated spot per
        line type so two tubes never share an anchor.
    """
    import math
    w, h = default_dims(unit.category, unit.type_id)
    cx, cy = unit.x + w / 2, unit.y + h / 2

    if unit.category == "routing":
        n = port_count(unit.category, unit.type_id) or 1
        if role == "target" and port:
            # Land on the actual inlet, matching the cartoon's port blocks.
            slot = w / n
            return (unit.x + slot * (port - 0.5), unit.y + h * 0.10)
        if role == "source":
            return (unit.x + w, cy)          # common outlet
        return (cx, unit.y + h * 0.10)

    if unit.category == "reservoir":
        # Leave from whichever end faces the other unit, so feed lines run
        # straight down instead of looping back over the bottle.
        if other_unit is not None:
            oh = default_dims(other_unit.category, other_unit.type_id)[1]
            if other_unit.y + oh / 2 > cy:
                return (unit.x + w * 0.5, unit.y + h)
        return (unit.x + w * 0.5, unit.y + h * 0.07)

    if unit.category == "sampling" and unit.type_id == "robot_arm":
        # The tube plugs into the base plate the machine stands on, not the
        # bounding box - anchoring mid-air reads as a cut hose.
        bx, by = unit.x + w * 0.24, unit.y + h * 0.88
        if other_unit is not None:
            ow = default_dims(other_unit.category, other_unit.type_id)[0]
            if other_unit.x + ow / 2 > cx:
                return (bx + w * 0.19, by)
        return (bx - w * 0.19, by)

    if unit.category in ("sampling", "plate"):
        if other_unit is not None:
            ow = default_dims(other_unit.category, other_unit.type_id)[0]
            ocx = other_unit.x + ow / 2
            return ((unit.x, cy) if ocx < cx else (unit.x + w, cy))
        return (unit.x, cy)

    if unit.category == "sensor":
        return (unit.x + w * 0.5, unit.y)

    if unit.category == "pump":
        # Peristaltic pump has tube legs; other types use bounding box edges
        tid = getattr(unit, "type_id", "peristaltic")
        if tid == "peristaltic":
            pcx = unit.x + w / 2
            pcy = unit.y + h * 0.45
            radius = min(w, h) * 0.3
            tube_r = radius + 8
            left_leg = (pcx - tube_r - 4, pcy + tube_r * 0.5 + 6)
            right_leg = (pcx + tube_r + 4, pcy + tube_r * 0.5 + 6)
            if other_unit:
                ow = default_dims(other_unit.category, other_unit.type_id)[0]
                ocx = other_unit.x + ow / 2
                if abs(ocx - pcx) < w * 0.9:
                    # Both neighbours sit above/below (a vertical feed
                    # chain): split the legs by role so the in and out
                    # tubes never share one anchor.
                    return right_leg if role == "target" else left_leg
                return left_leg if ocx < cx else right_leg
            return right_leg
        if other_unit:
            ow, oh = default_dims(other_unit.category, other_unit.type_id)
            ocx, ocy = other_unit.x + ow / 2, other_unit.y + oh / 2
            dx, dy = ocx - cx, ocy - cy
            if abs(dy) > abs(dx) * 1.2:
                if dy < 0:
                    return (unit.x + w * 0.5, unit.y)
                return (unit.x + w * 0.5, unit.y + h)
            if dx < 0:
                return (unit.x, unit.y + h * 0.5)
            return (unit.x + w, unit.y + h * 0.5)
        return (unit.x + w, unit.y + h * 0.5)

    if unit.category == "reactor":
        # Sensors read the vessel body, not the cap.
        if other_unit and other_unit.category == "sensor":
            ow = default_dims(other_unit.category, other_unit.type_id)[0]
            ocx = other_unit.x + ow / 2
            frac = max(0.2, min(0.8, (ocx - unit.x) / w))
            return (unit.x + w * frac, unit.y + h)

        # Every liquid line enters and leaves through the cap on the vial,
        # the way it does on a real Pioreactor - never off the housing edge.
        # The vial spans 0.32-0.68 of the unit, so all slots live in there.
        cap_y = unit.y + h * 0.11
        if other_unit is None:
            return (unit.x + w * 0.50, cap_y)

        ow, oh = default_dims(other_unit.category, other_unit.type_id)
        ocx, ocy = other_unit.x + ow / 2, other_unit.y + oh / 2

        # One dedicated cap slot per line type: culture hugs the vial edges,
        # feed and sample take the middle. Keeps every tube's anchor apart.
        if kind in ("culture", "waste"):
            frac = 0.36 if ocx < cx else 0.64
        elif kind == "media":
            frac = 0.455
        elif kind == "sample":
            frac = 0.545
        elif abs(ocx - cx) < w * 0.35:
            frac = 0.50                      # roughly above or below
        else:
            frac = 0.37 if ocx < cx else 0.63
        return (unit.x + w * frac, cap_y)

    return (cx, cy)


def port_tangent(unit, px: float, py: float,
                 kind: str | None = None) -> tuple[float, float]:
    """Unit-length direction vector pointing outward from a port."""
    import math
    w, h = default_dims(unit.category, unit.type_id)
    cx, cy = unit.x + w / 2, unit.y + h / 2

    # Devices with a flat face should leave perpendicular to it, otherwise a
    # port near the middle gives an almost-random direction and lines cross.
    if unit.category == "routing":
        return (1.0, 0.0) if px >= unit.x + w - 1 else (0.0, -1.0)
    if unit.category == "reservoir":
        return (0.0, 1.0) if py >= unit.y + h - 1 else (0.0, -1.0)
    if unit.category in ("sampling", "plate"):
        return (-1.0, 0.0) if px < cx else (1.0, 0.0)

    if unit.category == "reactor" and py < unit.y + h * 0.3:
        # Tubing leaves the cap upward, then drapes away to the side.
        # Feed and sample lines run to things above/below, so they rise
        # nearly straight; culture lines drape hard toward their pump.
        if kind == "sample":
            lean = 0.0                       # straight up, then dive
        elif kind == "media":
            lean = 0.12 if px > cx else -0.12
        else:
            lean = -0.55 if px < cx else (0.55 if px > cx else 0.0)
        n = math.hypot(lean, 1.0)
        return (lean / n, -1.0 / n)

    dx, dy = px - cx, py - cy
    length = math.sqrt(dx * dx + dy * dy) or 1.0
    return (dx / length, dy / length)
