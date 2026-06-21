"""Detect disposal-site (dump) events misread as bin lifts.

A garbage truck tips its full load at the disposal site by raising the body/arm
past 90 deg — identical to a bin lift to the angle sensor. These show up as
repeated high-angle events at a fixed spot far from any bin, every day. We flag
them so they don't pollute the bin-collection counts or the "unmatched" review list.

Signature: lifts > DUMP_MIN_DIST m from the nearest bin, clustered in the same
~110 m cell, hit on >= DUMP_MIN_DAYS distinct days by the same truck.
"""
from collections import defaultdict

from . import db

DUMP_MIN_DIST = 100      # metres from nearest bin
DUMP_MIN_DAYS = 2        # repeated on at least this many days


def flag_dump_events() -> int:
    rows = db.query("""SELECT id, agent_id, day, lat, lon FROM lifts
                       WHERE distance_m > %s AND lat IS NOT NULL""", (DUMP_MIN_DIST,))
    cells = defaultdict(lambda: {"ids": [], "days": set()})
    for r in rows:
        key = (r["agent_id"], round(r["lat"], 3), round(r["lon"], 3))
        cells[key]["ids"].append(r["id"])
        cells[key]["days"].add(str(r["day"]))

    dump_ids = [i for c in cells.values() if len(c["days"]) >= DUMP_MIN_DAYS for i in c["ids"]]
    if dump_ids:
        with db.connect() as conn:
            conn.execute(
                """UPDATE lifts SET distance_band='dump',
                       suggested_status='Disposal site (not a bin)'
                   WHERE id = ANY(%s)""", (dump_ids,))
    print(f"dump events flagged: {len(dump_ids)} (at {sum(1 for c in cells.values() if len(c['days'])>=DUMP_MIN_DAYS)} site(s))")
    return len(dump_ids)
