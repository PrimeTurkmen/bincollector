"""Thin client for the Pilot GPS v3 REST API (read-only endpoints we use)."""
import time
import requests

from . import config


class PilotClient:
    def __init__(self, base=None, user=None, password=None):
        self.base = (base or config.PILOT_BASE).rstrip("/")
        self.user = user or config.PILOT_USER
        self.password = password or config.PILOT_PASS
        self._token = None
        self._node = None
        self._expires_at = 0
        self.s = requests.Session()

    # ---- auth ----
    def _login(self):
        r = self.s.post(
            f"{self.base}/api/v3/auth/token",
            json={"username": self.user, "password": self.password},
            timeout=20,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Pilot auth failed: {d.get('msg')}")
        self._token = d["token"]
        self._node = d.get("node_id", 0)
        self._expires_at = time.time() + int(d.get("expires_in", 3600)) - 60
        self.s.headers.update(
            {"Authorization": f"Bearer {self._token}", "X-Node": str(self._node)}
        )

    def _ensure(self):
        if not self._token or time.time() >= self._expires_at:
            self._login()

    def _get(self, path, params=None):
        self._ensure()
        r = self.s.get(f"{self.base}{path}", params=params or {}, timeout=90)
        r.raise_for_status()
        return r.json()

    # ---- endpoints ----
    def vehicles(self) -> list[dict]:
        return self._get("/api/v3/vehicles").get("data", [])

    def status(self, agent_ids: list[int]) -> list[dict]:
        # agent_id is the reliable key — imei sometimes carries a "_1" suffix
        return self._get(
            "/api/v3/vehicles/status",
            {"agent_id": ",".join(str(a) for a in agent_ids)},
        ).get("data", [])

    def geofences(self) -> list[dict]:
        return self._get("/api/v3/geofences").get("data", [])

    def raw_events(self, agent_id: int, ts: int, te: int) -> list[dict]:
        d = self._get(
            "/api/v3/vehicles/events/raw", {"agent_id": agent_id, "ts": ts, "te": te}
        ).get("data", {})
        return d.get("raw", []) if isinstance(d, dict) else (d or [])

    def last24h(self, imei: str) -> dict:
        data = self._get("/api/v3/vehicles/last24h", {"imei": imei}).get("data", [])
        return data[0] if data else {}
