"""Configuration loaded from environment / .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PILOT_BASE = os.getenv("PILOT_BASE", "https://pilot-gps.com")
PILOT_USER = os.getenv("PILOT_USER", "")
PILOT_PASS = os.getenv("PILOT_PASS", "")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/aims_bin")

APP_SECRET = os.getenv("APP_SECRET", "dev-secret")
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "aims")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "aims2026")
POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "180"))

TRIAL_AGENT_IDS = [int(x) for x in os.getenv("TRIAL_AGENT_IDS", "").split(",") if x.strip()]
BIN_GROUP_NAME = os.getenv("BIN_GROUP_NAME", "15m All Bins Coloured")

# Admin rawpoints feed (carries per-point angle/DIS1 via 'triggerdata').
# Customer accounts cannot access this; Kvadrat's admin credentials can.
# When unset, historical pulls fall back to position-only (no lift detection).
PILOT_ADMIN_URL = os.getenv("PILOT_ADMIN_URL", "")          # e.g. https://adm.pilot-gps.com/backend/api.php
PILOT_ADMIN_USER = os.getenv("PILOT_ADMIN_USER", "")
PILOT_ADMIN_PASS = os.getenv("PILOT_ADMIN_PASS", "")

# Lift detection thresholds (matches the trial report logic)
ANGLE_LIFT_THRESHOLD = 90      # Param463 >= 90 degrees
SPEED_MAX = 5                  # km/h, must be below this
# Distance bands in meters
BAND_MATCHED = 15
BAND_NEAR = 30
BAND_POSSIBLE = 50

# Paths to source data (for demo seeding)
RAW_DATA_DIR = os.getenv("RAW_DATA_DIR", "/tmp/rawpackets/Raw Data Packets from device")
REPORT_XLSX = os.getenv(
    "REPORT_XLSX",
    str(ROOT.parent / "AIMS Bin Collection3Vehicles 3Days Compiled Report_from 20260608_20260610.xlsx"),
)
