"""The hometown card's data in the design prototype: plate prefixes and county outlines.

The card must not be wrong (owner, 2026-11-27), so the table is checked on every commit: each prefix belongs to its
province, no two cities of a province share one, each carries where it was confirmed, and every county the card lets
you pick has an outline to light up."""

import json

from conftest import ROOT

DATA = ROOT / "explorations" / "design-freeze" / "data"
PROV = {"13": "冀", "14": "晋", "15": "蒙", "21": "辽", "22": "吉", "23": "黑", "32": "苏", "33": "浙", "34": "皖", "35": "闽", "36": "赣",
        "37": "鲁", "41": "豫", "42": "鄂", "43": "湘", "44": "粤", "45": "桂", "46": "琼", "51": "川", "52": "贵", "53": "云", "54": "藏",
        "61": "陕", "62": "甘", "63": "青", "64": "宁", "65": "新"}
MUNICIPAL = {"110000": "京", "120000": "津", "310000": "沪", "500000": "渝"}


def load(name):
    return json.load(open(DATA / name, encoding="utf-8"))


def test_every_plate_fits_its_province_and_names_its_source():
    plates = load("plates.json")["plates"]
    cities = {c["id"] for c in load("cities.json")}
    assert len(plates) >= 330 and set(plates) <= cities
    seen = {}
    for cid, v in plates.items():
        assert v["src"], cid
        if cid in MUNICIPAL:
            assert v["plate"] == MUNICIPAL[cid]
            continue
        assert len(v["plate"]) == 2 and v["plate"][0] == PROV[cid[:2]] and "A" <= v["plate"][1] <= "Z" and v["plate"][1] not in "IO", (cid, v)
        assert seen.setdefault(v["plate"], cid) == cid, f"{v['plate']} given to both {seen[v['plate']]} and {cid}"
    assert not {c for c in cities if c[:2] in ("71", "81", "82")} & set(plates)  # 港澳台: no mainland plate


def test_the_page_shows_exactly_the_checked_plates():
    assert load("cityview.json")["plates"] == {cid: v["plate"] for cid, v in load("plates.json")["plates"].items()}


def test_every_county_on_the_card_has_an_outline_and_files_stay_small():
    counties = load("cityview.json")["counties"]
    missing, cache = [], {}
    for cid, rows in counties.items():
        pp = cid[:2]
        if pp not in cache:
            path = DATA / "counties" / f"{pp}.json"
            assert path.stat().st_size < 250_000, f"{path.name} is too heavy to fetch on a phone"
            cache[pp] = load(f"counties/{pp}.json")
        have = cache[pp].get(cid, {})
        missing += [(cid, r[1]) for r in rows if r[0] not in have]
    assert len(missing) <= 15, missing  # a few new or disputed units have no outline in the source; they still show as a name


def test_named_treasures_are_few_marked_and_match_the_page():
    pride = load("pride.json")["pride"]
    cities = {c["id"] for c in load("cities.json")}
    assert set(pride) <= cities and len(pride) >= 150
    for cid, rows in pride.items():
        assert 1 <= len(rows) <= 3, cid
        for name, marks, x, y, en, src in rows:
            assert len(name) >= 2 and marks and set(marks) <= {"遗", "5A", "保"} and src, (cid, name)
            assert not name.endswith(("市", "县", "自治州")), f"{name}: an administrative unit is not a treasure"
        assert len({r[0] for r in rows}) == len(rows), cid
    assert load("cityview.json")["pride"] == {cid: [r[:5] for r in rows] for cid, rows in pride.items()}


def test_food_names_come_from_the_state_council_lists_and_match_the_page():
    doc = load("pride.json")
    food, cities = doc["food"], {c["id"] for c in load("cities.json")}
    assert set(food) <= cities and len(food) >= 80
    for cid, rows in food.items():
        assert 1 <= len(rows) <= 2, cid
        for name, en, src, kind in rows:
            assert name and en, (cid, name)
            if kind == "遗":   # the State Council's lists: batch, item code, declaring place
                assert src.startswith("国家级非遗 B") and "Ⅷ-" in src and " @ " in src, (cid, name, src)
            else:              # a geographical indication: place of origin as printed, and the ministry's page
                assert kind == "标" and src.startswith("地理标志") and "原产地" in src and "ipr.mofcom.gov.cn" in src, (cid, name, src)
    assert load("cityview.json")["food"] == {cid: [[r[0], r[1], r[3]] for r in rows] for cid, rows in food.items()}
    assert sum(1 for rows in food.values() for r in rows if r[3] == "标") >= 40
    # a few everyone knows, each in the right city
    by_name = {c["n"]: c["id"] for c in load("cities.json")}
    for city, dish in (("兰州", "兰州牛肉面"), ("柳州", "柳州螺蛳粉"), ("南充", "保宁醋"), ("遵义", "茅台酒"), ("北京", "北京烤鸭"), ("三明", "沙县小吃"), ("哈尔滨", "五常大米"), ("湖州", "安吉白茶"), ("烟台", "烟台葡萄酒")):
        assert dish in [r[0] for r in food[by_name[city]]], (city, dish)
