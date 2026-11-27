"""Prepare sample data for the style-proposal page.

Inputs (downloaded, untrusted data only):  dl/geo, dl/prov, dl/dem, chinaciv cities.json
Outputs: styles/data/geo.json, styles/data/dem.png, styles/data/cities.json
Projection: Albers equal-area conic on a sphere, lat1=25 lat2=47 lon0=105 (km).
"""
import json, math, sys, os, glob
import numpy as np
from PIL import Image

SP = sys.argv[1]
CHINACIV = sys.argv[2]
OUT = os.path.join(SP, "styles", "data")
os.makedirs(OUT, exist_ok=True)

R = 6371.0088
P1, P2, L0 = math.radians(25), math.radians(47), math.radians(105)
N = (math.sin(P1) + math.sin(P2)) / 2
C = math.cos(P1) ** 2 + 2 * N * math.sin(P1)
RHO0 = R * math.sqrt(C) / N  # lat0 = 0


def proj(lon, lat):
    rho = R * math.sqrt(C - 2 * N * math.sin(math.radians(lat))) / N
    th = N * (math.radians(lon) - L0)
    return rho * math.sin(th), RHO0 - rho * math.cos(th)


def inv(x, y):
    rho = np.sqrt(x ** 2 + (RHO0 - y) ** 2)
    th = np.arctan2(x, RHO0 - y)
    lat = np.degrees(np.arcsin(np.clip((C - (rho * N / R) ** 2) / (2 * N), -1, 1)))
    lon = np.degrees(L0 + th / N)
    return lon, lat


def dp(pts, tol):
    """Douglas-Peucker, iterative. Closed rings are split in two so the chord is never zero-length."""
    if len(pts) < 4:
        return pts
    if pts[0] == pts[-1]:
        m = len(pts) // 2
        return dp(pts[:m + 1], tol)[:-1] + dp(pts[m:], tol)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


# Map frame (km, y down): fixed from mainland + Hainan + Taiwan bounds, rounded out.
def rings_of(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    if geom["type"] == "LineString":
        return [[geom["coordinates"]]]
    if geom["type"] == "MultiLineString":
        return [[l] for l in geom["coordinates"]]
    return []


full = json.load(open(os.path.join(SP, "dl/geo/china_full.json")))
xs, ys = [], []
for f in full["features"]:
    if f["properties"].get("adcode") == "100000_JD":
        continue
    for poly in rings_of(f["geometry"]):
        ring = poly[0]
        if max(p[1] for p in ring) < 17.5:
            continue
        for lon, lat in ring:
            x, y = proj(lon, lat); xs.append(x); ys.append(y)
MINX, MAXX, MINY, MAXY = min(xs), max(xs), min(ys), max(ys)
MARGIN = 160
ASPECT = 5400 / 4374                     # canvas aspect used by the page
# Taiwan's east coast; the South China Sea inset (19% of the width, bottom right) must sit east of it
tw_x = max(proj(lon, lat)[0] for f in full["features"] if f["properties"].get("adcode") == 710000
           for poly in rings_of(f["geometry"]) for lon, lat in poly[0])
FX0 = MINX - MARGIN
W = max((MAXX - MINX) + 2 * MARGIN, (tw_x + 90 - FX0) / (1 - 0.19 - 0.03))
H = W / ASPECT
FY1 = (MAXY + MINY) / 2 + H / 2          # centre China vertically
assert H >= (MAXY - MINY) + 2 * MARGIN, (H, MAXY - MINY)
print("frame km", round(W), round(H))


def to_map(lon, lat):
    x, y = proj(lon, lat)
    return round(x - FX0, 1), round(FY1 - y, 1)


def proj_rings(geom, tol, minlat=None, min_area=0.0):
    out = []
    for poly in rings_of(geom):
        rings = []
        for k, ring in enumerate(poly):
            if minlat is not None and k == 0 and max(p[1] for p in ring) < minlat:
                rings = None
                break
            pts = [to_map(lon, lat) for lon, lat in ring]
            pts = dp(pts, tol)
            if len(pts) >= 3 or geom["type"].endswith("LineString"):
                rings.append(pts)
        if rings:
            if min_area and not geom["type"].endswith("LineString"):
                r = rings[0]
                a = abs(sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))) / 2
                if a < min_area:
                    continue
            out.append(rings)
    return out


