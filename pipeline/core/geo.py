"""Map projection and the fixed map frame.

Everything on the map is in **map km**: an Albers equal-area conic projection of China on a sphere, shifted so the
frame's top-left corner is (0, 0) and y points **down** (screen convention). The browser mirrors these numbers in
web/js/geo.js; world.json publishes them too.

    lat1 = 25°N, lat2 = 47°N (standard parallels), lat0 = 0°, lon0 = 105°E, R = 6371.0088 km

The frame is fixed (not fitted at build time) so that tiles, caches and shared links stay valid across rebuilds:

* x: from 160 km west of China's westernmost point to far enough east that the South China Sea inset (19 % of the
  width, bottom right) sits east of Taiwan;
* y: China's mainland + Hainan + Taiwan centred vertically, with the frame aspect 5400:4374 the web page uses.
"""

from __future__ import annotations

import math

R = 6371.0088
LAT1, LAT2, LAT0, LON0 = 25.0, 47.0, 0.0, 105.0

_P1, _P2, _L0 = math.radians(LAT1), math.radians(LAT2), math.radians(LON0)
N = (math.sin(_P1) + math.sin(_P2)) / 2
C = math.cos(_P1) ** 2 + 2 * N * math.sin(_P1)
RHO0 = R * math.sqrt(C - 2 * N * math.sin(math.radians(LAT0))) / N

# Fixed frame (map km). X0 / Y1 are the Albers coordinates of the frame's left edge and top edge.
X0 = -2778.96
Y1 = 6409.01
WIDTH = 6167.0
HEIGHT = 4995.0


def albers(lon: float, lat: float) -> tuple[float, float]:
    """Raw Albers (km, y up)."""
    rho = R * math.sqrt(C - 2 * N * math.sin(math.radians(lat))) / N
    th = N * (math.radians(lon) - _L0)
    return rho * math.sin(th), RHO0 - rho * math.cos(th)


def to_map(lon: float, lat: float) -> tuple[float, float]:
    """lon/lat (degrees) → map km (origin top-left, y down)."""
    x, y = albers(lon, lat)
    return x - X0, Y1 - y


def from_map(x, y):
    """map km → lon/lat. Works on floats or numpy arrays."""
    try:
        import numpy as np  # noqa: PLC0415

        sqrt, atan2, asin, clip, deg = np.sqrt, np.arctan2, np.arcsin, np.clip, np.degrees
    except ImportError:  # pragma: no cover
        sqrt, atan2, asin, deg = math.sqrt, math.atan2, math.asin, math.degrees
        clip = lambda v, a, b: min(max(v, a), b)  # noqa: E731
    ax, ay = x + X0, Y1 - y
    rho = sqrt(ax ** 2 + (RHO0 - ay) ** 2)
    th = atan2(ax, RHO0 - ay)
    lat = deg(asin(clip((C - (rho * N / R) ** 2) / (2 * N), -1, 1)))
    lon = deg(_L0 + th / N)
    return lon, lat


def projection_dict() -> dict:
    return {"name": "Albers equal-area conic (sphere)", "R": R, "lat1": LAT1, "lat2": LAT2, "lat0": LAT0, "lon0": LON0,
            "x0": X0, "y1": Y1, "width": WIDTH, "height": HEIGHT}


# Raster grids on the frame. Level 0 is the whole frame in one image; level 1 is cut into tiles.
RASTER_LEVELS = {
    0: {"km_per_px": 4.0},
    1: {"km_per_px": 1.0, "tile": 256},
}


def grid_shape(km_per_px: float) -> tuple[int, int]:
    return math.ceil(WIDTH / km_per_px), math.ceil(HEIGHT / km_per_px)
