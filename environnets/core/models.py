"""Local data models and SQLite storage.

The Pioreactor API stores experiment data on the Pi.
We store EnvironNets-specific data locally: network layouts,
unit positions, culture labels, and connection maps.
"""

import json
import sqlite3
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

APP_DIR = Path.home() / ".environnets"
DB_PATH = APP_DIR / "environnets.db"


def _ensure_dir():
    APP_DIR.mkdir(parents=True, exist_ok=True)


# -- dataclasses -----------------------------------------------------------

@dataclass
class Unit:
    """A single piece of hardware on the canvas."""
    uid: str
    kind: str
    label: str = ""
    pioreactor_unit: str = ""
    x: float = 100.0
    y: float = 100.0
    status: str = "disconnected"
    config: dict = field(default_factory=dict)
    category: str = "reactor"
    type_id: str = "pio_20ml"
    last_od: float = 0.0
    last_temp: float = 0.0
    last_gr: float = 0.0

    def __hash__(self):
        return hash(self.uid)

    def __eq__(self, other):
        if not isinstance(other, Unit):
            return NotImplemented
        return self.uid == other.uid


@dataclass
class Connection:
    """A link between two units on the canvas (e.g. pump feeds reactor)."""
    source_uid: str
    target_uid: str
    kind: str = "flow"  # "flow", "data", "control"


@dataclass
class Network:
    """A bioreactor network layout."""
    network_id: str
    name: str
    description: str = ""
    units: list[Unit] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


# -- database layer --------------------------------------------------------

class Store:
    """SQLite-backed persistence for networks and app settings."""

    def __init__(self, db_path: Optional[Path] = None):
        _ensure_dir()
        self.db_path = db_path or DB_PATH
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self):
        c = self._conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS networks (
                network_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                data TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.commit()

    # -- settings ----------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    # -- networks ----------------------------------------------------------

    def save_network(self, net: Network):
        data = {
            "units": [asdict(u) for u in net.units],
            "connections": [asdict(c) for c in net.connections],
        }
        self._conn.execute(
            "INSERT OR REPLACE INTO networks (network_id, name, description, data, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (net.network_id, net.name, net.description, json.dumps(data), net.created_at),
        )
        self._conn.commit()

    def load_network(self, network_id: str) -> Optional[Network]:
        row = self._conn.execute(
            "SELECT * FROM networks WHERE network_id = ?", (network_id,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        return Network(
            network_id=row["network_id"],
            name=row["name"],
            description=row["description"],
            units=[Unit(**u) for u in data.get("units", [])],
            connections=[Connection(**c) for c in data.get("connections", [])],
            created_at=row["created_at"],
        )

    def list_networks(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT network_id, name, description, created_at FROM networks ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_network(self, network_id: str):
        self._conn.execute("DELETE FROM networks WHERE network_id = ?", (network_id,))
        self._conn.commit()

    def close(self):
        self._conn.close()
