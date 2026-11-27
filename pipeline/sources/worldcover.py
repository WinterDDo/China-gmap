"""ESA WorldCover 2021 v200 → a 1 km land-cover class raster on the map frame.

WorldCover is a 10 m global land-cover map published as 3°×3° cloud-optimized GeoTIFFs (one public S3 object per
tile, named by its SW corner, ~3–150 MB each). Only one internal overview per tile is read, with HTTP range requests:
OVERVIEW_PX = 1125 px per 3° (≈300 m). Its pixels are mode aggregates (each is one of the classes of the 2×2 block
of the next finer overview, but at no fixed offset), so an overview pixel is a dominant class, not a point sample.
fetch() saves each decoded overview as an 8-bit grayscale PNG (value = class code) under
data/raw/worldcover/ovr1125/, so process() runs offline from the cache.

Which tiles: those reaching within BUFFER_KM of China's national outline (DataV standard-map outline, without the
South China Sea islands south of SOUTH_CUTOFF_LAT) and inside the map frame. Tiles missing from the bucket (open sea)
are skipped, using the bucket listing (cached too).

process():
1. every overview pixel votes for the 1 km map pixel its centre falls in; Albers is equal-area, so a map pixel's
   votes are an area sample of its footprint (~10–20 votes). The plurality class wins (ties → lower code);
2. the sea is removed. WorldCover labels the sea "permanent water" (80) in a band ~20–40 km wide along the coast and
   0 (no data) farther out. Water connected to that offshore no-data through water at least 2·OCEAN_OPEN_KM+1 km
   wide becomes 0, plus water within OCEAN_FRINGE_KM of that (channels between islands, the last km of river
   mouths); inland lakes and rivers stay 80. Inside China's outline nothing is removed: the map draws that outline
   as the coast, and the bays, estuaries and tidal flats it encloses (inner Hangzhou Bay, Lingdingyang, the Jiangsu
   flats, the Liao delta) would otherwise become holes; they stay water (80);
3. pixels farther than BUFFER_KM from China become 0.

Output: data/interim/worldcover_1km.png (8-bit grayscale on the 1 km frame grid; pixel (i, j) covers map km
[i, i+1) × [j, j+1); value = class code, 0 = no data / sea / outside the buffer) and the interim JSON (class table,
pixel counts inside China, provenance).
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw

from ..core import fetch, geo
from ..core.paths import INTERIM
from ..core.source import Source, SourceInfo

BUCKET = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
KEY_PREFIX = "v200/2021/map/ESA_WorldCover_10m_2021_v200_"
BOUND_URL = "https://geo.datav.aliyun.com/areas_v3/bound/100000.json"
BOUND_FILE = "china_bound.json"

TILE_DEG = 3
OVERVIEW_PX = 1125  # overview width per 3° tile: 36000 / 2**5 → 9.6″ ≈ 300 m (N–S)
BUFFER_KM = 100.0  # keep land cover this far beyond China's outline
SOUTH_CUTOFF_LAT = 17.5  # outline polygons entirely south of this (South China Sea islands) are ignored
DASH_COMPACTNESS = 0.08  # outline polygons less compact than this are the dashed sea line, not land
OCEAN_OPEN_KM = 3  # sea removal follows water at least 2*3+1 = 7 km wide (see module docstring)
OCEAN_FRINGE_KM = 15  # ...and then any water within this distance of that (island channels, river mouths)
WORKERS = 8  # parallel tile downloads
RASTER = "worldcover_1km.png"

CLASSES = [
    # code, key, Chinese name, English name (ESA legend)
    (10, "tree", "林地", "Tree cover"),
    (20, "shrub", "灌木地", "Shrubland"),
    (30, "grass", "草地", "Grassland"),
    (40, "crop", "耕地", "Cropland"),
    (50, "built", "建设用地", "Built-up"),
    (60, "bare", "裸地与稀疏植被", "Bare / sparse vegetation"),
    (70, "snow", "冰雪", "Snow and ice"),
    (80, "water", "永久水体", "Permanent water bodies"),
    (90, "wetland", "草本湿地", "Herbaceous wetland"),
    (95, "mangrove", "红树林", "Mangroves"),
    (100, "moss", "苔藓与地衣", "Moss and lichen"),
]
CODES = np.array([c[0] for c in CLASSES], np.uint8)
_INDEX = np.zeros(256, np.uint8)  # class code → 1-based index into CLASSES; 0 = no data (or an unknown value)
_INDEX[CODES] = np.arange(1, len(CLASSES) + 1)

ATTRIBUTION = "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium"
CITATION = "Zanaga, D. et al. (2022). ESA WorldCover 10 m 2021 v200. https://doi.org/10.5281/zenodo.7254221"


# ---------------------------------------------------------------- tiles


def tile_name(lat0: int, lon0: int) -> str:
    """Tile name from its SW corner, e.g. (30, 117) → "N30E117"."""
    return f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"


def parse_tile(name: str) -> tuple[int, int]:
    """"N30E117" → (30, 117): latitude and longitude of the SW corner."""
    m = re.fullmatch(r"([NS])(\d\d)([EW])(\d{3})", name)
    if not m:
        raise ValueError(f"bad tile name {name!r}")
    return int(m[2]) * (1 if m[1] == "N" else -1), int(m[4]) * (1 if m[3] == "E" else -1)


def tile_url(name: str) -> str:
    return f"{BUCKET}/{KEY_PREFIX}{name}_Map.tif"


def listing_url(row: str) -> str:
    """S3 listing (ListObjectsV2) of one 3° latitude row, e.g. row "N30"."""
    return f"{BUCKET}/?list-type=2&prefix={KEY_PREFIX}{row}"


def overview_file(name: str) -> str:
    return f"ovr{OVERVIEW_PX}/{name}.png"


def listed_tiles(xml: str) -> set[str]:
    """Tile names in a cached S3 listing."""
    if re.search(r"<IsTruncated>\s*true\s*</IsTruncated>", xml):
        raise RuntimeError("S3 listing is truncated (more than one page for a latitude row?)")
    return set(re.findall(r"<Key>[^<]*_v200_([NS]\d\d[EW]\d{3})_Map\.tif</Key>", xml))


# ---------------------------------------------------------------- projection and China masks


def to_map_np(lon, lat):
    """geo.to_map for numpy arrays (broadcasting): lon/lat degrees → map km (origin top-left, y down)."""
    rho = geo.R * np.sqrt(geo.C - 2 * geo.N * np.sin(np.radians(lat))) / geo.N
    th = geo.N * np.radians(np.asarray(lon, float) - geo.LON0)
    return rho * np.sin(th) - geo.X0, geo.Y1 - geo.RHO0 + rho * np.cos(th)


def _compactness(ring: np.ndarray) -> float:
    """4πA/P² of a lon/lat ring in map km: 1 for a disk, ~0.05 for the 125 × 2 km dash bars."""
    x, y = to_map_np(ring[:, 0], ring[:, 1])
    area = 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
    perim = np.hypot(np.diff(np.r_[x, x[:1]]), np.diff(np.r_[y, y[:1]])).sum()
    return 4 * math.pi * area / perim**2 if perim else 0.0


def china_rings(path: Path) -> list[tuple[np.ndarray, bool]]:
    """(lon/lat ring, is_hole) of the national outline's land polygons that reach north of SOUTH_CUTOFF_LAT.

    The DataV outline also draws the ten dashes of the South China Sea line as thin polygons (three of them north
    of 17.5°N: east of Taiwan, in the Luzon Strait and west of Luzon); they are not land, so polygons thinner than
    DASH_COMPACTNESS are dropped (the least compact island scores 0.108, the dashes ≤ 0.07).
    """
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    rings = []
    for feat in gj["features"]:
        g = feat["geometry"]
        polys = {"Polygon": [g["coordinates"]], "MultiPolygon": g["coordinates"]}.get(g["type"], [])
        for poly in polys:
            outer = np.asarray(poly[0], float)[:, :2]
            if outer[:, 1].max() < SOUTH_CUTOFF_LAT or _compactness(outer) < DASH_COMPACTNESS:
                continue
            rings.append((outer, False))
            rings += [(np.asarray(r, float)[:, :2], True) for r in poly[1:]]
    if not rings:
        raise ValueError(f"{path}: no polygons north of {SOUTH_CUTOFF_LAT}°N")
    return rings


def china_masks(rings: list[tuple[np.ndarray, bool]], km_per_px: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """(inside China, within BUFFER_KM of China) as bool rasters (h, w) on the frame grid."""
    w, h = geo.grid_shape(km_per_px)
    inside, near = Image.new("1", (w, h)), Image.new("1", (w, h))
    d_in, d_near = ImageDraw.Draw(inside), ImageDraw.Draw(near)
    r = BUFFER_KM / km_per_px
    for ring, hole in rings:
        x, y = to_map_np(ring[:, 0], ring[:, 1])
        pts = list(zip(x / km_per_px - 0.5, y / km_per_px - 0.5))  # PIL puts pixel centres on integer coordinates
        d_in.polygon(pts, fill=0 if hole else 1)
        if not hole:
            d_near.polygon(pts, fill=1)
        # buffer of the boundary = thick segments plus a disk at every vertex
        d_near.line(pts + pts[:1], fill=1, width=max(1, round(2 * r)))
        for px, py in pts:
            d_near.ellipse((px - r, py - r, px + r, py + r), fill=1)
    return np.array(inside, bool), np.array(near, bool)


def tiles_covering(mask: np.ndarray) -> list[str]:
    """Names of the 3° tiles that contain the centre of at least one True pixel of a 1 km frame mask."""
    n_lon = 360 // TILE_DEG
    hits = np.zeros((180 // TILE_DEG) * n_lon, bool)  # [lat row from -90, lon column from -180]
    for j0 in range(0, mask.shape[0], 256):
        jj, ii = np.nonzero(mask[j0 : j0 + 256])
        if len(jj):
            lon, lat = geo.from_map(ii + 0.5, jj + j0 + 0.5)
            row = np.floor((lat + 90) / TILE_DEG).astype(np.int64)
            col = np.floor((lon + 180) / TILE_DEG).astype(np.int64) % n_lon
            hits[np.unique(row * n_lon + col)] = True
    return sorted(
        tile_name(int(k // n_lon) * TILE_DEG - 90, int(k % n_lon) * TILE_DEG - 180) for k in np.flatnonzero(hits)
    )


def tile_cover(tiles: list[str], shape: tuple[int, int]) -> np.ndarray:
    """Union of the tiles' boxes on the 1 km frame grid (pixel centres inside)."""
    h, w = shape
    im = Image.new("1", (w, h))
    draw = ImageDraw.Draw(im)
    s = np.linspace(0, TILE_DEG, 31)
    for name in tiles:
        la, lo = parse_tile(name)
        lon = np.r_[lo + s, np.full(31, lo + TILE_DEG), lo + TILE_DEG - s, np.full(31, lo)]
        lat = np.r_[np.full(31, la), la + s, np.full(31, la + TILE_DEG), la + TILE_DEG - s]
        x, y = to_map_np(lon, lat)
        draw.polygon(list(zip(x - 0.5, y - 0.5)), fill=1)
    return np.array(im, bool)


