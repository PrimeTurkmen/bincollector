"""Collected-vs-missed — computed PER DAY (recurring service), with a consistency rollup.

Bins are permanent assets serviced on a recurring schedule. For each DAY we assign
that day's lifts to the nearest bins within wheel-out reach. Per (bin, day):
  collected — got a lift that day
  missed    — no lift, but a collected bin sits within MISS_R that day (truck was there)
Rollup across days (for the All-days view):
  every_day  — collected on every day its area was serviced (reliable)
  some_days  — collected on some days, skipped on others (inconsistent)
  never      — area serviced but the bin was never collected
  off_pilot  — no pilot activity near it on any day
"""
from collections import defaultdict

from . import db
from .geometry import haversine_m

REACH = 150.0     # wheel-out: a stop this close still collects the bin
MISS_R = 30.0     # uncollected bin this close to a collected one = skipped
CELL = 0.0015     # ~150 m grid


def build_collection_status() -> dict:
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS collect_status TEXT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS days_collected INT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS service_days INT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS last_lift_ts BIGINT")
    db.execute("ALTER TABLE bins ADD COLUMN IF NOT EXISTS pickups INT")
    db.execute("""CREATE TABLE IF NOT EXISTS bin_day_status (
        unique_id TEXT, day DATE, status TEXT, collected_m DOUBLE PRECISION,
        PRIMARY KEY (unique_id, day))""")
    db.execute("TRUNCATE bin_day_status")

    bins = db.query("SELECT unique_id, lat, lon FROM bins WHERE lat IS NOT NULL")
    grid = defaultdict(list)
    for i, b in enumerate(bins):
        grid[(int(b["lat"] / CELL), int(b["lon"] / CELL))].append(i)
    days = [str(r["day"]) for r in db.query("SELECT DISTINCT day FROM lifts ORDER BY day")]

    collected_days = defaultdict(set)   # bin idx -> set of days collected
    service_days = defaultdict(set)     # bin idx -> set of days its area was serviced
    last_ts = defaultdict(int)          # bin idx -> most recent lift ts
    pickups = defaultdict(int)          # bin idx -> total lifts collected
    day_rows = []

    for day in days:
        lifts = db.query("""SELECT lat, lon, start_ts FROM lifts
                            WHERE distance_band<>'dump' AND lat IS NOT NULL AND day=%s""", (day,))
        assigned = {}   # bin idx -> distance
        for lf in lifts:
            ci, cj = int(lf["lat"] / CELL), int(lf["lon"] / CELL)
            best, bestd = None, REACH
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for idx in grid.get((ci + di, cj + dj), []):
                        if idx in assigned:
                            continue
                        d = haversine_m(lf["lat"], lf["lon"], bins[idx]["lat"], bins[idx]["lon"])
                        if d <= bestd:
                            best, bestd = idx, d
            if best is not None:
                assigned[best] = bestd
                pickups[best] += 1
                if lf["start_ts"] and lf["start_ts"] > last_ts[best]:
                    last_ts[best] = lf["start_ts"]

        # collected this day
        cgrid = defaultdict(list)
        for idx, dist in assigned.items():
            collected_days[idx].add(day)
            service_days[idx].add(day)
            cgrid[(int(bins[idx]["lat"] / CELL), int(bins[idx]["lon"] / CELL))].append(idx)
            day_rows.append((bins[idx]["unique_id"], day, "collected", round(dist, 1)))

        # missed this day = uncollected bin with a collected bin within MISS_R
        for i, b in enumerate(bins):
            if i in assigned:
                continue
            ci, cj = int(b["lat"] / CELL), int(b["lon"] / CELL)
            near = False
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for idx in cgrid.get((ci + di, cj + dj), []):
                        if haversine_m(b["lat"], b["lon"], bins[idx]["lat"], bins[idx]["lon"]) <= MISS_R:
                            near = True
                            break
                    if near:
                        break
                if near:
                    break
            if near:
                service_days[i].add(day)
                day_rows.append((b["unique_id"], day, "missed", None))

    # rollup
    roll, counts = [], {"every_day": 0, "some_days": 0, "never": 0, "off_pilot": 0}
    for i, b in enumerate(bins):
        dc, sd = len(collected_days[i]), len(service_days[i])
        if sd == 0:
            st = "off_pilot"
        elif dc == sd:
            st = "every_day"
        elif dc > 0:
            st = "some_days"
        else:
            st = "never"
        counts[st] += 1
        roll.append((st, dc, sd, last_ts[i] or None, pickups[i], b["unique_id"]))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE bins SET collect_status=%s, days_collected=%s, service_days=%s,
                       last_lift_ts=%s, pickups=%s WHERE unique_id=%s""",
                roll)
            cur.executemany(
                "INSERT INTO bin_day_status (unique_id, day, status, collected_m) VALUES (%s,%s,%s,%s)",
                day_rows)
    print(f"collection compliance (rollup): {counts}")
    return counts
