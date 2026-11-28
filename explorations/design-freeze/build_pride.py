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
GENERIC = {"孔庙", "文庙", "清真寺", "大佛寺", "城隍庙", "关帝庙", "鼓楼", "钟楼", "白塔", "古城"}   # a bare type is not a name
FAMOUS, ALONE = 10, 5   # language editions a plain protected site needs: among others / as the only name
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
            stats[kind][2] += 1
            e = found[cid].setdefault(q, {"name": name, "en": b.get("itemLabel_en", {}).get("value", "").replace("_", " "), "kinds": [], "links": int(b["links"]["value"]), "x": x, "y": y, "q": q})
            if kind not in e["kinds"]:
                e["kinds"].append(kind)

    # World Heritage from the project's own list leads; Wikidata fills in 5A areas and well-known protected sites
    own = defaultdict(list)
    sites = json.load(open(os.path.join(out_dir, "cityview.json"), encoding="utf-8")).get("sites", {})
    for cid, rows in sites.items():
        for r in rows:
            if r[0] == "whs":
                own[cid].append({"name": r[1], "en": r[6] or "", "kinds": ["whs"], "links": 0, "x": r[2], "y": r[3], "q": f"UNESCO {r[4]}"})
    out = {}
    for cid in set(found) | set(own):
        rows = sorted(found.get(cid, {}).values(), key=lambda e: -(e["links"] + sum(BONUS[k] for k in e["kinds"])))
        picked = [dict(e) for e in own.get(cid, [])][:3]
        for e in rows:
            twin = next((p for p in picked if same(p["name"], e["name"], cities[cid]["n"])
                         or math.hypot(p["x"] - e["x"], p["y"] - e["y"]) < (5 if "whs" in p["kinds"] and e["kinds"] == ["guobao"] else 1.2)),
                        None)   # next door, or a plain protected site beside a World Heritage entry: parts of one site (孔府 and 曲阜三孔)
            if twin:  # the 5A area, the protected site and the World Heritage entry of the same place: one line, all marks
                twin["kinds"] += [k for k in e["kinds"] if k not in twin["kinds"]]
                continue
            plain = e["kinds"] == ["guobao"]
            if len(picked) >= 3 or (plain and e["links"] < (FAMOUS if picked else ALONE)):
                continue
            picked.append(dict(e))
        if picked:
            out[cid] = [[p["name"], [KINDS[k][0] for k in KINDS if k in p["kinds"]], p["x"], p["y"], p["en"], p["q"]] for p in picked[:3]]
    doc = {"note": "世界遗产（联合国教科文组织）、5A 景区（文化和旅游部）、全国重点文物保护单位（国务院）；经维基数据汇编，坐标与行政归属一致才收；名录不全，只列名字，不计数",
           "pride": out}
    json.dump(doc, open(os.path.join(out_dir, "pride.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for k, (a, b, c) in stats.items():
        print(f"{k}: {a} with coordinates, {b} inside a city, {c} where the admin chain agrees")
    print(f"{len(out)} of {len(cities)} cities have at least one name; none: {[c['n'] for cid, c in cities.items() if cid not in out]}")
    return doc


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
