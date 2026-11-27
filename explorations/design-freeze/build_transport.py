"""City View railways and expressways for the design prototype, from the OpenStreetMap download made on the owner's Mac.

Input   jiangshan_osm_lines.zip from tools/local_fetch/fetch_osm_lines.py: one gzip JSON per province and kind, each way
        as [class, tags, [lon, lat, ...]] with class hsr (high-speed rail), rail (main-line rail) or exp (expressway),
        already thinned to about 150 m.
Output  data/transport.json
        names   [[class, 中文名, English, ref], ...]
        lines   [[name index, x, y, dx, dy, ...], ...] in tenths of a map km (the prototype's Albers frame), deltas after
                the first point
        byCity  {city id: [name index, ...]}  lines running through the prefecture, the longest stretch inside first
        source  where and when the data came from, and its licence

Steps   project with the prototype's Albers; drop the second carriageway of an expressway and the second track of a
        railway (a point within about 1 km of a line of the same class already kept is dropped, longest lines first,
        runs under 1.5 km dropped); simplify at 0.25 km; assign lines to prefectures by the share of their points that
        fall inside. The lengths are used only to order the lines: OpenStreetMap is drawn by volunteers, so this file
        carries no mileage (owner's decision, 2026-11-27).

Usage   python3 build_transport.py <jiangshan_osm_lines.zip> data
        (needs pypinyin for English names OpenStreetMap lacks)
Data    © OpenStreetMap contributors, ODbL 1.0. The derived file is offered under the same licence.
"""
import gzip
import io
import json
import math
import os
import re
import sys
import zipfile
from collections import defaultdict

from placenames import py

HERE = os.path.dirname(os.path.abspath(__file__))
D = math.pi / 180
Rr, P1, P2, L0 = 6371.0088, 25 * D, 47 * D, 105 * D
N = (math.sin(P1) + math.sin(P2)) / 2
C = math.cos(P1) ** 2 + 2 * N * math.sin(P1)
RHO0 = Rr * math.sqrt(C) / N
CLASSES = ("exp", "rail", "hsr")
GRID = 0.5          # km, for finding the second carriageway / track
NEAR = 1            # grid cells around a kept point that count as "the same line"
MIN_RUN_KM = 1.5
SIMPLIFY_KM = 0.25


def projector(frame):
    def proj(lon, lat):
        rho = Rr * math.sqrt(C - 2 * N * math.sin(lat * D)) / N
        th = N * (lon * D - L0)
        return rho * math.sin(th) - frame["x0"], frame["y1"] - (RHO0 - rho * math.cos(th))
    return proj


def read_zip(path):
    """Every way in the download, plus the per-file provenance."""
    ways, prov = [], []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if not n.endswith(".json.gz"):
                continue
            rec = json.load(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(z.read(n))), encoding="utf-8"))
            prov.append({"file": os.path.basename(n), "osm_base": rec.get("osm_base"), "fetched_at": rec.get("fetched_at"), "ways": len(rec["ways"])})
            ways += rec["ways"]
    return ways, prov


def short_zh(cls, tags):
    nm = (tags.get("name") or "").strip()
    nm = re.sub(r"[（(].*?[）)]", "", nm).split(";")[0].strip()
    if cls == "exp":
        return nm.replace("高速公路", "高速")
    return nm.replace("高速铁路", "高铁").replace("客运专线", "客专")


def en_name(cls, tags, zh):
    en = (tags.get("name:en") or "").strip()
    if en:
        return en.replace("High-Speed Railway", "HSR").replace("High-speed Railway", "HSR").replace("High Speed Railway", "HSR")
    if not zh:
        return ""
    core = zh
    while (cut := re.sub(r"(高铁|客专|城际铁路|铁路|高速公路|高速|环线|线)$", "", core)) != core:
        core = cut
    kind = {"hsr": "HSR", "rail": "Railway", "exp": "Expressway"}[cls]
    return f"{py(core) if core else ''} {kind}".strip()


def key_of(cls, tags):
    """Lines are grouped by their expressway number, else by name."""
    zh = short_zh(cls, tags)
    ref = (tags.get("ref") or "").split(";")[0].strip() if cls == "exp" else ""
    return (cls, ref or zh), zh, ref


def chains(ways):
    """Join ways that share an end point (OpenStreetMap splits a line into many ways) into longer polylines."""
    end = lambda p: (round(p[0], 2), round(p[1], 2))  # noqa: E731  (10 m)
    at = defaultdict(list)
    for i, w in enumerate(ways):
        at[end(w[0])].append(i)
        at[end(w[-1])].append(i)
    used, out = [False] * len(ways), []

    def grab(pt):
        for j in at[end(pt)]:
            if not used[j]:
                used[j] = True
                w = ways[j]
                return w if end(w[0]) == end(pt) else w[::-1]
        return None

    for i, w in enumerate(ways):
        if used[i]:
            continue
        used[i] = True
        line = list(w)
        while (nxt := grab(line[-1])) is not None:
            line += nxt[1:]
        while (prv := grab(line[0])) is not None:
            line = prv[::-1][:-1] + line  # prv starts at our first point; reversed, it ends there
        out.append(line)
    return out


