"""Background scheduler: periodic live-position refresh (and angle pull if admin)."""
import threading
import time
import traceback

from . import config, live, ingest_pilot, process

_thread: threading.Thread | None = None
_stop = threading.Event()


def _loop():
    interval = max(60, config.POLL_INTERVAL_MINUTES * 60)
    while not _stop.wait(interval):
        try:
            live.refresh_positions(kind="scheduled")
            # If admin feed is configured, also pull recent angle data + reprocess.
            if config.PILOT_ADMIN_URL and config.PILOT_ADMIN_USER:
                ingest_pilot.pull_last_days(1)
                process.process_all()
        except Exception:
            traceback.print_exc()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="poller", daemon=True)
    _thread.start()


def stop():
    _stop.set()
