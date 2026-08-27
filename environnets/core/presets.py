"""Prebuilt network assemblies.

Dragging a preset drops a complete, already-wired setup onto the canvas:
units placed, lines typed, router ports claimed. Everything stays ordinary
after it lands, so it can be edited, extended or pulled apart like anything
else that was drawn by hand.

Positions are relative to the drop point, in canvas units.
"""

from dataclasses import dataclass, field


@dataclass
class PresetUnit:
    key: str            # local name, used to wire connections below
    category: str
    type_id: str
    label: str
    dx: float
    dy: float


@dataclass
class PresetLink:
    source: str         # PresetUnit.key
    target: str
    kind: str
    target_port: int | None = None


@dataclass
class Preset:
    preset_id: str
    label: str
    description: str
    units: list[PresetUnit] = field(default_factory=list)
    links: list[PresetLink] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return f"{len(self.units)} units, {len(self.links)} connections"


WATER_DEMO = Preset(
    preset_id="water_demo",
    label="Water demo",
    description=(
        "Three reactors sampled through the 8-port selector into the 3x3 demo "
        "plate. The Friday integration setup."
    ),
    # Reactors in a row above the router: ports 1-3 then sit left-to-right in
    # the same order as their sources, so no two sample lines cross.
    units=[
        PresetUnit("b1", "reactor", "pio_20ml", "B1", 0, 0),
        PresetUnit("b2", "reactor", "pio_20ml", "B2", 230, 0),
        PresetUnit("b3", "reactor", "pio_20ml", "B3", 460, 0),
        PresetUnit("router", "routing", "selector_8", "Router", 200, 300),
        # Plate sits inside the arm's reach, the way it would on the bench.
        # It is listed before the arm so the arm draws on top and the needle
        # reads as hovering over the wells rather than behind them.
        PresetUnit("plate", "plate", "plate_3x3", "Demo plate", 550, 345),
        PresetUnit("arm", "sampling", "robot_arm", "Arm", 470, 250),
    ],
    links=[
        PresetLink("b1", "router", "sample", 1),
        PresetLink("b2", "router", "sample", 2),
        PresetLink("b3", "router", "sample", 3),
        PresetLink("router", "arm", "sample"),
        PresetLink("arm", "plate", "sample"),
    ],
)


SINGLE_CHEMOSTAT = Preset(
    preset_id="single_chemostat",
    label="Single chemostat",
    description=(
        "One reactor with media in, waste out, and the standard sensor set. "
        "The smallest thing that runs."
    ),
    units=[
        PresetUnit("media", "reservoir", "media_bottle", "Media", 0, 40),
        PresetUnit("pin", "pump", "peristaltic", "Media pump", 170, 60),
        PresetUnit("r1", "reactor", "pio_20ml", "B1", 340, 20),
        PresetUnit("pout", "pump", "peristaltic", "Waste pump", 540, 60),
        PresetUnit("waste", "reservoir", "waste_bottle", "Waste", 710, 40),
        PresetUnit("od", "sensor", "od", "OD", 320, 250),
        PresetUnit("temp", "sensor", "temperature", "Temperature", 430, 250),
    ],
    links=[
        PresetLink("media", "pin", "media"),
        PresetLink("pin", "r1", "media"),
        PresetLink("r1", "pout", "waste"),
        PresetLink("pout", "waste", "waste"),
        PresetLink("od", "r1", "data"),
        PresetLink("temp", "r1", "data"),
    ],
)


DECK_CASCADE = Preset(
    preset_id="deck_cascade",
    label="B1 - B2 - B3 cascade",
    description=(
        "The serial cascade from Figure 1 with its four feeds, sampled to a "
        "96-well plate. Note the selector cannot hold the cascade open "
        "continuously - validation will say so."
    ),
    units=[
        PresetUnit("xyl", "reservoir", "media_bottle", "Xylose", 0, 0),
        PresetUnit("glu", "reservoir", "media_bottle", "Glucose", 150, 0),
        PresetUnit("pcoum", "reservoir", "media_bottle", "p-coumarate", 300, 0),
        PresetUnit("buf", "reservoir", "media_bottle", "Buffer", 450, 0),
        PresetUnit("b1", "reactor", "pio_20ml", "B1", 0, 220),
        PresetUnit("b2", "reactor", "pio_20ml", "B2", 230, 220),
        PresetUnit("b3", "reactor", "pio_20ml", "B3", 460, 220),
        PresetUnit("out", "reservoir", "waste_bottle", "OUT", 700, 240),
        PresetUnit("router", "routing", "selector_8", "Router", 200, 470),
        PresetUnit("arm", "sampling", "robot_arm", "Arm", 470, 455),
        PresetUnit("plate", "plate", "plate_96", "Plate", 690, 470),
    ],
    links=[
        PresetLink("xyl", "b1", "media"),
        PresetLink("glu", "b2", "media"),
        PresetLink("pcoum", "b3", "media"),
        PresetLink("b1", "b2", "culture"),
        PresetLink("b2", "b3", "culture"),
        PresetLink("b3", "out", "waste"),
        PresetLink("b1", "router", "sample", 1),
        PresetLink("b2", "router", "sample", 2),
        PresetLink("b3", "router", "sample", 3),
        PresetLink("router", "arm", "sample"),
        PresetLink("arm", "plate", "sample"),
    ],
)


