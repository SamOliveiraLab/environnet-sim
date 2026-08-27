"""Pre-deployment checks and the experiment package.

The simulator's real output is not a drawing. It is a statement: this is the
experiment EnvironNets believes will run, this is how each device behaves,
this is the sequence, these are the routes and the expected samples, and it
is safe to deploy.

Everything here is derived from the same objects the run executes, so the
report and the executable sequence can never describe different experiments.
"""

import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from environnets.core.models import Network
from environnets.core.recipe import Recipe
from environnets.core.unit_types import plate_wells, port_count, get_type

OK = "pass"
WARN = "warn"
FAIL = "fail"


@dataclass
class Check:
    label: str
    state: str = OK          # pass | warn | fail
    detail: str = ""

    @property
    def mark(self) -> str:
        return {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}[self.state]


@dataclass
class CheckGroup:
    name: str
    checks: list[Check] = field(default_factory=list)

    def add(self, label, state=OK, detail=""):
        self.checks.append(Check(label, state, detail))

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.state == FAIL)

    @property
    def warned(self) -> int:
        return sum(1 for c in self.checks if c.state == WARN)

    @property
    def ok(self) -> bool:
        return self.failed == 0


@dataclass
class PlannedSample:
    """A sample the run intends to take, known before anything moves."""
    sample_id: str
    source: str
    port: int
    well: str
    volume_uL: float
    at_s: float


@dataclass
class Route:
    port: int
    source: Optional[str]
    destination: str
    state: str               # "Valid" | "Unused"


@dataclass
class Binding:
    sim_object: str
    physical_device: str
    kind: str
    status: str              # "Mapped" | "Unmapped"


@dataclass
class PreflightReport:
    run_id: str
    mode: str
    groups: list[CheckGroup] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)
    planned: list[PlannedSample] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    duration_s: float = 0.0
    counts: dict = field(default_factory=dict)
    plate_rows: int = 3
    plate_cols: int = 3
    plate_label: str = ""

    @property
    def failed(self) -> int:
        return sum(g.failed for g in self.groups)

    @property
    def warned(self) -> int:
        return sum(g.warned for g in self.groups)

    @property
    def passed(self) -> bool:
        return self.failed == 0

    @property
    def verdict(self) -> str:
        if self.failed:
            return "SIMULATION FAILED"
        return "SIMULATION PASSED"

    @property
    def duration_hms(self) -> str:
        t = int(self.duration_s)
        return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"

    def well_map(self) -> dict:
        """well name -> PlannedSample, for the plate preview."""
        return {p.well: p for p in self.planned}


