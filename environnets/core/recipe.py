"""Experiment recipe: the contract between the model and the bench.

A recipe is what the GEM/FBA layer proposes and what the execution layer runs.
Field names follow proposal_002.json from the architecture deck (Figure 1) so a
file written by the model loads here unchanged.

The loop is: model proposes -> validate() -> approved recipe -> bench executes.
validate() is step 2 of Figure 1, the safety check that "refuses anything the
pumps cannot deliver or that washes the culture out".
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from environnets.core.models import Network, Unit, Connection

SCHEMA = "environnets.recipe.v1"

# Hardware limits from the deck's pump manifold spec (Figure 2).
MIN_SIP_ML = 0.1            # smallest volume a peristaltic head can meter
MAX_DOSE_ML_PER_2S = 3.56   # throughput ceiling of one head

# Growth ceilings used for the washout check, per organism.
MU_MAX = {"ecoli": 0.7, "yeast": 0.35}


@dataclass
class Recipe:
    """One proposed experiment, as emitted by the model layer."""

    run_id: str
    nodes: list[str] = field(default_factory=list)
    edges: list[list[str]] = field(default_factory=list)

    model: str = ""
    iteration: int = 0
    objective: str = ""
    link: str = ""

    # Per-node carbon source, keyed by node id: {"B1": "xylose 10 g/L"}
    sources: dict = field(default_factory=dict)

    # Dilution rate per node, same order as `nodes`.
    d_per_h: list[float] = field(default_factory=list)

    draw_uL: float = 500.0
    cadence_min: list[float] = field(default_factory=list)
    plates: str = ""
    stop_rule: str = ""

    organism: str = "ecoli"
    vessel_volume_ml: float = 20.0
    run_hours: float = 24.0
    schema: str = SCHEMA
    created_at: float = field(default_factory=time.time)

    # -- deck-format interop ----------------------------------------------

    @classmethod
    def from_proposal(cls, data: dict) -> "Recipe":
        """Load the deck's proposal_002.json shape.

        Sources arrive as flat "source_B1" keys; everything else maps directly.
        """
        sources = {
            k.removeprefix("source_"): v
            for k, v in data.items()
            if k.startswith("source_")
        }
        return cls(
            run_id=data.get("run_id", ""),
            nodes=list(data.get("nodes", [])),
            edges=[list(e) for e in data.get("edges", [])],
            model=data.get("model", ""),
            iteration=int(data.get("iteration", 0)),
            objective=data.get("objective", ""),
            link=data.get("link", ""),
            sources=sources,
            d_per_h=list(data.get("D_per_h", [])),
            draw_uL=float(data.get("draw_uL", 500.0)),
            cadence_min=list(data.get("cadence_min", [])),
            plates=data.get("plates", ""),
            stop_rule=data.get("stop_rule", ""),
            organism=data.get("organism", "ecoli"),
            vessel_volume_ml=float(data.get("vessel_volume_ml", 20.0)),
            run_hours=float(data.get("run_hours", 24.0)),
        )

    def to_proposal(self) -> dict:
        """Emit the deck's proposal_002.json shape."""
        out = {
            "run_id": self.run_id,
            "model": self.model,
            "iteration": self.iteration,
            "objective": self.objective,
            "nodes": self.nodes,
            "edges": self.edges,
            "link": self.link,
            "D_per_h": self.d_per_h,
            "draw_uL": self.draw_uL,
            "cadence_min": self.cadence_min,
            "plates": self.plates,
            "stop_rule": self.stop_rule,
        }
        for node, src in self.sources.items():
            out[f"source_{node}"] = src
        return out

    @classmethod
    def load(cls, path: str) -> "Recipe":
        with open(path) as fh:
            return cls.from_proposal(json.load(fh))

    def save(self, path: str):
        with open(path, "w") as fh:
            json.dump(self.to_proposal(), fh, indent=2)

    # -- network interop ---------------------------------------------------

    @classmethod
    def from_network(cls, net: Network, run_id: str = "") -> "Recipe":
        """Derive a recipe skeleton from a drawn network.

        Reactor units become nodes; flow connections between reactors become
        edges. Rates and sources still have to be filled in by the model.
        """
        reactors = [u for u in net.units if u.category == "reactor"]
        by_uid = {u.uid: u for u in reactors}
        nodes = [(u.label or u.uid) for u in reactors]

        edges = []
        for c in net.connections:
            src, tgt = by_uid.get(c.source_uid), by_uid.get(c.target_uid)
            if src and tgt:
                edges.append([src.label or src.uid, tgt.label or tgt.uid])

        return cls(
            run_id=run_id or net.network_id,
            nodes=nodes,
            edges=edges,
            d_per_h=[0.0] * len(nodes),
        )

    def dose_ml(self, node_index: int) -> Optional[float]:
        """Volume the pump must meter per dose for one node, in mL.

        dose = D * V * (cadence / 60). Returns None if inputs are missing.
        """
        try:
            d = self.d_per_h[node_index]
            cadence = self.cadence_min[min(node_index, len(self.cadence_min) - 1)]
        except (IndexError, ValueError):
            return None
        return d * self.vessel_volume_ml * (cadence / 60.0)


