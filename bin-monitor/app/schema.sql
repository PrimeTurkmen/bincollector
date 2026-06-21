-- AIMS Bin Collection Monitor schema (PostgreSQL, no PostGIS — geometry precomputed in Python)

CREATE TABLE IF NOT EXISTS vehicles (
    agent_id        BIGINT PRIMARY KEY,
    imei            TEXT,
    plate           TEXT,
    object_name     TEXT,
    has_angle_sensor BOOLEAN DEFAULT TRUE,
    last_lat        DOUBLE PRECISION,
    last_lon        DOUBLE PRECISION,
    last_speed      DOUBLE PRECISION,
    last_seen_ts    BIGINT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geozones (
    pilot_id        BIGINT PRIMARY KEY,
    name            TEXT,
    group_name      TEXT,
    type            TEXT,
    color           TEXT,
    points          JSONB,          -- [[lat,lon],...]
    center_lat      DOUBLE PRECISION,
    center_lon      DOUBLE PRECISION,
    bin_unique_id   TEXT            -- linked bin (if a bin zone)
);
CREATE INDEX IF NOT EXISTS idx_geozones_group ON geozones(group_name);

CREATE TABLE IF NOT EXISTS bins (
    unique_id       TEXT PRIMARY KEY,
    asset_number    TEXT,
    area_name       TEXT,
    bin_size        TEXT,
    quantity        TEXT,
    placement       TEXT,
    condition       TEXT,
    vehicle_type    TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    geozone_id      BIGINT,
    nearest1_id     TEXT, nearest1_m DOUBLE PRECISION, nearest1_same TEXT,
    nearest2_id     TEXT, nearest2_m DOUBLE PRECISION, nearest2_same TEXT,
    nearest3_id     TEXT, nearest3_m DOUBLE PRECISION, nearest3_same TEXT
);
CREATE INDEX IF NOT EXISTS idx_bins_area ON bins(area_name);

CREATE TABLE IF NOT EXISTS raw_points (
    id          BIGSERIAL PRIMARY KEY,
    agent_id    BIGINT NOT NULL,
    ts          BIGINT NOT NULL,
    lat         DOUBLE PRECISION,
    lon         DOUBLE PRECISION,
    speed       DOUBLE PRECISION,
    angle       INTEGER,            -- Param463
    dis1        INTEGER,            -- ignition
    mvmnt       INTEGER,
    vsourse     INTEGER,
    source_file TEXT,
    UNIQUE (agent_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_raw_agent_ts ON raw_points(agent_id, ts);

CREATE TABLE IF NOT EXISTS lifts (
    id              BIGSERIAL PRIMARY KEY,
    agent_id        BIGINT NOT NULL,
    day             DATE,
    lift_no         INTEGER,
    start_ts        BIGINT,
    end_ts          BIGINT,
    duration_s      INTEGER,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    start_angle     INTEGER,
    last_high_angle INTEGER,
    reset_angle     INTEGER,
    speed           DOUBLE PRECISION,
    dis1            INTEGER,
    matched_bin_id  TEXT,
    distance_m      DOUBLE PRECISION,
    distance_band   TEXT,           -- '<=15m' | '15-30m' | '30-50m' | '>50m'
    suggested_status TEXT,
    source          TEXT
);
CREATE INDEX IF NOT EXISTS idx_lifts_agent_day ON lifts(agent_id, day);
CREATE INDEX IF NOT EXISTS idx_lifts_band ON lifts(distance_band);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id          BIGSERIAL PRIMARY KEY,
    started_at  TIMESTAMPTZ DEFAULT now(),
    kind        TEXT,               -- 'rawfile' | 'scheduled' | 'ondemand'
    agent_id    BIGINT,
    window_ts   BIGINT,
    window_te   BIGINT,
    rows        INTEGER,
    note        TEXT
);
