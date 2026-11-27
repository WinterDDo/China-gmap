"""The per-(code, year) bulletin record shared by every bulletin source, merging, coverage and the 2023 cross-check.

A record (one per unit and year, JSON):

    {"code": "130100", "name": "石家庄市", "level": "city", "province": "130000", "year": 2023,
     "source": "tjcn_bulletins",                    # which pipeline source produced it
     "status": "text" | "image_only" | "attachment_only" | "missing",
     "url": "http://www.tjcn.org/tjgb/03hb/37692.html",   # the page read (tjcn republish or the bureau's own page)
     "title": "石家庄市2023年国民经济和社会发展统计公报",
     "bureau": "石家庄市统计局",                     # original publisher (tjcn 来源 / the official site)
     "published": "2024-04-07 13:33:40",            # when the page was posted (tjcn 时间 / the site's 发布时间)
     "dated": "2024-03-11",                          # the date printed in the bulletin itself, if any
     "images": [...], "attachments": [...],          # absolute URLs found in the body (always kept, never OCR'd)
     "fields": {"gdp": {"value": 7534.2, "unit": "亿元", "raw": "7534.2亿元", "quote": "初步核算，…"} | null, …},
     "fields_found": 12, "flags": ["sum:+1.8%", "title_mismatch", …],
     "files": ["tjcn_bulletins/pages/03hb/37692.html"],   # cached raw files, relative to data/raw/
     "note": "…"}

Each source saves its records under data/interim/bulletins/sources/<source>/<year>.json; write_outputs() merges all
sources into data/interim/bulletins/<year>.json (one record per code and year: the best one, see RANK) and
coverage.csv, so a source added later (the owner's local collection) drops straight in.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import INTERIM
from ..core.store import atomic_write_text
from . import bulletin, htmltext
from .places import NATION, PlaceMatcher, bulletin_units, name_variants

BULLETINS = INTERIM / "bulletins"
STATUSES = ("text", "image_only", "attachment_only", "missing")
MIN_TEXT_CJK = 200  # fewer Chinese characters than this in the body → not a text bulletin
SOURCE_PRIORITY = {"local_bulletins": 2, "tjcn_bulletins": 1}  # equal quality: prefer the bureau's own page


def level_of(code: str, names: dict) -> str:
    if code == NATION:
        return "nation"
    return "province" if names[code]["level"] == "province" else "city"


def _cjk(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def classify(text: str, images: list[str], attachments: list[str]) -> str:
    if _cjk(text) >= MIN_TEXT_CJK:
        return "text"
    if images:
        return "image_only"
    if attachments:
        return "attachment_only"
    return "missing"


def printed_date(text: str) -> str | None:
    """The date printed at the head of a bulletin ("2024年 3月11日" → "2024-03-11"), from its first 400 characters."""
    m = re.search(r"(20\d\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text[:400])
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def title_ok(title: str | None, code: str, year: int, names: dict) -> bool:
    """The page title names the unit (any of its variants) and the year."""
    if not title:
        return False
    t = re.sub(r"\s+", "", title)
    if f"{year}年" not in t and f"{year}" not in t:
        return False
    variants = ["全国", "中华人民共和国", "中国"] if code == NATION else name_variants(names[code])
    return any(v in t for v in variants)


def missing_record(base: dict, note: str | None = None) -> dict:
    return {**base, "status": "missing", "fields": {k: None for k in bulletin.FIELDS}, "fields_found": 0,
            "flags": [], **({"note": note} if note else {})}


def build_record(base: dict, *, url: str, title: str | None, bureau: str | None, published: str | None,
                 body_html: str | None = None, text: str | None = None, base_url: str | None = None,
                 files: list[str] | None = None, names: dict | None = None, media: dict | None = None) -> dict:
    """A record from one bulletin's body: HTML (`body_html`), or plain `text` plus `media` ({images, attachments},
    absolute URLs) when the caller already has them (documents, the local collection)."""
    names = names if names is not None else PlaceMatcher().names
    code, year = base["code"], base["year"]
    if text is None:
        text = htmltext.to_text(body_html or "")
    found = media or (htmltext.media(body_html or "", base_url) if body_html else {"images": [], "attachments": []})
    status = classify(text, found["images"], found["attachments"])
    fields = bulletin.parse_fields(text, year) if status == "text" else {k: None for k in bulletin.FIELDS}
    level = level_of(code, names)
    flags = bulletin.validate(fields, level) if status == "text" else []
    if not title_ok(title, code, year, names):
        flags.append("title_mismatch")
    rec = {
        **base,
        "level": level,
        "province": code if level != "city" else names[code]["parent"],
        "status": status,
        "url": url,
        "title": title,
        "bureau": bureau,
        "published": published,
        "dated": printed_date(text),
        "images": found["images"],
        "attachments": found["attachments"],
        "text_chars": len(text),
        "fields": fields,
        "fields_found": bulletin.fields_found(fields),
        "flags": flags,
        "files": files or [],
    }
    if status == "missing":
        rec["note"] = "页面无正文、图片或附件"
    return rec


def status_counts(recs: list[dict]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for r in recs:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


# ------------------------------------------------------------------ per-source files and merging


def save_source_years(source_id: str, by_year: dict[int, list[dict]]) -> None:
    for year, recs in by_year.items():
        payload = {"source": source_id, "year": year,
                   "processed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "records": sorted(recs, key=lambda r: r["code"])}
        atomic_write_text(BULLETINS / "sources" / source_id / f"{year}.json",
                          json.dumps(payload, ensure_ascii=False, indent=1))


def load_source_years(root: Path | None = None) -> dict[str, dict[int, list[dict]]]:
    root = root or BULLETINS / "sources"
    out: dict[str, dict[int, list[dict]]] = {}
    for f in sorted(root.glob("*/*.json")) if root.exists() else []:
        payload = json.loads(f.read_text(encoding="utf-8"))
        out.setdefault(payload["source"], {})[int(payload["year"])] = payload["records"]
    return out


_RANK = {"text": 3, "attachment_only": 2, "image_only": 1, "missing": 0}


def rank(rec: dict) -> tuple:
    """Best record first: text over attachment/image-only over missing; then more fields, fewer flags, the bureau's
    own page over a republish."""
    return (_RANK[rec["status"]], rec.get("fields_found", 0), -len(rec.get("flags") or []),
            SOURCE_PRIORITY.get(rec.get("source"), 0))


def merge(candidates: list[dict]) -> dict:
    """The best of several records for one (code, year); the others are summarised under "other_sources"."""
    best = max(candidates, key=rank)
    others = [c for c in candidates if c is not best]
    if others:
        best = {**best, "other_sources": [
            {"source": o.get("source"), "status": o["status"], "url": o.get("url"), "fields_found": o.get("fields_found", 0)}
            for o in others]}
    return best


COVERAGE_COLUMNS = ["code", "name", "level", "province", "year", "status", "source", "fields_found", "missing_fields",
                    "flags", "url", "bureau", "published", "n_images", "n_attachments"]


def write_outputs(matcher: PlaceMatcher | None = None, root: Path | None = None) -> dict:
    """Merge every source's records into bulletins/<year>.json and coverage.csv; returns per-year status counts."""
    matcher = matcher or PlaceMatcher()
    root = root or BULLETINS
    per_source = load_source_years(root / "sources")
    years = sorted({y for by_year in per_source.values() for y in by_year})
    units = bulletin_units(matcher.names)
    rows = []
    summary = {}
    for year in years:
        merged = []
        for code in units:
            cands = [r for by_year in per_source.values() for r in by_year.get(year, []) if r["code"] == code]
            if not cands:
                continue
            merged.append(merge(cands))
        payload = {"year": year, "processed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "sources": sorted(s for s, by_year in per_source.items() if year in by_year),
                   "fields": {k: {"label": lab, "unit": unit} for k, (lab, unit) in bulletin.FIELDS.items()},
                   "records": merged}
        atomic_write_text(root / f"{year}.json", json.dumps(payload, ensure_ascii=False, indent=1))
        summary[str(year)] = status_counts(merged)
        for r in merged:
            missing = [k for k, v in r["fields"].items() if v is None]
            rows.append({
                "code": r["code"], "name": r["name"], "level": r.get("level") or level_of(r["code"], matcher.names),
                "province": r.get("province") or matcher.province_of(r["code"]), "year": year,
                "status": r["status"], "source": r.get("source"), "fields_found": r.get("fields_found", 0),
                "missing_fields": " ".join(missing) if r["status"] == "text" else "",
                "flags": " ".join(r.get("flags") or []), "url": r.get("url") or "", "bureau": r.get("bureau") or "",
                "published": r.get("published") or "", "n_images": len(r.get("images") or []),
                "n_attachments": len(r.get("attachments") or []),
            })
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COVERAGE_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(sorted(rows, key=lambda r: (r["code"], r["year"])))
    atomic_write_text(root / "coverage.csv", buf.getvalue())
    return summary


