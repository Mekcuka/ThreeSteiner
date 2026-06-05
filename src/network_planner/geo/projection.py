"""Local equirectangular projection: lon/lat <-> meters."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalProjection:
    """Origin at bbox center; x east, y north in meters."""

    origin_lon: float
    origin_lat: float
    cos_lat: float

    @classmethod
    def from_points(cls, lons: list[float], lats: list[float]) -> LocalProjection:
        if not lons:
            raise ValueError("need at least one point for projection")
        return cls(
            origin_lon=sum(lons) / len(lons),
            origin_lat=sum(lats) / len(lats),
            cos_lat=math.cos(math.radians(sum(lats) / len(lats))),
        )

    def to_local(self, lon: float, lat: float) -> tuple[float, float]:
        x = math.radians(lon - self.origin_lon) * 6371000.0 * self.cos_lat
        y = math.radians(lat - self.origin_lat) * 6371000.0
        return x, y

    def to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        lat = self.origin_lat + math.degrees(y / 6371000.0)
        lon = self.origin_lon + math.degrees(x / (6371000.0 * self.cos_lat))
        return lon, lat

    def distance_m(self, lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        x1, y1 = self.to_local(lon1, lat1)
        x2, y2 = self.to_local(lon2, lat2)
        return math.hypot(x2 - x1, y2 - y1)