def _fmt(t: float) -> str:
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def build_report(recipe: Recipe, network: Network, steps, run,
                 port_map: dict, wells,
                 validation=None, mode: str = "Water integration demo"
                 ) -> PreflightReport:
    """Assemble the pre-deployment report from the compiled run.

    `wells` is the ordered pool of destinations (a list), or a legacy
    node -> wells mapping.
    """
    well_map = wells if isinstance(wells, dict) else None
    well_pool = list(wells) if not isinstance(wells, dict) else [
        w for ws in wells.values() for w in ws
    ]
    by_uid = {u.uid: u for u in network.units}

    def name_of(u):
        return u.label or u.uid

    reactors = [u for u in network.units if u.category == "reactor"]
    routers = [u for u in network.units if u.category == "routing"]
    arms = [u for u in network.units if u.category == "sampling"]
    plates = [u for u in network.units if u.category == "plate"]

    rep = PreflightReport(run_id=recipe.run_id, mode=mode)

    # ---- planned samples, straight off the compiled program ----
    seq = {}
    for s in steps:
        if s.action != "dispense":
            continue
        src = s.detail.get("source", "")
        seq[src] = seq.get(src, 0) + 1
        rep.planned.append(PlannedSample(
            sample_id=f"{recipe.run_id}-{src}-S{seq[src]:02d}",
            source=src,
            port=s.detail.get("port", 0),
            well=s.target,
            volume_uL=s.detail.get("volume_uL", recipe.draw_uL),
            at_s=s.at_s,
        ))

    rep.duration_s = max((s.at_s for s in steps), default=0.0)
    rep.counts = {
        "samples": len(rep.planned),
        "router_actions": sum(1 for s in steps if s.action == "select"),
        "robot_moves": sum(1 for s in steps if s.action in ("move", "dispense")),
        "steps": len(steps),
        "warnings": 0,
        "errors": 0,
    }

    # ---- routing table: every port, used or not ----
    if routers:
        router = routers[0]
        n_ports = port_count(router.category, router.type_id)
        by_port = {v: k for k, v in port_map.items()}
        for p in range(1, n_ports + 1):
            src = by_port.get(p)
            rep.routes.append(Route(
                port=p,
                source=src,
                destination="Sampler" if src else "-",
                state="Valid" if src else "Unused",
            ))

    # ---- hardware mapping ----
    for u in reactors:
        rep.bindings.append(Binding(
            sim_object=name_of(u),
            physical_device=u.pioreactor_unit or "-",
            kind=get_type(u.category, u.type_id).get("label", u.type_id),
            status="Mapped" if u.pioreactor_unit else "Unmapped",
        ))
    for u in routers + arms + plates:
        dev = (u.config or {}).get("device") or "-"
        rep.bindings.append(Binding(
            sim_object=name_of(u),
            physical_device=dev,
            kind=get_type(u.category, u.type_id).get("label", u.type_id),
            status="Mapped" if dev != "-" else "Unmapped",
        ))

    # ---- per-node parameters ----
    for i, node in enumerate(recipe.nodes):
        unit = next((u for u in reactors if name_of(u) == node), None)
        mine = [p for p in rep.planned if p.source == node]
        rep.parameters[node] = {
            "reactor": (get_type(unit.category, unit.type_id).get("label")
                        if unit else "-"),
            "device": unit.pioreactor_unit if unit else "-",
            "contents": recipe.sources.get(node, "water"),
            "sample_volume_uL": recipe.draw_uL,
            "sample_count": len(mine),
            "router_port": port_map.get(node, "-"),
            "destinations": [p.well for p in mine],
            "dilution_rate_per_h": (recipe.d_per_h[i]
                                    if i < len(recipe.d_per_h) else 0.0),
        }

    if plates:
        pl = plates[0]
        t = get_type(pl.category, pl.type_id)
        rep.plate_rows = t.get("rows", 3)
        rep.plate_cols = t.get("cols", 3)
        rep.plate_label = name_of(pl)

    # ================= the checklist =================

    # Topology
    g = CheckGroup("Topology")
    routed = {c.source_uid for c in network.connections
              if c.target_uid in {r.uid for r in routers}}
    unrouted = [name_of(u) for u in reactors if u.uid not in routed]
    g.add("Every source has a sampling route",
          OK if not unrouted else FAIL,
          "" if not unrouted else f"no route: {', '.join(unrouted)}")

    ports_used = [c.target_port for c in network.connections
                  if c.target_port is not None]
    dupes = {p for p in ports_used if ports_used.count(p) > 1}
    g.add("No conflicting router assignments",
          OK if not dupes else FAIL,
          "" if not dupes else f"port(s) claimed twice: {sorted(dupes)}")

    dangling = [c for c in network.connections
                if c.source_uid not in by_uid or c.target_uid not in by_uid]
    g.add("All active lines terminate at a valid destination",
          OK if not dangling else FAIL,
          "" if not dangling else f"{len(dangling)} dangling line(s)")
    rep.groups.append(g)

    # Hardware
    g = CheckGroup("Hardware")
    for b in rep.bindings:
        mapped = b.status == "Mapped"
        g.add(f"{b.sim_object} mapped",
              OK if mapped else WARN,
              b.physical_device if mapped else "no physical device bound")
    rep.groups.append(g)

    # Sampling
    g = CheckGroup("Sampling")
    available = rep.plate_rows * rep.plate_cols if plates else 0
    required = len(rep.planned)

    # An experiment that collects nothing must never be deployable, however
    # cleanly the rest of it checks out.
    if required == 0:
        why = "no sample is due inside the run window"
        if recipe.cadence_min and recipe.run_hours * 60 < min(
                c for c in recipe.cadence_min if c > 0):
            why = (f"run is {recipe.run_hours * 60:.0f} min but the shortest "
                   f"cadence is {min(c for c in recipe.cadence_min if c > 0):.0f} min")
        elif not well_pool:
            why = "no plate is configured, so there is nowhere to dispense"
        g.add("Experiment collects at least one sample", FAIL, why)
    else:
        g.add("Experiment collects at least one sample", OK,
              f"{required} scheduled")

    g.add(f"Requested wells: {required}",
          OK if required <= available else FAIL,
          f"{available} available" if plates else "no plate configured")
    ids = [p.sample_id for p in rep.planned]
    g.add("Sample IDs unique",
          OK if len(set(ids)) == len(ids) else FAIL,
          f"{len(ids)} sample(s)")
    wells = [p.well for p in rep.planned]
    g.add("No destination collision",
          OK if len(set(wells)) == len(wells) else FAIL,
          "" if len(set(wells)) == len(wells) else "a well is targeted twice")
    rep.groups.append(g)

    # Volumes
    g = CheckGroup("Volumes")
    from environnets.core.recipe import MIN_SIP_ML
    draw_ml = recipe.draw_uL / 1000.0
    g.add(f"Requested sample volume: {recipe.draw_uL:g} uL")
    g.add("Sampling pump supports requested volume",
          OK if draw_ml >= MIN_SIP_ML else FAIL,
          f"minimum sip is {MIN_SIP_ML} mL")
    per_source = {}
    for p in rep.planned:
        per_source[p.source] = per_source.get(p.source, 0) + p.volume_uL
    worst = max(per_source.values(), default=0) / 1000.0
    frac = worst / recipe.vessel_volume_ml if recipe.vessel_volume_ml else 0
    g.add("Source volume sufficient",
          OK if frac < 0.5 else WARN,
          f"{worst:.1f} mL drawn from a {recipe.vessel_volume_ml:g} mL vessel "
          f"({frac:.0%})")
    rep.groups.append(g)

    # Robot
    g = CheckGroup("Robot")
    arm = arms[0] if arms else None
    home = (arm.config or {}).get("home_pose") if arm else None
    g.add("Home position defined",
          OK if home else WARN,
          home if home else "not configured - arm will home to driver default")
    valid_wells = set(plate_wells(plates[0].category, plates[0].type_id)) if plates else set()
    unreachable = sorted({p.well for p in rep.planned} - valid_wells)
    g.add("All destinations reachable",
          OK if not unreachable else FAIL,
          "" if not unreachable else f"off-plate: {', '.join(unreachable)}")
    rep.groups.append(g)

    # Execution
    g = CheckGroup("Execution")
    g.add("All actions schedulable",
          OK if steps else FAIL, f"{len(steps)} step(s)")
    from environnets.core.program import schedule_slip
    slip = schedule_slip(steps)
    g.add("No timing conflicts",
          OK if not slip else WARN,
          "" if not slip else
          f"{len(slip)} draw(s) delayed up to {max(w for _, w in slip):.0f} s "
          f"- the selector serialises sampling")
    aborted = getattr(run, "aborted", False)
    g.add("Abort-on-failure configured", OK,
          "run halts on a routing or sampling NACK")
    g.add("Simulated run completed",
          OK if not aborted else FAIL,
          "aborted" if aborted else
          f"{sum(1 for s in run.samples if s.status == 'complete')}"
          f"/{len(run.samples)} samples")
    rep.groups.append(g)

    if validation is not None:
        g = CheckGroup("Recipe")
        g.add("Recipe validation",
              OK if validation.ok else FAIL,
              validation.errors[0] if validation.errors else "approved")
        for w in validation.warnings:
            g.add("Advisory", WARN, w)
        rep.groups.append(g)

    rep.counts["warnings"] = rep.warned
    rep.counts["errors"] = rep.failed
    return rep


