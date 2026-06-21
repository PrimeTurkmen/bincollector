"""Access-consistency detector — distinguishes permanent vs dynamic obstruction
from how close the truck got to each bin on different days (pure GPS, no maps).

For each bin, find the nearest collection stop per day. Then:
  * good       — truck reached the bin (<= NEAR m) on every service day
  * permanent  — truck stopped far (> NEAR m) on every day  -> narrow lane / wheel-out
  * dynamic    — reached some days, blocked others  -> parked cars / traffic that day
  * single     — only one service day, not enough to judge
A bin with no nearby stop stays NULL (not serviced by the pilot).
"""
from collections import defaultdict
import statistics

from . import db
from .geometry import haversine_m

NEAR = 20.0       # metres — "the truck got to the bin"
WHEEL_OUT = 150.0  # metres — a stop this close is still servicing the bin
CELL = 0.0015      # ~150 m grid


def analyze_access() -> dict:
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS access_class TEXT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS access_days INT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS access_detail TEXT")

    lifts = db.query("""SELECT day, lat, lon FROM lifts
                        WHERE lat IS NOT NULL AND distance_band <> 'dump'""")
    grid = defaultdict(list)
    for lf in lifts:
        grid[(int(lf["lat"] / CELL), int(lf["lon"] / CELL))].append(lf)

    bins = db.query("SELECT unique_id, lat, lon FROM bins WHERE lat IS NOT NULL")
    updates, counts = [], defaultdict(int)
    for b in bins:
        ci, cj = int(b["lat"] / CELL), int(b["lon"] / CELL)
        per_day: dict = {}
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for lf in grid.get((ci + di, cj + dj), []):
                    d = haversine_m(b["lat"], b["lon"], lf["lat"], lf["lon"])
                    if d <= WHEEL_OUT:
                        dy = str(lf["day"])
                        if dy not in per_day or d < per_day[dy]:
                            per_day[dy] = d
        if not per_day:
            cls, detail = None, None
        elif len(per_day) == 1:
            cls = "single"
            detail = next(f"{k[5:]}:{v:.0f}m" for k, v in per_day.items())
        else:
            dists = list(per_day.values())
            reached = [d <= NEAR for d in dists]
            if all(reached):
                cls = "good"
            elif not any(reached):
                cls = "permanent"
            else:
                cls = "dynamic"
            detail = ", ".join(f"{k[5:]}:{v:.0f}m" for k, v in sorted(per_day.items()))
        counts[cls] += 1
        updates.append((cls, len(per_day) or None, detail, b["unique_id"]))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE bins SET access_class=%s, access_days=%s, access_detail=%s WHERE unique_id=%s",
                updates)
    summary = {k: v for k, v in counts.items() if k}
    print(f"access analysis: {summary}")
    return summary