@dataclass
class ValidationResult:
    """Outcome of the Figure 1 safety check."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __str__(self) -> str:
        if self.ok and not self.warnings:
            return "Recipe approved."
        lines = [f"REJECTED: {e}" for e in self.errors]
        lines += [f"warning: {w}" for w in self.warnings]
        return "\n".join(lines)


def validate(recipe: Recipe, network: Optional[Network] = None) -> ValidationResult:
    """Refuse anything the pumps cannot deliver or that washes the culture out.

    Errors block execution; warnings are advisory.
    """
    r = ValidationResult()

    if not recipe.nodes:
        r.errors.append("Recipe has no nodes.")
        return r

    known = set(recipe.nodes)
    for edge in recipe.edges:
        if len(edge) != 2:
            r.errors.append(f"Edge {edge} must have exactly two endpoints.")
            continue
        for endpoint in edge:
            if endpoint not in known:
                r.errors.append(f"Edge {edge} references unknown node '{endpoint}'.")

    if len(recipe.d_per_h) != len(recipe.nodes):
        r.errors.append(
            f"D_per_h has {len(recipe.d_per_h)} entries "
            f"but there are {len(recipe.nodes)} nodes."
        )

    # Washout: a chemostat is stable only while dilution stays under growth.
    mu_max = MU_MAX.get(recipe.organism, 0.7)
    for i, node in enumerate(recipe.nodes):
        if i >= len(recipe.d_per_h):
            break
        d = recipe.d_per_h[i]
        if d < 0:
            r.errors.append(f"{node}: negative dilution rate {d}.")
        elif d >= mu_max:
            r.errors.append(
                f"{node}: D = {d:.3f}/h exceeds mu_max = {mu_max:.2f}/h "
                f"for {recipe.organism} - culture washes out."
            )
        elif d > 0.8 * mu_max:
            r.warnings.append(
                f"{node}: D = {d:.3f}/h is within 20% of mu_max "
                f"({mu_max:.2f}/h) - little margin before washout."
            )

    # Deliverability: every dose has to be inside the pump's working range.
    for i, node in enumerate(recipe.nodes):
        dose = recipe.dose_ml(i)
        if dose is None:
            continue
        if 0 < dose < MIN_SIP_ML:
            r.errors.append(
                f"{node}: dose of {dose:.3f} mL is below the pump's "
                f"{MIN_SIP_ML} mL minimum sip."
            )
        if dose > MAX_DOSE_ML_PER_2S:
            r.warnings.append(
                f"{node}: dose of {dose:.2f} mL exceeds {MAX_DOSE_ML_PER_2S} mL "
                f"per 2 s - the pump needs a longer run."
            )

    # Sampling has to leave the vessel with something in it.
    draw_ml = recipe.draw_uL / 1000.0
    if draw_ml > recipe.vessel_volume_ml * 0.1:
        r.warnings.append(
            f"Each {recipe.draw_uL:.0f} uL draw removes "
            f"{draw_ml / recipe.vessel_volume_ml:.1%} of a "
            f"{recipe.vessel_volume_ml:.0f} mL vessel."
        )

    for i, cadence in enumerate(recipe.cadence_min):
        if cadence <= 0:
            r.errors.append(f"Sampling cadence #{i + 1} must be positive.")

    # Cross-check against the drawn network, when there is one.
    if network is not None:
        _validate_network(recipe, network, r)

    return r


def _validate_network(recipe: Recipe, network: Network, r: ValidationResult):
    """Checks that need the drawn topology: units, links, routes, wells."""
    from environnets.core.unit_types import (
        line_allowed, port_count, plate_wells, get_type,
    )

    by_uid = {u.uid: u for u in network.units}

    def name_of(u):
        return u.label or u.uid

    def category_of(uid: str) -> str:
        u = by_uid.get(uid)
        return u.category if u else ""

    drawn = {name_of(u) for u in network.units if u.category == "reactor"}
    for node in recipe.nodes:
        if node not in drawn and node.upper() != "OUT":
            r.errors.append(f"Recipe node '{node}' has no reactor on the canvas.")

    for unit in network.units:
        if unit.category == "reactor" and not unit.pioreactor_unit:
            r.warnings.append(f"'{name_of(unit)}' is not linked to hardware.")

    # Typed links: refuse connections that make no physical sense.
    for c in network.connections:
        src, tgt = by_uid.get(c.source_uid), by_uid.get(c.target_uid)
        if src is None or tgt is None:
            r.errors.append("A connection references a unit that is not on the canvas.")
            continue
        if not line_allowed(c.kind, src.category, tgt.category):
            r.errors.append(
                f"{name_of(src)} ({src.category}) cannot feed "
                f"{name_of(tgt)} ({tgt.category}) on a '{c.kind}' line."
            )

    # Routing: ports must exist and may not be double-booked.
    routers = [u for u in network.units if u.category == "routing"]
    for router in routers:
        n_ports = port_count(router.category, router.type_id)
        taken: dict[int, str] = {}
        for c in network.connections:
            if c.target_uid != router.uid or c.target_port is None:
                continue
            src = by_uid.get(c.source_uid)
            label = name_of(src) if src else "?"
            if not 1 <= c.target_port <= n_ports:
                r.errors.append(
                    f"{label} is assigned to port {c.target_port}, but "
                    f"{name_of(router)} has ports 1..{n_ports}."
                )
            elif c.target_port in taken:
                r.errors.append(
                    f"Port {c.target_port} on {name_of(router)} is claimed by "
                    f"both {taken[c.target_port]} and {label}."
                )
            else:
                taken[c.target_port] = label

        # A rotary selector holds one path; a cascade needs several at once.
        limit = get_type(router.category, router.type_id).get(
            "simultaneous_routes", 1)
        if limit == 1:
            cascade = [
                c for c in network.connections
                if c.kind == "culture"
                and category_of(c.source_uid) == "reactor"
                and category_of(c.target_uid) == "reactor"
            ]
            if len(cascade) > 1 and routers:
                r.warnings.append(
                    f"{name_of(router)} can hold one route open at a time, so "
                    f"it cannot maintain {len(cascade)} continuous reactor-to-"
                    f"reactor transfers. Those need a crossbar."
                )

    # Sampling capacity: enough wells for the run.
    plates = [u for u in network.units if u.category == "plate"]
    if plates and recipe.cadence_min:
        capacity = sum(len(plate_wells(p.category, p.type_id)) for p in plates)
        per_node = []
        for i, node in enumerate(recipe.nodes):
            cadence = recipe.cadence_min[min(i, len(recipe.cadence_min) - 1)]
            if cadence > 0:
                per_node.append(int((recipe.run_hours * 60) // cadence))
        needed = sum(per_node)
        if needed > capacity:
            r.errors.append(
                f"A {recipe.run_hours:g} h run needs {needed} wells, but the "
                f"configured plates hold {capacity}."
            )

    # Every reactor that is sampled must actually reach the sampler.
    if routers:
        router_uids = {u.uid for u in routers}
        reaching = {
            by_uid[c.source_uid].uid
            for c in network.connections
            if c.target_uid in router_uids and c.source_uid in by_uid
        }
        for u in network.units:
            if u.category == "reactor" and u.uid not in reaching:
                r.warnings.append(
                    f"'{name_of(u)}' has no sample line to the router, so it "
                    f"cannot be sampled."
                )
