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
        for name, marks, x, y, en, src in (r[:6] for r in rows):      # a seventh, when there, is the row of the State Council's list
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


# ---- the card draw's pool: every highlight a draw can turn up has a source, and sits under the right city ----
SRC = ROOT / "explorations" / "design-freeze" / "sources"
CATS = ["民间文学", "传统音乐", "传统舞蹈", "传统戏剧", "曲艺", "传统体育、游艺与杂技", "传统美术", "传统技艺", "传统医药", "民俗"]
NUMERALS = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"


def heritage_rows():
    return [line.rstrip("\n").split("\t") for line in open(SRC / "feiyi_all.tsv", encoding="utf-8") if line.strip() and not line.startswith("#")]


def test_heritage_filings_name_a_place_of_the_city_they_sit_under():
    import re
    cities = {c["n"]: c for c in load("cities.json")}
    counties = load("cityview.json")["counties"]
    import sys
    sys.path.insert(0, str(DATA.parent))
    from build_feiyi import WAS_PREFECTURE as was_prefecture
    rows = heritage_rows()
    assert len(rows) >= 3000 and len({r[0] for r in rows}) >= 325
    assert sum(1 for r in rows if r[3].startswith("B5")) >= 400       # the fifth list, read off pictures by two readers apart
    for city, cat, name, code, orig, by in rows:
        c = cities[city]
        assert re.fullmatch(rf"B[1-5]x? [{NUMERALS}]-\d+", code), (city, name, code)
        assert CATS[NUMERALS.index(code.split(" ")[1][0])] == cat, (city, name, code, cat)   # the numeral is the category
        item, _, where = orig.partition(" @ ")
        # the item's own name, one of its sub-items, or the two as the notice prints them: 灯彩（佛山彩灯）
        m = re.fullmatch(r"([^（]+)（([^（）]+)）", name)
        assert 2 <= len(name) <= 18 and (name in item or (m and item.startswith(m.group(1) + "（") and m.group(2) in item)), (city, name, item)
        # no place and no list fused into the name, nothing the page could not print
        assert not re.search(r"省|自治区|自治州|字旁|[、，]$|^[（(]|[\ue000-\uf8ff]", name) and name.count("（") == name.count("）"), (city, name)
        if by:      # declared by a county: it is one of this city's, and the notice names it (湟中区 as 湟中县 if it has changed rank since)
            assert by in {r[1] for r in counties.get(c["id"], [])} and (by in where or re.search(re.escape(by[:-1]) + "(县|市|区|旗)", where)), (city, name, by)
        else:       # declared by the prefecture itself (or, for a municipality, by a body in it)
            # 哈密地区 is 哈密市 today; 思茅市 is 普洱 and 莱芜市 is part of 济南 (the reader's own short list of such cases)
            # or the reader left the county blank on purpose, because it has been split since (揭东, 余杭)
            mine = [r[1] for r in counties.get(c["id"], []) if len(r[1]) >= 3]
            assert (c["full"] in where or c["n"] + "地区" in where or any(old in where for old in was_prefecture)
                    or any(re.search(re.escape(n[:-1]) + "(县|市|区|旗)", where) for n in mine)), (city, name, where)
    filed = {(r[0], r[2]): r for r in rows}
    # ones checked by hand against the notices, including two that an earlier version of the reader got wrong
    assert filed[("天水", "太昊伏羲祭典")][1] == "民俗" and filed[("天水", "太昊伏羲祭典")][3] == "B1 Ⅹ-37"
    assert ("乐山", "峨眉武术") in filed and ("眉山", "峨眉武术") not in filed    # 峨眉山市 belongs to 乐山
    assert filed[("塔城", "江格尔")][5] == "和布克赛尔蒙古自治县" and ("巴音郭楞", "江格尔") in filed   # a place list wrapped over four lines
    for pair in (("七台河", "七台河刀剑锻制技艺"), ("福州", "佾舞"), ("三亚", "疍歌"), ("泉州", "泉州刣狮"), ("百色", "末伦"), ("天水", "武山旋鼓舞"), ("天水", "秦安小曲"), ("吉安", "鲤鱼灯舞"), ("佛山", "灯彩（佛山彩灯）"), ("泉州", "江加走木偶头雕刻"), ("郑州", "小相狮舞"), ("苏州", "苏州评弹"),
                 ("邯郸", "豫剧（桑派）"), ("沧州", "沧州武术"), ("文山", "铜鼓舞"), ("大同", "广灵染色剪纸")):
        assert pair in filed, pair
    # found by an independent read of every row with sub-items: the place decides by its position in the row, not by a
    # name that happens to occur in a sub-item (黄山区 declared 太平猴魁, though "黄山" is in 黄山毛峰)
    assert filed[("黄山", "绿茶制作技艺（太平猴魁）")][5] == "黄山区" and filed[("黄山", "绿茶制作技艺（黄山毛峰）")][5] == "徽州区"
    assert not [r for r in rows if r[0] == "镇江" and r[3] == "B2x Ⅶ-50"]      # the saved page is in doubt there: left out
    # a county that has become a district or a city since the notice is found under today's name
    assert [r for r in rows if r[0] == "西宁" and r[5] == "湟中区"] and [r for r in rows if r[0] == "荆门" and r[5] == "京山市"]
    assert [r for r in rows if r[0] == "普洱" and "思茅市" in r[4]]             # and a prefecture renamed since, through its seat,
    assert filed[("普洱", "牡帕密帕")][5] == "" and filed[("济南", "莱芜梆子")][5] == ""   # without naming that seat as the declaring county


