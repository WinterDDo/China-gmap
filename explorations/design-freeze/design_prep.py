"""Data for the design-freeze prototype (scratch; not the production pipeline).

Reads: styles/data/{geo.json,cities.json,dem.*} (from prep.py), chinaciv cities.json (2023 bulletins),
       optional pipeline/reference/names.json (bilingual names), optional data/interim/worldcover_1km.png.
Writes: design/data/{geo.json,dem.png,dem.json,cities.json,provinces.json,nation.json[,lc.png,urban.png]}
"""
import json, math, os, shutil, sys
import numpy as np
from PIL import Image

SP, REPO, CHINACIV = sys.argv[1], sys.argv[2], sys.argv[3]
SRC = os.path.join(SP, "styles", "data")
OUT = os.path.join(SP, "design", "data")
os.makedirs(OUT, exist_ok=True)
for f in ("geo.json", "dem.png", "dem.json"):
    shutil.copy(os.path.join(SRC, f), os.path.join(OUT, f))

names_path = os.path.join(REPO, "pipeline", "reference", "names.json")
NAMES = json.load(open(names_path)) if os.path.exists(names_path) else {}
print("names:", len(NAMES))

geo = json.load(open(os.path.join(SRC, "geo.json")))
seat = {c["id"]: (c["x"], c["y"]) for c in json.load(open(os.path.join(SRC, "cities.json")))}
cc = json.load(open(CHINACIV))

PROV_EN = {"11": "Beijing", "12": "Tianjin", "13": "Hebei", "14": "Shanxi", "15": "Inner Mongolia", "21": "Liaoning", "22": "Jilin",
           "23": "Heilongjiang", "31": "Shanghai", "32": "Jiangsu", "33": "Zhejiang", "34": "Anhui", "35": "Fujian", "36": "Jiangxi",
           "37": "Shandong", "41": "Henan", "42": "Hubei", "43": "Hunan", "44": "Guangdong", "45": "Guangxi", "46": "Hainan",
           "50": "Chongqing", "51": "Sichuan", "52": "Guizhou", "53": "Yunnan", "54": "Xizang", "61": "Shaanxi", "62": "Gansu",
           "63": "Qinghai", "64": "Ningxia", "65": "Xinjiang", "71": "Taiwan", "81": "Hong Kong", "82": "Macao"}
SHORT = lambda n: (n.replace("维吾尔自治区", "").replace("壮族自治区", "").replace("回族自治区", "").replace("自治区", "")
                   .replace("特别行政区", "").replace("省", "").rstrip("市"))

provinces = []
for p in geo["provinces"]:
    pid = p["id"][:2]
    nm = NAMES.get(p["id"], {})
    provinces.append({"id": pid, "zh": nm.get("zh") or SHORT(p["name"]), "en": nm.get("en") or PROV_EN.get(pid, ""), "lc": p["lc"], "c": p["c"]})
pz = {p["id"]: p for p in provinces}

KIND_EN = {"municipality": "Municipality", "city": "Prefecture-level city", "prefecture": "Prefecture", "autonomous_prefecture": "Autonomous prefecture",
           "league": "League", "sar": "Special administrative region", "taiwan_city": "City"}
cities = []
for c in cc:
    if c["id"] not in seat:
        continue
    gbi = c.get("gdp_by_industry") or {}
    nm = NAMES.get(c["id"], {})
    prov = (c.get("states") or [None])[0]
    cities.append({
        "id": c["id"], "n": nm.get("zh") or c["name"], "full": c.get("full"), "en": nm.get("en") or None, "enFull": nm.get("en_full"),
        "enDis": nm.get("en_disambig"), "kind": c.get("kind"), "kindZh": c.get("kind_label"), "prov": prov,
        "x": seat[c["id"]][0], "y": seat[c["id"]][1],
        "pop": c.get("population"), "popYear": c.get("population_year"), "pop20": c.get("pop_census_2020"),
        "gdp": c.get("gdp"), "p1": gbi.get("primary"), "p2": gbi.get("secondary"), "p3": gbi.get("tertiary"),
        "growth": c.get("growth"), "cap": bool(c.get("capital")), "pcap": bool(c.get("province_capital")), "note": c.get("note"),
    })
