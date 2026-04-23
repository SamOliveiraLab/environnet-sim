"""Bioreactor simulation engine.

Simulates E. coli (or generic microbe) growth in a chemostat/turbidostat
using ODE-based models. Tracks OD, temperature, media/waste volumes,
growth rate, and generates time-series data for visualization.

Physics:
    dOD/dt = μ * OD * (1 - OD/K) - D * OD
    D = F / V  (dilution rate = flow / volume)
    μ = μ_max * f(T) * f(stir)
    dV_media/dt = -F_in
    dV_waste/dt = +F_out
    dT/dt = (T_target - T) / τ_thermal
"""

import math
import time
import random
from dataclasses import dataclass, field


@dataclass
class SimState:
    """Snapshot of the bioreactor at a single instant."""
    t: float = 0.0
    od: float = 0.05
    growth_rate: float = 0.0
    temperature: float = 25.0
    target_temp: float = 30.0
    rpm: int = 400
    volume_ml: float = 20.0
    media_remaining_ml: float = 500.0
    waste_collected_ml: float = 0.0
    flow_rate_ml_min: float = 0.0
    dose_volume_ml: float = 0.5
    dose_interval_min: float = 15.0
    cells: list = field(default_factory=list)


@dataclass
class SimConfig:
    """Tunable parameters for the simulation."""
    organism: str = "ecoli"
    mu_max: float = 0.7
    carrying_capacity: float = 2.5
    optimal_temp: float = 37.0
    temp_sigma: float = 8.0
    thermal_tau: float = 5.0
    initial_od: float = 0.05
    vial_volume_ml: float = 20.0
    media_bottle_ml: float = 500.0
    time_scale: float = 60.0

    @classmethod
    def ecoli(cls):
        return cls(organism="ecoli", mu_max=0.7, carrying_capacity=2.5,
                   optimal_temp=37.0, temp_sigma=8.0)

    @classmethod
    def yeast(cls):
        return cls(organism="yeast", mu_max=0.35, carrying_capacity=3.0,
                   optimal_temp=30.0, temp_sigma=6.0)


class SimEngine:
    """Runs the bioreactor simulation, producing time-series data."""

    def __init__(self, config: SimConfig = None):
        self.config = config or SimConfig.ecoli()
        self.state = SimState(
            od=self.config.initial_od,
            volume_ml=self.config.vial_volume_ml,
            media_remaining_ml=self.config.media_bottle_ml,
        )
        self.running = False
        self.mode = "manual"
        self._last_dose_t = 0.0
        self._wall_start = 0.0
        self._sim_start = 0.0

        self.history: list[dict] = []
        self._max_history = 5000

    def start(self, rpm: int = 400, target_temp: float = 37.0,
              mode: str = "chemostat", dose_ml: float = 0.5,
              dose_interval_min: float = 15.0):
        self.running = True
        self.mode = mode.lower()
        self.state.rpm = rpm
        self.state.target_temp = target_temp
        self.state.dose_volume_ml = dose_ml
        self.state.dose_interval_min = dose_interval_min
        self._wall_start = time.time()
        self._sim_start = self.state.t
        self._last_dose_t = self.state.t

    def stop(self):
        self.running = False

    def step(self, dt_real: float):
        if not self.running:
            return
        dt = dt_real * self.config.time_scale / 60.0
        s = self.state
        c = self.config

        s.t += dt

        temp_factor = math.exp(-0.5 * ((s.temperature - c.optimal_temp) / c.temp_sigma) ** 2)
        stir_factor = min(1.0, s.rpm / 300.0) if s.rpm > 0 else 0.3
        mu = c.mu_max * temp_factor * stir_factor
        noise = 1.0 + random.gauss(0, 0.02)
        mu *= noise

        D = 0.0
        if self.mode == "chemostat" and s.dose_interval_min > 0:
            D = (s.dose_volume_ml / s.volume_ml) / s.dose_interval_min

            if s.t - self._last_dose_t >= s.dose_interval_min:
                actual_dose = min(s.dose_volume_ml, s.media_remaining_ml)
                if actual_dose > 0:
                    s.media_remaining_ml -= actual_dose
                    s.waste_collected_ml += actual_dose
                    s.flow_rate_ml_min = actual_dose / max(0.1, dt)
                self._last_dose_t = s.t
            else:
                s.flow_rate_ml_min = max(0, s.flow_rate_ml_min * 0.9)

        elif self.mode == "turbidostat":
            if s.od > 1.0 and s.media_remaining_ml > 0:
                excess = (s.od - 1.0) * 0.5
                dose = min(excess, s.media_remaining_ml, s.dose_volume_ml)
                D = dose / s.volume_ml / max(dt, 0.01)
                s.media_remaining_ml -= dose * dt
                s.waste_collected_ml += dose * dt
                s.flow_rate_ml_min = dose
            else:
                s.flow_rate_ml_min = max(0, s.flow_rate_ml_min * 0.9)
        else:
            s.flow_rate_ml_min = max(0, s.flow_rate_ml_min * 0.9)

        dod = mu * s.od * (1 - s.od / c.carrying_capacity) - D * s.od
        s.od = max(0.001, s.od + dod * dt)
        s.growth_rate = mu * (1 - s.od / c.carrying_capacity)

        dtemp = (s.target_temp - s.temperature) / c.thermal_tau
        s.temperature += dtemp * dt
        s.temperature += random.gauss(0, 0.05)

        self._update_cells()
        self._record()

    def _update_cells(self):
        target_count = int(min(80, self.state.od * 35))
        cells = self.state.cells
        while len(cells) < target_count:
            cells.append({
                "x": random.uniform(0.2, 0.8),
                "y": random.uniform(0.3, 0.85),
                "vx": random.gauss(0, 0.003),
                "vy": random.gauss(0, 0.002),
                "size": random.uniform(0.6, 1.4),
            })
        while len(cells) > target_count:
            cells.pop(random.randint(0, len(cells) - 1))
        for cell in cells:
            cell["x"] += cell["vx"]
            cell["y"] += cell["vy"]
            if cell["x"] < 0.15 or cell["x"] > 0.85:
                cell["vx"] *= -1
            if cell["y"] < 0.25 or cell["y"] > 0.9:
                cell["vy"] *= -1
            cell["x"] = max(0.15, min(0.85, cell["x"]))
            cell["y"] = max(0.25, min(0.9, cell["y"]))
            if self.state.rpm > 0:
                swirl = self.state.rpm / 8000.0
                cell["vx"] += random.gauss(0, swirl)
                cell["vy"] += random.gauss(0, swirl * 0.5)

    def _record(self):
        s = self.state
        self.history.append({
            "t": s.t,
            "od": s.od,
            "growth_rate": s.growth_rate,
            "temperature": s.temperature,
            "media_ml": s.media_remaining_ml,
            "waste_ml": s.waste_collected_ml,
            "flow": s.flow_rate_ml_min,
        })
        if len(self.history) > self._max_history:
            self.history = self.history[-self._max_history:]

    def get_series(self, key: str) -> tuple[list[float], list[float]]:
        ts = [h["t"] for h in self.history]
        vs = [h[key] for h in self.history]
        return ts, vs

    @property
    def elapsed_hours(self) -> float:
        return self.state.t / 60.0
