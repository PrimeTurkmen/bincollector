# AIMS Bin Collection Monitor — Phase 1 Design

**Date:** 2026-06-17
**Owner:** Kvadrat Systems (for AIMS Group bin-collection contract)
**Status:** Approved for build (demo-first)

## Purpose

Replace the manual Pilot-export → Excel → Power BI workflow with a single application that:
- Pulls vehicle + sensor data from the Pilot GPS account automatically (and on demand),
- Stores it in PostgreSQL,
- Detects bin lifts from the angle sensor and matches them to expected bin geozones,
- Displays a live Leaflet map (logo/attribution removed) + the bin-collection report,
- Exports the familiar Excel report for management.

This is the system to demo to AIMS to win the contract.

## Decisions (from brainstorming)

- **Scope:** Phase 1 = the 3 trial trucks (angle-sensor agents 193843, 193930, 194072) and their bins/areas. Built fleet-ready (adding a truck = config, not code).
- **Mode:** Both — live map now + nightly/on-demand report (build live core first).
- **Freshness:** Relaxed. Scheduled background refresh every ~15 min up to a few hours, **plus on-demand "pull latest" from the dashboard.**
- **Approach:** A — single FastAPI service, Docker, on one EC2.
- **Stack:** Python + FastAPI; PostgreSQL (no PostGIS — geometry precomputed in Python with shapely); Leaflet front end; Excel export retained.

## Validated facts (probed against the live account)

- Auth works on `https://pilot-gps.com` (account "AIMS GROUP for BIN Collection", node 0).
- Live position + speed available (`/api/v3/vehicles/status`, `/events/raw`).
- **4,248 bin geozones + 27 area zones** readable via `/api/v3/geofences` (group "15m All Bins Coloured").
- Angle = `Param463` "Tilt Angle Sensor1" (tag 36517); ignition = `DIS1` (tag 36575).
- **Lift detection reproduced from raw data: 596 lifts vs report's 588 (1.4% off; per-vehicle near-exact).** Logic: `Param463 ≥ 90` while `DIS1 = 1` and `speed < 5`, one lift per cycle until angle resets `< 90`.
- **Open item:** clean per-point angle/DIS1 time-series from the live API (the obvious sensor endpoints return definitions, not readings). Data demonstrably exists (in exports). Resolve during build; admin internal API (`pilot_live_service.py` style) is the fallback. **Demo is seeded from the real raw files, so this does not block the demo.**

## Components (one FastAPI service)

1. **pilot_client** — auth + `vehicles`, `status`, `events/raw`, `geofences`, `last24h`, sensor feed.
2. **ingest_raw** — parse the 9 sensor-tracing `.xlsx` files → `raw_points` (angle/DIS1 parsed from the `raw data` string).
3. **ingest_pilot** — seed `geozones` + `vehicles` from Pilot; pull live `status`; on-demand pull.
4. **seed_bins** — load bin master (asset no., area, size, placement, condition, vehicle type, nearest 1/2/3) from the Bins Distribution list.
5. **lift_detection** — the validated state machine → `lifts`.
6. **geometry** — geodesic nearest-bin distance + point-in-polygon (shapely + pyproj) → distance band + suggested status.
7. **process** — run detection + matching, build summary views.
8. **report_excel** — export the multi-sheet Excel report.
9. **web app (FastAPI + Leaflet)** — live map, KPI dashboard, report tables, on-demand refresh button, simple login.

## Data model (PostgreSQL)

- `vehicles` (agentid PK, imei, plate, object_name, has_angle_sensor)
- `geozones` (pilot_id PK, name, group_name, type, points JSON, bin_unique_id FK)
- `bins` (unique_id PK, asset_number, area_name, bin_size, quantity, placement, condition, vehicle_type, lat, lon, geozone_id, nearest1/2/3 …)
- `raw_points` (id, agent_id, ts, lat, lon, speed, angle, dis1, mvmnt, vsourse, source_file) — unique (agent_id, ts)
- `lifts` (id, agent_id, day, lift_no, start_ts, end_ts, duration_s, lat, lon, start_angle, last_high_angle, reset_angle, speed, dis1, matched_bin_id, distance_m, distance_band, suggested_status, source)
- `ingest_runs` (id, started_at, kind [scheduled|ondemand|rawfile], window_ts/te, rows, note)
- Views: `vehicle_day_summary`, `area_summary`, `expected_bin_status` (match existing sheets)

## Distance bands (unchanged)

`≤15m` matched · `15–30m` near/recheck · `30–50m` possible moved/wrong coord · `>50m` unmatched · expected bin with no lift within 50m = `Not detected`.

## Hosting

One small EC2 (t3.small), Docker Compose: `app` + `postgres` (persistent volume), nightly DB dump. Postgres-in-container for trial; swap to RDS for production with no code change (just `DATABASE_URL`). For local demo: existing local PostgreSQL 17, database `aims_bin`, run via `uvicorn`.

## Build order

DB schema → seed bins/geozones (Pilot + report) → ingest 9 raw files → lift detection → matching → summaries → FastAPI API → Leaflet dashboard → on-demand refresh → Excel export → Docker/EC2 packaging.

## Out of scope (Phase 1)

QR codes, full fleet onboarding, weight integration, multi-tenant, mobile app. (Noted in email thread as later phases.)
