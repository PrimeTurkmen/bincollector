# AIMS Bin Collection Monitor

Pulls fleet + sensor data from the Pilot GPS account, detects bin lifts from the
angle sensor, matches them to expected bin geozones, and shows a live Leaflet map
+ the bin-collection report. Built for the AIMS Group / Kvadrat bin-collection pilot.

## What it does
- **Ingest** — Pilot v3 API (vehicles, live position, 4,248 bin geozones, daily rollups)
  + historical angle/DIS1 via the admin `rawpoints` feed (or the trial `.xlsx` files).
- **Detect lifts** — `Param463 ≥ 90°` while `DIS1 = 1` and `speed < 5 km/h`, one lift per
  up/down cycle. Reproduces the trial report (593 vs 588 lifts; matched/unmatched bands ≈ exact).
- **Match** — point-in-polygon against the real 15 m bin geozones; bands ≤15 / 15–30 / 30–50 / >50 m.
- **Dashboard** — live map (Leaflet, no logo); colour by **status**, **truck**, or **coverage**;
  pilot-bins-only filter; per-truck route paths; per-truck coverage; Excel export; on-demand refresh.

## Layout
```
app/
  config.py          settings (env / .env)
  db.py  schema.sql  Postgres helper + DDL
  pilot_client.py    Pilot v3 API client
  params.py          parse Param463/DIS1 from device strings
  ingest_raw.py      load the trial sensor-tracing .xlsx
  ingest_pilot.py    historical pulls (admin rawpoints / events-raw), windowed
  seed.py            vehicles + geozones (Pilot) + bin master (report)
  lift_detection.py  the lift state machine
  geometry.py        haversine, nearest-bin index, 15 m polygon matcher
  process.py         detection + matching -> lifts
  coverage.py        classify bins: serviced / on-route-unused / off-pilot
  queries.py         dashboard read queries
  live.py            on-demand live position refresh
  scheduler.py       background poller
  report_excel.py    multi-sheet Excel export
  main.py            FastAPI app + auth + static
web/                 dashboard UI (index.html, login.html, static/)
scripts/bootstrap_demo.py   one-shot: schema -> seed -> ingest -> process
```

## Local run (dev)
```bash
uv venv --python 3.12 .venv
uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env          # set DATABASE_URL + Pilot creds
.venv/bin/python scripts/bootstrap_demo.py
.venv/bin/python -m uvicorn app.main:app --port 8000
```

## Deploy
See [DEPLOY.md](DEPLOY.md) for the EC2 + Docker Compose runbook.

## Note on the angle feed
Per-point angle/DIS1 history is **not** exposed to a Pilot *customer* account; it comes
from the **admin `rawpoints`** feed (the `triggerdata` string), which Kvadrat operates.
Set `PILOT_ADMIN_*` to enable fully-automated lift detection from the API. Without it the
app still runs on position data + the seeded trial lifts.
```
