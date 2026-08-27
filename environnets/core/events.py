"""EnvironNets event log: the experiment's audit trail.

This is deliberately not the Pioreactor's log. The Pi has no idea what a
recipe, a router port or a sample id is; this log records what EnvironNets
decided and what the hardware said back.

Every actuation produces two records: a COMMAND, meaning the software asked
for something, and an ACK or NACK, meaning the device reported the outcome.
Keeping them separate is what stops an actuator failure from being read later
as a biological effect.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# Log channels, mirroring the layers in the architecture notes.
SYSTEM = "system"
MODEL = "model"
VALIDATION = "validation"
DEVICE = "device"
CONTROL = "control"
ROUTER = "router"
ROBOT = "robot"
SAMPLE = "sample"

COMMAND = "command"
ACK = "ack"
NACK = "nack"
INFO = "info"


@dataclass
class Event:
    """One line in the audit trail."""

    channel: str
    kind: str          # COMMAND | ACK | NACK | INFO
    message: str
    t: float = field(default_factory=time.time)
    sim_t: Optional[float] = None   # seconds into the run, when simulated
    detail: dict = field(default_factory=dict)
    corr_id: Optional[str] = None   # ties an ACK back to its COMMAND

    def line(self) -> str:
        stamp = (
            f"{self.sim_t:8.1f}s"
            if self.sim_t is not None
            else time.strftime("%H:%M:%S", time.localtime(self.t))
        )
        tag = {COMMAND: "CMD ", ACK: "ACK ", NACK: "NACK", INFO: "    "}.get(
            self.kind, "    "
        )
        return f"{stamp}  {tag}  {self.channel.upper():<10} {self.message}"


class EventLog:
    """Ordered event store for one run."""

    def __init__(self, run_id: str = ""):
        self.run_id = run_id
        self.events: list[Event] = []
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"c{self._seq:04d}"

    def info(self, channel: str, message: str, **detail) -> Event:
        e = Event(channel=channel, kind=INFO, message=message, detail=detail)
        self.events.append(e)
        return e

    def command(self, channel: str, message: str, sim_t: Optional[float] = None,
                **detail) -> str:
        """Record an intent. Returns the correlation id to acknowledge with."""
        corr = self._next_id()
        self.events.append(Event(
            channel=channel, kind=COMMAND, message=message,
            sim_t=sim_t, detail=detail, corr_id=corr,
        ))
        return corr

    def ack(self, channel: str, message: str, corr_id: str,
            sim_t: Optional[float] = None, **detail) -> Event:
        e = Event(channel=channel, kind=ACK, message=message,
                  sim_t=sim_t, detail=detail, corr_id=corr_id)
        self.events.append(e)
        return e

    def nack(self, channel: str, message: str, corr_id: str,
             sim_t: Optional[float] = None, **detail) -> Event:
        e = Event(channel=channel, kind=NACK, message=message,
                  sim_t=sim_t, detail=detail, corr_id=corr_id)
        self.events.append(e)
        return e

    # -- reporting ---------------------------------------------------------

    def text(self, channel: Optional[str] = None) -> str:
        rows = self.events if channel is None else [
            e for e in self.events if e.channel == channel
        ]
        return "\n".join(e.line() for e in rows)

    def unacknowledged(self) -> list[Event]:
        """Commands that never got a reply - the interesting failures."""
        answered = {e.corr_id for e in self.events if e.kind in (ACK, NACK)}
        return [
            e for e in self.events
            if e.kind == COMMAND and e.corr_id not in answered
        ]

    def counts(self) -> dict:
        out = {"commands": 0, "acks": 0, "nacks": 0}
        for e in self.events:
            if e.kind == COMMAND:
                out["commands"] += 1
            elif e.kind == ACK:
                out["acks"] += 1
            elif e.kind == NACK:
                out["nacks"] += 1
        out["unacknowledged"] = len(self.unacknowledged())
        return out

    def to_dict(self) -> list[dict]:
        return [asdict(e) for e in self.events]


@dataclass
class SampleRecord:
    """One physical sample, from source reactor to destination well."""

    sample_id: str
    source: str
    well: str
    port: Optional[int] = None
    target_uL: float = 0.0
    delivered_uL: Optional[float] = None   # filled in by gravimetry
    sim_t: Optional[float] = None
    status: str = "pending"   # pending | complete | failed


def write_results(path: str, *, run_id: str, recipe: dict, log: EventLog,
                  samples: list[SampleRecord], mode: str,
                  measurements: Optional[dict] = None) -> dict:
    """Emit results.json: the return half of the loop.

    Three sections, so the shape does not change between a water run and a
    biological one - only `measurements` gains content.
    """
    ok = [s for s in samples if s.status == "complete"]
    failed = [s for s in samples if s.status == "failed"]

    results = {
        "schema": "environnets.results.v1",
        "run_id": run_id,
        "mode": mode,                       # "simulated" | "hardware"
        "finished_at": time.time(),
        "configuration": recipe,            # what was requested
        "execution": {                      # what actually happened
            "samples_requested": len(samples),
            "samples_successful": len(ok),
            "samples_failed": len(failed),
            **log.counts(),
            "router_selections": sum(
                1 for e in log.events
                if e.channel == ROUTER and e.kind == COMMAND
            ),
            "samples": [asdict(s) for s in samples],
            "log": log.to_dict(),
        },
        "measurements": measurements or {},  # what the biology/chemistry gave
    }

    with open(path, "w") as fh:
        json.dump(results, fh, indent=2)
    return results
