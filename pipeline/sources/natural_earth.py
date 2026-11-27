"""Natural Earth 1:10m vectors: neighbouring countries (China point of view), lakes and rivers.

China's own outline and borders never come from here (they come from DataV, based on the standard map). Natural
Earth's "China POV" admin-0 file is used only for the neighbours drawn as background; its CHN/TWN/HKG/MAC features
are dropped.
"""

from __future__ import annotations

import json

from ..core.source import Source, SourceInfo

TAG = "v5.1.2"
BASE = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{TAG}/geojson"
FILES = {
    "countries_chn": "ne_10m_admin_0_countries_chn.geojson",
    "lakes": "ne_10m_lakes.geojson",
    "rivers": "ne_10m_rivers_lake_centerlines.geojson",
}
BBOX = (55.0, 0.0, 155.0, 62.0)  # lon/lat window of interest around the map frame


def _touches_bbox(geom) -> bool:
    def pts(g):
        t, c = g["type"], g["coordinates"]
        if t == "Polygon":
            yield from c[0]
        elif t == "MultiPolygon":
            for p in c:
                yield from p[0]
        elif t == "LineString":
            yield from c
        elif t == "MultiLineString":
            for line in c:
                yield from line

    return any(BBOX[0] <= x <= BBOX[2] and BBOX[1] <= y <= BBOX[3] for x, y in pts(geom))


class NaturalEarth(Source):
    info = SourceInfo(
        id="natural_earth",
        title="Natural Earth 1:10m（邻国〔中国视角版〕、湖泊、河流）",
        publisher="Natural Earth",
        homepage="https://www.naturalearthdata.com/",
        license="公有领域",
        description=f"取自 natural-earth-vector {TAG} 的 GeoJSON：中国视角版国家边界（只用作邻国背景，中国本身的疆域不取自此处）、湖泊、河流中心线。",
        used_for=["邻国背景", "河流", "湖泊"],
    )

    def fetch(self, force: bool = False) -> None:
        for name in FILES.values():
            self.download(f"{BASE}/{name}", name, force=force)

    def process(self) -> dict:
        load = lambda k: json.loads((self.raw_dir / FILES[k]).read_text(encoding="utf-8"))  # noqa: E731
        neighbours = []
        for f in load("countries_chn")["features"]:
            p = f["properties"]
            if p.get("ADM0_A3") in ("CHN", "TWN", "HKG", "MAC") or not _touches_bbox(f["geometry"]):
                continue
            neighbours.append({"iso": p.get("ADM0_A3"), "name_zh": p.get("NAME_ZH"), "name_en": p.get("NAME_EN") or p.get("NAME"),
                               "geometry": f["geometry"]})
        lakes = []
        for f in load("lakes")["features"]:
            p = f["properties"]
            if _touches_bbox(f["geometry"]):
                lakes.append({"name_zh": p.get("name_zh"), "name_en": p.get("name"), "rank": p.get("scalerank"),
                              "geometry": f["geometry"]})
        rivers = []
        for f in load("rivers")["features"]:
            p = f["properties"]
            if (p.get("featurecla") or "").startswith("Lake") or not _touches_bbox(f["geometry"]):
                continue
            rivers.append({"name_zh": p.get("name_zh"), "name_en": p.get("name_en") or p.get("name"),
                           "rank": p.get("scalerank"), "geometry": f["geometry"]})
        return {"vintage": f"Natural Earth {TAG}", "neighbours": neighbours, "lakes": lakes, "rivers": rivers,
                "_files": list(FILES.values())}
