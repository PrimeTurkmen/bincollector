"""Service-completeness check: did the truck empty every bin at a location it visited?

Cluster registered bins that sit together (<= GROUP_R) into one service location.
For each location, on each day the truck actually serviced it (>=1 lift within
SERVICE_R), compare bins-expected vs lifts-done:
  * complete — lifts >= bins
  * partial  — 0 < lifts < bins  -> at least one bin skipped (review)
This is the missed-collection evidence: the truck was right there but did fewer
lifts than there are bins.
"""
from collections import defaultdict

from . import db
from .geometry import haversine_m

GROUP_R = 25.0     # bins within this of each other = one service location
SERVICE_R = 40.0   # a lift this close counts as servicing the location
GCELL = 0.0003
LCELL = 0.0006


def _bin_groups(bins):
    grid = defaultdict(list)
    for b in bins:
        grid[(int(b["lat"] / GCELL), int(b["lon"] / GCELL))].append(b)
    seen, groups = set(), []
    for b in bins:
        if b["unique_id"] in seen:
            continue
        ci, cj = int(b["lat"] / GCELL), int(b["lon"] / GCELL)
        members = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for o in grid[(ci + di, cj + dj)]:
                    if o["unique_id"] not in seen and \
                       haversine_m(b["lat"], b["lon"], o["lat"], o["lon"]) <= GROUP_R:
                        members.append(o); seen.add(o["unique_id"])
        if members:
            areas = [m["area_name"] for m in members if m["area_name"]]
            groups.append({
                "n": len(members),
                "lat": sum(m["lat"] for m in members) / len(members),
                "lon": sum(m["lon"] for m in members) / len(members),
                "area": max(set(areas), key=areas.count) if areas else None,
                "ids": [m["unique_id"] for m in members],
            })
    return groups


def build_service_checks() -> dict:
    db.execute("""CREATE TABLE IF NOT EXISTS service_checks (
        id BIGSERIAL PRIMARY KEY, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
        area TEXT, day DATE, expected INT, done INT, missed INT, status TEXT)""")
    db.execute("TRUNCATE service_checks RESTART IDENTITY")

    bins = db.query("SELECT unique_id, lat, lon, area_name FROM bins WHERE lat IS NOT NULL")
    groups = _bin_groups(bins)

    lifts = db.query("SELECT day, lat, lon FROM lifts WHERE lat IS NOT NULL AND distance_band <> 'dump'")
    lgrid = defaultdict(list)
    for lf in lifts:
        lgrid[(int(lf["lat"] / LCELL), int(lf["lon"] / LCELL))].append(lf)

    def done_on(lat, lon, day):
        ci, cj = int(lat / LCELL), int(lon / LCELL)
        return sum(1 for di in (-1, 0, 1) for dj in (-1, 0, 1)
                   for lf in lgrid[(ci + di, cj + dj)]
                   if str(lf["day"]) == day and haversine_m(lat, lon, lf["lat"], lf["lon"]) <= SERVICE_R)

    days = [str(r["day"]) for r in db.query("SELECT DISTINCT day FROM lifts ORDER BY day")]
    rows, counts = [], {"complete": 0, "partial": 0}
    for g in groups:
        if g["n"] < 2:
            continue  # single-bin "misses" are the coverage story; here we want clear shortfalls
        for day in days:
            done = done_on(g["lat"], g["lon"], day)
            if done == 0:
                continue  # not serviced that day — not a "skip while present"
            status = "complete" if done >= g["n"] else "partial"
            counts[status] += 1
            rows.append((g["lat"], g["lon"], g["area"], day, g["n"], done,
                         max(0, g["n"] - done), status))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO service_checks (lat, lon, area, day, expected, done, missed, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    print(f"service checks: {counts}")
    return counts
