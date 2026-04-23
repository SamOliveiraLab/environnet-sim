"""Pioreactor API client.

Wraps the Pioreactor leader REST API into clean Python methods.
All endpoints discovered from the existing fluidic-automation dashboard.
"""

import json
import logging
import time
from typing import Any, Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 8  # seconds

_log_listeners: list = []


def add_log_listener(fn):
    _log_listeners.append(fn)


def remove_log_listener(fn):
    try:
        _log_listeners.remove(fn)
    except ValueError:
        pass


def _emit_log(method: str, path: str, status: int | str, detail: str = ""):
    entry = {"ts": time.time(), "method": method, "path": path,
             "status": status, "detail": detail}
    for fn in _log_listeners:
        try:
            fn(entry)
        except Exception:
            pass


class PioAPI:
    """Stateless HTTP client for one Pioreactor leader node."""

    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # -- low level ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str, **kw) -> Optional[Any]:
        try:
            r = self._session.get(self._url(path), timeout=DEFAULT_TIMEOUT, **kw)
            r.raise_for_status()
            _emit_log("GET", path, r.status_code)
            return r.json()
        except Exception as exc:
            _emit_log("GET", path, "ERR", str(exc))
            logger.warning("GET %s failed: %s", path, exc)
            return None

    def _post(self, path: str, body: Optional[dict] = None, **kw) -> Optional[requests.Response]:
        try:
            r = self._session.post(
                self._url(path),
                data=json.dumps(body or {}),
                timeout=DEFAULT_TIMEOUT,
                **kw,
            )
            _emit_log("POST", path, r.status_code, json.dumps(body or {})[:200])
            return r
        except Exception as exc:
            _emit_log("POST", path, "ERR", str(exc))
            logger.warning("POST %s failed: %s", path, exc)
            return None

    def _put(self, path: str, body: Optional[dict] = None) -> Optional[requests.Response]:
        try:
            r = self._session.put(
                self._url(path),
                data=json.dumps(body or {}),
                timeout=DEFAULT_TIMEOUT,
            )
            return r
        except Exception as exc:
            logger.warning("PUT %s failed: %s", path, exc)
            return None

    def _patch(self, path: str, body: Optional[dict] = None) -> Optional[requests.Response]:
        try:
            r = self._session.patch(
                self._url(path),
                data=json.dumps(body or {}),
                timeout=DEFAULT_TIMEOUT,
            )
            return r
        except Exception as exc:
            logger.warning("PATCH %s failed: %s", path, exc)
            return None

    def _delete(self, path: str) -> Optional[requests.Response]:
        try:
            r = self._session.delete(self._url(path), timeout=DEFAULT_TIMEOUT)
            return r
        except Exception as exc:
            logger.warning("DELETE %s failed: %s", path, exc)
            return None

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _enc(val: str) -> str:
        return quote(val, safe="")

    def ping(self) -> bool:
        """Return True if leader is reachable."""
        try:
            r = self._session.get(
                self._url("/api/workers"), timeout=4
            )
            return r.ok
        except Exception:
            return False

    # -- workers -----------------------------------------------------------

    def get_workers(self) -> list[dict]:
        return self._get("/api/workers") or []

    def get_worker(self, unit: str) -> Optional[dict]:
        return self._get(f"/api/workers/{self._enc(unit)}")

    def set_worker_active(self, unit: str, active: bool) -> bool:
        r = self._patch(
            f"/api/workers/{self._enc(unit)}/is_active",
            {"is_active": 1 if active else 0},
        )
        return r is not None and r.ok

    def assign_worker(self, unit: str, experiment: str) -> bool:
        r = self._put(
            f"/api/experiments/{self._enc(experiment)}/workers",
            {"pioreactor_unit": unit},
        )
        if r and r.ok:
            return True
        r2 = self._put(
            f"/api/experiments/{self._enc(experiment)}/workers/{self._enc(unit)}",
        )
        return r2 is not None and r2.ok

    # -- experiments -------------------------------------------------------

    def get_experiments(self) -> list[dict]:
        return self._get("/api/experiments") or []

    def create_experiment(self, name: str, description: str = "") -> bool:
        r = self._post("/api/experiments", {"experiment": name, "description": description})
        return r is not None and r.ok

    def delete_experiment(self, name: str) -> bool:
        r = self._delete(f"/api/experiments/{self._enc(name)}")
        return r is not None and r.ok

    # -- jobs --------------------------------------------------------------

    def start_job(self, unit: str, job_name: str, experiment: str, options: Optional[dict] = None) -> bool:
        """Start a job on a specific worker.

        POST /api/workers/{unit}/jobs/run/job_name/{job}/experiments/{exp}
        Body: {"options": {...}}
        """
        path = f"/api/workers/{self._enc(unit)}/jobs/run/job_name/{job_name}/experiments/{self._enc(experiment)}"
        r = self._post(path, {"options": options or {}})
        if r and r.status_code == 404:
            logger.info("Worker %s not assigned, auto-assigning to %s", unit, experiment)
            self.assign_worker(unit, experiment)
            r = self._post(path, {"options": options or {}})
        return r is not None and r.ok

    def stop_job(self, unit: str, job_name: str, experiment: str) -> bool:
        """Stop a job on a specific worker.

        POST /api/workers/{unit}/jobs/stop/job_name/{job}/experiments/{exp}
        """
        path = f"/api/workers/{self._enc(unit)}/jobs/stop/job_name/{job_name}/experiments/{self._enc(experiment)}"
        r = self._post(path)
        return r is not None and r.ok

    def update_job(self, unit: str, job_name: str, experiment: str, settings: dict) -> bool:
        """Update a running job's settings.

        POST /api/workers/{unit}/jobs/update/job_name/{job}/experiments/{exp}
        Body: {"settings": {...}}
        """
        path = f"/api/workers/{self._enc(unit)}/jobs/update/job_name/{job_name}/experiments/{self._enc(experiment)}"
        r = self._post(path, {"settings": settings})
        return r is not None and r.ok

    # -- convenience job starters ------------------------------------------

    def start_stirring(self, unit: str, experiment: str, rpm: int = 400) -> bool:
        return self.start_job(unit, "stirring", experiment, {"target_rpm": str(rpm)})

    def start_od_reading(self, unit: str, experiment: str) -> bool:
        return self.start_job(unit, "od_reading", experiment)

    def start_growth_rate(self, unit: str, experiment: str) -> bool:
        return self.start_job(unit, "growth_rate_calculating", experiment)

    def start_temperature(self, unit: str, experiment: str, target: float = 30.0) -> bool:
        return self.start_job(unit, "temperature_automation", experiment, {
            "automation_name": "thermostat",
            "target_temperature": target,
        })

    def start_chemostat(self, unit: str, experiment: str, volume_ml: float = 0.5, duration_min: float = 60) -> bool:
        return self.start_job(unit, "dosing_automation", experiment, {
            "automation_name": "chemostat",
            "exchange_volume_ml": volume_ml,
            "duration": duration_min,
        })

    def start_turbidostat(self, unit: str, experiment: str, target_od: float = 1.0,
                          volume_ml: float = 0.5, duration_min: float = 60) -> bool:
        return self.start_job(unit, "dosing_automation", experiment, {
            "automation_name": "turbidostat",
            "target_od": target_od,
            "volume": volume_ml,
            "duration": duration_min,
        })

    def dose_media(self, unit: str, experiment: str, ml: float = 0.5) -> bool:
        return self.start_job(unit, "add_media", experiment, {"ml": str(ml)})

    def dose_waste(self, unit: str, experiment: str, ml: float = 0.5) -> bool:
        return self.start_job(unit, "remove_waste", experiment, {"ml": str(ml)})

    # -- time series -------------------------------------------------------

    def get_od_readings(self, experiment: str, filter_mod: int = 1, hours: Optional[int] = None) -> Optional[dict]:
        q = f"?filter_mod_N={filter_mod}"
        if hours:
            q += f"&hours={hours}"
        return self._get(f"/api/experiments/{self._enc(experiment)}/time_series/od_readings{q}")

    def get_temperature_readings(self, experiment: str, filter_mod: int = 1, hours: Optional[int] = None) -> Optional[dict]:
        q = f"?filter_mod_N={filter_mod}"
        if hours:
            q += f"&hours={hours}"
        return self._get(f"/api/experiments/{self._enc(experiment)}/time_series/temperature_readings{q}")

    def get_growth_rates(self, experiment: str, filter_mod: int = 1, hours: Optional[int] = None) -> Optional[dict]:
        q = f"?filter_mod_N={filter_mod}"
        if hours:
            q += f"&hours={hours}"
        return self._get(f"/api/experiments/{self._enc(experiment)}/time_series/growth_rates{q}")

    def get_logs(self, experiment: str) -> list[dict]:
        return self._get(f"/api/experiments/{self._enc(experiment)}/logs") or []
