"""Discover real collection points from where the truck stopped and the arm fired.

Instead of trusting pre-drawn geozones, cluster the actual lift events (sensor
ground truth) within the device's GPS error (~CLUSTER_R metres) into collection
points. A point seen on multiple days is a confirmed stop. Each point is then
compared to the nearest known bin to label it confirmed / coordinate-off / new.
"""
from . import db
from .geometry import haversine_m, BinIndex

CLUSTER_R = 12.0    # metres — within FMC/FTC observed GPS error band
CELL = 0.00015      # ~15 m grid for neighbour lookup
WHEEL_OUT = 150.0   # metres — how far a bin may be rolled out to a blocked truck


def _cluster(lifts: list[dict]) -> list[dict]:
    grid: dict = {}
    clusters: list[dict] = []

    def cell(lat, lon):
        return (int(lat / CELL), int(lon / CELL))

    for lf in lifts:
        lat, lon = lf["lat"], lf["lon"]
        ci, cj = cell(lat, lon)
        best, bestd = None, CLUSTER_R
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for c in grid.get((ci + di, cj + dj), []):
                    d = haversine_m(lat, lon, c["lat"], c["lon"])
                    if d <= bestd:
                        best, bestd = c, d
        if best is None:
            best = {"lat": lat, "lon": lon, "n": 0, "sumlat": 0.0, "sumlon": 0.0,
                    "days": set(), "trucks": set(), "ids": []}
            clusters.append(best)
            grid.setdefault((ci, cj), []).append(best)
        best["n"] += 1
        best["sumlat"] += lat
        best["sumlon"] += lon
        best["days"].add(str(lf["day"]))
        best["trucks"].add(lf["agent_id"])
        best["ids"].append(lf["id"])
        best["lat"] = best["sumlat"] / best["n"]   # running centroid
        best["lon"] = best["sumlon"] / best["n"]
    return clusters


def build_collection_points() -> dict:
    db.execute("""CREATE TABLE IF NOT EXISTS collection_points (
        id BIGSERIAL PRIMARY KEY, lat DOUBLE PRECISION, lon DOUBLE PRECISION,
        lifts INT, days INT, trucks INT, primary_agent BIGINT,
        nearest_bin TEXT, nearest_m DOUBLE PRECISION, bins_150 INT, status TEXT)""")
    db.execute("ALTER TABLE collection_points ADD COLUMN IF NOT EXISTS bins_150 INT")
    db.execute("ALTER TABLE lifts ADD COLUMN IF NOT EXISTS cp_status TEXT")
    db.execute("ALTER TABLE lifts ADD COLUMN IF NOT EXISTS cp_lifts INT")
    db.execute("ALTER TABLE lifts ADD COLUMN IF NOT EXISTS cp_days INT")
    db.execute("TRUNCATE collection_points RESTART IDENTITY")

    lifts = db.query("""SELECT id, agent_id, day, lat, lon FROM lifts
                        WHERE lat IS NOT NULL AND distance_band <> 'dump'""")
    clusters = _cluster(lifts)

    bins = db.query("SELECT unique_id, lat, lon FROM bins WHERE lat IS NOT NULL")
    index = BinIndex(bins)
    # grid for counting bins within wheel-out radius
    from collections import defaultdict
    gcell = 0.0015
    bgrid = defaultdict(list)
    for b in bins:
        bgrid[(int(b["lat"] / gcell), int(b["lon"] / gcell))].append(b)

    def bins_within(lat, lon, r):
        ci, cj = int(lat / gcell), int(lon / gcell)
        return sum(1 for di in (-1, 0, 1) for dj in (-1, 0, 1)
                   for b in bgrid[(ci + di, cj + dj)]
                   if haversine_m(lat, lon, b["lat"], b["lon"]) <= r)

    rows, counts = [], {"confirmed": 0, "coord_review": 0, "wheel_out": 0, "new": 0}
    lift_updates = []
    for c in clusters:
        b, d = index.nearest(c["lat"], c["lon"])
        nb, nm = (b["unique_id"], round(d, 1)) if b else (None, None)
        n150 = bins_within(c["lat"], c["lon"], WHEEL_OUT)
        if nm is not None and nm <= 15:
            status = "confirmed"                       # truck at the bin
        elif nm is not None and nm <= 50:
            status = "coord_review"                     # near, but offset — review coordinate
        elif n150 > 0:
            status = "wheel_out"                        # far, but known bin(s) within wheel-out range
        else:
            status = "new"                              # isolated — genuinely unknown
        counts[status] += 1
        days, n = len(c["days"]), c["n"]
        rows.append((c["lat"], c["lon"], n, days, len(c["trucks"]),
                     sorted(c["trucks"])[0], nb, nm, n150, status))
        for lid in c["ids"]:
            lift_updates.append((status, n, days, lid))

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO collection_points
                   (lat, lon, lifts, days, trucks, primary_agent, nearest_bin, nearest_m, bins_150, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
            cur.executemany(
                "UPDATE lifts SET cp_status=%s, cp_lifts=%s, cp_days=%s WHERE id=%s",
                lift_updates)
    out = {"points": len(clusters), **counts,
           "repeat_points": sum(1 for c in clusters if len(c["days"]) >= 2)}
    print(f"collection points: {out}")
    return out
