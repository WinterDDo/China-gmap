"""Administrative boundaries of China from Alibaba DataV.GeoAtlas (based on the standard map).

DataV publishes GeoJSON per administrative unit: `100000.json` is the national outline, `100000_full.json` the
provinces (plus the South China Sea dashed line as feature `100000_JD`), `<province>_full.json` the prefecture-level
units of a province (for the four municipalities: their districts/counties). Coordinates are GCJ-02 as published by
Amap; the offset from WGS-84 is under ~0.6 km, far below anything the map draws, so they are used as they are.
"""

from __future__ import annotations

import json

from ..core.source import Source, SourceInfo

BASE = "https://geo.datav.aliyun.com/areas_v3/bound"
PROVINCES = [
    "110000", "120000", "130000", "140000", "150000", "210000", "220000", "230000", "310000", "320000", "330000",
    "340000", "350000", "360000", "370000", "410000", "420000", "430000", "440000", "450000", "460000", "500000",
    "510000", "520000", "530000", "540000", "610000", "620000", "630000", "640000", "650000", "710000", "810000",
    "820000",
]
NO_CHILDREN = {"710000"}  # DataV has no prefecture split for Taiwan


def _features(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for f in d.get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry")
        if not g:
            continue
        out.append({
            "adcode": str(p.get("adcode")),
            "name": p.get("name"),
            "level": p.get("level"),
            "center": p.get("center"),
            "centroid": p.get("centroid"),
            "parent": str((p.get("parent") or {}).get("adcode") or ""),
            "geometry": g,
        })
    return out


class DataV(Source):
    info = SourceInfo(
        id="datav",
        title="中国行政区划边界（国界、省级、地级）与南海断续线",
        publisher="阿里云 DataV.GeoAtlas（数据源自高德开放平台，依据标准地图）",
        homepage="https://datav.aliyun.com/portal/school/atlas/area_selector",
        license="免费公开数据，仅供学习研究使用",
        description="国界轮廓（100000.json）、省级行政区与南海断续线（100000_full.json）、各省的地级行政区（<省代码>_full.json）。"
        "坐标为高德 GCJ-02，与 WGS-84 相差不足 1 公里，远小于地图的绘制精度，未作纠偏。",
        used_for=["国界、陆地国界与海岸线", "省界与省名", "地级区边界（透镜着色、点击查询）", "南海诸岛附图与断续线", "城市驻地位置"],
    )

    def files(self):
        yield f"{BASE}/100000.json", "100000.json"
        yield f"{BASE}/100000_full.json", "100000_full.json"
        for p in PROVINCES:
            if p not in NO_CHILDREN:
                yield f"{BASE}/{p}_full.json", f"{p}_full.json"

    def fetch(self, force: bool = False) -> None:
        for url, rel in self.files():
            self.download(url, rel, force=force)

    def process(self) -> dict:
        nation = _features(self.raw_dir / "100000.json")
        provinces = [f for f in _features(self.raw_dir / "100000_full.json") if f["adcode"] != "100000_JD"]
        jd = [f for f in _features(self.raw_dir / "100000_full.json") if f["adcode"] == "100000_JD"]
        children = []
        for p in PROVINCES:
            if p in NO_CHILDREN:
                continue
            for f in _features(self.raw_dir / f"{p}_full.json"):
                f["province"] = p
                children.append(f)
        return {
            "vintage": "DataV.GeoAtlas areas_v3",
            "nation": nation,
            "provinces": provinces,
            "dashed_line": jd,
            "prefectures": children,
            "_files": [rel for _, rel in self.files()],
        }