geo = {"frame": {"w": round(W), "h": round(H), "projection": "Albers equal-area, lat1=25 lat2=47 lon0=105, km",
                 "x0": FX0, "y1": FY1}}

# Provinces (main map: drop the far-south islands, they go to the inset)
provs, jd, scs = [], None, []
for f in full["features"]:
    p = f["properties"]
    if p.get("adcode") == "100000_JD":
        jd = proj_rings(f["geometry"], 0.5)
        continue
    rings = proj_rings(f["geometry"], 1.2, minlat=17.5, min_area=4)
    small = [pl for pl in rings_of(f["geometry"]) if max(q[1] for q in pl[0]) < 17.5]
    small = proj_rings({"type": "MultiPolygon", "coordinates": small}, 0.3) if small else []
    provs.append({"id": str(p["adcode"]), "name": p["name"], "c": to_map(*p["center"]), "lc": to_map(*(p.get("centroid") or p["center"])), "rings": rings})
    scs += small
geo["provinces"] = provs
geo["jd"] = jd
geo["inset_islands"] = scs  # all polygons at fine tolerance; the page clips to the inset window

# National outline from DataV 100000.json (bound without children)
nat_path = os.path.join(SP, "dl/geo/china_bound.json")
if os.path.exists(nat_path):
    nat = json.load(open(nat_path))
    geo["nation"] = [r for f in nat["features"] for r in proj_rings(f["geometry"], 1.0, minlat=17.5, min_area=4)]

# Prefectures
prefs, seats = [], {}
for fn in sorted(glob.glob(os.path.join(SP, "dl/prov/*.json"))):
    d = json.load(open(fn))
    for f in d.get("features", []):
        p = f["properties"]
        if not f.get("geometry"):
            continue
        aid = str(p["adcode"])
        seats[aid] = p.get("center")
        prefs.append({"id": aid, "name": p["name"], "level": p.get("level"),
                      "rings": proj_rings(f["geometry"], 3.0, minlat=17.5, min_area=6)})
geo["prefectures"] = prefs
for p in full["features"]:
    pp = p["properties"]
    if pp.get("adcode") in (110000, 120000, 310000, 500000, 810000, 820000):
        seats[str(pp["adcode"])] = pp["center"]

# Neighbours, land, lakes, rivers, deserts (Natural Earth; China point of view)
ne = lambda n: json.load(open(os.path.join(SP, "dl/geo", n + ".geojson")))
BBOX = (60, 5, 150, 60)


def in_bbox(geom):
    for poly in rings_of(geom):
        for lon, lat in poly[0]:
            if BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]:
                return True
    return False


def clip_lonlat(geom):
    """Crop coordinates to a lon/lat box so Albers stays sane."""
    def c(r):
        return [[min(max(lon, 40), 170), min(max(lat, -10), 75)] for lon, lat in r]
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [c(r) for r in geom["coordinates"]]}
    if geom["type"] == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": [[c(r) for r in p] for p in geom["coordinates"]]}
    return geom


nbrs = []
for f in ne("ne_10m_admin_0_countries_chn")["features"]:
    p = f["properties"]
    if p.get("ADM0_A3") in ("CHN", "TWN", "HKG", "MAC") or not in_bbox(f["geometry"]):
        continue
    nbrs.append({"name": p.get("NAME_ZH") or p.get("NAME"), "iso": p.get("ADM0_A3"),
                 "rings": proj_rings(clip_lonlat(f["geometry"]), 3.0, min_area=30)})
geo["neighbours"] = nbrs

lakes = []
for f in ne("ne_10m_lakes")["features"]:
    if in_bbox(f["geometry"]) and (f["properties"].get("scalerank") or 9) <= 6:
        lakes.append({"name": f["properties"].get("name_zh") or f["properties"].get("name"),
                      "rings": proj_rings(f["geometry"], 1.0, min_area=40)})
geo["lakes"] = [l for l in lakes if l["rings"]]

rivers = []
for f in ne("ne_10m_rivers_lake_centerlines")["features"]:
    p = f["properties"]
    if p.get("featurecla", "").startswith("Lake"):
        continue
    if not in_bbox(f["geometry"]) or (p.get("scalerank") or 99) > 7:
        continue
    rivers.append({"name": p.get("name_zh") or p.get("name"), "rank": p.get("scalerank"),
                   "lines": [r[0] for r in proj_rings(f["geometry"], 1.0)]})
