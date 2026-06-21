"""Parse device parameter strings.

Pilot exposes per-point device parameters as a delimited key=value string,
either comma-delimited (sensor-tracing xlsx 'raw data' column) or
semicolon-delimited (admin rawpoints 'triggerdata'). A single regex handles
both. Param463 = tilt angle, DIS1 = ignition.
"""
import re

_CACHE: dict[str, re.Pattern] = {}


def param(blob: str, key: str):
    """Return the integer value of `key` in a key=value blob, or None."""
    if not blob:
        return None
    rx = _CACHE.get(key)
    if rx is None:
        rx = re.compile(rf"{re.escape(key)}\s*=\s*(-?\d+)")
        _CACHE[key] = rx
    m = rx.search(blob)
    return int(m.group(1)) if m else None
