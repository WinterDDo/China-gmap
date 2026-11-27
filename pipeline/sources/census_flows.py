"""Province-to-province population flows from the 2020 (七普) and 2010 (六普) census yearbooks of 国家统计局.

Where people from each province went to live, as three origin × destination matrices over the 31 provinces per census:

* hukou_outside_province (stock) – people living in province d on census day whose 户口登记地 is province o ≠ d.
  Full count. 2020: 《中国人口普查年鉴-2020》 第一部分 第七卷 表 7-3 「全国按现住地、性别分的户口登记地在外省的人口」;
  2010: 《中国2010年人口普查资料》 the same table 7-3.
* five_years_ago (recent movers) – people living in d whose 常住地 five years before census day was o ≠ d
  (2015-11-01 → 2020-11-01; 2005 → 2010). Long-form table: the 10% household sample, counted as registered and
  not weighted (编辑说明: "长表抽取了10%的户"; "推算总体时，对采用的方法予以注意"). 2020: 第二部分 第七卷 表 7-7
  「全国按现住地和五年前常住地分的人口」; 2010: 第二部分 第七卷 表 7-8 (same title).
* birthplace (lifetime migrants) – people living in d who were born in o ≠ d, all ages. Long-form table as well.
  2020: 第二部分 第七卷 表 7-6 「全国按现住地和出生地分的人口」; 2010: 第二部分 第七卷 表 7-7 (same title).
For an estimate of the whole population, `sample.scale[d]` of a long-form matrix is the full-count population of d
over its long-form population (人口数合计 of table 1-1 「各地区户数、人口数和性别比」 in each part).

fetch() downloads, from www.stats.gov.cn only, each yearbook's frame page, its table of contents (left.htm, where the
table titles and their 部分/卷 come from) and editorial note, the three tables per year (2020: .xls; 2010:
Excel-exported .htm) and the two population tables per year for the sample scale. Everything is cached under data/raw/census/<year>/ with
the usual manifest (url, sha256, bytes, retrieved). The .xls files are read by parse/xls.py (cell values only).

process() writes data/interim/census/flows_<year>.json:

    {"year": 2020, "census": …, "yearbook": {…},
     "matrices": [{"source": {title, table_id, part, volume, yearbook, url, toc_url, file, retrieved, sha256},
                   "kind": "hukou_outside_province" | "five_years_ago" | "birthplace", "unit": "人", "sampled": bool,
                   "provinces": {code: name}, "flows": [{"o": "510000", "d": "440000", "n": 12345}, …],
                   "published_totals": {…}, "checks": {…}, …}, …]}

`flows` holds every non-empty off-diagonal cell (a blank cell – "无数字或数字很小" – is left out, never written as 0).
A row's own province column (the diagonal: people of d counted under d's own name) is never a flow; whatever the table
prints there is kept in `published_totals.diagonal` and in the checks. The checks compare the flows with the table's
own totals: each destination's row (合计, minus the within-province, 港澳台或国外 and diagonal cells where the table
has them) and each origin's column (the 全国 row, minus the diagonal cell); 小计 = 男 + 女 too.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ..core.fetch import read_manifest
from ..core.paths import INTERIM
from ..core.source import Source, SourceInfo
from ..core.store import atomic_write_text
from ..parse import htmltext, xls
from ..parse.places import clean, load_names

OUT = INTERIM / "census"
NATION = "100000"

YEARBOOKS = {
    2020: {"title": "中国人口普查年鉴-2020", "census": "第七次全国人口普查", "moment": "2020-11-01 00:00",
           "base": "https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/"},
    2010: {"title": "中国2010年人口普查资料", "census": "第六次全国人口普查", "moment": "2010-11-01 00:00",
           "base": "https://www.stats.gov.cn/sj/pcsj/rkpc/6rp/"},
}
PAGES = ("indexch.htm", "left.htm", "html/note.htm")  # frame page, table of contents, 编辑说明

DEFINITIONS = {
    "hukou_outside_province": "普查时点现住地在 d 省、户口登记地在外省 o 的人口（全部人口，存量）",
    "five_years_ago": "普查时点现住地在 d 省、五年前常住地在外省 o 的人口（5 岁及以上；长表 10% 抽样登记数，未加权）",
    "birthplace": "普查时点现住地在 d 省、出生地在外省 o 的人口（全部年龄；长表 10% 抽样登记数，未加权）",
}
TABLES = {  # (year, kind) → table file (relative to the yearbook's base URL), table number, title in the file
    (2020, "hukou_outside_province"): ("html/A0703.xls", "7-3", "全国按现住地、性别分的户口登记地在外省的人口"),
    (2020, "five_years_ago"): ("html/B0707.xls", "7-7", "全国按现住地和五年前常住地分的人口"),
    (2020, "birthplace"): ("html/B0706.xls", "7-6", "全国按现住地和出生地分的人口"),
    (2010, "hukou_outside_province"): ("html/A0703a.htm", "7-3", "全国按现住地、性别分的户口登记地在外省的人口"),
    (2010, "five_years_ago"): ("html/B0708.htm", "7-8", "全国按现住地和五年前常住地分的人口"),
    (2010, "birthplace"): ("html/B0707.htm", "7-7", "全国按现住地和出生地分的人口"),
}
LONG_FORM = {"five_years_ago", "birthplace"}
POPULATION = {  # year → (full count, long form): table 1-1 各地区户数、人口数和性别比 of each part, for the sample scale
    2020: ("html/A0101.xls", "html/B0101.xls"),
    2010: ("html/A0101a.htm", "html/B0101a.htm"),
}


def rel(year: int, file: str) -> str:
    """Path of a yearbook file under data/raw/census/."""
    return f"{year}/{file.rsplit('/', 1)[-1]}"


def province_codes(names: dict | None = None) -> dict[str, str]:
    """The 31 mainland provinces: short name ("内蒙古") → code."""
    names = names if names is not None else load_names()
    return {v["zh"]: k for k, v in names.items() if v["level"] == "province" and k < "710000"}


# ------------------------------------------------------------------ reading tables (pure)


def load_grid(data: bytes, filename: str) -> list[list]:
    """The first sheet (.xls) or the first table (.htm, gb18030) as a grid of cells (None = empty / merged)."""
    if filename.lower().endswith(".xls"):
        return xls.grid(xls.sheets(data)[0][1])
    grids = htmltext.table_grids(data.decode("gb18030", errors="replace"))
    if not grids:
        raise ValueError(f"{filename}: no table")
    return grids[0]


def count(v) -> int | None:
    """A cell as a head count: None for a blank cell; ValueError for anything that is not a whole number."""
    if v is None:
        return None
    if isinstance(v, float):
        if v != int(v) or v < 0:
            raise ValueError(f"not a head count: {v!r}")
        return int(v)
    s = clean(str(v)).replace(",", "")
    if s in ("", "-", "—", "…"):
        return None
    if not re.fullmatch(r"\d+(?:\.0+)?", s):
        raise ValueError(f"not a head count: {v!r}")
    return int(float(s))


def _text(v) -> str:
    return clean(v) if isinstance(v, str) else ""


def read_matrix(grid: list[list], codes: dict[str, str]) -> dict:
    """Origin × destination counts of a census table laid out as 现住地 rows × 户口登记地 / 五年前常住地 columns.

    Returns {title, flows {(o, d): n}, row_total {d: n}, nation_row {o: n}, nation_total, within {d: {...}},
    abroad {d: n}, diagonal {d: n} (every non-blank own-province cell, 0 included), sex_mismatches [...]}
    (codes as in `codes`)."""
    title = next((re.sub(r"\s+", " ", v).strip() for v in grid[0] if _text(v)), "") if grid else ""
    first = next((r for r, row in enumerate(grid) if row and _text(row[0]) == "全国"), None)
    if first is None:
        raise ValueError("no 全国 row")
    head = grid[:first]
    # the header row naming the origins: the one with the most province names
    best = max(range(len(head)), key=lambda r: sum(_text(v) in codes for v in head[r][1:]))
    origin_col: dict[str, int] = {}
    for c, v in enumerate(head[best]):
        if c and _text(v) in codes and codes[_text(v)] not in origin_col:
            origin_col[codes[_text(v)]] = c
    if len(origin_col) != len(set(codes.values())):
        missing = sorted(set(codes.values()) - set(origin_col))
        raise ValueError(f"origin columns missing for {missing}")

    def col_of(pred) -> int | None:
        cols = [c for row in head for c, v in enumerate(row) if c and pred(_text(v))]
        return min(cols) if cols else None

    total_col = col_of(lambda t: t == "合计")
    if total_col is None or total_col >= min(origin_col.values()):
        raise ValueError("no 合计 column before the origins")
    within_cols = {}
    if (c := col_of(lambda t: t == "本县市区")) is not None:
        within_cols = {"same_county": c, "other_county": col_of(lambda t: t.startswith("本省其他"))}
    elif (c := col_of(lambda t: t == "省内")) is not None:
        within_cols = {"total": c}
    abroad_col = col_of(lambda t: t.startswith("港澳台"))
    sub = head[best + 1] if best + 1 < len(head) else []
    has_sex = all(c + 2 < len(sub) and _text(sub[c]) == "小计" and _text(sub[c + 1]) == "男" and _text(sub[c + 2]) == "女"
                  for c in origin_col.values())

    rows: dict[str, int] = {}
    for r in range(first, len(grid)):
        name = _text(grid[r][0])
        code = NATION if name == "全国" else codes.get(name)
        if code and code not in rows:
            rows[code] = r
    missing = sorted(set(codes.values()) - set(rows))
    if missing:
        raise ValueError(f"destination rows missing for {missing}")

    cell = lambda r, c: count(grid[r][c]) if c is not None and c < len(grid[r]) else None  # noqa: E731
    flows, diagonal, sex_bad = {}, {}, []
    for d, r in rows.items():
        if d == NATION:
            continue
        for o, c in origin_col.items():
            n = cell(r, c)
            if o == d:
                if n is not None:
                    diagonal[d] = n
                continue
            if n:
                flows[o, d] = n
            if has_sex and n is not None:
                m, f = cell(r, c + 1) or 0, cell(r, c + 2) or 0
                if m + f != n:
                    sex_bad.append({"o": o, "d": d, "n": n, "male": m, "female": f})
    nat = rows[NATION]
    return {
        "title": title,
        "flows": flows,
        "row_total": {d: cell(r, total_col) for d, r in rows.items() if d != NATION},
        "nation_row": {o: cell(nat, c) for o, c in origin_col.items()},
        "nation_total": cell(nat, total_col),
        "within": {d: {k: cell(r, c) for k, c in within_cols.items()} for d, r in rows.items() if d != NATION}
        if within_cols else {},
        "nation_within": {k: cell(nat, c) for k, c in within_cols.items()},
        "abroad": {d: cell(r, abroad_col) for d, r in rows.items() if d != NATION} if abroad_col else {},
        "nation_abroad": cell(nat, abroad_col) if abroad_col else None,
        "has_sex": has_sex,
        "sex_mismatches": sex_bad,
        "diagonal": diagonal,
    }


def check_matrix(m: dict) -> dict:
    """Flows against the table's own totals: rows (destinations), columns (origins: the 全国 row) and the grand total.
    The diagonal cells are not flows but are part of the totals: they are taken out of the row, column and grand totals."""
    diag = m["diagonal"]
    inflow: dict[str, int] = {}
    outflow: dict[str, int] = {}
    for (o, d), n in m["flows"].items():
        inflow[d] = inflow.get(d, 0) + n
        outflow[o] = outflow.get(o, 0) + n
    row_bad, col_bad = [], []
    for d, total in m["row_total"].items():
        expected = ((total or 0) - sum(v or 0 for v in m["within"].get(d, {}).values()) - (m["abroad"].get(d) or 0)
                    - diag.get(d, 0))
        if expected != inflow.get(d, 0):
            row_bad.append({"d": d, "table": expected, "sum_of_flows": inflow.get(d, 0)})
    for o, total in m["nation_row"].items():
        expected = (total or 0) - diag.get(o, 0)
        if expected != outflow.get(o, 0):
            col_bad.append({"o": o, "table": expected, "sum_of_flows": outflow.get(o, 0)})
    grand = sum(m["flows"].values())
    nation_expected = ((m["nation_total"] or 0) - sum(v or 0 for v in m["nation_within"].values())
                       - (m["nation_abroad"] or 0) - sum(diag.values()))
    return {
        "sum_of_flows": grand,
        "table_total_between_provinces": nation_expected,
        "grand_total_ok": grand == nation_expected,
        "rows_ok": not row_bad, "row_mismatches": row_bad,
        "columns_ok": not col_bad, "column_mismatches": col_bad,
        "diagonal_total": sum(diag.values()),
        "diagonal_empty": not any(diag.values()),
        **({"sex_split_ok": not m["sex_mismatches"], "sex_mismatches": m["sex_mismatches"][:20]} if m["has_sex"] else {}),
    }


def read_population(grid: list[list], codes: dict[str, str]) -> dict[str, int]:
    """人口数 合计 of table 1-1 「各地区户数、人口数和性别比」, by province code and NATION: the 合计 column of the header
    row that splits the population by sex (合计 | 男 | 女 | 性别比), not the 户数 合计 before it."""
    first = next((r for r, row in enumerate(grid) if row and _text(row[0]) == "全国"), None)
    if first is None:
        raise ValueError("no 全国 row")
    col = next((c for row in grid[:first] if "男" in [_text(v) for v in row]
                for c, v in enumerate(row) if c and _text(v) == "合计"), None)
    if col is None:
        raise ValueError("no 人口数 合计 column")
    out = {}
    for row in grid[first:]:
        name = _text(row[0]) if row else ""
        code = NATION if name == "全国" else codes.get(name)
        if code and code not in out:
            out[code] = count(row[col])
    return out


def parse_toc(html: str) -> dict[str, dict]:
    """Table of contents (left.htm): file stem ("A0703", "B0708") → {title, part, volume} from the folding headers."""
    out, part, volume = {}, None, None
    token = re.compile(r"<li[^>]*id=[\"']?foldheader[\"']?[^>]*>(.*?)</li>|<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                       re.S | re.I)
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s).replace("　", " ")).strip()  # noqa: E731
    for m in token.finditer(html):
        heading = m.group(1) if m.group(1) is not None else (m.group(3) if "foldheader" in m.group(3) else None)
        if heading is not None:  # <a href="ge08.jpg"><li id="foldheader">第七卷 户口登记状况</li></a>
            head = strip(heading)
            if re.match(r"第.部分", head):
                part, volume = head, None
            elif re.match(r"第.{1,2}卷", head):
                volume = head
            continue
        href, text = m.group(2), strip(m.group(3))
        stem = href.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if re.fullmatch(r"[AB]\d{4}[a-z]?", stem) and stem not in out:
            out[stem] = {"title": text, "part": part, "volume": volume}
    return out


# ------------------------------------------------------------------ the source


class CensusFlows(Source):
    info = SourceInfo(
        id="census",
        title="全国人口普查：省际人口流向（第七次 2020、第六次 2010）",
        publisher="国家统计局（《中国人口普查年鉴-2020》《中国2010年人口普查资料》网络版）",
        homepage="https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/indexch.htm",
        license="政府公开统计资料",
        description="31 个省级行政区之间的人口流向矩阵：①按现住地和户口登记地在外省分的人口（表 7-3，全部人口，存量）；"
        "②按现住地和五年前常住地分的人口（长表表 7-7 / 7-8）；③按现住地和出生地分的人口（长表表 7-6 / 7-7）。"
        "长表为 10% 抽样户的登记数，未加权。各为 2020 年和 2010 年两期。"
        "数值照抄年鉴表格，空项不记为 0；每个矩阵都与表内合计行、合计列核对。",
        used_for=["人口流向：户籍地 → 现住地（存量）", "近五年迁移：五年前常住地 → 现住地", "终身迁移：出生地 → 现住地",
                  "2010 → 2020 变化"],
    )

    def fetch(self, force: bool = False) -> None:
        for year, yb in YEARBOOKS.items():
            for page in PAGES:
                self.download(yb["base"] + page, rel(year, page), force=force)
            files = [f for (y, _k), (f, _id, _t) in TABLES.items() if y == year] + list(POPULATION[year])
            for f in files:
                self.download(yb["base"] + f, rel(year, f), force=force, expect_binary=f.endswith(".xls"))

    def _grid(self, year: int, file: str) -> list[list]:
        return load_grid((self.raw_dir / rel(year, file)).read_bytes(), file)

    def process(self) -> dict:
        codes = province_codes()
        names = load_names()
        provinces = {c: names[c]["zh_full"] for c in sorted(set(codes.values()))}
        manifest = read_manifest(self.id)
        used, summary = [], {}
        for year, yb in YEARBOOKS.items():
            toc = parse_toc((self.raw_dir / rel(year, "left.htm")).read_bytes().decode("gb18030", errors="replace"))
            used += [rel(year, p) for p in PAGES]
            full_file, long_file = POPULATION[year]
            full, long = read_population(self._grid(year, full_file), codes), read_population(self._grid(year, long_file), codes)
            used += [rel(year, full_file), rel(year, long_file)]
            matrices = []
            for (y, kind), (file, table_id, title) in TABLES.items():
                if y != year:
                    continue
                r = rel(year, file)
                used.append(r)
                m = read_matrix(self._grid(year, file), codes)
                if title not in clean(m["title"]) or not m["title"].startswith(table_id):
                    raise ValueError(f"{r}: title {m['title']!r} is not {table_id} {title}")
                stem = file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                entry = toc.get(stem) or {}
                if title not in (entry.get("title") or ""):
                    raise ValueError(f"{r}: table of contents lists {entry.get('title')!r}")
                checks = check_matrix(m)
                info = manifest.get(r, {})
                out = {
                    "source": {
                        "title": m["title"], "table_id": table_id, "part": entry.get("part"), "volume": entry.get("volume"),
                        "yearbook": yb["title"], "publisher": "国家统计局", "url": yb["base"] + file,
                        "toc_url": yb["base"] + "left.htm", "file": f"census/{r}",
                        "retrieved": info.get("retrieved"), "sha256": info.get("sha256"), "bytes": info.get("bytes"),
                    },
                    "kind": kind,
                    "definition": DEFINITIONS[kind],
                    "census_moment": yb["moment"],
                    "unit": "人",
                    "sampled": kind in LONG_FORM,
                    "provinces": provinces,
                    "flows": [{"o": o, "d": d, "n": n} for (o, d), n in sorted(m["flows"].items())],
                    "published_totals": {
                        "by_destination": m["row_total"],  # the table's 合计 column
                        "by_origin": m["nation_row"],  # the 全国 row, origin columns
                        "national": m["nation_total"],
                        **({"within_province": m["within"], "national_within_province": m["nation_within"]}
                           if m["within"] else {}),
                        **({"abroad": m["abroad"], "national_abroad": m["nation_abroad"]} if m["abroad"] else {}),
                        **({"diagonal": m["diagonal"]} if m["diagonal"] else {}),  # own-province cells as printed
                    },
                    "checks": checks,
                }
                if kind in LONG_FORM:
                    out["sample"] = {
                        "design": "普查长表：按户抽取 10% 的户填报；表中为抽样登记数，未加权",
                        "scale": {d: round(full[d] / long[d], 5) for d in provinces},
                        "scale_national": round(full[NATION] / long[NATION], 5),
                        "scale_note": f"scale[d] = 全部人口数 / 长表人口数（{yb['title']} 两部分表 1-1 的人口数合计，现住地 d）；"
                                      "n × scale[d] 为推算的总体人数，仅为近似",
                        "scale_files": [f"census/{rel(year, full_file)}", f"census/{rel(year, long_file)}"],
                    }
                matrices.append(out)
                summary[f"{year}/{kind}"] = {
                    "table": m["title"], "pairs": len(m["flows"]), "sum_of_flows": checks["sum_of_flows"],
                    "ok": all(checks[k] for k in ("grand_total_ok", "rows_ok", "columns_ok"))
                    and checks.get("sex_split_ok", True),
                    "diagonal_total": checks["diagonal_total"],
                }
            payload = {
                "year": year, "census": yb["census"], "census_moment": yb["moment"],
                "processed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "yearbook": {"title": yb["title"], "url": yb["base"] + "indexch.htm", "toc_url": yb["base"] + "left.htm",
                             "note_url": yb["base"] + "html/note.htm"},
                "matrices": matrices,
            }
            atomic_write_text(OUT / f"flows_{year}.json", json.dumps(payload, ensure_ascii=False, indent=1))
            print(f"    → {Path('data/interim/census') / f'flows_{year}.json'}")
        return {"vintage": "第七次（2020）、第六次（2010）全国人口普查", "matrices": summary, "_files": sorted(set(used))}
