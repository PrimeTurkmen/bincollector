#!/usr/bin/env bash
set -e

echo "Waiting for Postgres..."
python - <<'PY'
import time, psycopg, os
url = os.environ["DATABASE_URL"]
for _ in range(60):
    try:
        psycopg.connect(url).close(); print("Postgres ready"); break
    except Exception as e:
        print("  waiting:", e); time.sleep(2)
else:
    raise SystemExit("Postgres never came up")
PY

# Initialise schema (idempotent)
python -c "from app import db; db.init_schema(); print('schema ready')"

# Optional one-time seed: SEED=1 seeds vehicles+geozones from Pilot, bins from the
# report, and ingests any raw trial files mounted at RAW_DATA_DIR.
if [ "${SEED:-0}" = "1" ]; then
  echo "Seeding..."
  python scripts/bootstrap_demo.py || echo "seed step reported an issue (continuing)"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
