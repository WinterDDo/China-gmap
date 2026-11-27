"""Match place names as publishers write them to the 6-digit codes of pipeline/reference/names.json.

Publishers shorten names: 延边州 for 延边朝鲜族自治州, 内蒙古 for 内蒙古自治区, 广　西 (with a full-width space) for
广西壮族自治区. Matching is always done *within a known province*, which settles the traps:

* 海南州 (青海 海南藏族自治州, 632500) vs 海南省 (460000): a city is only looked up among its province's cities;
* 吉林市 (220200) vs 吉林省 (220000): "吉林市" is a city key, "吉林省"/"吉林" are province keys;
* 朝阳市 (辽宁) vs 朝阳区 (北京): districts are never candidates.

Scope: the nation ("中国" → 100000), the 34 provincial units and the prefecture-level units (level "city"). County-level
units (districts, 省直辖县) are not matched: their bulletins are out of scope.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

NAMES_FILE = Path(__file__).resolve().parents[1] / "reference" / "names.json"
NATION = "100000"
NATION_NAMES = ("中国", "全国", "中华人民共和国")

# tjcn.org bulletin folders: two-digit order + pinyin initials of the province. The number decides (2022 files
# 吉林市 under "08jl", whose number is 黑龙江's and whose letters are 吉林's); a folder is a hint, never the only key.
TJCN_FOLDERS = {
    "00zg": NATION, "01bj": "110000", "02tj": "120000", "03hb": "130000", "04sx": "140000", "05nmg": "150000",
    "06ln": "210000", "07jl": "220000", "08hlj": "230000", "09sh": "310000", "10js": "320000", "11zj": "330000",
    "12ah": "340000", "13fj": "350000", "14jx": "360000", "15sd": "370000", "16hn": "410000", "17hb": "420000",
    "18hn": "430000", "19gd": "440000", "20gx": "450000", "21hn": "460000", "22cq": "500000", "23sc": "510000",
    "24gz": "520000", "25yn": "530000", "26xz": "540000", "27sx": "610000", "28gs": "620000", "29qh": "630000",
    "30nx": "640000", "31xj": "650000",
}

_SPACES = re.compile(r"[\s　\xa0]+")


def clean(text: str) -> str:
    """Drop all whitespace, including full-width spaces ("广　西" → "广西")."""
    return _SPACES.sub("", text or "")


@lru_cache(maxsize=1)
def load_names(path: str | None = None) -> dict[str, dict]:
    return json.loads(Path(path or NAMES_FILE).read_text(encoding="utf-8"))


def name_variants(entry: dict) -> list[str]:
    """Names a publisher may use for a unit, longest first (all are unambiguous within its province)."""
    zh, full, level = entry["zh"], entry["zh_full"], entry["level"]
    out = [full]
    if level == "province":
        out += [zh, zh + ("市" if full.endswith("市") else "省")] if not full.endswith("区") else [zh]
    elif full.endswith("自治州"):
        out += [zh + "州", zh + "自治州", full.replace("自治州", "州")]  # 延边州, 巴音郭楞蒙古州
    elif full.endswith("地区"):
        out += [zh + "地区"]
    elif full.endswith("盟"):
        out += [zh + "盟"]
    seen: list[str] = []
    for v in out:
        if v not in seen:
            seen.append(v)
    return sorted(seen, key=len, reverse=True)


class PlaceMatcher:
    """Looks up names → codes, province by province."""

    def __init__(self, names: dict[str, dict] | None = None):
        self.names = names if names is not None else load_names()
        self.provinces: dict[str, str] = {}  # key → province code
        self.cities: dict[str, dict[str, str]] = {}  # province code → {key → city code}
        for code, e in self.names.items():
            if e["level"] == "province":
                for v in name_variants(e):
                    self.provinces[v] = code
            elif e["level"] == "city":
                bucket = self.cities.setdefault(e["parent"], {})
                for v in name_variants(e):
                    bucket[v] = code

    def province(self, text: str) -> str | None:
        """Province (or nation) code for a province-level name, e.g. "内蒙古", "广　西", "河北省", "中　国"."""
        t = clean(text)
        if t in NATION_NAMES:
            return NATION
        return self.provinces.get(t)

    def city(self, text: str, province: str) -> str | None:
        """Prefecture-level code for `text` among `province`'s cities ("海南州" in 630000 → 632500)."""
        return self.cities.get(province, {}).get(clean(text))

    def unit(self, text: str, province: str) -> str | None:
        """A city of `province`, or `province` itself when `text` names it (list pages mix both)."""
        t = clean(text)
        code = self.city(t, province)
        if code:
            return code
        p = self.province(t)
        return p if p == province else None

    def find_in(self, text: str, province: str) -> str | None:
        """Code of the unit of `province` (or the province itself) whose name *starts* `text`.

        For titles such as "鹰潭市2023年国民经济和社会发展统计公报": the longest matching key wins, and it must be
        followed by the year or the end of the name (so "吉林市" in "吉林市船营区…" does not count)."""
        t = clean(text)
        keys = dict(self.cities.get(province, {}))
        for k, c in self.provinces.items():
            if c == province:
                keys[k] = c
        if province == NATION:
            keys.update({n: NATION for n in NATION_NAMES})
        for k in sorted(keys, key=len, reverse=True):
            if t.startswith(k) and (len(t) == len(k) or re.match(r"(?:20\d\d|（|\()", t[len(k):])):
                return keys[k]
        return None

    def label(self, code: str) -> str:
        if code == NATION:
            return "全国"
        return self.names[code]["zh_full"]

    def province_of(self, code: str) -> str:
        """Province code of a unit (itself for provinces and the nation)."""
        if code == NATION or self.names[code]["level"] == "province":
            return code
        return self.names[code]["parent"]


def bulletin_units(names: dict[str, dict] | None = None, *, mainland_only: bool = True) -> list[str]:
    """Codes that publish a 国民经济和社会发展统计公报: the nation, provinces and prefecture-level units.

    Taiwan, Hong Kong and Macao publish no such bulletin and are left out when `mainland_only`."""
    names = names if names is not None else load_names()
    skip = {"710000", "810000", "820000"} if mainland_only else set()
    out = [NATION]
    for code, e in names.items():
        if e["level"] not in ("province", "city") or code in skip or e.get("parent") in skip:
            continue
        out.append(code)
    return sorted(out)