# ---------------------------------------------------------------- cloud-optimized GeoTIFF overview reader

_TIFF_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 5: "I", 6: "b", 7: "B", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}
_TIFF_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
_TAGS = {256, 257, 258, 259, 277, 284, 317, 322, 323, 324, 325, 339, 33550, 33922}  # the ones we read
_COMPRESSION = {1: "none", 8: "deflate", 32946: "deflate"}


def _tiff_ifds(get: Callable[[int, int], bytes]) -> list[dict[int, tuple]]:
    """The IFDs of a little-endian TIFF or BigTIFF (only the tags in _TAGS). get(offset, n) returns file bytes."""
    head = get(0, 16)
    if head[:2] != b"II":
        raise ValueError("not a little-endian TIFF")
    magic = struct.unpack_from("<H", head, 2)[0]
    if magic == 42:
        big, off = False, struct.unpack_from("<I", head, 4)[0]
    elif magic == 43:
        big, off = True, struct.unpack_from("<Q", head, 8)[0]
    else:
        raise ValueError(f"not a TIFF (magic {magic})")
    cnt_fmt, ent, ptr_fmt = ("<Q", 20, "<Q") if big else ("<H", 12, "<I")
    cnt_size, ptr_size = struct.calcsize(cnt_fmt), struct.calcsize(ptr_fmt)
    ifds = []
    while off and len(ifds) < 64:
        n = struct.unpack(cnt_fmt, get(off, cnt_size))[0]
        raw = get(off + cnt_size, n * ent + ptr_size)
        tags = {}
        for k in range(n):
            e = raw[k * ent : (k + 1) * ent]
            tag, typ, count = struct.unpack_from("<HHQ" if big else "<HHI", e)
            inline = e[12:] if big else e[8:]
            if tag not in _TAGS or typ not in _TIFF_TYPES:
                continue
            size = _TIFF_SIZES[typ] * count
            data = inline[:size] if size <= ptr_size else get(struct.unpack(ptr_fmt, inline)[0], size)
            if typ == 2:
                tags[tag] = (data.split(b"\0")[0].decode("latin-1"),)
            else:
                tags[tag] = struct.unpack(f"<{count * (2 if typ == 5 else 1)}{_TIFF_TYPES[typ]}", data)
        ifds.append(tags)
        off = struct.unpack(ptr_fmt, raw[n * ent : n * ent + ptr_size])[0]
    return ifds


