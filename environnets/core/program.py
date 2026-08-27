"""Compile a recipe into an ordered program, then run it.

SIMULATE and DEPLOY are the same program executed against different adapters.
That is the point: what you rehearse is what you run, and the event log has
the same shape either way, so results.json does not change form when the
hardware appears.

Step order for one sample follows the architecture notes:
    SELECT (router picks the source) -> REDIRECT (arm moves) -> DISPENSE.
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from environnets.core import events as ev
from environnets.core.events import EventLog, SampleRecord
from environnets.core.recipe import Recipe


@dataclass
class Step:
    """One scheduled action."""

    at_s: float           # seconds from run start
    action: str           # init | feed | select | move | dispense | purge | home
    target: str = ""      # node, port or well this acts on
    detail: dict = field(default_factory=dict)

    def __str__(self) -> str:
        t = f"{int(self.at_s // 3600):02d}:{int(self.at_s % 3600 // 60):02d}:{int(self.at_s % 60):02d}"
        extra = f" {self.target}" if self.target else ""
        return f"{t}  {self.action.upper()}{extra}"


# Fixed costs of the physical motions, in seconds. Rough but explicit, so the
# simulated timeline is honest about taking time rather than being instant.
SELECT_S = 2.0
MOVE_S = 3.0
DISPENSE_S = 2.0
PURGE_S = 4.0


def compile_program(recipe: Recipe, *, port_map: dict, wells=None,
                    well_map: Optional[dict] = None,
                    duration_min: float = 60.0,
                    sample_nodes: Optional[list] = None) -> list[Step]:
    """Turn a recipe into a timeline of steps.

    port_map: node -> selector port, e.g. {"B1": 1}
    wells:    ordered pool of empty wells. Each sample, in the order it comes
              due, takes the next free one - so B1/B2/B3 fill A1, A2, A3, then
              the next round continues where that left off. A well is never
              reused, which is what makes a well collision impossible rather
              than merely unlikely.
    well_map: legacy per-node well lists; used only if `wells` is not given.
    """
    steps: list[Step] = []
    nodes = sample_nodes if sample_nodes is not None else [
        n for n in recipe.nodes if n in port_map
    ]

    steps.append(Step(0.0, "init", detail={"nodes": list(recipe.nodes)}))
    steps.append(Step(0.0, "home", target="router"))

    # Feeds start once, at the top of the run.
    for i, node in enumerate(recipe.nodes):
        d = recipe.d_per_h[i] if i < len(recipe.d_per_h) else 0.0
        if d > 0:
            steps.append(Step(
                5.0, "feed", target=node,
                detail={"d_per_h": d, "dose_ml": recipe.dose_ml(i)},
            ))

    # When each sample comes due, before any well is assigned.
    due_list: list[tuple[float, str]] = []        # (due_s, node)
    for idx, node in enumerate(nodes):
        cadence_min = (
            recipe.cadence_min[idx]
            if idx < len(recipe.cadence_min)
            else (recipe.cadence_min[-1] if recipe.cadence_min else 30.0)
        )
        if cadence_min <= 0:
            continue
        limit = (len(well_map.get(node, [])) if (wells is None and well_map)
                 else 10_000)
        round_no = 1
        while round_no <= limit:
            due = round_no * cadence_min * 60.0
            if due > duration_min * 60.0:
                break
            due_list.append((due, node))
            round_no += 1

    due_list.sort(key=lambda r: (r[0], r[1]))

    # Hand out wells in the order samples come due, never reusing one.
    requests: list[tuple[float, str, str]] = []
    if wells is not None:
        pool = list(wells)
        for i, (due, node) in enumerate(due_list):
            if i >= len(pool):
                break                      # out of wells; preflight reports it
            requests.append((due, node, pool[i]))
    else:
        taken: dict[str, int] = {}
        for due, node in due_list:
            slot = taken.get(node, 0)
            node_wells = (well_map or {}).get(node, [])
            if slot >= len(node_wells):
                continue
            taken[node] = slot + 1
            requests.append((due, node, node_wells[slot]))

    # The router and the arm are one shared, exclusive resource: a selector
    # holds a single path at a time, so draws cannot overlap. Anything due
    # while the sampler is busy waits its turn rather than running in parallel.
    cycle_s = SELECT_S + MOVE_S + DISPENSE_S + PURGE_S
    sampler_free_at = 0.0
    per_source: dict[str, int] = {}

    for due, node, well in requests:
        start = max(due, sampler_free_at)
        port = port_map[node]
        per_source[node] = per_source.get(node, 0) + 1
        sample_id = f"{recipe.run_id}-{node}-S{per_source[node]:02d}"

        steps.append(Step(start, "select", target=node,
                          detail={"port": port, "due_s": due,
                                  "waited_s": round(start - due, 1)}))
        steps.append(Step(start + SELECT_S, "move", target=well,
                          detail={"source": node, "port": port}))
        steps.append(Step(start + SELECT_S + MOVE_S, "dispense", target=well,
                          detail={"source": node, "port": port,
                                  "sample_id": sample_id,
                                  "volume_uL": recipe.draw_uL}))
        steps.append(Step(start + SELECT_S + MOVE_S + DISPENSE_S, "purge",
                          target="line", detail={"source": node}))

        sampler_free_at = start + cycle_s

    steps.sort(key=lambda s: (s.at_s, _ORDER.get(s.action, 9)))
    return steps


# Keeps same-timestamp steps in a sensible order when sorting.
_ORDER = {"init": 0, "home": 1, "feed": 2,
          "select": 3, "move": 4, "dispense": 5, "purge": 6}


def schedule_slip(steps: list[Step]) -> list[tuple[str, float]]:
    """Samples that could not be taken on time because the sampler was busy.

    A single selector serialises every draw, so a tight cadence across many
    reactors silently drifts. This surfaces that instead of hiding it.
    """
    return [
        (s.target, s.detail["waited_s"])
        for s in steps
        if s.action == "select" and s.detail.get("waited_s", 0) > 0
    ]


@dataclass
class RunResult:
    log: EventLog
    samples: list[SampleRecord]
    steps: list[Step]
    mode: str
    aborted: bool = False


def run_program(steps: list[Step], recipe: Recipe, *, reactors: dict,
                selector, robot, mode: str = "simulated",
                log: Optional[EventLog] = None,
                on_step: Optional[Callable[[Step], None]] = None,
                stop_on_failure: bool = True) -> RunResult:
    """Execute a compiled program against whatever adapters are supplied.

    reactors: node -> ReactorAdapter
    Passing simulated drivers gives SIMULATE; passing wired ones gives DEPLOY.
    """
    log = log or EventLog(recipe.run_id)
    samples: list[SampleRecord] = []
    aborted = False
    per_source: dict[str, int] = {}   # sample numbering, per reactor

    log.info(ev.SYSTEM, f"Run {recipe.run_id} starting in {mode} mode",
             mode=mode, steps=len(steps))
    log.info(ev.MODEL, f"{recipe.model or 'recipe'} iteration {recipe.iteration} "
                       f"accepted", objective=recipe.objective)

    for step in steps:
        if on_step:
            on_step(step)

        if step.action == "init":
            for node, adapter in reactors.items():
                corr = log.command(ev.DEVICE, f"connect {node}", step.at_s,
                                   node=node, kind=getattr(adapter, "kind", "?"))
                ack = adapter.connect()
                (log.ack if ack.ok else log.nack)(
                    ev.DEVICE, f"{node}: {ack.detail}", corr, step.at_s,
                    **ack.state)

        elif step.action == "home":
            corr = log.command(ev.ROUTER, "home", step.at_s)
            ack = selector.home()
            (log.ack if ack.ok else log.nack)(
                ev.ROUTER, ack.detail, corr, step.at_s, **ack.state)

        elif step.action == "feed":
            node = step.target
            adapter = reactors.get(node)
            d = step.detail.get("d_per_h", 0.0)
            corr = log.command(
                ev.CONTROL, f"{node}: set dilution rate {d:.3f}/h", step.at_s,
                node=node, d_per_h=d)
            if adapter is None:
                log.nack(ev.CONTROL, f"{node}: no adapter bound", corr, step.at_s)
            else:
                ack = adapter.set_dilution_rate(d, 15.0)
                (log.ack if ack.ok else log.nack)(
                    ev.CONTROL, f"{node}: {ack.detail}", corr, step.at_s,
                    **ack.state)

        elif step.action == "select":
            port = step.detail["port"]
            corr = log.command(ev.ROUTER, f"select port {port} ({step.target})",
                               step.at_s, port=port, source=step.target)
            ack = selector.select(port)
            if ack.ok:
                log.ack(ev.ROUTER, ack.detail, corr, step.at_s, **ack.state)
            else:
                log.nack(ev.ROUTER, ack.detail, corr, step.at_s, **ack.state)
                if stop_on_failure:
                    log.info(ev.SYSTEM, "Run aborted: routing failure")
                    aborted = True
                    break

        elif step.action == "move":
            corr = log.command(ev.ROBOT, f"move to {step.target}", step.at_s,
                               well=step.target)
            ack = robot.move_to(step.target)
            if ack.ok:
                log.ack(ev.ROBOT, ack.detail, corr, step.at_s, **ack.state)
            else:
                log.nack(ev.ROBOT, ack.detail, corr, step.at_s, **ack.state)
                if stop_on_failure:
                    log.info(ev.SYSTEM, "Run aborted: sampling failure")
                    aborted = True
                    break

        elif step.action == "dispense":
            source = step.detail["source"]
            vol = step.detail["volume_uL"]
            per_source[source] = per_source.get(source, 0) + 1
            sample_id = f"{recipe.run_id}-{source}-S{per_source[source]:02d}"
            corr = log.command(ev.ROBOT, f"dispense {vol:g} uL into {step.target}",
                               step.at_s, well=step.target, volume_uL=vol)
            ack = robot.dispense(vol)
            rec = SampleRecord(
                sample_id=sample_id, source=source, well=step.target,
                port=step.detail.get("port"), target_uL=vol,
                sim_t=step.at_s, status="complete" if ack.ok else "failed",
            )
            samples.append(rec)
            (log.ack if ack.ok else log.nack)(
                ev.ROBOT, ack.detail, corr, step.at_s, **ack.state)
            log.info(ev.SAMPLE, f"{sample_id} -> {step.target}",
                     sample_id=sample_id, source=source, well=step.target)

        elif step.action == "purge":
            log.info(ev.ROUTER, "line purged", step_at=step.at_s)

    ok = sum(1 for s in samples if s.status == "complete")
    log.info(ev.SYSTEM,
             f"Run {'aborted' if aborted else 'complete'}: "
             f"{ok}/{len(samples)} samples successful")

    return RunResult(log=log, samples=samples, steps=steps, mode=mode,
                     aborted=aborted)