# ------------------------------------------------------------------ 2023 cross-check against chinaciv

CROSS_FIELDS = {  # our field → (chinaciv key path, factor from chinaciv's unit to ours)
    "gdp": (("gdp",), 1e-8),
    "gdp_primary": (("gdp_by_industry", "primary"), 1e-8),
    "gdp_secondary": (("gdp_by_industry", "secondary"), 1e-8),
    "gdp_tertiary": (("gdp_by_industry", "tertiary"), 1e-8),
    "population": (("population",), 1e-4),
}
CROSS_TOLERANCE = 0.001  # relative; both read the same bulletins, so anything above rounding is a real difference


def _dig(d: dict, path: tuple[str, ...]):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def chinaciv_values(raw_dir: Path) -> dict[str, dict]:
    """chinaciv's 2023 entries by our code: cities.json ids, states.json fips + "0000", nation.json → 100000."""
    load = lambda n: json.loads((raw_dir / n).read_text(encoding="utf-8"))  # noqa: E731
    out = {c["id"]: c for c in load("cities.json") if c.get("kind") not in ("municipality",)}
    for s in load("states.json"):
        out[f"{s['fips']}0000"] = s
    out[NATION] = load("nation.json")["nation"]
    return out


def crosscheck_chinaciv(raw_dir: Path, recs: list[dict], out_dir: Path | None = None) -> dict:
    """Compare our 2023 values with chinaciv's (sources/city_stats.py); writes crosscheck_2023.csv/.json."""
    out_dir = out_dir or BULLETINS
    if not (raw_dir / "cities.json").exists():
        return {"skipped": f"{raw_dir} not cached – run: python -m pipeline fetch city_stats"}
    theirs = chinaciv_values(raw_dir)
    rows, counts = [], {"compared": 0, "agree": 0, "differ": 0, "only_ours": 0, "only_chinaciv": 0}
    for r in recs:
        c = theirs.get(r["code"])
        if c is None:
            continue
        for key, (path, factor) in CROSS_FIELDS.items():
            if key == "population" and c.get("population_year") not in (2023, None):
                continue
            if key != "population" and c.get("gdp_year") not in (2023, None):
                continue
            ours = (r["fields"].get(key) or {}).get("value")
            raw = _dig(c, path)
            them = raw * factor if raw is not None else None
            if ours is None and them is None:
                continue
            if ours is None or them is None:
                counts["only_ours" if them is None else "only_chinaciv"] += 1
                kind = "only_ours" if them is None else "only_chinaciv"
                rel = None
            else:
                counts["compared"] += 1
                rel = (ours - them) / them if them else None
                kind = "agree" if rel is not None and abs(rel) <= CROSS_TOLERANCE else "differ"
                counts[kind] += 1
            rows.append({"code": r["code"], "name": r["name"], "field": key, "kind": kind,
                         "ours": ours, "chinaciv": None if them is None else round(them, 6),
                         "rel_diff": None if rel is None else round(rel, 6), "status": r["status"],
                         "url": r.get("url") or "", "quote": (r["fields"].get(key) or {}).get("quote") or ""})
    rows.sort(key=lambda x: (x["kind"] != "differ", -abs(x["rel_diff"] or 0), x["code"], x["field"]))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]) if rows else ["code"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    atomic_write_text(out_dir / "crosscheck_2023.csv", buf.getvalue())
    worst = [x for x in rows if x["kind"] == "differ"][:10]
    summary = {"tolerance": CROSS_TOLERANCE, **counts, "worst": worst}
    atomic_write_text(out_dir / "crosscheck_2023.json", json.dumps(summary, ensure_ascii=False, indent=1))
    return {k: v for k, v in summary.items() if k != "worst"} | {"worst": [
        {k: x[k] for k in ("code", "name", "field", "ours", "chinaciv", "rel_diff")} for x in worst]}
