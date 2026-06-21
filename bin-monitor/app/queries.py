"""Read queries that back the dashboard API (match the report's sheets)."""
from . import db


def kpis() -> dict:
    row = db.query("""
        SELECT
          (SELECT count(*) FROM lifts) AS total_lifts,
          (SELECT count(*) FROM lifts WHERE distance_band='<=15m') AS matched,
          (SELECT count(*) FROM lifts WHERE distance_band='15-30m') AS near1,
          (SELECT count(*) FROM lifts WHERE distance_band='30-50m') AS near2,
          (SELECT count(*) FROM lifts WHERE distance_band='>50m') AS unmatched,
          (SELECT count(*) FROM lifts WHERE distance_band='dump') AS dumps,
          (SELECT count(*) FROM bins WHERE collect_status='every_day') AS every_day,
          (SELECT count(*) FROM bins WHERE collect_status='some_days') AS some_days,
          (SELECT count(*) FROM bins WHERE collect_status='never') AS never_bins,
          (SELECT count(*) FROM bins WHERE collect_status IN ('every_day','some_days','never')) AS in_area,
          (SELECT coalesce(sum(missed),0) FROM service_checks WHERE status='partial') AS missed,
          (SELECT count(*) FROM lifts WHERE distance_band <> 'dump') AS bin_lifts,
          (SELECT count(*) FROM bins) AS bins,
          (SELECT count(*) FROM vehicles) AS vehicles,
          (SELECT count(DISTINCT day) FROM lifts) AS days
    """)[0]
    return row


def days() -> list[str]:
    return [str(r["day"]) for r in db.query("SELECT DISTINCT day FROM lifts ORDER BY day")]


def vehicles() -> list[dict]:
    return db.query("""SELECT agent_id, imei, plate, object_name,
                        last_lat, last_lon, last_speed, last_seen_ts FROM vehicles ORDER BY agent_id""")


def _where(day, agent):
    clauses, params = [], []
    if day:
        clauses.append("day=%s"); params.append(day)
    if agent:
        clauses.append("agent_id=%s"); params.append(int(agent))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def lifts(day=None, agent=None, band=None, limit=2000) -> list[dict]:
    w, params = _where(day, agent)
    if band:
        w = (w + (" AND " if w else " WHERE ") + "l.distance_band=%s")
        params.append(band)
    sql = f"""
        SELECT l.agent_id, v.plate, l.day, l.lift_no,
               to_char(to_timestamp(l.start_ts) AT TIME ZONE 'Asia/Dubai','YYYY-MM-DD HH24:MI:SS') AS start_time,
               l.duration_s, l.lat, l.lon, l.matched_bin_id, b.area_name, b.bin_size,
               l.distance_m, l.distance_band, l.suggested_status,
               l.start_angle, l.last_high_angle, l.reset_angle
        FROM lifts l
        LEFT JOIN vehicles v ON v.agent_id=l.agent_id
        LEFT JOIN bins b ON b.unique_id=l.matched_bin_id
        {w.replace('day','l.day').replace('agent_id','l.agent_id') if w else ''}
        ORDER BY l.agent_id, l.day, l.lift_no LIMIT {int(limit)}
    """
    return db.query(sql, params)


