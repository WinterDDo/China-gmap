"""County outlines for the design prototype's City View and hometown card, one small file per province.

A visitor's hometown goes down to the county (owner's decision, 2026-11-27), so the map must be able to light up one
county inside its prefecture. The outlines come from DataV.GeoAtlas (`areas_v3/bound/<adcode>_full.json`: the
county-level children of a prefecture or municipality), the same source as the prototype's other boundaries.

Output  data/counties/<province code>.json, loaded only when a city of that province is opened:
        {city id: {county code: [ring, ...]}}  each ring as [x, y, dx, dy, ...] in tenths of a map km (deltas after the
        first point), simplified at 0.3 km. Rings under 2 km² (islets, slivers) are dropped unless they are a
        county's only ring.

Usage   python3 build_counties.py <cache dir> data
        Downloads what the cache dir lacks (about 340 small files from geo.datav.aliyun.com), then builds.
"""
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict

D = math.pi / 180
Rr, P1, P2, L0 = 6371.0088, 25 * D, 47 * D, 105 * D
N = (math.sin(P1) + math.sin(P2)) / 2
C = math.cos(P1) ** 2 + 2 * N * math.sin(P1)
RHO0 = Rr * math.sqrt(C) / N
URL = "https://geo.datav.aliyun.com/areas_v3/bound/{}_full.json"
SIMPLIFY_KM = 0.3
MIN_RING_KM2 = 2.0


def fetch(cid, cache):
    path = os.path.join(cache, f"{cid}_full.json")
    if os.path.exists(path):
        return path
    req = urllib.request.Request(URL.format(cid), headers={"User-Agent": "Mozilla/5.0 (jiangshan-atlas prototype)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except Exception as e:  # cities with no county level (东莞, 中山, 儋州, 嘉峪关) have no _full file
        print("   no county file for", cid, type(e).__name__)
        return None
    with open(path, "wb") as f:
        f.write(body)
    time.sleep(0.25)
    return path


def simplify(pts, tol):
    if len(pts) <= 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            t = 0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
            d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def build(cache, out_dir):
    os.makedirs(cache, exist_ok=True)
    geo = json.load(open(os.path.join(out_dir, "geo.json"), encoding="utf-8"))
    cities = json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))
    fr = geo["frame"]

    def proj(lon, lat):
        rho = Rr * math.sqrt(C - 2 * N * math.sin(lat * D)) / N
        th = N * (lon * D - L0)
        return rho * math.sin(th) - fr["x0"], fr["y1"] - (RHO0 - rho * math.cos(th))

    by_prov, n_county, n_pts, none = defaultdict(dict), 0, 0, []
    for c in cities:
        path = fetch(c["id"], cache)
        feats = json.load(open(path, encoding="utf-8")).get("features", []) if path else []
        out = {}
        for f in feats:
            p, g = f.get("properties") or {}, f.get("geometry") or {}
            code = str(p.get("adcode") or "")
            if p.get("level") not in ("district", "county") or not code or code == c["id"]:
                continue
            polys = g.get("coordinates") or []
            if g.get("type") == "Polygon":
                polys = [polys]
            rings = []
            for poly in polys:
                if not poly:
                    continue
                pts = simplify([proj(lon, lat) for lon, lat in poly[0]], SIMPLIFY_KM)  # outer ring only
                if len(pts) >= 4:
                    rings.append(pts)
            if not rings:
                continue
            big = [r for r in rings if area(r) >= MIN_RING_KM2] or [max(rings, key=area)]
            enc = []
            for r in big:
                q = [(round(x * 10), round(y * 10)) for x, y in r]
                row = [q[0][0], q[0][1]]
                for (ax, ay), (bx, by) in zip(q, q[1:]):
                    row += [bx - ax, by - ay]
                enc.append(row)
                n_pts += len(q)
            out[code] = enc
        if out:
            by_prov[c["id"][:2]][c["id"]] = out
            n_county += len(out)
        else:
            none.append(c["n"])
    cdir = os.path.join(out_dir, "counties")
    os.makedirs(cdir, exist_ok=True)
    sizes = []
    for pp, d in sorted(by_prov.items()):
        path = os.path.join(cdir, pp + ".json")
        json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
        sizes.append(os.path.getsize(path))
    print(f"{n_county} counties in {sum(len(d) for d in by_prov.values())} cities, {n_pts} points; {len(sizes)} province files, "
          f"largest {max(sizes) / 1e3:.0f} KB, total {sum(sizes) / 1e6:.1f} MB; cities without counties: {none}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
