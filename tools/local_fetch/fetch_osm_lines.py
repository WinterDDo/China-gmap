#!/usr/bin/env python3
"""Download China's railways (high-speed and main lines) and expressways from OpenStreetMap, on the owner's computer.

江山图鉴 draws them in the City View. The cloud session cannot reach the OpenStreetMap query servers (the connection
is dropped during the handshake), so this runs where it can: on the owner's Mac, with nothing but Python's standard
library. It asks the public Overpass API, province by province, for

    way[railway=rail][highspeed=yes][!service]   high-speed rail
    way[railway=rail][usage=main][!service]      main-line rail
    way[highway=motorway]                        expressways (ramps are motorway_link and not asked for)

thins every line to points about 150 m apart at most (Douglas-Peucker; the map never zooms closer than about
1.5 screen pixels per km), and writes one small gzip file per province and kind, then one zip to hand back.

    python3 fetch_osm_lines.py               everything (about 20 to 40 minutes), resumes where it stopped
    python3 fetch_osm_lines.py --only SC     one province, to try it out

Data © OpenStreetMap contributors, available under the Open Database License (ODbL 1.0).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "osm_lines")
ZIP = os.path.join(HERE, "jiangshan_osm_lines.zip")
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
AGENT = "jiangshan-atlas-local-fetch/1.0 (non-commercial map prototype)"
TOLERANCE_M = 150.0

# ISO 3166-2 province codes as OpenStreetMap tags them (letters since 2017; the old numbers are accepted too)
PROVINCES = [
    ("BJ", "11", "北京"), ("TJ", "12", "天津"), ("HE", "13", "河北"), ("SX", "14", "山西"), ("NM", "15", "内蒙古"),
    ("LN", "21", "辽宁"), ("JL", "22", "吉林"), ("HL", "23", "黑龙江"), ("SH", "31", "上海"), ("JS", "32", "江苏"),
    ("ZJ", "33", "浙江"), ("AH", "34", "安徽"), ("FJ", "35", "福建"), ("JX", "36", "江西"), ("SD", "37", "山东"),
    ("HA", "41", "河南"), ("HB", "42", "湖北"), ("HN", "43", "湖南"), ("GD", "44", "广东"), ("GX", "45", "广西"),
    ("HI", "46", "海南"), ("CQ", "50", "重庆"), ("SC", "51", "四川"), ("GZ", "52", "贵州"), ("YN", "53", "云南"),
    ("XZ", "54", "西藏"), ("SN", "61", "陕西"), ("GS", "62", "甘肃"), ("QH", "63", "青海"), ("NX", "64", "宁夏"),
    ("XJ", "65", "新疆"), ("HK", "91", "香港"), ("MO", "92", "澳门"), ("TW", "71", "台湾"),
]
KINDS = {
    "rail": '  way["railway"="rail"]["highspeed"="yes"][!"service"](area.a);\n'
            '  way["railway"="rail"]["usage"="main"][!"service"](area.a);\n',
    "road": '  way["highway"="motorway"](area.a);\n',
}
KEEP = ("name", "name:en", "ref", "maxspeed", "usage", "highspeed")


def say(*parts) -> None:
    print(*parts, flush=True)


def area_filter(code: str, num: str) -> str:
    if code == "TW":  # Taiwan is tagged as its own country in OpenStreetMap
        return 'area["ISO3166-1"="TW"]["admin_level"="2"]'
    return f'area["ISO3166-2"~"^CN-({code}|{num})$"]["boundary"="administrative"]'


def query_for(code: str, num: str, kind: str) -> str:
    return (f"[out:json][timeout:900][maxsize:2000000000];\n{area_filter(code, num)}->.a;\n(\n{KINDS[kind]});\n"
            "out tags geom qt;\n")


def simplify(points: list, tol_m: float = TOLERANCE_M) -> list:
    """Douglas-Peucker on [(lon, lat), ...], distances in metres on a local equirectangular plane."""
    if len(points) <= 2:
        return points
    lat0 = math.radians(sum(p[1] for p in points) / len(points))
    kx, ky = 111320.0 * math.cos(lat0), 110540.0
    xy = [(p[0] * kx, p[1] * ky) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = xy[a], xy[b]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x, y = xy[i]
            if L2 == 0:
                d = math.hypot(x - x1, y - y1)
            else:
                t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
                d = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
            if d > best:
                best, idx = d, i
        if best > tol_m:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def classify(tags: dict) -> str:
    if tags.get("highway") == "motorway":
        return "exp"
    return "hsr" if tags.get("highspeed") == "yes" else "rail"


def compact(answer: dict) -> list:
    """Overpass JSON -> [[class, {kept tags}, [lon, lat, lon, lat, ...]], ...] with thinned, rounded coordinates."""
    out = []
    for el in answer.get("elements", []):
        geom = el.get("geometry") or []
        pts = [(g["lon"], g["lat"]) for g in geom if g and "lon" in g]
        if len(pts) < 2:
            continue
        tags = el.get("tags") or {}
        flat = []
        for lon, lat in simplify(pts):
            flat += [round(lon, 5), round(lat, 5)]
        out.append([classify(tags), {k: tags[k] for k in KEEP if k in tags}, flat])
    return out


def ask(query: str, tries: int = 3) -> tuple:
    """POST the query to each mirror in turn; returns (answer, url). Raises after every mirror failed `tries` rounds."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for rnd in range(tries):
        for url in MIRRORS:
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": AGENT})
                with urllib.request.urlopen(req, timeout=960) as r:
                    answer = json.loads(r.read().decode("utf-8"))
                remark = answer.get("remark") or ""
                if "error" in remark.lower():  # Overpass reports timeouts and memory limits here, with HTTP 200
                    raise RuntimeError(remark[:200])
                return answer, url
            except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
                last = f"{url}: {e}"
                say(f"    没成功，换一个服务器再试（{type(e).__name__}）")
                time.sleep(10 * (rnd + 1))
    raise RuntimeError(last)


