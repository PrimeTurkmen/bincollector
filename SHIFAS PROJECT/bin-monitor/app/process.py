"""Run lift detection + bin matching over raw_points, populate the lifts table."""
from datetime import datetime, timezone, timedelta

from . import db, config, coverage, depot, points, access, reconcile, assign
from .lift_detection import detect_lifts
from .geometry import BinIndex, PolygonMatcher, band_for, haversine_m

UAE = timezone(timedelta(hours=4))  # Asia/Dubai, no DST — matches trial report "Day"


def _day(ts: int):
    return datetime.fromtimestamp(ts, UAE).date()


def process_agent(agent_id: int, bin_index: BinIndex, matcher: PolygonMatcher,
                   bin_xy: dict, only_day=None) -> int:
    pts = db.query(
        "SELECT ts, lat, lon, speed, angle, dis1 FROM raw_points WHERE agent_id=%s ORDER BY ts",
        (agent_id,),
    )
    # group by local day so lift numbering resets daily (as in the report)
    by_day: dict = {}
    for p in pts:
        by_day.setdefault(_day(p["ts"]), []).append(p)

    out = []
    for day, day_pts in by_day.items():
        if only_day and day != only_day:
            continue
        lifts = detect_lifts(day_pts)
        for n, lf in enumerate(lifts, start=1):
            matched_id = dist = band = status = None
            if lf["lat"] is not None and lf["lon"] is not None:
                inside = matcher.contains(lf["lat"], lf["lon"])
                if inside:
                    # lift point falls within a bin's real 15m geozone -> matched <=15m
                    bx = bin_xy.get(inside)
                    d = haversine_m(lf["lat"], lf["lon"], bx[0], bx[1]) if bx else 0.0
                    matched_id, dist = inside, round(d, 2)
                    band, status = "<=15m", "Collected <=15m"
                else:
                    b, d = bin_index.nearest(lf["lat"], lf["lon"])
                    if b:
                        matched_id, dist = b["unique_id"], round(d, 2)
                        band, status = band_for(d)
            out.append((
                agent_id, day, n, lf["start_ts"], lf["end_ts"], lf.get("duration_s"),
                lf["lat"], lf["lon"], lf["start_angle"], lf["last_high_angle"],
                lf.get("reset_angle"), lf.get("speed"), lf.get("dis1"),
                matched_id, dist, band, status, "raw-trial",
            ))

    with db.connect() as conn:
        with conn.cursor() as cur:
            if only_day:
                cur.execute("DELETE FROM lifts WHERE agent_id=%s AND day=%s", (agent_id, only_day))
            else:
                cur.execute("DELETE FROM lifts WHERE agent_id=%s", (agent_id,))
            cur.executemany(
                """INSERT INTO lifts (agent_id, day, lift_no, start_ts, end_ts, duration_s,
                       lat, lon, start_angle, last_high_angle, reset_angle, speed, dis1,
                       matched_bin_id, distance_m, distance_band, suggested_status, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                out,
            )
    return len(out)


def process_all(only_day=None) -> int:
    bins = db.query("SELECT unique_id, lat, lon FROM bins WHERE lat IS NOT NULL")
    index = BinIndex(bins)
    bin_xy = {b["unique_id"]: (b["lat"], b["lon"]) for b in bins}
    zones = db.query("SELECT bin_unique_id, points FROM geozones WHERE group_name=%s",
                     (config.BIN_GROUP_NAME,))
    import json as _json
    for z in zones:
        if isinstance(z["points"], str):
            z["points"] = _json.loads(z["points"])
    matcher = PolygonMatcher(zones)
    agents = [r["agent_id"] for r in db.query("SELECT agent_id FROM vehicles ORDER BY agent_id")]
    total = 0
    for aid in agents:
        n = process_agent(aid, index, matcher, bin_xy, only_day=only_day)
        total += n
        print(f"  agent {aid}: {n} lifts")
    print(f"lifts total: {total}")
    depot.flag_dump_events()
    coverage.classify_bins()
    points.build_collection_points()
    assign.build_collection_status()
    access.analyze_access()
    reconcile.build_service_checks()
    return total
