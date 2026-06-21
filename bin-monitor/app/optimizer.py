"""Route optimization with Google OR-Tools (free; the Routific/WorkWave equivalent).

Cluster-first, route-second — the standard scalable heuristic:
  1. Sweep bins by bearing from the depot into capacity-bounded clusters (one truck-route each).
  2. OR-Tools solves the optimal visiting order (TSP) within each route.
Distance = haversine x DETOUR for now; swap in an OSRM road matrix later with no
other change. Scales to the full municipality (each cluster solves independently).
"""
import math
import requests
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from . import db
from .geometry import haversine_m

OSRM_BASE = "https://router.project-osrm.org"  # public demo; self-host on EC2 for prod


def snap_to_roads(points: list[list[float]]):
    """Snap an ordered [[lat,lon],...] route to the road network via OSRM.
    Returns (road_points, road_km) or (original, None) on failure."""
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    try:
        r = requests.get(f"{OSRM_BASE}/route/v1/driving/{coords}",
                         params={"overview": "full", "geometries": "geojson"}, timeout=25)
        d = r.json()
        if d.get("code") == "Ok":
            geo = d["routes"][0]["geometry"]["coordinates"]
            return [[c[1], c[0]] for c in geo], round(d["routes"][0]["distance"] / 1000, 2)
    except Exception:
        pass
    return points, None

DETOUR = 1.4
TSP_TIME_LIMIT_S = 1

# Truck / operation assumptions (override via the /api/optimize call when AIMS
# confirms real figures). A "trip" = leave the dump, fill up, return to the dump.
TRUCK_CBM = 16.0          # rear-loading compactor body volume
COMPACTION = 3.5          # waste compresses ~3.5x inside the body
FILL_FACTOR = 0.7         # how full a bin typically is when collected
TRIPS_PER_DAY = 2.5       # dump runs a truck can do per shift


def _depot() -> tuple[float, float]:
    d = db.query("""SELECT avg(lat) la, avg(lon) lo FROM lifts WHERE distance_band='dump'""")
    if d and d[0]["la"]:
        return (d[0]["la"], d[0]["lo"])
    c = db.query("SELECT avg(lat) la, avg(lon) lo FROM bins WHERE lat IS NOT NULL")[0]
    return (c["la"], c["lo"])


