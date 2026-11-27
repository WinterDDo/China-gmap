"""Search index for the prototype: every prefecture-level unit and county/district, with pinyin and initials (pypinyin, offline)."""
import json, sys
from pypinyin import lazy_pinyin
infos, cities_p, out_p = sys.argv[1:4]
d = json.load(open(infos, encoding="utf-8")); cities = {c["id"]: c for c in json.load(open(cities_p, encoding="utf-8"))}
SUF = ["特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "自治州", "自治县", "地区", "林区", "新区", "市", "县", "区", "旗", "盟", "州", "省"]
def short(n):
    for s in SUF:
        if n.endswith(s) and len(n) - len(s) >= 2: return n[: -len(s)]
    return n
FIX = {"朝阳": ("chaoyang", "cy"), "重庆": ("chongqing", "cq"), "长沙": ("changsha", "cs"), "长春": ("changchun", "cc"), "长治": ("changzhi", "cz"), "厦门": ("xiamen", "xm"), "蚌埠": ("bengbu", "bb"), "六安": ("luan", "la"), "丽水": ("lishui", "ls"), "台州": ("taizhou", "tz"), "亳州": ("bozhou", "bz"), "乐山": ("leshan", "ls"), "长寿": ("changshou", "cs"), "番禺": ("panyu", "py")}
def py(n, en=None):
    sh = short(n)
    if sh in FIX: return FIX[sh]
    if en and en.isascii(): p = en.lower().replace(" ", "").replace("'", "")
    else: p = "".join(lazy_pinyin(sh)).lower()
    s = lazy_pinyin(sh); return p, "".join(x[0] for x in s if x).lower()
rows = []
for k, v in d.items():
    lv, code, name = v.get("level"), str(v.get("adcode")), v.get("name")
    par = str((v.get("parent") or {}).get("adcode") or "")
    if lv == "city" and code in cities: tgt = code
    elif lv == "district":
        tgt = par if par in cities else (par[:2] + "0000" if par[:2] + "0000" in cities else None)
        if tgt is None and code[:2] + "0000" in cities: tgt = code[:2] + "0000"
    elif lv == "province" and code in cities: tgt = code
    else: continue
    if not tgt: continue
    p, ini = py(name, (cities.get(tgt) or {}).get("en") if lv in ("city", "province") else None)
    rows.append([name, short(name), p, ini, tgt, "c" if lv in ("city", "province") else "x"])
seen = set(); out = []
for r in rows:
    key = (r[0], r[4])
    if key in seen: continue
    seen.add(key); out.append(r)
json.dump(out, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("entries", len(out), "cities", sum(r[5] == "c" for r in out), "sample", [r for r in out if r[0] in ("南充市", "阆中市", "朝阳区")][:4])
