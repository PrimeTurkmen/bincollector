"""Geodesic helpers and bin matching (pure Python + shapely)."""
import math
from shapely.geometry import Polygon, Point
from shapely import STRtree
from . import config

EARTH_R = 6371000.0  # meters


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def polygon_center(points: list[list[float]]) -> tuple[float, float]:
    """Centroid of a [[lat,lon],...] ring (simple average — fine for tiny bin zones)."""
    if not points:
        return (None, None)
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return (lat, lon)


def band_for(distance_m: float) -> tuple[str, str]:
    """Return (distance_band, suggested_status) for a lift-to-bin distance."""
    if distance_m <= config.BAND_MATCHED:
        return "<=15m", "Collected <=15m"
    if distance_m <= config.BAND_NEAR:
        return "15-30m", "Near 15-30m - recheck coordinate"
    if distance_m <= config.BAND_POSSIBLE:
        return "30-50m", "Possible moved bin / wrong coordinate"
    return ">50m", "Unmatched lift point"


class PolygonMatcher:
    """Point-in-polygon against the real 15 m bin geozones (the report's <=15m rule)."""

    def __init__(self, zones: list[dict]):
        # zones: dicts with bin_unique_id and points [[lat,lon],...]
        self.polys, self.bin_ids = [], []
        for z in zones:
            pts = z.get("points") or []
            if z.get("bin_unique_id") and len(pts) >= 3:
                self.polys.append(Polygon([(p[1], p[0]) for p in pts]))  # (lon,lat)
                self.bin_ids.append(z["bin_unique_id"])
        self.tree = STRtree(self.polys) if self.polys else None

    def contains(self, lat: float, lon: float):
        """Return the bin_unique_id whose 15m zone contains the point, or None."""
        if not self.tree:
            return None
        pt = Point(lon, lat)
        for i in self.tree.query(pt):
            if self.polys[i].contains(pt):
                return self.bin_ids[i]
        return None


class BinIndex:
    """Spatial index over bin centroids for fast nearest-bin lookup."""

    def __init__(self, bins: list[dict]):
        # bins: dicts with unique_id, lat, lon
        self.bins = [b for b in bins if b.get("lat") is not None and b.get("lon") is not None]
        # bucket by ~0.005 deg (~500m) grid for a cheap neighbor search
        self.cell = 0.005
        self.grid: dict[tuple[int, int], list[dict]] = {}
        for b in self.bins:
            key = (int(b["lat"] / self.cell), int(b["lon"] / self.cell))
            self.grid.setdefault(key, []).append(b)

    def nearest(self, lat: float, lon: float):
        """Return (bin_dict, distance_m) of the closest bin, or (None, None)."""
        ci, cj = int(lat / self.cell), int(lon / self.cell)
        candidates = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                candidates.extend(self.grid.get((ci + di, cj + dj), []))
        if not candidates:  # fall back to full scan if sparse
            candidates = self.bins
        best, bestd = None, float("inf")
        for b in candidates:
            d = haversine_m(lat, lon, b["lat"], b["lon"])
            if d < bestd:
                best, bestd = b, d
        return (best, bestd) if best else (None, None)