def _tsp(depot, pts) -> tuple[list[int], float]:
    """Optimal order through pts starting/ending at depot. Returns (order_idx, km)."""
    nodes = [depot] + pts
    n = len(nodes)
    mat = [[int(haversine_m(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1]) * DETOUR)
            for j in range(n)] for i in range(n)]
    mgr = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(mgr)
    cb = routing.RegisterTransitCallback(
        lambda i, j: mat[mgr.IndexToNode(i)][mgr.IndexToNode(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.seconds = TSP_TIME_LIMIT_S
    sol = routing.SolveWithParameters(p)
    if not sol:
        return list(range(1, n)), sum(mat[0][k] for k in range(1, n)) / 1000
    order, idx, dist = [], routing.Start(0), 0
    while not routing.IsEnd(idx):
        nxt = sol.Value(routing.NextVar(idx))
        dist += routing.GetArcCostForVehicle(idx, nxt, 0)
        node = mgr.IndexToNode(nxt)
        if node != 0:
            order.append(node - 1)  # back to pts index
        idx = nxt
    return order, dist / 1000


import re as _re


def _cbm(s):
    """Volume in CBM. Handles 'X CBM', 'X L'/'XXXL' (litres->CBM), and misc text."""
    if not s:
        return 0.36
    txt = str(s)
    m = _re.search(r"(\d+(?:\.\d+)?)", txt)
    if not m:
        return 0.36                      # named bins (books / cage) -> small default
    val = float(m.group(1))
    if _re.search(r"\bL\b|litre|liter|\dL", txt, _re.I) and "CBM" not in txt.upper():
        return val / 1000.0              # litres -> CBM (e.g. 360 L = 0.36)
    return val



def _proximity_trips(bins, capacity, fill):
    """Greedy compact clustering: seed a bin, keep adding the NEAREST unassigned bin
    until the compactor is full. Produces tight neighbourhood routes (no radial wedges)."""
    from collections import defaultdict
    CELL = 0.0025  # ~250 m grid
    cell = lambda la, lo: (int(la / CELL), int(lo / CELL))
    grid = defaultdict(list)
    for i, b in enumerate(bins):
        grid[cell(b["lat"], b["lon"])].append(i)
    assigned = bytearray(len(bins))

    def nearest(clat, clon):
        ci, cj = cell(clat, clon)
        best, bestd, found = None, 1e18, None
        ring = 0
        while ring <= 60:
            for di in range(-ring, ring + 1):
                for dj in range(-ring, ring + 1):
                    if max(abs(di), abs(dj)) != ring:
                        continue
                    for idx in grid.get((ci + di, cj + dj), []):
                        if assigned[idx]:
                            continue
                        d = haversine_m(clat, clon, bins[idx]["lat"], bins[idx]["lon"])
                        if d < bestd:
                            best, bestd = idx, d
            if best is not None and found is None:
                found = ring
            if found is not None and ring >= found + 1:
                break
            ring += 1
        return best

    trips = []
    for seed in range(len(bins)):
        if assigned[seed]:
            continue
        assigned[seed] = 1
        cl = [seed]
        clat, clon = bins[seed]["lat"], bins[seed]["lon"]
        load = _cbm(bins[seed]["bin_size"]) * fill
        while load < capacity:
            nb = nearest(clat, clon)
            if nb is None:
                break
            l = _cbm(bins[nb]["bin_size"]) * fill
            if load + l > capacity:
                break
            assigned[nb] = 1
            cl.append(nb)
            n = len(cl)
            clat += (bins[nb]["lat"] - clat) / n
            clon += (bins[nb]["lon"] - clon) / n
            load += l
        trips.append([bins[i] for i in cl])
    return trips


def build_optimized_routes(truck_cbm=TRUCK_CBM, compaction=COMPACTION,
                           fill=FILL_FACTOR, trips_per_day=TRIPS_PER_DAY) -> dict:
    """Capacity-constrained: each trip fills the compactor (by CBM) then returns to
    the dump. Trucks = trips / trips-per-day."""
    import json
    db.execute("""CREATE TABLE IF NOT EXISTS optimized_routes (
        id BIGSERIAL PRIMARY KEY, route_no INT, bins INT, cbm DOUBLE PRECISION,
        km DOUBLE PRECISION, points JSONB)""")
    db.execute("ALTER TABLE optimized_routes ADD COLUMN IF NOT EXISTS cbm DOUBLE PRECISION")
    db.execute("TRUNCATE optimized_routes RESTART IDENTITY")
    db.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, val JSONB)")

    bins = db.query("SELECT lat, lon, bin_size FROM bins WHERE lat IS NOT NULL")
    depot = _depot()
    capacity = truck_cbm * compaction           # loose-waste CBM a full trip holds
    # compact, proximity-based trips (grow a tight neighbourhood until the truck is full)
    trips = _proximity_trips(bins, capacity, fill)

    total_km, total_cbm, rows = 0.0, 0.0, []
    for n, cl in enumerate(trips, 1):
        pts = [(b["lat"], b["lon"]) for b in cl]
        order, km = _tsp(depot, pts)
        path = [[depot[0], depot[1]]] + [[pts[i][0], pts[i][1]] for i in order] + [[depot[0], depot[1]]]
        cbm = sum(_cbm(b["bin_size"]) * fill for b in cl)
        rows.append((n, len(cl), round(cbm, 1), round(km, 2), json.dumps(path)))
        total_km += km; total_cbm += cbm

    trucks = math.ceil(len(trips) / trips_per_day)
    summary = {
        "trips": len(trips), "trucks": trucks, "total_km": round(total_km, 1),
        "bins": len(bins), "km_per_bin": round(total_km / len(bins), 3),
        "assumptions": {"truck_cbm": truck_cbm, "compaction": compaction,
                        "fill": fill, "trips_per_day": trips_per_day,
                        "trip_capacity_cbm": round(capacity, 1)},
    }
    with db.connect() as conn:
        with conn.cursor() as cur_:
            cur_.executemany(
                "INSERT INTO optimized_routes (route_no, bins, cbm, km, points) VALUES (%s,%s,%s,%s,%s)", rows)
            cur_.execute("""INSERT INTO app_meta (key, val) VALUES ('optimized', %s)
                            ON CONFLICT (key) DO UPDATE SET val=EXCLUDED.val""", (json.dumps(summary),))
    print(f"optimized: {summary}")
    return summary