for c in cities:
    c["pc"] = c["gdp"] / c["pop"] if c["gdp"] and c["pop"] else None
    c["sv"] = c["p3"] / c["gdp"] if c["p3"] and c["gdp"] else None


def rank(key):
    vals = sorted([c for c in cities if c.get(key) is not None], key=lambda c: (-c[key], -(c["pop"] or 0)))
    for i, c in enumerate(vals):
        c.setdefault("rk", {})[key] = i + 1
    return len(vals)


N = {k: rank(k) for k in ("pop", "gdp", "pc", "growth", "sv")}
for c in cities:
    c.setdefault("rk", {})
    if c["pop"]:
        others = sorted((o for o in cities if o is not c and o["pop"]), key=lambda o: abs(math.log(o["pop"] / c["pop"])))
        c["peers"] = [o["id"] for o in others[:5]]
cities.sort(key=lambda c: -(c["gdp"] or 0))
json.dump(cities, open(os.path.join(OUT, "cities.json"), "w"), ensure_ascii=False, separators=(",", ":"))
json.dump(provinces, open(os.path.join(OUT, "provinces.json"), "w"), ensure_ascii=False, separators=(",", ":"))
nation = {
    "year": 2023, "population": 1409670000, "gdp": 126058200000000, "pcgdp": 89358, "urban": 0.6616, "income": 39218,
    "rankN": N, "cities": len(cities),
    "source": "国家统计局《中华人民共和国2023年国民经济和社会发展统计公报》",
    "sourceEn": "National Bureau of Statistics, Statistical Communiqué on the 2023 National Economic and Social Development",
    "url": "https://www.stats.gov.cn/sj/zxfb/202402/t20240228_1947915.html",
}
json.dump(nation, open(os.path.join(OUT, "nation.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print("cities", len(cities), "ranks", N)

# Land cover (optional): 1 km classes → 4 km grid: majority class + built-up fraction
lc_path = os.path.join(REPO, "data", "interim", "worldcover_1km.png")
dj = json.load(open(os.path.join(SRC, "dem.json")))
if os.path.exists(lc_path):
    a = np.asarray(Image.open(lc_path))
    k = 4
    h4, w4 = dj["h"], dj["w"]
    a = a[: h4 * k, : w4 * k]
    pad = np.zeros((h4 * k, w4 * k), np.uint8)
    pad[: a.shape[0], : a.shape[1]] = a
    blocks = pad.reshape(h4, k, w4, k).transpose(0, 2, 1, 3).reshape(h4, w4, k * k)
    codes = np.array([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100], np.uint8)
    counts = np.stack([(blocks == cd).sum(-1) for cd in codes], -1)
    counts[..., 0] = 0  # nodata never wins if anything else exists
    maj = codes[counts.argmax(-1)]
    maj[counts.sum(-1) == 0] = 0
    urban = ((blocks == 50).sum(-1) * 255 // (k * k)).astype(np.uint8)
    Image.fromarray(maj, "L").save(os.path.join(OUT, "lc.png"), optimize=True)
    Image.fromarray(urban, "L").save(os.path.join(OUT, "urban.png"), optimize=True)
    # 2 km majority for the zoomed-in painting
    k2 = 2; h2, w2 = h4 * 2, w4 * 2
    pad2 = np.zeros((h2 * k2, w2 * k2), np.uint8); aa = np.asarray(Image.open(lc_path))[: h2 * k2, : w2 * k2]; pad2[: aa.shape[0], : aa.shape[1]] = aa
    bl = pad2.reshape(h2, k2, w2, k2).transpose(0, 2, 1, 3).reshape(h2, w2, k2 * k2)
    cnt = np.stack([(bl == cd).sum(-1) for cd in codes], -1); cnt[..., 0] = 0
    m2 = codes[cnt.argmax(-1)]; m2[cnt.sum(-1) == 0] = 0
    Image.fromarray(m2, "L").save(os.path.join(OUT, "lc2.png"), optimize=True)
    print("landcover 4km written", maj.shape, "urban cells", int((urban > 0).sum()))
else:
    print("no landcover yet")
for f in sorted(os.listdir(OUT)):
    print(f, os.path.getsize(os.path.join(OUT, f)))