def test_the_draw_pool_only_holds_what_the_provenance_file_holds():
    import re
    pool, doc = load("pool.json"), load("pride.json")
    cities = {c["id"]: c for c in load("cities.json")}
    counties = load("cityview.json")["counties"]
    heritage = {(r[0], r[2]) for r in heritage_rows()}
    assert set(pool) == {"more", "food", "lore"}
    for cid, rows in pool["more"].items():      # further places: never one of the card's own three, never two of a name
        names = [r[0] for r in doc["pride"].get(cid, [])] + [r[0] for r in rows]
        assert len(names) == len(set(names)) <= 12, cid
        assert rows == [r[:5] for r in doc["more"][cid]]
        for name, marks, x, y, en in rows:
            assert len(name) >= 2 and marks and set(marks) <= {"遗", "5A", "保"}, (cid, name)
    import sys
    sys.path.insert(0, str(DATA.parent))
    import build_pride as bp                      # the rules themselves: one place for the pattern and the lists
    names = [(cities[cid]["n"], r[0]) for key in ("pride", "more") for cid, rows in doc[key].items() for r in rows]
    # a draw celebrates what it turns up: no massacre site, no prison, no war cemetery
    assert not [x for x in names if bp.SOMBRE.search(x[1]) or x[1] in bp.DROP or x in bp.DROP_IN]
    # what an independent read of every name found (2026-11-28): labels in traditional characters, a character phones
    # cannot draw, a bare type standing in for a name. The first is a tripwire of common characters, not a full test.
    trad = re.compile("[國會舊島萬墳關營驛漢樓橋龍閣觀遠晉鄧張園樂薩爾滸煬蘆飛峽東門廟寶陽陰陳劉趙吳鄭馬馮楊黃齊魯遼寧廣蘇貴雲滿區縣鎮鄉莊橫嶺巖灣澤濟溫滄瀘澗淵塢壩壇牆壘塚處遺跡蹟紀館學書畫傳圖磚窯鐵銅銀鋼鐘鑄鍾錢鏡長開閘間階隊陣戰軍總統議辦業廠礦產倉庫車輪運郵電氣機農漁鹽麥麵絲織紡綢繡紙筆硯藝術戲劇臺碼頭邊內側鄰與壽祿禎禪釋聖靈齋廳鋪衛嶽崗灘溝場]")
    assert not [x for x in names if trad.search(x[1]) or any(ord(ch) > 0xFFFF for ch in x[1]) or x[1] in bp.GENERIC]
    # a mark belongs to the place itself: a neighbour does not lend its own (东方明珠 is a 5A area, not a protected site)
    marks = {(cities[cid]["n"], r[0]): r[1] for cid, rows in doc["pride"].items() for r in rows}
    assert marks[("上海", "东方明珠广播电视塔")] == ["5A"] and marks[("开封", "清明上河园")] == ["5A"] and marks[("南昌", "滕王阁")] == ["5A"]
    assert marks[("天水", "麦积山石窟")] == ["5A", "保"]      # one place under two records still carries both
    assert ("泉州", "泉州") not in marks and ("马鞍山", "采石矶") in marks and ("韶关", "丹霞山") not in marks
    for cid, rows in doc["more"].items():
        assert all(r[5] for r in rows), cid       # each carries its record
    for cid, rows in pool["food"].items():
        assert 1 <= len(rows) <= 6 and rows == [[r[0], r[1], r[3]] for r in doc["food_all"][cid]], cid
        assert [r[:2] for r in rows[:2]] == [r[:2] for r in doc["food"][cid]], cid     # the card's own food line is the first two
    for cid, rows in pool["lore"].items():
        assert 1 <= len(rows) <= 12 and rows == [r[:4] for r in doc["lore"][cid]], cid
        foods = {r[0] for r in pool["food"].get(cid, [])}
        mine = {r[1] for r in counties.get(cid, [])}
        for (name, en, cat, by), full in zip(rows, doc["lore"][cid]):
            assert (cities[cid]["n"], name) in heritage and name not in foods, (cid, name)
            assert en and 0 <= cat < len(CATS) and (not by or by in mine), (cid, name)
            assert full[4].startswith("国家级非遗 B") and " @ " in full[4], (cid, name)
    # enough to draw from: a draw shows three, so a city needs more than three for the next draw to differ
    size = {cid: len(doc["pride"].get(cid, [])) + len(pool["more"].get(cid, [])) + len(pool["food"].get(cid, [])) + len(pool["lore"].get(cid, [])) for cid in cities}
    assert sum(1 for n in size.values() if n > 3) >= 320, sum(1 for n in size.values() if n > 3)


