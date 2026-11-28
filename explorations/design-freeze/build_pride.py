"""The named treasures on the hometown card: data/pride.json (and embedded in cityview.json by build_cityview.py).

The owner's verdict on the first card (2026-11-28): forest share and population change are nothing to be proud of;
show "真正值得自豪的东西". So the card names places that carry a national or world designation and lie in the city:

  遗   UNESCO World Heritage            Wikidata P1435 = Q9259, in China
  5A   5A scenic area                   Wikidata P31 = Q6838244          (文化和旅游部 评定)
  保   全国重点文物保护单位               Wikidata P1435 = Q1188574        (国务院 公布)

Wikidata is a compiled copy of those lists, and it is incomplete (about 220 of some 360 5A areas; World Heritage
component sites are thin), so the card never counts ("N 处") and never says a city has none: it only names.

World Heritage comes first from the project's own list (cityview.json "sites", UNESCO's list with the year of
inscription, one city per site), since Wikidata marks few of them.

A Wikidata place is given to a city only when two things agree, else it is dropped (少林寺 sits 3 km from Luoyang's
border, and belongs to Zhengzhou):
  1. its coordinates fall inside one of the city's counties (data/counties/*.json, 0.3 km outlines; the prefecture's
     own outline for the few cities with no county level), and
  2. its "located in" chain (P131) reaches that city's division code (P442), or stops at the city's province without
     naming another prefecture (泰山 is recorded as "in Shandong").

Up to three per city, the best known first: the number of Wikipedia language editions (sitelinks) stands in for fame,
World Heritage and 5A count extra; names that repeat (the 5A area and the protected site of the same name) are merged.
The bar is high on purpose ("宁少勿错"): a protected site that is neither World Heritage nor 5A needs 10 language
editions to be named (5 if it would be the city's only name), so a little-known site is never offered as a city's
pride. Cities left with nothing show the plate and the county question only.

Food ("吃的", the owner's second face after standing, 2026-11-28) comes from sources/feiyi_food.tsv: the food and
drink entries of the State Council's five lists of national intangible cultural heritage (传统技艺), read off the
notices on www.gov.cn and filed under the prefecture of the declaring place. Entries declared by a whole province are
left out. Up to two per city, in the order of that file. A second source fills cities the heritage lists miss:
the geographical indications protected under the China-EU agreement (sources/gi_cn_eu.tsv, made by build_gi.py from
the Ministry of Commerce's product pages, each with its place of origin). There is no single official list of all
geographical indications, so this is the well-known hundred, not the full set (TODOS.md).

Usage   python3 build_pride.py <dir with whs.json a5.json guobao.json + *_loc.json> data
        The queries are in QUERIES; each result is the SPARQL JSON from https://query.wikidata.org/sparql.
"""
import json
import math
import os
import re
import sys
from collections import defaultdict

KINDS = {"whs": ("遗", "wdt:P1435 wd:Q9259 ; wdt:P17 wd:Q148"), "a5": ("5A", "wdt:P31 wd:Q6838244"), "guobao": ("保", "wdt:P1435 wd:Q1188574")}
QUERIES = {k: f"""SELECT ?item ?itemLabel ?itemLabel_en ?coord ?links WHERE {{ ?item {v[1]} ; wdt:P625 ?coord ; wikibase:sitelinks ?links .
  OPTIONAL {{ ?item rdfs:label ?itemLabel_en . FILTER(LANG(?itemLabel_en) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh-cn,zh-hans,zh". }} }}""" for k, v in KINDS.items()}
LOC_QUERIES = {k: f"""SELECT ?item ?code WHERE {{ ?item {v[1]} ; wdt:P131+ ?a . ?a wdt:P442 ?code . FILTER(REGEX(?code, "^[0-9]{{2}}( ?[0-9]{{2}})?$")) }}"""
               for k, v in KINDS.items()}
BONUS = {"whs": 100, "a5": 15, "guobao": 0}
GENERIC = {"孔庙", "文庙", "清真寺", "大佛寺", "城隍庙", "关帝庙", "鼓楼", "钟楼", "白塔", "古城",
           "观音堂", "观音阁", "文昌阁", "文昌庙", "府君庙", "大王庙"}   # a bare type is not a name
