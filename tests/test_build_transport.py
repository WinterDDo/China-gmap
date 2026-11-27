"""explorations/design-freeze/build_transport.py on a small made-up download: joining ways, dropping the second
carriageway, naming, and which lines run through which prefecture."""

import gzip
import json
import sys
import zipfile

import pytest
from conftest import ROOT

pytest.importorskip("pypinyin")
sys.path.insert(0, str(ROOT / "explorations" / "design-freeze"))
import build_transport as bt  # noqa: E402

FRAME = json.load(open(ROOT / "explorations" / "design-freeze" / "data" / "geo.json", encoding="utf-8"))["frame"]
proj = bt.projector(FRAME)


def way(cls, tags, lonlats):
    return [cls, tags, [v for ll in lonlats for v in ll]]


def make(tmp_path, ways):
    z = tmp_path / "lines.zip"
    rec = {"osm_base": "2026-11-27T00:00:00Z", "fetched_at": "2026-11-27T01:00:00+00:00", "ways": ways}
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("osm_lines/SC-road.json.gz", gzip.compress(json.dumps(rec, ensure_ascii=False).encode()))
    # one square prefecture around Chengdu (103.6-104.6 E, 30.2-31.0 N)
    ring = [list(proj(lon, lat)) for lon, lat in [(103.6, 30.2), (104.6, 30.2), (104.6, 31.0), (103.6, 31.0)]]
    out = tmp_path / "data"
    out.mkdir()
    (out / "geo.json").write_text(json.dumps({"frame": FRAME, "prefectures": [{"id": "510100", "rings": [[ring]]}]}))
    (out / "cities.json").write_text(json.dumps([{"id": "510100"}]))
    return z, out


def test_ways_are_joined_and_the_second_carriageway_dropped(tmp_path):
    lon = [103.0 + 0.1 * i for i in range(21)]  # 103.0-105.0 E along 30.6 N, about 190 km
    north = [(x, 30.6) for x in lon]
    south = [(x, 30.6004) for x in lon]  # the other carriageway, about 45 m away
    ways = [way("exp", {"ref": "G42", "name": "沪蓉高速公路"}, north[i:i + 6]) for i in range(0, 20, 5)]
    ways += [way("exp", {"ref": "G42", "name": "沪蓉高速公路"}, list(reversed(south)))]
    ways += [way("hsr", {"name": "成渝高速铁路", "name:en": "Chengdu–Chongqing High-Speed Railway"}, [(104.0, 30.3), (104.5, 30.9), (105.5, 30.0)])]
    z, out = make(tmp_path, ways)
    d = bt.build(str(z), str(out))
    exp = [r for r in d["lines"] if d["names"][r[0]][0] == "exp"]
    assert len(exp) == 1  # four ways joined into one, the parallel carriageway gone
    pts = (len(exp[0]) - 1) // 2
    assert pts <= 4  # a straight road keeps hardly any points after simplifying
    names = {n[1]: n for n in d["names"]}
    assert names["沪蓉高速"] == ["exp", "沪蓉高速", "Hurong Expressway", "G42"]
    assert names["成渝高铁"][2] == "Chengdu–Chongqing HSR"
    assert sorted(d["names"][i][1] for i in d["byCity"]["510100"]) == ["成渝高铁", "沪蓉高速"]
    assert "OpenStreetMap" in d["source"]["zh"] and d["source"]["license"] == "ODbL 1.0"


def test_a_line_that_only_grazes_the_prefecture_is_not_listed(tmp_path):
    ways = [way("rail", {"name": "成昆铁路"}, [(103.55, 29.0), (103.62, 30.21), (103.55, 31.5)])]  # under 3 km inside
    z, out = make(tmp_path, ways)
    d = bt.build(str(z), str(out))
    assert d["byCity"] == {}


def test_english_names_fall_back_to_corrected_pinyin():
    assert bt.en_name("hsr", {}, "川藏铁路") == "Chuanzang HSR"
    assert bt.en_name("rail", {}, "宝成铁路") == "Baocheng Railway"
    assert bt.en_name("exp", {}, "京昆高速") == "Jingkun Expressway"
    assert bt.en_name("hsr", {}, "西成客专线") == "Xicheng HSR"
    assert bt.short_zh("hsr", {"name": "成渝高速铁路（成都段）"}) == "成渝高铁"