def map_bins(day=None, agent=None) -> list[dict]:
    """Each bin with its best (nearest) matched lift -> status/color.
    Collection status is per-day when a day is selected, else the all-days rollup."""
    w, params = _where(day, agent)
    lw = w.replace("day", "l.day").replace("agent_id", "l.agent_id") if w else ""
    if day:
        status_sel = "COALESCE(bd.status,'off_pilot') AS collect_status, bd.collected_m AS collected_m"
        day_join = "LEFT JOIN bin_day_status bd ON bd.unique_id=b.unique_id AND bd.day=%s"
        params = params + [day]
    else:
        status_sel = "b.collect_status AS collect_status, NULL::double precision AS collected_m"
        day_join = ""
    sql = f"""
        WITH bl AS (
            SELECT matched_bin_id,
                   min(distance_m) AS nearest_m,
                   count(*) AS nearby,
                   (array_agg(agent_id ORDER BY distance_m))[1] AS serviced_agent
            FROM lifts l {lw}
            {'AND' if lw else 'WHERE'} matched_bin_id IS NOT NULL AND distance_m <= 50
            GROUP BY matched_bin_id
        )
        SELECT b.unique_id, b.area_name, b.bin_size, b.placement, b.condition,
               b.lat, b.lon, bl.nearest_m, COALESCE(bl.nearby,0) AS nearby_lifts,
               bl.serviced_agent, b.coverage_class, b.covering_agent,
               b.access_class, b.access_detail, b.days_collected, b.service_days,
               b.last_lift_ts, b.pickups,
               {status_sel},
               CASE
                 WHEN bl.nearest_m IS NULL THEN 'not_detected'
                 WHEN bl.nearest_m <= 15 THEN 'matched'
                 WHEN bl.nearest_m <= 30 THEN 'near1'
                 ELSE 'near2'
               END AS status
        FROM bins b
        LEFT JOIN bl ON bl.matched_bin_id = b.unique_id
        {day_join}
        WHERE b.lat IS NOT NULL
    """
    return db.query(sql, params)


def truck_coverage() -> list[dict]:
    """Per-truck: how many distinct bins it actually services (lift within 50m)."""
    rows = db.query("""
        SELECT v.agent_id, v.plate,
               count(DISTINCT l.matched_bin_id) FILTER (WHERE l.distance_m <= 50) AS bins_serviced,
               count(l.id) AS lifts,
               count(l.id) FILTER (WHERE l.distance_band='<=15m') AS matched
        FROM vehicles v LEFT JOIN lifts l ON l.agent_id = v.agent_id
        GROUP BY v.agent_id, v.plate ORDER BY v.agent_id
    """)
    total_bins = db.query("SELECT count(*) n FROM bins WHERE lat IS NOT NULL")[0]["n"]
    serviced = db.query("""
        SELECT count(DISTINCT matched_bin_id) n FROM lifts WHERE distance_m <= 50
    """)[0]["n"]
    rows.append({"agent_id": None, "plate": "— Unused (no truck) —",
                 "bins_serviced": total_bins - serviced, "lifts": None, "matched": None})
    return rows


def map_lifts(day=None, agent=None) -> list[dict]:
    w, params = _where(day, agent)
    sql = f"""SELECT agent_id, day, lift_no, lat, lon, distance_band, distance_m,
                     matched_bin_id, suggested_status, cp_status, cp_lifts, cp_days
              FROM lifts {w}
              {'AND' if w else 'WHERE'} lat IS NOT NULL"""
    return db.query(sql, params)


def route_lines(day=None, agent=None) -> list[dict]:
    """Ordered lift sequence per (agent, day) — the driven collection path."""
    w, params = _where(day, agent)
    rows = db.query(f"""
        SELECT l.agent_id, l.day, l.lift_no, l.lat, l.lon,
               to_char(to_timestamp(l.start_ts) AT TIME ZONE 'Asia/Dubai','HH24:MI') AS t
        FROM lifts l {w}
        {'AND' if w else 'WHERE'} l.lat IS NOT NULL
        ORDER BY l.agent_id, l.day, l.lift_no
    """, params)
    routes: dict = {}
    for r in rows:
        key = (r["agent_id"], str(r["day"]))
        routes.setdefault(key, {"agent_id": r["agent_id"], "day": str(r["day"]),
                                "points": [], "stops": 0})
        routes[key]["points"].append([r["lat"], r["lon"]])
        routes[key]["stops"] += 1
    out = []
    for v in routes.values():
        # straight-line length of the lift sequence (km) — a rough route-effort proxy
        km = 0.0
        for a, b in zip(v["points"], v["points"][1:]):
            km += _haversine_km(a, b)
        v["length_km"] = round(km, 2)
        out.append(v)
    return out


