"""Elevation from the AWS Terrain Tiles (Tilezen "terrarium" PNG tiles).

Each 256 px tile encodes height as  h = R·256 + G + B/256 − 32768  metres. Zoom 7 (≈1.2 km/px at the equator,
≈0.9 km at 40°N) is enough for the 2 km map raster. Tiles covering the map frame are cached under data/raw/terrain/;
process() mosaics them and resamples onto the map grids (see build/raster.py), so it only records what was fetched.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..core import fetch, geo
from ..core.source import Source, SourceInfo
from ..core.store import atomic_write_text

ZOOM = 7
URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"


def tile_range(z: int = ZOOM):
    """Tiles covering the map frame (sampled along its edges and interior)."""
    lons, lats = [], []
    steps = 40
    for i in range(steps + 1):
        for j in range(steps + 1):
            lon, lat = geo.from_map(geo.WIDTH * i / steps, geo.HEIGHT * j / steps)
            lons.append(float(lon))
            lats.append(float(lat))
    n = 2 ** z

    def tx(lon):
        return int((lon + 180) / 360 * n)

    def ty(lat):
        lr = math.radians(lat)
        return int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)

    return range(tx(min(lons)), tx(max(lons)) + 1), range(ty(max(lats)), ty(min(lats)) + 1)


class Terrain(Source):
    info = SourceInfo(
        id="terrain",
        title="地形高程（AWS Terrain Tiles，terrarium 编码）",
        publisher="Tilezen / Mapzen，托管于 Amazon Web Services 开放数据；底层数据为 SRTM、GMTED2010、ETOPO1 等",
        homepage="https://registry.opendata.aws/terrain-tiles/",
        license="开放数据，需署名（© Mapzen；SRTM、GMTED2010、ETOPO1 等各自的公开许可）",
        description="第 7 级 terrarium 瓦片（约 1 公里分辨率）拼接后重采样到地图网格，用于山体晕渲与按海拔着色（山脚赭石、山腰石绿、峰顶石青）。",
        used_for=["山体晕渲", "按海拔分层设色", "雪线"],
    )

    def tiles(self):
        xs, ys = tile_range()
        for x in xs:
            for y in ys:
                yield x, y

    def fetch(self, force: bool = False) -> None:
        todo = []
        for x, y in self.tiles():
            rel = f"{ZOOM}/{x}/{y}.png"
            if force or not (self.raw_dir / rel).exists():
                todo.append((x, y, rel))
        if not todo:
            return
        if fetch.OFFLINE:
            raise fetch.OfflineError(f"--offline: {len(todo)} terrain tiles are not cached")
        print(f"    ↓ {len(todo)} terrain tiles (z{ZOOM})")

        def get(job):
            x, y, rel = job
            url = URL.format(z=ZOOM, x=x, y=y)
            for attempt in range(3):
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": fetch.USER_AGENT})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        body = r.read()
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code in (403, 404):
                        return rel, url, None  # no tile there
                    if attempt == 2:
                        raise
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    if attempt == 2:
                        raise
            dest = self.raw_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return rel, url, body

        manifest = fetch.read_manifest(self.id)
        with cf.ThreadPoolExecutor(12) as pool:
            for rel, url, body in pool.map(get, todo):
                if body is None:
                    continue
                manifest[rel] = {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                                 "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        atomic_write_text(fetch.manifest_path(self.id), json.dumps(manifest, indent=2, sort_keys=True))

    def process(self) -> dict:
        have = [f"{ZOOM}/{x}/{y}.png" for x, y in self.tiles() if (self.raw_dir / f"{ZOOM}/{x}/{y}.png").exists()]
        xs, ys = tile_range()
        return {
            "vintage": "AWS Terrain Tiles (terrarium)",
            "zoom": ZOOM,
            "x": [xs.start, xs.stop - 1],
            "y": [ys.start, ys.stop - 1],
            "tiles": len(have),
            "_files": have,
        }
