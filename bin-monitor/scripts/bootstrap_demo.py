"""One-shot: schema -> seed (Pilot + report) -> ingest raw -> detect + match."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, seed, ingest_raw, process
from app.pilot_client import PilotClient


def main():
    print("== schema ==")
    db.init_schema()

    print("== seed from Pilot ==")
    client = PilotClient()
    seed.seed_vehicles(client)
    seed.seed_geozones(client)

    print("== seed bins from report ==")
    seed.seed_bins()
    seed.link_geozones_to_bins()

    print("== ingest raw trial files ==")
    ingest_raw.ingest_all()

    print("== detect lifts + match bins ==")
    process.process_all()

    print("== summary ==")
    for r in db.query("""SELECT distance_band, count(*) n FROM lifts
                         GROUP BY distance_band ORDER BY distance_band"""):
        print(f"   {r['distance_band']}: {r['n']}")
    tot = db.query("SELECT count(*) n FROM lifts")[0]["n"]
    print(f"   TOTAL lifts: {tot}")


if __name__ == "__main__":
    main()