def guobao_rows():
    return [line.rstrip("\n").split("\t") for line in open(SRC / "guobao_all.tsv", encoding="utf-8") if line.strip() and not line.startswith("#")]


def test_protected_sites_are_read_off_the_state_council_lists():
    """The owner chose this over everything else on 2026-11-28: a name on a card must lead back to the official
    original. Each list is checked against the count its own notice states."""
    import re
    from collections import Counter
    rows, cities = guobao_rows(), {c["n"] for c in load("cities.json")}
    stated = {"1": 180, "2": 62, "3": 258, "4": 250, "5": 518, "6": 1080, "7": 1943, "8": 762}
    per = Counter(r[0] for r in rows)
    assert {"1", "2", "3", "4", "5", "6", "8"} <= set(per) <= set(stated)
    assert all(per[b] == stated[b] for b in per), per
    prov = re.compile("^(北京市|天津市|上海市|重庆市|.{2,3}省|内蒙古自治区|广西[壮僮]族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|新疆生产建设兵团)")
    for b in per:
        assert [int(r[1]) for r in rows if r[0] == b] == list(range(1, per[b] + 1)), b
    for r in rows:
        assert len(r) == 8 and r[3] and r[4] and prov.match(r[6]), r
        assert not re.search(r"\s", "".join(r)) and set(c for c in r[7].split("、") if c) <= cities, r
    at = {(r[0], r[4]): r[7] for r in rows}
    # as printed, and filed by the printed address: an old style of today's city, a county that changed province
    assert at[("1", "故宫")] == "北京" and at[("1", "芦沟桥")] == "北京" and at[("6", "元大都城墙遗址")] == "北京" and at[("8", "上宅遗址")] == "北京"
    assert at[("1", "延安革命遗址")] == "延安" and at[("1", "中苏友谊纪念塔")] == "大连" and at[("1", "独乐寺")] == "天津"
    assert at[("4", "龙骨坡遗址")] == "重庆" and at[("1", "八路军重庆办事处旧址")] == "重庆" and at[("6", "闽东北廊桥")] == "宁德、南平"
    # a county since abolished, a whole province, a line across the country, a name the page cannot print: nowhere
    assert at[("1", "武当山金殿")] == "" and at[("6", "京杭大运河")] == "" and at[("5", "长城")] == ""
    assert [r[7] for r in rows if "字旁加" in r[4]] == [""]
    # the transcribed lists say how they were read, and state their sections
    for b in "12345":
        text = open(SRC / f"guobao_b{b}.tsv", encoding="utf-8").read()
        assert "两位互不相见的读者" in text and "https://www.gov.cn/" in text and text.count("#HEAD") == 6, b
    # the fifth list's picture drops or garbles a few characters: the file keeps them as printed
    assert ("5", "泥国王墓") in at and ("5", "大丕山摩崖大佛及石刻") in at and ("4", "硇州灯塔") in at