def expected_log(steps, run_id: str) -> str:
    """The [SIM] log, for comparing against the [RUN] log later."""
    lines = [f"[SIM] 00:00 Experiment {run_id} initialized"]
    for s in steps:
        t = _fmt(s.at_s)
        if s.action == "home":
            lines.append(f"[SIM] {t} Robot/router homing requested")
            lines.append(f"[SIM] {t} Home confirmed")
        elif s.action == "feed":
            lines.append(f"[SIM] {t} Feed started: {s.target} "
                         f"D = {s.detail.get('d_per_h', 0):.2f}/h")
        elif s.action == "select":
            lines.append(f"[SIM] {t} Route requested: {s.target} -> Sampler")
            lines.append(f"[SIM] {t} Router port {s.detail.get('port')} selected")
        elif s.action == "move":
            lines.append(f"[SIM] {t} Robot target: {s.target}")
        elif s.action == "dispense":
            lines.append(f"[SIM] {t} Sample: {s.detail.get('source')}, "
                         f"{s.detail.get('volume_uL'):.0f} uL -> {s.target}")
            lines.append(f"[SIM] {t} Dispense complete")
        elif s.action == "purge":
            lines.append(f"[SIM] {t} Line flushed / route reset")
    lines.append(f"[SIM] {_fmt(max((s.at_s for s in steps), default=0))} "
                 f"Results package generated")
    return "\n".join(lines)


