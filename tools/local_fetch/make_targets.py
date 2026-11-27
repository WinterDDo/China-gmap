#!/usr/bin/env python3
"""Write tools/local_fetch/targets.json for the local collector (developer side; needs the repo's pipeline).

    python3 tools/local_fetch/make_targets.py            # after: python -m pipeline fetch/process tjcn_bulletins

Targets: every unit of bulletin_units() (the nation, 31 provinces, 333 prefecture-level units) for NEW_YEARS, plus
every 2020–2023 (code, year) whose tjcn.org record is missing, image-only or attachment-only (with the bureau's own
image/attachment URLs from tjcn as known_urls, so the collector can fetch them directly).

hint_host – where the unit published before, so the collector can prefer it among search results – is the most
recent gov.cn host among: the image/attachment URLs in its tjcn.org pages 2020–2023, and the official attachment
URLs chinaciv read for 2023 (data/raw/city_stats/sources.json; archive.org copies count for their original host).
A unit with no such evidence gets hint_host null: the collector then just prefers gov.cn sites.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline.core.paths import INTERIM, RAW  # noqa: E402
from pipeline.parse.places import NATION, PlaceMatcher, bulletin_units, name_variants  # noqa: E402

NEW_YEARS = (2025, 2024)
GAP_YEARS = (2023, 2022, 2021, 2020)
OUT = Path(__file__).resolve().parent / "targets.json"
NATION_HOST = "www.stats.gov.cn"


def host(url: str) -> str | None:
    """Host of a URL; for web.archive.org copies, the archived page's host."""
    u = urllib.parse.urlsplit(url)
    h = (u.hostname or "").lower()
    if h.endswith("archive.org"):
        m = re.search(r"/web/[^/]+/(https?://[^ ]+)", url)
        return host(m.group(1)) if m else None
    return h or None


def official(h: str | None) -> bool:
    return bool(h) and (h.endswith(".gov.cn") or h == "gov.cn")


def title_names(code: str, names: dict) -> list[str]:
    """Names a bulletin title may use for the unit; never a bare name that is also the start of another unit's
    name (吉林省 → only "吉林省", so "吉林市…" titles are not taken for the province)."""
    if code == NATION:
        return ["中华人民共和国", "全国"]
    e = names[code]
    if e["level"] == "province":
        return [e["zh_full"]] + ([e["zh"]] if e["zh_full"].endswith("自治区") else [])
    return name_variants(e)


def tjcn_records() -> dict[tuple[str, int], dict]:
    out = {}
    for year in GAP_YEARS:
        p = INTERIM / "bulletins" / "sources" / "tjcn_bulletins" / f"{year}.json"
        if not p.exists():
            sys.exit(f"{p} missing – run: python -m pipeline process tjcn_bulletins")
        for r in json.loads(p.read_text(encoding="utf-8"))["records"]:
            out[(r["code"], year)] = r
    return out


def chinaciv_hosts(recs: dict[tuple[str, int], dict]) -> dict[str, list[str]]:
    """code → hosts of the official 2023 attachments chinaciv read (its files are named tjcn/att2023/<tjcn id>_n.ext)."""
    src = RAW / "city_stats" / "sources.json"
    if not src.exists():
        return {}
    by_id = {}
    for (code, year), r in recs.items():
        m = re.search(r"/(\d+)\.html$", r.get("url") or "")
        if year == 2023 and m:
            by_id[m.group(1)] = code
    out: dict[str, list[str]] = {}
    for s in json.loads(src.read_text(encoding="utf-8")):
        for f in s.get("files", []):
            m = re.match(r"tjcn/att2023/(\d+)_\d+\.", f.get("file", ""))
            if m and m.group(1) in by_id:
                h = host(f.get("url", ""))
                if h:
                    out.setdefault(by_id[m.group(1)], []).append(h)
    return out


def hints(code: str, recs: dict, civ: dict[str, list[str]]) -> tuple[str | None, list[str]]:
    """(hint_host, all official hosts seen, most recent and most frequent first)."""
    seen: list[tuple[int, str]] = []
    for year in GAP_YEARS:
        r = recs.get((code, year)) or {}
        for u in (r.get("images") or []) + (r.get("attachments") or []):
            h = host(u)
            if official(h):
                seen.append((year, h))
    seen += [(2023, h) for h in civ.get(code, []) if official(h)]
    if code == NATION:
        seen.append((9999, NATION_HOST))
    if not seen:
        return None, []
    count = Counter(h for _, h in seen)
    latest = {}
    for y, h in seen:
        latest[h] = max(latest.get(h, 0), y)
    ordered = sorted(count, key=lambda h: (-latest[h], -count[h], h))
    return ordered[0], ordered


def main() -> None:
    matcher = PlaceMatcher()
    names = matcher.names
    recs = tjcn_records()
    civ = chinaciv_hosts(recs)
    units = bulletin_units(names)
    targets = []

    def target(code: str, year: int, reason: str, known: list[str] | None = None) -> dict:
        hint, all_hosts = hints(code, recs, civ)
        prov = matcher.province_of(code)
        t = {"code": code, "zh_full": matcher.label(code) if code != NATION else "中华人民共和国",
             "names": title_names(code, names), "province": matcher.label(prov) if prov != NATION else "",
             "level": "nation" if code == NATION else ("province" if names[code]["level"] == "province" else "city"),
             "year": year, "reason": reason, "hint_host": hint, "hint_hosts": all_hosts}
        if known:
            t["known_urls"] = known
        return t

    for year in NEW_YEARS:
        for code in units:
            targets.append(target(code, year, "not_on_tjcn"))
    gaps = Counter()
    for year in GAP_YEARS:
        for code in units:
            r = recs.get((code, year))
            status = r["status"] if r else "missing"
            if status == "text":
                continue
            gaps[(year, status)] += 1
            known = [u for u in (r or {}).get("images", []) + (r or {}).get("attachments", [])
                     if host(u) and "tjcn.org" not in host(u)]
            targets.append(target(code, year, f"{status}_on_tjcn", known))
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "由 tools/local_fetch/make_targets.py 生成：2024、2025 年全部地区，以及中国统计信息网 2020–2023 年"
                "缺失、只有图片或只有附件的地区。hint_host 为该地区以往发布公报的官方网站（可能为空）。",
        "count": len(targets),
        "targets": targets,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with_hint = sum(1 for t in targets if t["hint_host"])
    print(f"{OUT}: {len(targets)} targets ({len(units)} units × {len(NEW_YEARS)} new years + "
          f"{sum(gaps.values())} gaps {dict(sorted(gaps.items()))}); {with_hint} with a hint_host")


if __name__ == "__main__":
    main()
