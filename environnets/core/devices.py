"""Device abstraction: one vocabulary, many machines.

The design layer says "hold B1 at D = 0.2/h". It must not have to know whether
B1 is a Pioreactor or a ChiBio. Each adapter translates that intent into the
commands its own hardware understands, and reports back whether the device
agreed.

Adapters never raise on hardware trouble. They return an Ack, because a
refused command is data the run needs to record, not an exception.
"""

import time
from dataclasses import dataclass
from typing import Optional, Protocol

from environnets.core import PioAPI


@dataclass
class Ack:
    """What a device said back."""

    ok: bool
    detail: str = ""
    state: dict = None

    def __post_init__(self):
        if self.state is None:
            self.state = {}


def flow_ml_per_h(dilution_per_h: float, volume_ml: float) -> float:
    """F = D * V."""
    return dilution_per_h * volume_ml


def dose_for_interval(dilution_per_h: float, volume_ml: float,
                      interval_min: float) -> float:
    """Volume one dose must deliver to realise D at this cadence, in mL."""
    return flow_ml_per_h(dilution_per_h, volume_ml) * (interval_min / 60.0)


class ReactorAdapter(Protocol):
    """The abstract controls every reactor exposes."""

    name: str

    def connect(self) -> Ack: ...
    def set_temperature(self, celsius: float) -> Ack: ...
    def set_stirring(self, rpm: int) -> Ack: ...
    def set_dilution_rate(self, per_h: float, interval_min: float) -> Ack: ...
    def read_state(self) -> dict: ...
    def stop(self) -> Ack: ...


class PioreactorAdapter:
    """Maps the abstract controls onto the Pioreactor REST API."""

    kind = "pioreactor"

    def __init__(self, api: PioAPI, unit: str, experiment: str,
                 volume_ml: float = 20.0, name: str = ""):
        self.api = api
        self.unit = unit
        self.experiment = experiment
        self.volume_ml = volume_ml
        self.name = name or unit

    def connect(self) -> Ack:
        workers = self.api.get_workers() or []
        for w in workers:
            if w.get("pioreactor_unit") == self.unit:
                if not w.get("is_active"):
                    return Ack(False, f"{self.unit} is registered but inactive")
                return Ack(True, f"{self.unit} active",
                           {"model": w.get("model_name"),
                            "version": w.get("model_version")})
        return Ack(False, f"{self.unit} not found on the leader")

    def set_temperature(self, celsius: float) -> Ack:
        ok = self.api.start_temperature(self.unit, self.experiment, celsius)
        return Ack(ok, f"thermostat -> {celsius} C" if ok
                   else "temperature_automation refused")

    def set_stirring(self, rpm: int) -> Ack:
        ok = self.api.start_stirring(self.unit, self.experiment, rpm)
        return Ack(ok, f"stirring -> {rpm} rpm" if ok else "stirring refused")

    def set_dilution_rate(self, per_h: float, interval_min: float = 15.0) -> Ack:
        """Pioreactor runs a chemostat automation directly from a volume."""
        dose = dose_for_interval(per_h, self.volume_ml, interval_min)
        ok = self.api.start_chemostat(
            self.unit, self.experiment,
            volume_ml=round(dose, 4), duration_min=interval_min,
        )
        return Ack(
            ok,
            f"chemostat {dose:.3f} mL every {interval_min:g} min "
            f"(D = {per_h:.3f}/h)" if ok else "dosing_automation refused",
            {"dose_ml": round(dose, 4), "interval_min": interval_min},
        )

    def dose(self, ml: float) -> Ack:
        ok = self.api.dose_media(self.unit, self.experiment, ml)
        return Ack(ok, f"add_media {ml:g} mL" if ok else "add_media refused")

    def read_state(self) -> dict:
        return {"unit": self.unit, "volume_ml": self.volume_ml}

    def stop(self) -> Ack:
        results = [
            self.api.stop_job(self.unit, job, self.experiment)
            for job in ("dosing_automation", "temperature_automation",
                        "stirring", "od_reading")
        ]
        return Ack(any(results), "jobs stopped")