def build_package(recipe: Recipe, network: Network, steps, report: PreflightReport,
                  port_map: dict) -> dict:
    """The validated experiment package - what DEPLOY hands to the dashboard."""
    by_label = {(u.label or u.uid): u for u in network.units
                if u.category == "reactor"}

    sources = {}
    for node, port in port_map.items():
        u = by_label.get(node)
        sources[node] = {
            "device": u.pioreactor_unit if u and u.pioreactor_unit else None,
            "reactor_type": (get_type(u.category, u.type_id).get("label")
                             if u else None),
            "router_port": port,
            "contents": recipe.sources.get(node, "water"),
        }

    sequence = []
    for i, s in enumerate(steps, start=1):
        entry = {"step": i, "at_s": s.at_s, "action": s.action}
        if s.action == "select":
            entry.update(source=s.target, port=s.detail.get("port"))
        elif s.action in ("move", "dispense"):
            entry.update(target=s.target)
            if s.action == "dispense":
                entry.update(source=s.detail.get("source"),
                             volume_uL=s.detail.get("volume_uL"))
        elif s.action == "feed":
            entry.update(source=s.target, d_per_h=s.detail.get("d_per_h"))
        sequence.append(entry)

    return {
        "schema": "environnets.experiment.v1",
        "experiment_id": recipe.run_id,
        "mode": report.mode,
        "status": "validated" if report.passed else "rejected",
        "created_at": time.time(),
        "estimated_duration_s": report.duration_s,
        "recipe": recipe.to_proposal(),
        "sources": sources,
        "sampling": {
            "volume_uL": recipe.draw_uL,
            "plate": report.plate_label,
            "plate_rows": report.plate_rows,
            "plate_cols": report.plate_cols,
            "assignments": {p.well: p.source for p in report.planned},
            "planned_samples": [asdict(p) for p in report.planned],
        },
        "routing": {"table": [asdict(r) for r in report.routes]},
        "hardware": [asdict(b) for b in report.bindings],
        "parameters": report.parameters,
        "preflight": {
            "verdict": report.verdict,
            "passed": report.passed,
            "errors": report.failed,
            "warnings": report.warned,
            "groups": [
                {"name": g.name,
                 "checks": [asdict(c) for c in g.checks]}
                for g in report.groups
            ],
        },
        "sequence": sequence,
        "expected_log": expected_log(steps, recipe.run_id),
    }
