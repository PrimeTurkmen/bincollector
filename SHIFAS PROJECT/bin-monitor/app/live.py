"""Live / on-demand refresh from the Pilot account."""
import time

from . import db, config
from .pilot_client import PilotClient

_client: PilotClient | None = None


def client() -> PilotClient:
    global _client
    if _client is None:
        _client = PilotClient()
    return _client


def refresh_positions(kind: str = "ondemand") -> dict:
    """Pull current truck positions from Pilot and update vehicles.last_*."""
    vs = db.query("SELECT agent_id FROM vehicles")
    agent_ids = [v["agent_id"] for v in vs]
    updated = 0
    try:
        statuses = client().status(agent_ids)
    except Exception as e:  # pragma: no cover - network
        return {"ok": False, "error": str(e), "updated": 0}

    with db.connect() as conn:
        for st in statuses:
            aid = st.get("agent_id")
            if not aid:
                continue
            conn.execute(
                """UPDATE vehicles SET last_lat=%s, last_lon=%s, last_speed=%s,
                       last_seen_ts=%s, updated_at=now() WHERE agent_id=%s""",
                (st.get("lat"), st.get("lon"), st.get("speed"),
                 int(st["unixtimestamp"]) if st.get("unixtimestamp") else None, aid),
            )
            updated += 1
        conn.execute(
            "INSERT INTO ingest_runs (kind, rows, note) VALUES (%s,%s,%s)",
            (kind, updated, "live positions"),
        )
    return {"ok": True, "updated": updated, "at": int(time.time())}


def seed_positions_from_raw():
    """Fallback: set last position from the most recent raw point per vehicle."""
    with db.connect() as conn:
        conn.execute("""
            UPDATE vehicles v SET last_lat=r.lat, last_lon=r.lon, last_speed=r.speed,
                last_seen_ts=r.ts
            FROM (
                SELECT DISTINCT ON (agent_id) agent_id, lat, lon, speed, ts
                FROM raw_points ORDER BY agent_id, ts DESC
            ) r WHERE r.agent_id = v.agent_id
        """)
