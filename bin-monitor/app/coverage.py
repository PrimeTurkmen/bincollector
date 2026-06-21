"""Classify every bin relative to pilot-truck coverage.

  * serviced        — a lift landed within 50 m of the bin (collected by a pilot truck)
  * on_route_unused — no lift, but the bin sits within ~40 m of where a truck
                      actually drove -> a genuinely-unused / empty / missed bin
                      worth reviewing
  * off_pilot       — not near any pilot truck's driven path (serviced by other
                      trucks not in this trial, so not the pilot's concern)

Coverage area = the driven GPS path (ordered raw points) buffered ~40 m.
"""
from shapely.geometry import LineString, Point

from . import db

PATH_BUFFER_DEG = 0.0004  # ~44 m around the driven path


def _ensure_column():
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS coverage_class TEXT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS covering_agent BIGINT")


def _truck_hulls() -> dict:
    """Buffer of each truck's actual driven path (ordered moving GPS points)."""
    hulls = {}
    agents = [r["agent_id"] for r in db.query("SELECT agent_id FROM vehicles")]
    for aid in agents:
        pts = db.query(
            "SELECT lon, lat FROM raw_points WHERE agent_id=%s AND lat IS NOT NULL ORDER BY ts",
            (aid,))
        coords = [(p["lon"], p["lat"]) for p in pts]
        if len(coords) < 2:
            continue
        hulls[aid] = LineString(coords).buffer(PATH_BUFFER_DEG)
    return hulls


def classify_bins() -> dict:
    _ensure_column()
    hulls = _truck_hulls()

    serviced = {r["matched_bin_id"] for r in db.query(
        "SELECT DISTINCT matched_bin_id FROM lifts WHERE distance_m <= 50 AND matched_bin_id IS NOT NULL")}

    bins = db.query("SELECT unique_id, lat, lon FROM bins WHERE lat IS NOT NULL")
    updates = []
    counts = {"serviced": 0, "on_route_unused": 0, "off_pilot": 0}
    for b in bins:
        if b["unique_id"] in serviced:
            cls, agent = "serviced", None
        else:
            pt = Point(b["lon"], b["lat"])
            agent = next((aid for aid, h in hulls.items() if h.contains(pt)), None)
            cls = "on_route_unused" if agent is not None else "off_pilot"
        counts[cls] += 1
        updates.append((cls, agent, b["unique_id"]))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE bins SET coverage_class=%s, covering_agent=%s WHERE unique_id=%s", updates)
    print(f"bin coverage: {counts}")
    return counts
