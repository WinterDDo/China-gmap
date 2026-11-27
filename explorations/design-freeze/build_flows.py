"""Design-prototype data: province flows (2020 census, hukou outside province) + 2023 registered population."""
import json, sys, collections
repo, out_dir = sys.argv[1], sys.argv[2]
d = json.load(open(f"{repo}/data/interim/census/flows_2020.json", encoding="utf-8"))
m = [x for x in d["matrices"] if x["kind"] == "hukou_outside_province"][0]
out, inn = collections.defaultdict(list), collections.defaultdict(list)
for f in m["flows"]:
    out[f["o"]].append([f["d"], f["n"]]); inn[f["d"]].append([f["o"], f["n"]])
res = {"source": {k: m["source"].get(k) for k in ("title", "url", "table")}, "kind": m["kind"], "year": 2020,
       "tot_out": {p: sum(n for _, n in v) for p, v in out.items()}, "tot_in": {p: sum(n for _, n in v) for p, v in inn.items()},
       "out": {p: sorted(v, key=lambda x: -x[1])[:8] for p, v in out.items()}, "in": {p: sorted(v, key=lambda x: -x[1])[:8] for p, v in inn.items()}}
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