def read_cog_overview(read: Callable[[int, int], bytes], width: int, head_bytes: int = 32768) -> tuple[np.ndarray, dict, dict]:
    """Decode the image of width `width` (an overview) of a tiled, 8-bit, single-band TIFF.

    read(start, end) returns bytes [start, end) of the file. The first `head_bytes` are read at once (a COG
    keeps all IFDs and tile indexes up front); the overview's tiles are then fetched in one range when they
    are contiguous. Deflate or uncompressed tiles, predictor 1 or 2.
    Returns (array, overview info for the manifest, the full-resolution IFD's tags).
    """
    buf = read(0, head_bytes)

    def get(off: int, n: int) -> bytes:
        return buf[off : off + n] if off + n <= len(buf) else read(off, off + n)

    ifds = _tiff_ifds(get)
    pick = [k for k, t in enumerate(ifds) if t.get(256, (0,))[0] == width]
    if not pick:
        raise ValueError(f"no overview {width} px wide (widths: {[t.get(256, (0,))[0] for t in ifds]})")
    k = pick[0]
    t = ifds[k]
    W, H = t[256][0], t[257][0]
    comp, pred = t.get(259, (1,))[0], t.get(317, (1,))[0]
    if t.get(258, (8,))[0] != 8 or t.get(277, (1,))[0] != 1 or t.get(339, (1,))[0] != 1 or 322 not in t:
        raise ValueError("expected a tiled, single-band, 8-bit unsigned image")
    if comp not in _COMPRESSION or pred not in (1, 2):
        raise NotImplementedError(f"TIFF compression {comp} / predictor {pred} not supported (use tifffile+imagecodecs)")
    tw, th = t[322][0], t[323][0]
    nx, ny = math.ceil(W / tw), math.ceil(H / th)
    offs, cnts = t[324], t[325]
    if len(offs) != nx * ny or len(cnts) != nx * ny:
        raise ValueError("tile index size mismatch")

    used = [(o, c) for o, c in zip(offs, cnts) if c]
    blocks: dict[int, bytes] = {}
    if used:
        a, b = min(o for o, _ in used), max(o + c for o, c in used)
        if b - a <= 2 * sum(c for _, c in used) + 65536:  # contiguous (COG layout): one request
            span = get(a, b - a)
            blocks = {o: span[o - a : o - a + c] for o, c in used}
        else:
            blocks = {o: get(o, c) for o, c in used}

    img = np.zeros((ny * th, nx * tw), np.uint8)  # sparse (empty) tiles stay 0 = no data
    for idx, (o, c) in enumerate(zip(offs, cnts)):
        if not c:
            continue
        raw = blocks[o]
        if comp != 1:
            raw = zlib.decompress(raw)
        tile = np.frombuffer(raw, np.uint8)
        if tile.size != tw * th:
            raise ValueError(f"tile {idx}: {tile.size} bytes, expected {tw * th}")
        tile = tile.reshape(th, tw)
        if pred == 2:
            tile = np.cumsum(tile, axis=1, dtype=np.uint8)
        r, q = divmod(idx, nx)
        img[r * th : (r + 1) * th, q * tw : (q + 1) * tw] = tile
    info = {"ifd": k, "width": W, "height": H, "tile_px": [tw, th], "compression": _COMPRESSION[comp],
            "full_width": ifds[0].get(256, (None,))[0]}
    return img[:H, :W], info, ifds[0]


