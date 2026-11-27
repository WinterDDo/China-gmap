"""Add 2023 bulletin life numbers (our own parse, with source sentences) to the design prototype's cities.json."""
import json, sys
cities_p, bul_p = sys.argv[1], sys.argv[2]
cities = json.load(open(cities_p, encoding="utf-8"))
b = json.load(open(bul_p, encoding="utf-8"))
recs = {r["code"]: r for r in b["records"]}
val = lambda f, k: (f.get(k) or {}).get("value") if isinstance(f.get(k), dict) else None
quo = lambda f, k: (f.get(k) or {}).get("quote") if isinstance(f.get(k), dict) else None
n = 0
for c in cities:
    r = recs.get(c["id"])
    if not r: continue
    f = r.get("fields") or {}
    c["inc"], c["incU"], c["incR"] = val(f, "income"), val(f, "income_urban"), val(f, "income_rural")
    u = val(f, "urbanization"); c["urb"] = u / 100 if u is not None else None
    c["gg"] = val(f, "gdp_growth")
    c["src"] = {"url": r.get("url"), "bureau": r.get("bureau"), "title": r.get("title"), "date": r.get("dated"),
                "q": {k: quo(f, k) for k in ("income", "income_urban", "population", "gdp") if quo(f, k)}}
    n += c["inc"] is not None or c["incU"] is not None
json.dump(cities, open(cities_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
nat = recs.get("100000", {}).get("fields", {})
print("cities", len(cities), "with income", n, "all-resident income", sum(c.get("inc") is not None for c in cities), "nation income", val(nat, "income"))