def fetch_one(code: str, num: str, zh: str, kind: str) -> dict:
    path = os.path.join(OUT, f"{code}-{kind}.json.gz")
    if os.path.exists(path):
        return {"file": os.path.basename(path), "status": "already"}
    q = query_for(code, num, kind)
    t0 = time.time()
    answer, url = ask(q)
    ways = compact(answer)
    rec = {"province": code, "zh": zh, "kind": kind, "url": url, "query": q,
           "osm_base": (answer.get("osm3s") or {}).get("timestamp_osm_base"),
           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ways": ways,
           "license": "© OpenStreetMap contributors, ODbL 1.0"}
    tmp = path + ".part"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return {"file": os.path.basename(path), "status": "done", "ways": len(ways), "seconds": round(time.time() - t0)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="只下载这些省（逗号分隔的字母代码，如 SC,CQ）")
    args = ap.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    todo = [p for p in PROVINCES if not args.only or p[0] in args.only.upper().split(",")]
    say(f"开始下载：{len(todo)} 个省级地区，每个两项（铁路、高速）。中途停了可以再运行一次，会接着下。")
    manifest, failed = [], []
    for i, (code, num, zh) in enumerate(todo, 1):
        for kind in ("rail", "road"):
            label = "铁路" if kind == "rail" else "高速"
            say(f"[{i}/{len(todo)}] {zh} {label} …")
            try:
                r = fetch_one(code, num, zh, kind)
                manifest.append(r)
                if r["status"] == "done":
                    say(f"    好了：{r['ways']} 段线路，用了 {r['seconds']} 秒")
                    if r["ways"] == 0:
                        say("    （一段都没有：这个地区可能没对上名字，最后会列出来）")
                        failed.append(f"{zh}{label}：0 段")
                    time.sleep(5)  # be gentle with a free public service
                else:
                    say("    之前已经下好了，跳过")
            except Exception as e:  # keep going; the summary lists what is missing
                failed.append(f"{zh}{label}：{e}")
                say(f"    这一项没下成，先跳过（{e}）")
    files = sorted(f for f in os.listdir(OUT) if f.endswith(".json.gz"))
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(os.path.join(OUT, f), arcname=f"osm_lines/{f}")
        z.writestr("osm_lines/manifest.json", json.dumps({"made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                         "files": files, "failed": failed}, ensure_ascii=False, indent=1))
    size = os.path.getsize(ZIP) / 1e6
    say("")
    if failed:
        say(f"完成，但有 {len(failed)} 项没下成：")
        for f in failed:
            say("  - " + f)
        say("可以再运行一次补下；补不上也没关系，把压缩包交回来就行。")
    else:
        say(f"全部完成：{len(files)} 个文件。")
    say(f"压缩包在：{ZIP}（{size:.1f} MB），把它交回给项目。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