def test_a_protected_site_on_a_card_is_named_as_its_list_names_it():
    import sys
    sys.path.insert(0, str(DATA.parent))
    import build_guobao as bg
    doc = load("pride.json")
    cities = {c["id"]: c["n"] for c in load("cities.json")}
    rows = {(int(r[0]), int(r[1])): r for r in guobao_rows()}
    pairs = {(int(f[2]), int(f[3])) for f in (line.rstrip("\n").split("\t") for line in open(SRC / "guobao_pairs.tsv", encoding="utf-8") if line.strip() and not line.startswith("#"))}
    assert pairs <= set(rows)
    marked = named = 0
    seen = set()
    for key in ("pride", "more"):
        for cid, rs in doc[key].items():
            for r in rs:
                if "保" not in r[1]:
                    assert len(r) == 6, (cities[cid], r[0])
                    continue
                marked += 1
                if len(r) == 6:        # not yet found in a list in hand: the seventh list is still to come
                    continue
                named += 1
                head, no, name, era, addr = r[6].split("｜")
                k = ("一二三四五六七八".index(head[len("国务院公布第")]) + 1, int(no[1:-1]))
                row = rows[k]
                assert (row[4], row[5], row[6]) == (name, era, addr), (cities[cid], r[0])
                assert r[0] == bg.shown(name) and len(r[0]) >= 2, (cities[cid], r[0], name)
                # the list's own address puts it in this city, or a reader approved the pair
                assert cities[cid] in row[7].split("、") or k in pairs, (cities[cid], r[0], row[6])
                assert (cid, k) not in seen, (cities[cid], r[0])      # one unit, one line on a city's card
                seen.add((cid, k))
    assert marked >= 2400 and named >= 1550, (marked, named)     # the rest wait for the seventh list (1,943 units) and for a reader's pairs
    # spelled as today where the list's print is old or broken, and the list's own form kept in the record
    names = {(cities[cid], r[0]): r for key in ("pride", "more") for cid, rs in doc[key].items() for r in rs}
    assert "硇州灯塔" in names[("湛江", "硇洲灯塔")][6] and "皇泽寺摩崖造象" in names[("广元", "皇泽寺摩崖造像")][6]
    assert "庐山青龙寺大殿" in names[("雅安", "芦山青龙寺大殿")][6] and names[("桂林", "李宗仁故居")][6].count("包括李宗仁官邸") == 1
    assert not [k for k in names if "造象" in k[1] or k[1] in bg.SPELL]