class ChiBioAdapter:
    """Maps the abstract controls onto ChiBio's C7 pulse-feed chemostat.

    C7 takes a sip duration and an interval, running Pump3 in and Pump4 out.
    Turning a dilution rate into a sip needs the pump's calibration, which is
    exactly why a calibration is required before this adapter will act.
    """

    kind = "chibio"

    def __init__(self, base_url: str, reactor: str = "M0",
                 volume_ml: float = 25.0,
                 calibration_ml_per_s: Optional[float] = None,
                 name: str = "", session=None):
        self.base_url = base_url.rstrip("/")
        self.reactor = reactor
        self.volume_ml = volume_ml
        self.calibration_ml_per_s = calibration_ml_per_s
        self.name = name or reactor
        self._session = session

    def _post(self, path: str) -> bool:
        if self._session is None:
            import requests
            self._session = requests.Session()
        try:
            r = self._session.post(f"{self.base_url}{path}", timeout=8)
            return r.ok
        except Exception:
            return False

    def connect(self) -> Ack:
        if self._session is None:
            import requests
            self._session = requests.Session()
        try:
            r = self._session.get(f"{self.base_url}/", timeout=6)
            return Ack(r.ok, "ChiBio reachable" if r.ok else "no response")
        except Exception as exc:
            return Ack(False, f"unreachable: {exc}")

    def set_temperature(self, celsius: float) -> Ack:
        ok = self._post(f"/SetOutputTarget/{self.reactor}/Thermostat/{celsius}")
        return Ack(ok, f"thermostat -> {celsius} C")

    def set_stirring(self, rpm: int) -> Ack:
        # ChiBio drives the stirrer as a 0-1 duty fraction, not rpm.
        duty = max(0.0, min(1.0, rpm / 1500.0))
        ok = self._post(f"/SetOutputTarget/{self.reactor}/Stirrer/{duty:.3f}")
        return Ack(ok, f"stirrer -> {duty:.2f} duty (from {rpm} rpm)")

    def set_dilution_rate(self, per_h: float, interval_min: float = 15.0) -> Ack:
        if not self.calibration_ml_per_s:
            return Ack(
                False,
                "no pump calibration - cannot convert a dilution rate into a "
                "sip duration",
            )
        dose_ml = dose_for_interval(per_h, self.volume_ml, interval_min)
        sip_s = dose_ml / self.calibration_ml_per_s
        ok = self._post(
            f"/SetCustomProgram/{self.reactor}/C7/{sip_s:.3f}/{int(interval_min)}"
        )
        return Ack(
            ok,
            f"C7 sip {sip_s:.2f} s every {interval_min:g} min "
            f"(D = {per_h:.3f}/h, {dose_ml:.3f} mL)",
            {"sip_s": round(sip_s, 3), "interval_min": interval_min,
             "dose_ml": round(dose_ml, 4)},
        )

    def read_state(self) -> dict:
        return {"reactor": self.reactor, "volume_ml": self.volume_ml}

    def stop(self) -> Ack:
        return Ack(self._post(f"/SetCustomProgram/{self.reactor}/C0/0/0"),
                   "custom program cleared")


class SelectorAdapter:
    """8-port rotary selector. One path at a time.

    `select` is deliberately the only routing verb: a rotary selector cannot
    hold two paths open, so there is no API here that would let a caller
    believe otherwise.
    """

    kind = "selector"
    simultaneous_routes = 1

    def __init__(self, ports: int = 8, name: str = "router", driver=None):
        self.ports = ports
        self.name = name
        self.driver = driver          # None until the real valve is wired
        self.position: Optional[int] = None

    def connect(self) -> Ack:
        if self.driver is None:
            return Ack(False, "no driver bound - selector is not wired yet")
        return Ack(True, "selector connected")

    def home(self) -> Ack:
        if self.driver is None:
            return Ack(False, "no driver bound")
        ok = bool(self.driver.home())
        if ok:
            self.position = 0
        return Ack(ok, "homed" if ok else "home failed")

    def select(self, port: int) -> Ack:
        if not 1 <= port <= self.ports:
            return Ack(False, f"port {port} outside 1..{self.ports}")
        if self.driver is None:
            return Ack(False, "no driver bound")
        ok = bool(self.driver.select(port))
        if not ok:
            return Ack(False, f"selector refused port {port}")
        reported = self.driver.position()
        if reported != port:
            return Ack(False,
                       f"requested port {port}, selector reports {reported}",
                       {"requested": port, "reported": reported})
        self.position = port
        return Ack(True, f"port {port} active", {"port": port})


class RobotAdapter:
    """Sampling arm. Moves to a named well and dispenses a volume."""

    kind = "robot"

    def __init__(self, name: str = "robot", driver=None,
                 plate_wells: Optional[list] = None):
        self.name = name
        self.driver = driver
        self.plate_wells = plate_wells or []
        self.at: Optional[str] = None

    def connect(self) -> Ack:
        if self.driver is None:
            return Ack(False, "no driver bound - arm is not wired yet")
        return Ack(True, "robot connected")

    def move_to(self, well: str) -> Ack:
        if self.plate_wells and well not in self.plate_wells:
            return Ack(False, f"well {well} is not on the configured plate")
        if self.driver is None:
            return Ack(False, "no driver bound")
        ok = bool(self.driver.move_to(well))
        if not ok:
            return Ack(False, f"move to {well} failed")
        reached = self.driver.position()
        if reached != well:
            return Ack(False, f"asked for {well}, arm reports {reached}",
                       {"requested": well, "reported": reached})
        self.at = well
        return Ack(True, f"at {well}", {"well": well})

    def dispense(self, volume_uL: float) -> Ack:
        if self.driver is None:
            return Ack(False, "no driver bound")
        ok = bool(self.driver.dispense(volume_uL))
        return Ack(ok, f"dispensed {volume_uL:g} uL" if ok else "dispense failed",
                   {"volume_uL": volume_uL})


# -- simulated drivers -----------------------------------------------------
#
# These stand in for hardware that is not wired yet, so a whole run can be
# rehearsed. They report the same shapes the real drivers must return.


class SimSelectorDriver:
    def __init__(self, ports: int = 8, fail_on: Optional[set] = None):
        self.ports = ports
        self._pos = 0
        self.fail_on = fail_on or set()

    def home(self) -> bool:
        self._pos = 0
        return True

    def select(self, port: int) -> bool:
        if port in self.fail_on:
            return False
        self._pos = port
        return True

    def position(self) -> int:
        return self._pos


class SimRobotDriver:
    def __init__(self, fail_on: Optional[set] = None):
        self._at = "home"
        self.fail_on = fail_on or set()

    def move_to(self, well: str) -> bool:
        if well in self.fail_on:
            return False
        self._at = well
        return True

    def position(self) -> str:
        return self._at

    def dispense(self, volume_uL: float) -> bool:
        return volume_uL > 0
