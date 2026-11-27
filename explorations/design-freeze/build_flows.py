"""Design-prototype data: province flows (2020 census, hukou outside province) + 2023 registered population."""
import json, sys, collections
repo, out_dir = sys.argv[1], sys.argv[2]
d = json.load(open(f"{repo}/data/interim/census/flows_2020.json", encoding="utf-8"))
def mat(year, kind):
    dd = json.load(open(f"{repo}/data/interim/census/flows_{year}.json", encoding="utf-8"))
    m = [x for x in dd["matrices"] if x["kind"] == kind][0]; sc = (m.get("sample") or {}).get("scale") or {}
    out, inn = collections.defaultdict(list), collections.defaultdict(list)
    for f in m["flows"]:
        n = round(f["n"] * sc.get(f["d"], 1)); out[f["o"]].append([f["d"], n]); inn[f["d"]].append([f["o"], n])
    return m, {"tot_out": {p: sum(n for _, n in v) for p, v in out.items()}, "tot_in": {p: sum(n for _, n in v) for p, v in inn.items()},
               "out": {p: sorted(v, key=lambda x: -x[1])[:8] for p, v in out.items()}, "in": {p: sorted(v, key=lambda x: -x[1])[:8] for p, v in inn.items()}}
m, cur = mat(2020, "birthplace"); _, old = mat(2010, "birthplace")
res = {"source": {k: m["source"].get(k) for k in ("title", "url", "table")}, "kind": "birthplace", "year": 2020, "scaled": True, **cur,
       "y2010": {"out": {p: dict(v) for p, v in mat(2010, "birthplace")[1]["out"].items()}, "in": {p: dict(v) for p, v in old["in"].items()},
                 "tot_out": old["tot_out"], "tot_in": old["tot_in"]}}
json.dump(res, open(f"{out_dir}/flows.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
b = json.load(open(f"{repo}/data/interim/bulletins/2023.json", encoding="utf-8")); recs = {r["code"]: r for r in b["records"]}
cp = f"{out_dir}/cities.json"; cities = json.load(open(cp, encoding="utf-8")); n = 0
for c in cities:
    f = (recs.get(c["id"]) or {}).get("fields") or {}; v = f.get("population_registered")
    if isinstance(v, dict) and v.get("value") is not None:
        c["popReg"] = round(v["value"] * 1e4); n += 1
        c.setdefault("src", {}).setdefault("q", {})["population_registered"] = v.get("quote")
json.dump(cities, open(cp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("flows provinces", len(res["out"]), "sichuan top", res["out"].get("510000", [])[:3], "popReg cities", n)