def _haversine_km(a, b) -> float:
    import math
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = math.radians(b[0] - a[0]); dl = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def track_lines(day=None, agent=None) -> list[dict]:
    """The real driven GPS path per (agent, day), from raw_points, glitch-filtered + simplified."""
    from shapely.geometry import LineString
    clauses, params = ["lat IS NOT NULL"], []
    if agent:
        clauses.append("agent_id=%s"); params.append(int(agent))
    rows = db.query(f"""
        SELECT agent_id, ts, to_char(to_timestamp(ts) AT TIME ZONE 'Asia/Dubai','YYYY-MM-DD') AS d,
               lat, lon FROM raw_points
        WHERE {' AND '.join(clauses)} ORDER BY agent_id, ts
    """, params)
    groups: dict = {}
    for r in rows:
        if day and r["d"] != day:
            continue
        groups.setdefault((r["agent_id"], r["d"]), []).append(r)

    MAX_MPS = 33.0  # ~120 km/h — anything faster between fixes is a GPS teleport
    out = []
    for (aid, d), pts in groups.items():
        clean = []
        for p in pts:
            if not clean:
                clean.append(p); continue
            prev = clean[-1]
            dt = p["ts"] - prev["ts"]
            if dt <= 0:
                continue
            dist = _haversine_km([prev["lat"], prev["lon"]], [p["lat"], p["lon"]]) * 1000
            if dist / dt > MAX_MPS:   # impossible jump -> drop this fix
                continue
            clean.append(p)
        if len(clean) < 2:
            continue
        simp = LineString([(c["lon"], c["lat"]) for c in clean]).simplify(0.00005)
        out.append({"agent_id": aid, "day": d, "points": [[y, x] for x, y in simp.coords]})
    return out


def service_checks(only_partial: bool = True) -> list[dict]:
    where = "WHERE status='partial'" if only_partial else ""
    return db.query(f"""SELECT lat, lon, area, day::text AS day, expected, done, missed, status
                        FROM service_checks {where} ORDER BY missed DESC, area""")


def optimized() -> dict:
    rows = db.query("SELECT route_no, bins, cbm, km, points FROM optimized_routes ORDER BY route_no")
    meta = db.query("SELECT val FROM app_meta WHERE key='optimized'")
    summary = meta[0]["val"] if meta else {"trips": len(rows), "trucks": len(rows),
        "total_km": round(sum(r["km"] for r in rows), 1), "bins": sum(r["bins"] for r in rows)}
    return {"summary": summary, "routes": rows}


def violations(days: int = 3) -> list[dict]:
    """Pilot-area bins not lifted within `days` days (SLA violations)."""
    import time
    cutoff = int(time.time()) - days * 86400
    return db.query("""
        SELECT unique_id, area_name, bin_size, COALESCE(pickups,0) AS pickups,
               last_lift_ts, lat, lon,
               to_char(to_timestamp(last_lift_ts) AT TIME ZONE 'Asia/Dubai','MM-DD HH24:MI') AS last_collected,
               CASE WHEN last_lift_ts IS NULL THEN NULL
                    ELSE round((extract(epoch from now()) - last_lift_ts)/86400.0, 1) END AS days_overdue
        FROM bins
        WHERE lat IS NOT NULL AND collect_status <> 'off_pilot'
          AND (last_lift_ts IS NULL OR last_lift_ts < %s)
        ORDER BY last_lift_ts ASC NULLS FIRST
    """, (cutoff,))


def bins_table() -> list[dict]:
    """Bin-centric list: name, area, size, pickups, last collected, status."""
    return db.query("""
        SELECT unique_id, area_name, bin_size, COALESCE(pickups,0) AS pickups,
               COALESCE(days_collected,0) AS days_collected, COALESCE(service_days,0) AS service_days,
               last_lift_ts, collect_status, lat, lon,
               to_char(to_timestamp(last_lift_ts) AT TIME ZONE 'Asia/Dubai','MM-DD HH24:MI') AS last_collected
        FROM bins
        WHERE lat IS NOT NULL AND collect_status <> 'off_pilot'
        ORDER BY pickups DESC, unique_id
    """)