FAMOUS, ALONE = 10, 5   # language editions a plain protected site needs: among others / as the only name
DEEP, POOL = 0, 12      # the draw's deeper pool: any protected site that passes the two checks, best known first; at most 12 a city
# A draw celebrates what it turns up. Sites of massacre, war crime and imprisonment are protected for another reason:
# they stay off the card (they belong in the history layer, told properly).
SOMBRE = re.compile(r"万人坑|万人[坟墳]|侵华|屠杀|惨案|细菌|集中营|遇难|殉难|死难|殉国|阵亡|劳工|矿工墓|血泪|慰安|毒气|罪证|罪行|监狱|战俘|战犯|管理所|警察厅|教案|大地震|墓园|红军墓|革命公墓|将士公墓")
# What follows is what an independent reader found wanting when all 2,832 names were read (2026-11-28), when every
# name was still a Wikidata label. Sites found in the State Council's lists now take the listed name (build_guobao.py);
# these tables still serve the sites not found in a list in hand (most of them of the seventh list): a label found
# wrong is put right here, and one that cannot be put right with confidence is left out.
FIX = {"采石磯": "采石矶", "应昌": "应昌路故城遗址", "天津張園": "天津张园", "薩爾滸城": "萨尔浒城", "潮音橋": "潮音桥", "晉江龍山寺": "晋江龙山寺",
       "中國國民黨第一次全國代表大會舊址": "中国国民党第一次全国代表大会旧址", "夾江千佛岩摩岩造像": "夹江千佛岩摩崖造像",
       "蘆山飛仙關及南界牌坊": "芦山飞仙关及南界牌坊", "零關古道清溪峽段": "零关古道清溪峡段", "登相營古驛站": "登相营古驿站",
       "漢長陵": "汉长陵", "唐橋陵": "唐桥陵", "惠遠城": "惠远城", "庐山青龙寺大殿": "芦山青龙寺大殿",
       "碧色寨站": "碧色寨车站", "鸡街站": "鸡街火车站"}   # 芦山县, not the mountain in 江西
OWN_FIX = {"泉州": "泉州：宋元中国的世界海洋商贸中心"}     # the World Heritage entry, not the bare city name
DROP = {  # sombre, by a name the pattern cannot catch
        "万忠墓", "乐道院", "石人血泪山", "虎头要塞", "胜山要塞", "三灶島萬人墳",
        # not in the city the record puts it in, or an umbrella for sites across several cities
        "万安陵", "九门口", "唐十八陵",
        # a part of one protected unit, under a bare name nobody will recognise
        "景安陵", "修陵", "修安陵", "兴安陵",
        # today's institution or business standing in for the site
        "东北电力大学", "喜林苑", "烟台市博物馆", "上海圣约翰大学", "德华大学", "北京动物园", "工部局宰牲場",
        # a bare name of an old capital or a tomb, short of what the list calls it
        "盛樂", "煬帝陵", "漢禪陵", "鄧城", "辽陵", "兴京", "雍城", "泰陵", "觀音閣",
        # a railway station under a label that reads as a working stop, where the list's own name is not known to me
        "白塔站", "吉林西站", "富拉尔基站", "沈阳东站"}
DROP_IN = {  # the same site as one already on the city's card, or its parts beside the whole
           ("长沙", "刘少奇故居"), ("延安", "延安革命遗址"), ("北海", "德国领事馆旧址"), ("北海", "法国领事馆旧址"), ("北海", "双孖楼旧址"), ("北海", "普仁医院旧址"),
           ("北海", "英国领事馆旧址"), ("北海", "北海天主堂旧址"), ("北海", "德国信义会教会楼旧址"), ("镇江", "庄陵"), ("镇江", "建陵"),
           ("韶关", "丹霞山"),                    # 中国丹霞 is the same mountain
           ("恩施", "湖北神农架国家公园"),          # all but an edge of it lies in 神农架林区
           ("黔东南", "和平村旧址")}               # a wartime camp for prisoners
PARTS_IN = {("北海", "旧址")}   # 北海近代建筑 is one protected unit of some twenty buildings; each is on record as "…旧址"
EN_DROP = {"Mukden Naniwa Square", "Hoten prisoner-of-war camp", "Schwarzwasserstaat site"}   # not names to greet a visitor with
FOODS, LORE = 6, 12     # and at most 6 foods and 12 heritage items a city
CATS = ["民间文学", "传统音乐", "传统舞蹈", "传统戏剧", "曲艺", "传统体育、游艺与杂技", "传统美术", "传统技艺", "传统医药", "民俗"]


