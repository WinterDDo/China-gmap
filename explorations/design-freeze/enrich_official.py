"""Prefer the communique's own figures in the design prototype's cities.json.

For every city with a parsed 2023 bulletin (data/interim/bulletins/2023.json), GDP, resident population and the
GDP per head *as the bulletin states it* replace the compiled values, and their source sentences are stored under
src.q so the "ⓘ" panel always quotes the very number it shows. Nothing is computed or estimated here: a figure the
bulletin does not state is left as it was (or null).

Usage: python enrich_official.py data/cities.json ../../data/interim/bulletins/2023.json
"""
import json
import sys

cities_p, bul_p = sys.argv[1], sys.argv[2]
cities = json.load(open(cities_p, encoding="utf-8"))
d = json.load(open(bul_p, encoding="utf-8"))
recs = d if isinstance(d, list) else (d.get("records") or d.get("data") or d)
if isinstance(recs, dict):
    recs = list(recs.values())
by_code = {r["code"]: r for r in recs}


def val(f, k):
    x = f.get(k)
    return x.get("value") if isinstance(x, dict) else None


def quote(f, k):
    x = f.get(k)
    return x.get("quote") if isinstance(x, dict) else None


changed = {"pc": 0, "gdp": 0, "pop": 0}
filled = {"pc": 0, "gdp": 0, "pop": 0}
for c in cities:
    r = by_code.get(c["id"])
    if not r:
        continue
    f = r.get("fields") or {}
    for key, field, scale in (("pc", "gdp_per_capita", 1), ("gdp", "gdp", 1e8), ("pop", "population", 1e4)):
        v = val(f, field)
        if v is None:
            continue
        v = round(v * scale) if key == "pop" else v * scale
        if c.get(key) is None:
            filled[key] += 1
        elif abs(v - c[key]) / abs(c[key]) > 1e-4:
            changed[key] += 1
        c[key] = v
        if key == "pop":  # the population is now this bulletin's year-end figure
            c["popYear"] = d.get("year") if isinstance(d, dict) and d.get("year") else 2023
    q = c.setdefault("src", {}).setdefault("q", {})
    for key, field in (("pc", "gdp_per_capita"), ("gdp", "gdp"), ("population", "population")):
        if quote(f, field):
            q[key] = quote(f, field)

json.dump(cities, open(cities_p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
cov = {k: sum(c.get(k) is not None for c in cities) for k in ("pop", "gdp", "pc", "inc")}
print("filled", filled, "aligned to the bulletin", changed, "coverage", cov, "of", len(cities))
