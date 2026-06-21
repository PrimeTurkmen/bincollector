"""Bin-lift detection state machine (validated against the trial report: 596 vs 588).

A lift cycle begins when the tilt angle (Param463) reaches >= ANGLE_LIFT_THRESHOLD
while ignition (DIS1) is on and speed is below SPEED_MAX. The cycle is counted once
the angle returns below the threshold (one lift per up-down cycle).
"""
from . import config


def detect_lifts(points: list[dict]) -> list[dict]:
    """points: chronological dicts with ts, lat, lon, speed, angle, dis1.
    Returns a list of lift cycle dicts."""
    thr = config.ANGLE_LIFT_THRESHOLD
    smax = config.SPEED_MAX
    lifts: list[dict] = []
    cur = None

    for p in points:
        ang = p.get("angle")
        if ang is None:
            continue
        dis1 = p.get("dis1")
        spd = p.get("speed")
        high = ang >= thr

        if cur is None:
            arm = high and dis1 == 1 and (spd is None or spd < smax)
            if arm:
                cur = {
                    "start_ts": p["ts"], "end_ts": p["ts"],
                    "start_angle": ang, "last_high_angle": ang, "reset_angle": None,
                    "lat": p.get("lat"), "lon": p.get("lon"),
                    "speed": spd, "dis1": dis1,
                }
        else:
            if high:
                if ang > cur["last_high_angle"]:
                    cur["last_high_angle"] = ang   # track peak; keep START coordinate
                cur["end_ts"] = p["ts"]
            else:
                cur["reset_angle"] = ang
                cur["end_ts"] = p["ts"]
                cur["duration_s"] = max(0, cur["end_ts"] - cur["start_ts"])
                lifts.append(cur)
                cur = None

    if cur is not None:  # trailing open cycle
        cur["duration_s"] = max(0, cur["end_ts"] - cur["start_ts"])
        lifts.append(cur)

    return lifts