def roman(name):
    """Syllable by syllable, as the EU register writes Chinese names (Yantai Pu Tao Jiu): a reading aid, not a translation."""
    from pypinyin import lazy_pinyin
    say = lambda t: " ".join(x.capitalize() for x in lazy_pinyin(re.sub(r"[（()）、，·“”\s]", "", t), v_to_u=True) if x.isalpha())
    m = re.fullmatch(r"([^（]+)（([^（）]+)）", name)      # 灯彩（佛山彩灯）: the item, then the local one in brackets
    return f"{say(m.group(1))} ({say(m.group(2))})" if m else say(name)
D = math.pi / 180
Rr, P1, P2, L0 = 6371.0088, 25 * D, 47 * D, 105 * D
N = (math.sin(P1) + math.sin(P2)) / 2
C = math.cos(P1) ** 2 + 2 * N * math.sin(P1)
RHO0 = Rr * math.sqrt(C) / N


def county_index(out_dir):
    """[(city id, bbox, rings)] from the per-province county outlines, bucketed by 50 km."""
    shapes, cell = [], defaultdict(list)
    cdir = os.path.join(out_dir, "counties")
    for f in sorted(os.listdir(cdir)):
        for cid, cs in json.load(open(os.path.join(cdir, f), encoding="utf-8")).items():
            for rings in cs.values():
                for q in rings:
                    x, y, pts = q[0], q[1], [(q[0] / 10, q[1] / 10)]
                    for i in range(2, len(q), 2):
                        x += q[i]
                        y += q[i + 1]
                        pts.append((x / 10, y / 10))
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    k = len(shapes)
                    shapes.append((cid, (min(xs), min(ys), max(xs), max(ys)), pts))
                    for i in range(int(min(xs) // 50), int(max(xs) // 50) + 1):
                        for j in range(int(min(ys) // 50), int(max(ys) // 50) + 1):
                            cell[(i, j)].append(k)
    return shapes, cell


def add_whole_cities(shapes, cell, geo, cities):
    """Cities with no county level (东莞, 中山, 儋州, 嘉峪关) are placed by their own outline."""
    have = {s[0] for s in shapes}
    for p in geo["prefectures"]:
        if p["id"] in cities and p["id"] not in have:
            for poly in p["rings"]:
                for ring in poly:
                    pts = [tuple(q) for q in ring]
                    if len(pts) < 3:
                        continue
                    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
                    k = len(shapes)
                    shapes.append((p["id"], (min(xs), min(ys), max(xs), max(ys)), pts))
                    for i in range(int(min(xs) // 50), int(max(xs) // 50) + 1):
                        for j in range(int(min(ys) // 50), int(max(ys) // 50) + 1):
                            cell[(i, j)].append(k)


def inside(x, y, ring):
    r = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            r = not r
    return r


def tidy(name, kind):
    """A usable name, or "" when the label is an administrative unit standing in for the site (登封市 for 天地之中)."""
    name = re.sub(r"[（(].*?[）)]", "", name).split("：")[0].strip()
    if len(name) < 2 or name in GENERIC:
        return ""
    if kind != "guobao":
        if re.search(r"(市|县|区|自治州|街道)$", name):
            return ""
        name = re.sub(r"镇$", "", name)   # 周庄镇 -> 周庄: the 5A area is known by the town's bare name
    return name


def same(a, b, city=""):
    """One place under two names: 苏州园林 / 苏州古典园林, 西递、宏村 / 西递村, 良渚古城 / 良渚遗址, 曲阜三孔 / 曲阜孔庙…"""
    parts = [t for t in re.split(r"[—、]", a) + re.split(r"[—、]", b) if len(t) >= 2]
    a, b = re.sub(r"[—、：:·\s]", "", a), re.sub(r"[—、：:·\s]", "", b)
    if a in b or b in a or any(t in a and t in b for t in parts):
        return True
    short, long_ = sorted((a, b), key=len)
    it = iter(long_)
    if len(short) >= 3 and all(ch in it for ch in short):   # the shorter name read off the longer one in order
        return True
    return a[:2] == b[:2] and a[:2] != city[:2]            # same leading word, and it is not just the city's name


def one_place(p, e, city):
    """same(), for two entries of a city's list. Two units of the State Council's lists are two places whatever their
    names share (贵池清溪塔 and 贵池百牙山塔; 渠县汉阙 twice is one). A listed unit with a bare name does not swallow a
    place of a longer name that lies elsewhere in the city (玉皇庙 at 府城 and 石掌玉皇庙, ten kilometres off)."""
    if p["name"] == e["name"] or (p.get("src") and e.get("src")):
        return p["name"] == e["name"]          # one name is one line on a card, wherever its two records lie
    plain = lambda z: z["kinds"] == ["guobao"]      # a World Heritage entry or a 5A area still gathers its parts by name
    if plain(p) and plain(e) and (p.get("src") or e.get("src")) and math.hypot(p["x"] - e["x"], p["y"] - e["y"]) > 5:
        return False
    return same(p["name"], e["name"], city)


def build(src, out_dir):
    geo = json.load(open(os.path.join(out_dir, "geo.json"), encoding="utf-8"))
    fr = geo["frame"]
    cities = {c["id"]: c for c in json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))}
    shapes, cell = county_index(out_dir)
    add_whole_cities(shapes, cell, geo, cities)

    def place(lon, lat):
        rho = Rr * math.sqrt(C - 2 * N * math.sin(lat * D)) / N
        th = N * (lon * D - L0)
        x, y = rho * math.sin(th) - fr["x0"], fr["y1"] - (RHO0 - rho * math.cos(th))
        for k in cell.get((int(x // 50), int(y // 50)), ()):
            cid, (a, b, c, d), ring = shapes[k]
            if a <= x <= c and b <= y <= d and inside(x, y, ring):
                return cid, round(x, 1), round(y, 1)
        return None, None, None

    found, stats = defaultdict(dict), defaultdict(lambda: [0, 0, 0])
    for kind in KINDS:
        loc = defaultdict(set)
        for b in json.load(open(os.path.join(src, kind + "_loc.json"), encoding="utf-8"))["results"]["bindings"]:
            code = b["code"]["value"].replace(" ", "")
            loc[b["item"]["value"].split("/")[-1]].add(code + "0000" if len(code) == 2 else code + "00")
        for b in json.load(open(os.path.join(src, kind + ".json"), encoding="utf-8"))["results"]["bindings"]:
            q, name = b["item"]["value"].split("/")[-1], tidy(b["itemLabel"]["value"], kind)
            if name in DROP or any(ord(ch) > 0xFFFF for ch in name):   # the second: a character most phones cannot draw
                continue
            name = FIX.get(name, name)
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b["coord"]["value"])
            if not m or re.fullmatch(r"Q\d+", name) or not name:
                continue
            stats[kind][0] += 1
            cid, x, y = place(float(m.group(1)), float(m.group(2)))
            if not cid:
                continue
            stats[kind][1] += 1
            codes = loc.get(q, set())
            prefs = {c for c in codes if not c.endswith("0000") or c == cid}
            links = int(b["links"]["value"])
            if cid not in codes:   # the two signals must agree
                # recorded only as "in <province>": fine for a mountain everyone knows, not for a wall that crosses ten cities
                if prefs or cid[:2] + "0000" not in codes or (kind == "guobao" and links < 25):
                    continue
            if (cities[cid]["n"], name) in DROP_IN or any(c == cities[cid]["n"] and name.endswith(tail) for c, tail in PARTS_IN):
                continue
            stats[kind][2] += 1
            en = b.get("itemLabel_en", {}).get("value", "").replace("_", " ")
            e = found[cid].setdefault(q, {"name": name, "en": "" if en in EN_DROP else en, "kinds": [], "links": int(b["links"]["value"]), "x": x, "y": y, "q": q})
            if kind not in e["kinds"]:
                e["kinds"].append(kind)

    # a protected site takes its name from the State Council's lists (build_guobao.py); Wikidata keeps the pin
    import build_guobao
    official, review = build_guobao.names(found, cities)
    for (cid, q), r in official.items():
        e = found[cid][q]
        e["label"], e["name"] = e["name"], build_guobao.shown(r[4])
        e["src"] = "｜".join([f"国务院公布第{'一二三四五六七八'[r[0] - 1]}批全国重点文物保护单位", f"第{r[1]}号", r[4], r[5], r[6]] + [x for x in [build_guobao.renamed_note(r[4])] if x])
    marked = [(cid, q) for cid in found for q, e in found[cid].items() if "guobao" in e["kinds"]]
    print(f"protected sites on the map: {len(marked)}; named from the lists: {len(official)}; looser likenesses left for a reader: {len(review)}")
    if os.environ.get("GUOBAO_REVIEW"):
        with open(os.environ["GUOBAO_REVIEW"], "w", encoding="utf-8") as f:
            for row in review:
                f.write("\t".join(map(str, row)) + "\n")
            for (cid, q), r in official.items():
                f.write("\t".join(["MATCHED", cities[cid]["n"], q, found[cid][q]["label"], str(r[0]), str(r[1]), r[4]]) + "\n")
            for cid, q in marked:
                if (cid, q) not in official:
                    f.write("\t".join(["UNMATCHED", cities[cid]["n"], q, found[cid][q]["name"], str(found[cid][q]["links"])]) + "\n")
    # World Heritage from the project's own list leads; Wikidata fills in 5A areas and well-known protected sites
    own = defaultdict(list)
    sites = json.load(open(os.path.join(out_dir, "cityview.json"), encoding="utf-8")).get("sites", {})
    for cid, rows in sites.items():
        for r in rows:
            if r[0] == "whs":
                own[cid].append({"name": OWN_FIX.get(r[1], r[1]), "en": r[6] or "", "kinds": ["whs"], "links": 0, "x": r[2], "y": r[3], "q": f"UNESCO {r[4]}"})
    out, more = {}, {}
    # name, marks, x, y, English name, record; a protected site named from the lists carries the listed row as a seventh
    row = lambda p: [p["name"], [KINDS[k][0] for k in KINDS if k in p["kinds"]], p["x"], p["y"], p["en"], p["q"]] + ([p["src"]] if p.get("src") else [])
    for cid in set(found) | set(own):
        rows = sorted(found.get(cid, {}).values(), key=lambda e: -(e["links"] + sum(BONUS[k] for k in e["kinds"])))
        picked = [dict(e) for e in own.get(cid, [])][:3]
        # next door, or a plain protected site beside a World Heritage entry: parts of one site (孔府 and 曲阜三孔), one line
        near = lambda p, e: math.hypot(p["x"] - e["x"], p["y"] - e["y"]) < (5 if "whs" in p["kinds"] and e["kinds"] == ["guobao"] else 1.2)
        for e in rows:
            twin = next((p for p in picked if one_place(p, e, cities[cid]["n"]) or near(p, e)), None)
            if twin:  # the 5A area and the protected site of one name share their marks; a neighbour of another name
                if one_place(twin, e, cities[cid]["n"]):   # lends none (东方明珠 is not a protected site)
                    twin["kinds"] += [k for k in e["kinds"] if k not in twin["kinds"]]
                continue
            plain = e["kinds"] == ["guobao"]
            if len(picked) >= 3 or (plain and e["links"] < (FAMOUS if picked else ALONE)) or SOMBRE.search(e["name"]):
                continue
            picked.append(dict(e))
        if picked:
            out[cid] = [row(p) for p in picked[:3]]
        # the card draw turns up more than the three best known: every other place that passed the same two checks
        deep = []
        for e in rows:
            if len(picked) + len(deep) >= POOL:
                break
            # beside one of the three it is a part of that site; among themselves two old-town sites a street apart are two sites
            twin = lambda p, km: one_place(p, e, cities[cid]["n"]) or math.hypot(p["x"] - e["x"], p["y"] - e["y"]) < km
            # (a temple inside a World Heritage landscape stays: 灵隐寺 and 留园 are highlights in their own right)
            if any(twin(p, 1.2) for p in picked) or any(twin(p, 0.3) for p in deep) or (e["kinds"] == ["guobao"] and e["links"] < DEEP) or SOMBRE.search(e["name"]):
                continue
            deep.append(dict(e))
        if deep:
            more[cid] = [row(p) for p in deep]
    food, by_name = {}, {c["n"]: cid for cid, c in cities.items()}
    here = os.path.dirname(os.path.abspath(__file__))
    for line in open(os.path.join(here, "sources", "feiyi_food.tsv"), encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        city, name, code, orig, en = line.rstrip("\n").split("\t")
        assert city in by_name, f"feiyi_food.tsv: no city called {city}"
        rows = food.setdefault(by_name[city], [])
        if name not in [r[0] for r in rows]:
            rows.append([name, en, f"国家级非遗 {code}：{orig}", "遗"])
    # second source: geographical indications protected under the China-EU agreement (sources/gi_cn_eu.tsv, build_gi.py)
    gi_p = os.path.join(here, "sources", "gi_cn_eu.tsv")
    for line in open(gi_p, encoding="utf-8") if os.path.exists(gi_p) else ():
        if line.startswith("#") or not line.strip():
            continue
        city, name, origin, reg, page, en = (line.rstrip("\n").split("\t") + [""])[:6]
        rows = food.setdefault(by_name[city], [])
        core = re.sub(r"(茶|酒|醋)$", "", name)
        if not any(r[0] in name or name in r[0] or (len(core) >= 2 and core in r[0]) or (r[3] == "遗" and r[0][:2] == name[:2]) for r in rows):
            rows.append([name, en, f"地理标志（中欧地理标志协定保护）：原产地 {origin}；{reg}；{page}", "标"])
    food_all = {cid: rows[:FOODS] for cid, rows in food.items()}
    food = {cid: rows[:2] for cid, rows in food.items()}   # the card's own food line stays the first two
    # culture: the same heritage lists beyond food (sources/feiyi_all.tsv, build_feiyi.py), a few from each category in turn
    lore, eaten = {}, {(cid, re.search(r"Ⅷ-\d+", r[2]).group(0)) for cid, rows in food_all.items() for r in rows if r[3] == "遗" and re.search(r"Ⅷ-\d+", r[2])}
    by_cat = defaultdict(lambda: defaultdict(list))
    for line in open(os.path.join(here, "sources", "feiyi_all.tsv"), encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        city, cat, name, code, orig, by = (line.rstrip("\n").split("\t") + [""])[:6]
        cid = by_name[city]
        if (cid, code.split(" ")[1]) in eaten or any(name == r[0] for r in food_all.get(cid, [])):
            continue
        by_cat[cid][cat].append([name, roman(name), CATS.index(cat), by, f"国家级非遗 {code}：{orig}"])
    for cid, cats in by_cat.items():
        rows, depth = [], 0
        while len(rows) < LORE and any(len(v) > depth for v in cats.values()):
            rows += [v[depth] for v in cats.values() if len(v) > depth]
            depth += 1
        lore[cid] = rows[:LORE]
    doc = {"note": "世界遗产（联合国教科文组织）、5A 景区（文化和旅游部）、全国重点文物保护单位（国务院）；位置取自维基数据，坐标与行政归属一致才收；全国重点文物保护单位的名字取自国务院公布名单原文（每行第七项是名单上的那一行），还没对上名单的沿用维基数据的名字；名录不全，只列名字，不计数",
           "pride": out,
           "food_note": "遗：列入国家级非物质文化遗产代表性项目名录（传统技艺）的饮食项目，国务院五批公布通知（www.gov.cn），按申报地区归到地级市；标：中欧地理标志协定保护的中国地理标志产品（商务部 ipr.mofcom.gov.cn，按原产地）",
           "food": food,
           "pool_note": "抽卡用的更深一层：more 是前三名之外通过同样两项核对的景点古迹；food_all 是全部饮食项目；lore 是国家级非遗名录里饮食以外的项目（前四批，按门类轮流取）",
           "more": more, "food_all": food_all, "lore": lore}
    json.dump(doc, open(os.path.join(out_dir, "pride.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # what the page fetches when someone first draws a card: names only, no provenance (that stays in pride.json)
    pool = {"more": {cid: [r[:5] for r in rows] for cid, rows in more.items()},
            "food": {cid: [[r[0], r[1], r[3]] for r in rows] for cid, rows in food_all.items()},
            "lore": {cid: [r[:4] for r in rows] for cid, rows in lore.items()}}
    json.dump(pool, open(os.path.join(out_dir, "pool.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for k, (a, b, c) in stats.items():
        print(f"{k}: {a} with coordinates, {b} inside a city, {c} where the admin chain agrees")
    print(f"food: {len(food)} cities")
    print(f"{len(out)} of {len(cities)} cities have at least one name; none: {[c['n'] for cid, c in cities.items() if cid not in out]}")
    return doc


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