def densify(pts, step):
    out = [pts[0]]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / step))
        out += [(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n) for k in range(1, n + 1)]
    return out


def length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def simplify(pts, tol):
    if len(pts) <= 2:
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


def dedupe(ways):
    """[(key, pts)] of one class -> runs with parallel duplicates removed, longest ways claimed first."""
    taken, runs = set(), []
    for key, pts in sorted(ways, key=lambda w: -length(w[1])):
        dense = densify(pts, GRID)
        cells = [(int(math.floor(x / GRID)), int(math.floor(y / GRID))) for x, y in dense]
        free = [not any((cx + i, cy + j) in taken for i in range(-NEAR, NEAR + 1) for j in range(-NEAR, NEAR + 1)) for cx, cy in cells]
        run = []
        for p, f in zip(dense, free):
            if f:
                run.append(p)
            elif run:
                runs.append((key, run))
                run = []
        if run:
            runs.append((key, run))
        taken.update(cells)
    return [(k, simplify(r, SIMPLIFY_KM)) for k, r in runs if length(r) >= MIN_RUN_KM]


def point_in_rings(x, y, rings):
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def prefecture_index(geo, city_ids):
    """[(city id, bbox, rings)] for the prototype's prefecture shapes; municipal districts count for their city."""
    out = []
    for p in geo["prefectures"]:
        cid = p["id"] if p["id"] in city_ids else p["id"][:2] + "0000"
        if cid not in city_ids:
            continue
        rings = [ring for poly in p["rings"] for ring in poly if len(ring) >= 3]
        if not rings:
            continue
        xs = [pt[0] for r in rings for pt in r]
        ys = [pt[1] for r in rings for pt in r]
        out.append((cid, (min(xs), min(ys), max(xs), max(ys)), rings))
    return out


def build(zip_path, out_dir):
    geo = json.load(open(os.path.join(out_dir, "geo.json"), encoding="utf-8"))
    cities = {c["id"] for c in json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))}
    proj = projector(geo["frame"])
    raw, prov = read_zip(zip_path)

    grouped, votes = defaultdict(list), defaultdict(lambda: defaultdict(float))
    for cls, tags, flat in raw:
        if cls not in CLASSES or len(flat) < 4:
            continue
        key, zh, ref = key_of(cls, tags)
        pts = [proj(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]
        grouped[key].append(pts)
        votes[key][(zh, en_name(cls, tags, zh), ref)] += length(pts)  # the name used along most of the line wins
    names, by_class = [], defaultdict(list)
    for key in sorted(grouped):
        zh, en, ref = max(votes[key].items(), key=lambda kv: kv[1])[0]
        names.append([key[0], zh, en, ref])
        by_class[key[0]] += [(len(names) - 1, line) for line in chains(grouped[key])]

    lines, inside = [], defaultdict(lambda: defaultdict(float))
    prefs, cell = prefecture_index(geo, cities), defaultdict(list)
    for k, (cid, (bx0, by0, bx1, by1), rings) in enumerate(prefs):  # 50 km buckets so each point tests a few shapes
        for i in range(int(bx0 // 50), int(bx1 // 50) + 1):
            for j in range(int(by0 // 50), int(by1 // 50) + 1):
                cell[(i, j)].append(k)
    for cls in CLASSES:
        for idx, pts in dedupe(by_class[cls]):
            q = [(round(x * 10), round(y * 10)) for x, y in pts]
            row = [idx, q[0][0], q[0][1]]
            for (ax, ay), (bx, by) in zip(q, q[1:]):
                row += [bx - ax, by - ay]
            lines.append(row)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                mx, my, seg = (x1 + x2) / 2, (y1 + y2) / 2, math.hypot(x2 - x1, y2 - y1)
                for k in cell.get((int(mx // 50), int(my // 50)), ()):
                    cid, (bx0, by0, bx1, by1), rings = prefs[k]
                    if bx0 <= mx <= bx1 and by0 <= my <= by1 and point_in_rings(mx, my, rings):
                        inside[cid][idx] += seg
                        break
    by_city = {cid: [i for i, km in sorted(d.items(), key=lambda kv: -kv[1]) if km >= 3 and names[i][1] + names[i][3]]
               for cid, d in inside.items()}
    bases = sorted({p["osm_base"][:10] for p in prov if p.get("osm_base")})
    out = {"names": names, "lines": lines, "byCity": {k: v for k, v in by_city.items() if v},
           "source": {"zh": "线路：© OpenStreetMap 贡献者（ODbL），" + (bases[-1] if bases else "") + " 下载；志愿者绘制，只画线，不计里程",
                      "en": "Lines © OpenStreetMap contributors (ODbL), downloaded " + (bases[-1] if bases else "") + "; volunteer-drawn, shown as lines only, no mileage",
                      "files": prov, "license": "ODbL 1.0"}}
    path = os.path.join(out_dir, "transport.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    pts = sum((len(r) - 1) // 2 for r in lines)
    print(f"{len(raw)} ways in, {len(lines)} lines and {pts} points out ({os.path.getsize(path) / 1e6:.1f} MB); "
          f"{len(names)} named lines; {len(out['byCity'])} cities with at least one line")
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