geo["rivers"] = rivers

deserts = []
for f in ne("ne_10m_geography_regions_polys")["features"]:
    p = f["properties"]
    if p.get("FEATURECLA") in ("Desert",) and in_bbox(f["geometry"]):
        deserts.append({"name": p.get("NAME_ZH") or p.get("NAME"), "rings": proj_rings(f["geometry"], 3.0)})
geo["deserts"] = deserts

json.dump(geo, open(os.path.join(OUT, "geo.json"), "w"), ensure_ascii=False, separators=(",", ":"))

# Cities: figures from chinaciv web/data/cities.json (official 2023 bulletins), seats from DataV
cc = json.load(open(CHINACIV))
cities = []
for c in cc:
    cen = seats.get(c["id"])
    if not cen:
        continue
    x, y = to_map(*cen)
    gbi = c.get("gdp_by_industry") or {}
    cities.append({"id": c["id"], "n": c["name"], "x": x, "y": y, "pop": c.get("population") or c.get("pop_census_2020"),
                   "gdp": c.get("gdp"), "p1": gbi.get("primary"), "p2": gbi.get("secondary"), "p3": gbi.get("tertiary"),
                   "prov": (c.get("states") or [None])[0], "kind": c.get("kind"),
                   "cap": bool(c.get("capital") or c.get("province_capital"))})
json.dump(cities, open(os.path.join(OUT, "cities.json"), "w"), ensure_ascii=False, separators=(",", ":"))
print("cities", len(cities), "of", len(cc))

# DEM: resample terrarium z6 to the frame at 4 km/px, store (h + 11000) as 16 bit in R,G
Z = 6
tiles = {}
for fn in glob.glob(os.path.join(SP, "dl/dem/t6_*.png")):
    _, tx, ty = os.path.basename(fn)[:-4].split("_")
    a = np.asarray(Image.open(fn).convert("RGB"), dtype=np.float32)
    tiles[(int(tx), int(ty))] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
TX0, TX1 = min(k[0] for k in tiles), max(k[0] for k in tiles)
TY0, TY1 = min(k[1] for k in tiles), max(k[1] for k in tiles)
mosaic = np.full(((TY1 - TY0 + 1) * 256, (TX1 - TX0 + 1) * 256), -4000, np.float32)
for (tx, ty), a in tiles.items():
    mosaic[(ty - TY0) * 256:(ty - TY0 + 1) * 256, (tx - TX0) * 256:(tx - TX0 + 1) * 256] = a
KM = 4.0
gw, gh = int(math.ceil(W / KM)), int(math.ceil(H / KM))
gx, gy = np.meshgrid(np.arange(gw) * KM + KM / 2, np.arange(gh) * KM + KM / 2)
lon, lat = inv(gx + FX0, FY1 - gy)
n = 2 ** Z
px = (lon + 180) / 360 * n * 256 - TX0 * 256
lr = np.radians(lat)
py = (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * n * 256 - TY0 * 256
x0 = np.clip(np.floor(px).astype(int), 0, mosaic.shape[1] - 2)
y0 = np.clip(np.floor(py).astype(int), 0, mosaic.shape[0] - 2)
fx, fy = np.clip(px - x0, 0, 1), np.clip(py - y0, 0, 1)
h = (mosaic[y0, x0] * (1 - fx) * (1 - fy) + mosaic[y0, x0 + 1] * fx * (1 - fy)
     + mosaic[y0 + 1, x0] * (1 - fx) * fy + mosaic[y0 + 1, x0 + 1] * fx * fy)
outside = (px < 0) | (py < 0) | (px >= mosaic.shape[1] - 1) | (py >= mosaic.shape[0] - 1)
h[outside] = -3000
v = np.clip(np.round(h + 11000), 0, 65535).astype(np.uint32)
rgb = np.zeros((gh, gw, 3), np.uint8)
rgb[..., 0] = v >> 8
rgb[..., 1] = v & 255
Image.fromarray(rgb, "RGB").save(os.path.join(OUT, "dem.png"), optimize=True)
json.dump({"km_per_px": KM, "w": gw, "h": gh, "offset": 11000}, open(os.path.join(OUT, "dem.json"), "w"))
print("dem", gw, gh, "max", float(h.max()), "min", float(h.min()))
for fn in os.listdir(OUT):
    print(fn, os.path.getsize(os.path.join(OUT, fn)))
