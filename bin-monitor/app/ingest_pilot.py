"""Download historical data from Pilot into raw_points, for any date range.

Two sources:
  * Admin `rawpoints` (preferred) — returns per-point `triggerdata` with the tilt
    angle (Param463) and ignition (DIS1), so lifts can be detected. Requires
    Kvadrat admin credentials (PILOT_ADMIN_*). Periods up to 10 days per call.
  * Customer `events/raw` (fallback) — position + speed only, no angle, so it
    populates tracks but cannot detect lifts.

Windows are chunked to <= 10 days to respect the rawpoints limit.
"""
import time
import requests
from requests.auth import HTTPBasicAuth

from . import db, config
from .params import param
from .pilot_client import PilotClient

CHUNK = 9 * 86400  # < 10-day rawpoints limit


def _save_points(rows: list[tuple], agent_id: int, ts: int, te: int, note: str):
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO raw_points
                   (agent_id, ts, lat, lon, speed, angle, dis1, mvmnt, vsourse, source_file)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (agent_id, ts) DO NOTHING""",
                rows,
            )
        conn.execute(
            "INSERT INTO ingest_runs (kind, agent_id, window_ts, window_te, rows, note) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            ("scheduled", agent_id, ts, te, len(rows), note),
        )


def pull_rawpoints_admin(agent_id: int, ts: int, te: int) -> int:
    """Admin feed with angle/DIS1. Returns rows inserted (0 if admin not configured)."""
    if not (config.PILOT_ADMIN_URL and config.PILOT_ADMIN_USER):
        return 0
    auth = HTTPBasicAuth(config.PILOT_ADMIN_USER, config.PILOT_ADMIN_PASS)
    total = 0
    for w0 in range(ts, te, CHUNK):
        w1 = min(w0 + CHUNK, te)
        r = requests.get(config.PILOT_ADMIN_URL,
                         params={"cmd": "rawpoints", "ts": w0, "te": w1, "agentid": agent_id},
                         auth=auth, timeout=120)
        r.raise_for_status()
        data = r.json().get("data", [])
        rows = []
        for p in data:
            trig = p.get("triggerdata", "")
            rows.append((
                agent_id,
                int(p.get("unixtimestamp")),
                float(p["latitude"]), float(p["longitude"]),
                p.get("speed"),
                param(trig, "Param463"), param(trig, "DIS1"),
                param(trig, "Mvmnt"), param(trig, "Vsourse"),
                "admin:rawpoints",
            ))
        _save_points(rows, agent_id, w0, w1, "admin:rawpoints")
        total += len(rows)
    return total


def pull_events_raw(agent_id: int, imei: str, ts: int, te: int) -> int:
    """Customer feed: position + speed only (angle/DIS1 = NULL)."""
    client = PilotClient()
    total = 0
    for w0 in range(ts, te, CHUNK):
        w1 = min(w0 + CHUNK, te)
        pts = client.raw_events(agent_id, w0, w1)
        rows = [(
            agent_id, int(p["ts"]), float(p["lat"]), float(p["lon"]),
            p.get("speed"), None, None, None, None, "events/raw",
        ) for p in pts]
        _save_points(rows, agent_id, w0, w1, "events/raw")
        total += len(rows)
    return total


def pull_window(ts: int, te: int) -> dict:
    """Pull all configured vehicles for [ts, te). Uses admin feed if available."""
    vs = db.query("SELECT agent_id, imei FROM vehicles")
    admin = bool(config.PILOT_ADMIN_URL and config.PILOT_ADMIN_USER)
    out = {"source": "admin:rawpoints" if admin else "events/raw",
           "angle": admin, "agents": {}}
    for v in vs:
        aid, imei = v["agent_id"], v["imei"]
        n = pull_rawpoints_admin(aid, ts, te) if admin else pull_events_raw(aid, imei, ts, te)
        out["agents"][aid] = n
    return out


def pull_last_days(days: int, now: int | None = None) -> dict:
    now = now or int(time.time())
    return pull_window(now - days * 86400, now)