def fleet_plan(coverage_pct: float = 70.0) -> dict:
    """Fewest efficient routes (best bins/km first) that cover >= coverage_pct of bins."""
    import math
    rows = db.query("SELECT route_no, bins, km, points FROM optimized_routes")
    total_bins = sum(r["bins"] for r in rows) or 1
    target = total_bins * coverage_pct / 100.0
    ranked = sorted(rows, key=lambda r: r["bins"] / (r["km"] or 0.1), reverse=True)
    sel, cum = [], 0
    for r in ranked:
        if cum >= target:
            break
        sel.append(r); cum += r["bins"]
    meta = db.query("SELECT val FROM app_meta WHERE key='optimized'")
    tpd = (meta[0]["val"].get("assumptions", {}).get("trips_per_day", 2.5)) if meta else 2.5
    # bins in the routes we did NOT select = left uncovered at this target
    import json as _json
    sel_ids = {r["route_no"] for r in sel}
    uncovered = []
    for r in rows:
        if r["route_no"] in sel_ids:
            continue
        pts = r["points"] if isinstance(r["points"], list) else _json.loads(r["points"])
        uncovered.extend(pts[1:-1])  # drop depot endpoints
    return {
        "coverage_pct": coverage_pct,
        "bins_covered": cum, "total_bins": total_bins,
        "bins_uncovered": total_bins - cum,
        "pct_actual": round(cum / total_bins * 100, 1),
        "trips": len(sel), "trucks": math.ceil(len(sel) / tpd),
        "total_km": round(sum(r["km"] for r in sel), 1),
        "routes": sel, "uncovered": uncovered,
    }


def collection_points() -> list[dict]:
    return db.query("""SELECT lat, lon, lifts, days, trucks, primary_agent,
                              nearest_bin, nearest_m, bins_150, status
                       FROM collection_points ORDER BY lifts DESC""")


def area_zones() -> list[dict]:
    return db.query("""SELECT pilot_id, name, color, points FROM geozones
                       WHERE group_name <> %s AND type='polygon'""", ("15m All Bins Coloured",))


def vehicle_day_summary() -> list[dict]:
    return db.query("""
        SELECT l.agent_id, v.plate, l.day,
               count(*) AS valid_lifts,
               count(*) FILTER (WHERE distance_band='<=15m') AS matched,
               count(DISTINCT matched_bin_id) FILTER (WHERE distance_band='<=15m') AS unique_bins,
               count(*) FILTER (WHERE distance_band='15-30m') AS near1,
               count(*) FILTER (WHERE distance_band='30-50m') AS near2,
               count(*) FILTER (WHERE distance_band='>50m') AS unmatched,
               round(avg(distance_m)::numeric,1) AS avg_distance_m
        FROM lifts l LEFT JOIN vehicles v ON v.agent_id=l.agent_id
        GROUP BY l.agent_id, v.plate, l.day ORDER BY l.agent_id, l.day
    """)


def area_summary() -> list[dict]:
    return db.query("""
        SELECT b.area_name,
               count(DISTINCT b.unique_id) AS expected_bins,
               count(l.id) AS nearby_lifts,
               count(l.id) FILTER (WHERE l.distance_band='<=15m') AS matched,
               count(l.id) FILTER (WHERE l.distance_band='15-30m') AS near1,
               count(l.id) FILTER (WHERE l.distance_band='30-50m') AS near2
        FROM bins b LEFT JOIN lifts l ON l.matched_bin_id=b.unique_id
        WHERE b.area_name IS NOT NULL
        GROUP BY b.area_name ORDER BY b.area_name
    """)