def _overview_png(name: str) -> Callable[[fetch.RangeReader], bytes]:
    """download_ranges() callback: read tile `name`'s overview, check its georeferencing, return it as PNG."""
    lat0, lon0 = parse_tile(name)

    def derive(reader: fetch.RangeReader) -> bytes:
        img, info, full = read_cog_overview(reader.read, OVERVIEW_PX)
        scale, tie = full.get(33550), full.get(33922)
        if not scale or not tie or abs(tie[3] - lon0) > 1e-6 or abs(tie[4] - (lat0 + TILE_DEG)) > 1e-6 \
                or abs(scale[0] * info["full_width"] - TILE_DEG) > 1e-6:
            raise ValueError(f"{name}: unexpected georeferencing (tiepoint {tie}, pixel scale {scale})")
        bad = np.unique(img[(_INDEX[img] == 0) & (img != 0)])
        if bad.size:
            raise ValueError(f"{name}: unknown class values {bad.tolist()}")
        reader.info.update(
            overview=info,
            bounds=[lon0, lat0, lon0 + TILE_DEG, lat0 + TILE_DEG],
            saved_as="8-bit grayscale PNG of the overview; value = WorldCover class code, 0 = no data",
        )
        out = io.BytesIO()
        Image.fromarray(img).save(out, format="PNG", optimize=True)
        return out.getvalue()

    return derive