BENCH = Preset(
    preset_id="bench",
    label="Full bench",
    description=(
        "The whole rig as it sits on the bench. Production runs left to right "
        "along the reactor row; sampling drops from every vessel into the "
        "selector, out one line to the needle, and into the plate."
    ),
    units=[
        # Feed row: each pump with its bottle beside it, the pair sitting
        # up and to the right of the reactor it feeds. The tube leaves the
        # bottle's cap (dip tube), loops over to the pump, and the pump
        # line swings down into the reactor cap.
        PresetUnit("p1", "pump", "peristaltic", "P1 feed", 135, 90),
        PresetUnit("xyl", "reservoir", "media_bottle", "Xylose", 335, 70),
        PresetUnit("p2", "pump", "peristaltic", "P2 feed", 515, 90),
        PresetUnit("glu", "reservoir", "media_bottle", "Glucose", 715, 70),
        PresetUnit("p3", "pump", "peristaltic", "P3 feed", 895, 90),
        PresetUnit("pcoum", "reservoir", "media_bottle", "p-coumarate", 1095, 70),

        # Reactor row: production flows along it, B1 -> B2 -> B3 -> OUT.
        PresetUnit("b1", "reactor", "pio_20ml", "B1", 0, 340),
        PresetUnit("b2", "reactor", "pio_20ml", "B2", 380, 340),
        PresetUnit("b3", "reactor", "pio_20ml", "B3", 760, 340),
        # The harvest pot sits a step lower - gravity drain - which also
        # keeps its sample line out of the router's unused ports.
        PresetUnit("out", "reservoir", "waste_bottle", "OUT", 1140, 440),

        # Transfer pumps ride high in the gaps, level with the caps they
        # connect, leaving the space below clear for the sample lines.
        PresetUnit("pt1", "pump", "peristaltic", "P4 transfer", 224, 300),
        PresetUnit("pt2", "pump", "peristaltic", "P5 transfer", 604, 300),
        PresetUnit("pt3", "pump", "peristaltic", "P6 harvest", 980, 300),

        # Sampling row, centred under the span it serves. Ports 1-4 sit left
        # to right under their own sources, so no two sample lines cross.
        PresetUnit("router", "routing", "selector_8", "Router", 460, 720),
        PresetUnit("ps", "pump", "peristaltic", "P7 sample", 760, 720),
        PresetUnit("plate", "plate", "plate_96", "Plate", 980, 760),
        PresetUnit("arm", "sampling", "robot_arm", "Arm", 920, 660),
    ],
    links=[
        # feeds: bottle -> pump -> reactor
        PresetLink("xyl", "p1", "media"),
        PresetLink("p1", "b1", "media"),
        PresetLink("glu", "p2", "media"),
        PresetLink("p2", "b2", "media"),
        PresetLink("pcoum", "p3", "media"),
        PresetLink("p3", "b3", "media"),
        # production train, each transfer driven by its own pump
        PresetLink("b1", "pt1", "culture"),
        PresetLink("pt1", "b2", "culture"),
        PresetLink("b2", "pt2", "culture"),
        PresetLink("pt2", "b3", "culture"),
        PresetLink("b3", "pt3", "waste"),
        PresetLink("pt3", "out", "waste"),
        # sampling: every vessel, including the harvest pot, has a port
        PresetLink("b1", "router", "sample", 1),
        PresetLink("b2", "router", "sample", 2),
        PresetLink("b3", "router", "sample", 3),
        PresetLink("out", "router", "sample", 4),
        # one outlet, one sample pump, one needle
        PresetLink("router", "ps", "sample"),
        PresetLink("ps", "arm", "sample"),
        PresetLink("arm", "plate", "sample"),
    ],
)


PRESETS = {
    p.preset_id: p
    for p in (BENCH, WATER_DEMO, SINGLE_CHEMOSTAT, DECK_CASCADE)
}

PRESET_ORDER = ["bench", "water_demo", "single_chemostat", "deck_cascade"]


def get_preset(preset_id: str) -> Preset | None:
    return PRESETS.get(preset_id)


def list_presets() -> list[Preset]:
    return [PRESETS[p] for p in PRESET_ORDER if p in PRESETS]


def instantiate(preset: Preset, x: float, y: float,
                existing_labels: set[str] | None = None):
    """Build real Units and Connections for a preset dropped at (x, y).

    Labels that already exist on the canvas get a numeric suffix so dropping
    the same preset twice does not produce two reactors both called B1 -
    the recipe addresses nodes by label, so duplicates would be ambiguous.
    """
    import uuid
    from environnets.core.models import Unit, Connection
    from environnets.core.unit_types import default_dims

    existing = set(existing_labels or ())

    # Centre the assembly on the cursor.
    span_x = max((u.dx for u in preset.units), default=0)
    span_y = max((u.dy for u in preset.units), default=0)
    ox = x - span_x / 2
    oy = y - span_y / 2

    def unique(label: str) -> str:
        if label not in existing:
            existing.add(label)
            return label
        n = 2
        while f"{label}-{n}" in existing:
            n += 1
        new = f"{label}-{n}"
        existing.add(new)
        return new

    uid_of: dict[str, str] = {}
    units: list[Unit] = []
    for pu in preset.units:
        uid = f"u-{uuid.uuid4().hex[:6]}"
        uid_of[pu.key] = uid
        units.append(Unit(
            uid=uid,
            kind=pu.category,
            label=unique(pu.label),
            x=ox + pu.dx,
            y=oy + pu.dy,
            category=pu.category,
            type_id=pu.type_id,
        ))

    connections = [
        Connection(
            source_uid=uid_of[l.source],
            target_uid=uid_of[l.target],
            kind=l.kind,
            target_port=l.target_port,
        )
        for l in preset.links
        if l.source in uid_of and l.target in uid_of
    ]

    return units, connections