# ---------------------------------------------------------------- raster ops


def _vote(counts: np.ndarray, img: np.ndarray, lat0: int, lon0: int) -> None:
    """Add one tile's overview pixels to counts[class index, y, x] of the map pixel their centre falls in."""
    n_cls, h, w = counts.shape
    d_lat, d_lon = TILE_DEG / img.shape[0], TILE_DEG / img.shape[1]
    lat = lat0 + TILE_DEG - (np.arange(img.shape[0]) + 0.5) * d_lat
    lon = lon0 + (np.arange(img.shape[1]) + 0.5) * d_lon
    x, y = to_map_np(lon[None, :], lat[:, None])
    ix, iy, k = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32), _INDEX[img]
    ok = (k > 0) & (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    if not ok.any():
        return
    ix, iy, k = ix[ok], iy[ok], k[ok].astype(np.int64) - 1
    x0, y0 = int(ix.min()), int(iy.min())
    ww, wh = int(ix.max()) - x0 + 1, int(iy.max()) - y0 + 1
    local = np.bincount((k * wh + (iy - y0)) * ww + (ix - x0), minlength=n_cls * wh * ww)
    counts[:, y0 : y0 + wh, x0 : x0 + ww] += local.reshape(n_cls, wh, ww).astype(counts.dtype)


def _dilate(m: np.ndarray, n: int = 1) -> np.ndarray:
    """n times a 3×3 binary dilation."""
    for _ in range(n):
        a = m.copy()
        a[1:] |= m[:-1]
        a[:-1] |= m[1:]
        m = a.copy()
        m[:, 1:] |= a[:, :-1]
        m[:, :-1] |= a[:, 1:]
    return m


def _erode(m: np.ndarray, n: int = 1) -> np.ndarray:
    return ~_dilate(~m, n)


def _spread_rows(domain: np.ndarray, reached: np.ndarray) -> np.ndarray:
    """Every horizontal run of `domain` pixels that contains a `reached` pixel, as a mask."""
    h, w = domain.shape
    d = np.zeros((h, w + 1), bool)  # a False column so that runs never wrap to the next row
    d[:, :w] = domain
    flat = d.ravel()
    run = np.cumsum(flat & ~np.r_[False, flat[:-1]], dtype=np.int32)
    run[~flat] = 0
    r = np.zeros((h, w + 1), bool)
    r[:, :w] = reached
    hit = np.bincount(run[r.ravel()], minlength=int(run[-1]) + 1).astype(bool)
    hit[0] = False
    return hit[run].reshape(h, w + 1)[:, :w]


def _flood(domain: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Pixels of `domain` 4-connected to `seeds` (alternating row and column run propagation)."""
    reached = seeds & domain
    if not reached.any():
        return reached
    rows, cols = np.nonzero(domain.any(1))[0], np.nonzero(domain.any(0))[0]
    win = np.s_[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
    dom, got = domain[win], reached[win]
    n = -1
    while (m := int(got.sum())) != n:
        n = m
        got = _spread_rows(dom, got)
        got = _spread_rows(dom.T, got.T).T
    out = np.zeros_like(domain)
    out[win] = got
    return out


def remove_sea(cls: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """Mask of class-80 pixels that are sea: connected to `seeds` (offshore no-data) through wide water."""
    water = cls == 80
    r = OCEAN_OPEN_KM
    wide = _dilate(_erode(water, r), r)  # opening: drops rivers and channels narrower than 2r+1 px
    sea = _flood(wide | seeds, seeds) & water
    for _ in range(OCEAN_FRINGE_KM):  # the opening's rounded edges, channels between islands, river mouths
        sea = _dilate(sea) & water
    return sea


def _save_png(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        Image.fromarray(arr).save(tmp, format="PNG", optimize=True)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- the source


class WorldCover(Source):
    info = SourceInfo(
        id="worldcover",
        title="ESA WorldCover 全球土地覆盖（2021）",
        publisher="欧洲航天局（ESA）WorldCover 项目组",
        homepage="https://esa-worldcover.org/",
        license="CC BY 4.0",
        description=(
            "欧洲航天局基于哨兵一号（雷达）与哨兵二号（光学）卫星影像制作的 2021 年全球 10 米分辨率土地覆盖图（v200 版），"
            "分林地、灌木地、草地、耕地、建设用地、裸地与稀疏植被、冰雪、永久水体、草本湿地、红树林、苔藓与地衣共 11 类。"
            "本图只读取每个 3°×3° 分幅文件内置的约 300 米概览层，再取每平方公里内面积最多的类别，"
            "重采样为 1 公里栅格，范围为中国及周边约 100 公里。原数据把近岸海面也标为水体；国界轮廓以外的海面已剔除，"
            "轮廓以内的海湾、河口与滩涂仍按水体保留。"
        ),
        used_for=["地表底色：林地、耕地、草地、荒漠、冰雪、水体与湿地的着色", "暗色主题中城镇建成区的灯光"],
    )

    # -------------------------------------------------- planning (shared by fetch and process)

    def _plan(self, bound: Path) -> tuple[list[tuple[np.ndarray, bool]], np.ndarray, np.ndarray, list[str]]:
        rings = china_rings(bound)
        inside, near = china_masks(rings)
        return rings, inside, near, tiles_covering(near)

    def _cached(self, rel: str) -> Path:
        p = self.raw_dir / rel
        if not p.exists():
            raise FileNotFoundError(f"{p} missing – run: uv run python -m pipeline fetch {self.id}")
        return p

    # -------------------------------------------------- fetch

    def fetch(self, force: bool = False) -> None:
        bound = self.download(BOUND_URL, BOUND_FILE, force=force)
        *_, tiles = self._plan(bound)
        existing: set[str] = set()
        for row in sorted({t[:3] for t in tiles}):
            xml = self.download(listing_url(row), f"listing/{row}.xml", force=force)
            existing |= listed_tiles(xml.read_text(encoding="utf-8"))
        todo = [t for t in tiles if t in existing]
        print(f"    {len(tiles)} tiles reach within {BUFFER_KM:g} km of China; {len(todo)} exist (the rest are open sea)")
        with ThreadPoolExecutor(WORKERS) as pool:
            jobs = [
                pool.submit(fetch.download_ranges, self.id, tile_url(t), overview_file(t), _overview_png(t), force=force)
                for t in todo
            ]
            for job in jobs:
                job.result()

    # -------------------------------------------------- process

    def process(self) -> dict:
        t0 = time.time()
        _, inside, near, tiles = self._plan(self._cached(BOUND_FILE))
        files = [BOUND_FILE]
        existing: set[str] = set()
        for row in sorted({t[:3] for t in tiles}):
            rel = f"listing/{row}.xml"
            existing |= listed_tiles(self._cached(rel).read_text(encoding="utf-8"))
            files.append(rel)
        present = [t for t in tiles if t in existing]

        # 1. votes → plurality class
        h, w = near.shape
        px_km = TILE_DEG / OVERVIEW_PX * 111.2  # overview pixel height; width shrinks with cos(lat)
        max_lat = max(parse_tile(t)[0] for t in tiles) + TILE_DEG
        most = (1 / px_km + 1) * (1 / (px_km * math.cos(math.radians(max_lat))) + 1)
        counts = np.zeros((len(CLASSES), h, w), np.uint8 if most < 255 else np.uint16)
        for name in present:
            rel = overview_file(name)
            with Image.open(self._cached(rel)) as im:
                img = np.asarray(im)
            if img.shape != (OVERVIEW_PX, OVERVIEW_PX) or img.dtype != np.uint8:
                raise ValueError(f"{rel}: unexpected image {img.shape} {img.dtype}")
            _vote(counts, img, *parse_tile(name))
            files.append(rel)
        votes = counts.sum(0, dtype=np.uint16)
        cls = np.zeros((h, w), np.uint8)
        for j in range(0, h, 512):
            cls[j : j + 512] = CODES[counts[:, j : j + 512].argmax(0)]
        del counts
        cls[votes == 0] = 0
        print(f"    {len(present)} tiles voted; median {int(np.median(votes[votes > 0]))} votes per 1 km pixel")

        # 2. sea outside China's outline → 0; 3. outside the buffer → 0
        covered = tile_cover(tiles, (h, w))
        sea = remove_sea(cls, covered & (votes == 0)) & ~inside
        cls[sea] = 0
        cls[~near] = 0
        _save_png(cls, INTERIM / RASTER)

        china_total = int(inside.sum())
        vals, cnt = np.unique(cls[inside], return_counts=True)
        by_code = dict(zip(vals.tolist(), cnt.tolist()))
        china_px = {key: by_code.get(code, 0) for code, key, _, _ in CLASSES}
        china_px["none"] = by_code.get(0, 0)
        print(f"    sea removed: {int(sea.sum()):,} px; inside China: {china_total:,} px "
              f"({china_px['none']:,} without a class); {time.time() - t0:.0f}s")

        return {
            "raster": RASTER,
            "km_per_px": 1.0,
            "shape": [w, h],
            "pixel": "pixel (i, j) covers map km [i, i+1) × [j, j+1) of the frame; value = class code",
            "nodata": 0,
            "nodata_means": "no data, sea outside China's outline, or farther than buffer_km from China",
            "classes": [{"code": c, "key": k, "zh": zh, "en": en} for c, k, zh, en in CLASSES],
            "china_px": china_px,  # 1 km² pixels inside the national outline (north of south_cutoff_lat), by class key
            "china_px_total": china_total,
            "buffer_km": BUFFER_KM,
            "south_cutoff_lat": SOUTH_CUTOFF_LAT,
            "method": (
                f"plurality of ~{OVERVIEW_PX}-px-per-3° WorldCover overview pixels (mode-aggregated, ≈300 m) whose "
                f"centres fall in each 1 km pixel; sea outside China's outline (class 80 joined to offshore no-data "
                f"through water ≥ {2 * OCEAN_OPEN_KM + 1} km wide) set to 0; water inside the outline kept"
            ),
            "tiles": {"near_china": len(tiles), "used": len(present), "absent": sorted(set(tiles) - existing)},
            "overview_px": OVERVIEW_PX,
            "sea_removed_px": int(sea.sum()),
            "attribution": ATTRIBUTION,
            "citation": CITATION,
            "vintage": "ESA WorldCover 2021 v200",
            "_files": files,
        }
