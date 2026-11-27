"""国民经济和社会发展统计公报 2020–2023 of the nation, every province and every prefecture-level unit, as republished
by 中国统计信息网 (tjcn.org), parsed into fields that each keep their exact source sentence.

tjcn.org republishes each bureau's bulletin and names the original publisher (页头 "时间：… 来源：XX市统计局"). It has
one index page per bulletin year (YEAR_INDEX: a table, one row per province: the province's own bulletin first, then
its cities') and one paginated list per province folder (/tjgb/03hb/, index_2.html, … newest first). Nothing for
2024 or later has been posted; those years come from the owner's local collection (sources/local_bulletins.py).

fetch():
1. the four year indexes;
2. every province folder's list pages back to the first page holding only bulletins older than YEARS[0] – these
   catch bulletins posted after the index was compiled, or missing from it (each list hit is matched by its title);
3. every bulletin page of the indexes and lists for YEARS, with all its sub-pages (xxx_2.html …).
One request at a time, DELAY seconds apart; everything is cached under data/raw/tjcn_bulletins/ with the usual
manifest (url, sha256, bytes, retrieved). Pages that fail (HTTP 4xx) are listed in fetch_errors.json.

process(): for each (code, year) of bulletin_units() × YEARS, one record (see parse/records.py): the tjcn URL,
title, publishing bureau, publish time, status – "text"; "image_only" (the body is only <img> of the bureau's own
host, whose URLs are kept; never OCR'd); "attachment_only" (only links to PDF/Word files, kept); "missing" (tjcn has
no such bulletin) – and the fields parsed by parse/bulletin.py, each {value, unit, quote}. Writes
data/interim/bulletins/{year}.json (merged with any local records), coverage.csv, and the 2023 cross-check against
the chinaciv compilation (sources/city_stats.py) as crosscheck_2023.csv / .json.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
from pathlib import Path

from ..core.paths import RAW
from ..core.source import Source, SourceInfo
from ..core.store import atomic_write_text
from ..parse import htmltext, records
from ..parse.places import TJCN_FOLDERS, PlaceMatcher, bulletin_units, clean

BASE = "http://www.tjcn.org"  # plain HTTP only: tjcn resets HTTPS connections
YEAR_INDEX = {
    2020: "/tjgbsy/nd/36541.html",
    2021: "/tjgbsy/nd/36944.html",
    2022: "/tjgbsy/nd/37292.html",
    2023: "/tjgbsy/nd/37660.html",
}
YEARS = tuple(sorted(YEAR_INDEX))
DELAY = 1.0  # seconds between two requests to tjcn
MAX_LIST_PAGES = 40  # safety stop per province folder
ENCODING = "gb18030"  # pages declare gb2312; gb18030 is its superset (and GBK's)

_ARTICLE = re.compile(r'href="(/tjgb/(\d\d[a-z]+)/(\d+)\.html)"[^>]*>([^<]*)</a>')
_LIST_ITEM = re.compile(r'<a href="(/tjgb/(\d\d[a-z]+)/(\d+)\.html)" title="([^"]*)"')
_LAST_PAGE = re.compile(r'href="/tjgb/\d\d[a-z]+/index_(\d+)\.html">尾页</a>')
_TITLE = re.compile(r"(20\d\d)年(?:度)?国民经济和社会发展统计公报")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def decode(raw: bytes) -> str:
    return raw.decode(ENCODING, errors="replace")


# ------------------------------------------------------------------ page parsers (pure)


def parse_year_index(html: str) -> list[dict]:
    """Links of a year index, in page order: {href, folder, id, text, row_head, head_text}.

    Each table row starts with its province's own bulletin (the row head); the first row is 中国 followed by the
    four municipalities."""
    out = []
    for row in _ROW.findall(html):
        links = _ARTICLE.findall(row)
        if not links:
            continue
        head_text = clean(links[0][3])
        for i, (href, folder, aid, text) in enumerate(links):
            out.append({"href": href, "folder": folder, "id": aid, "text": clean(text), "row_head": i == 0,
                        "head_text": head_text})
    return out


def parse_list_page(html: str) -> tuple[list[dict], int]:
    """Entries of one province list page ({href, folder, id, title}) and the number of the last page."""
    items = [{"href": h, "folder": f, "id": i, "title": clean(t)} for h, f, i, t in _LIST_ITEM.findall(html)]
    m = _LAST_PAGE.search(html)
    return items, int(m[1]) if m else 1


def title_year(title: str) -> int | None:
    m = _TITLE.search(clean(title))
    return int(m[1]) if m else None


def subpage_hrefs(html: str, href: str) -> list[str]:
    """Hrefs of the further pages of a multi-page bulletin (…/37692_2.html, _3 …), in order."""
    stem = re.escape(href[: -len(".html")])
    nums = sorted({int(n) for n in re.findall(rf'href="(?:{re.escape(BASE)})?{stem}_(\d+)\.html"', html)})
    return [f"{href[:-len('.html')]}_{n}.html" for n in nums if n >= 2]


def parse_page(html: str) -> dict:
    """Header and body of one bulletin page: {title, published, bureau, body_html}."""
    title = re.search(r"<h1>(.*?)</h1>", html, re.S)
    info = re.search(r'class="info_text">(.*?)</td>', html, re.S)
    info_text = htmltext.to_text(info[1]) if info else ""
    published = re.search(r"时间：\s*([0-9]{4}-[0-9]{2}-[0-9]{2}(?: [0-9:]{5,8})?)", info_text)
    bureau = re.search(r"来源：\s*(\S*)", info_text)
    return {
        "title": clean(htmltext.to_text(title[1])) if title else None,
        "published": published[1] if published else None,
        "bureau": (bureau[1].strip() or None) if bureau else None,
        "body_html": htmltext.element_html(html, id_="text") or "",
    }


# ------------------------------------------------------------------ link → code


def match_index(links: list[dict], matcher: PlaceMatcher) -> tuple[dict[str, dict], list[dict]]:
    """{code: link} for a year index, plus the links that matched nothing (e.g. 新疆生产建设兵团)."""
    matched: dict[str, dict] = {}
    unmatched: list[dict] = []
    head = None
    for link in links:
        if link["row_head"]:
            head = matcher.province(link["text"])
            code = head
        elif head == "100000":  # first row: the municipalities
            code = matcher.province(link["text"])
        else:
            code = matcher.city(link["text"], head) if head else None
        if code and code not in matched:
            matched[code] = link
        elif code:
            unmatched.append({**link, "reason": f"duplicate of {matched[code]['href']}"})
        else:
            unmatched.append({**link, "reason": "no such unit in names.json"})
    return matched, unmatched


def match_list_item(item: dict, matcher: PlaceMatcher) -> tuple[str | None, int | None]:
    """(code, year) of a province list entry, from its title; (None, year) if the name is not ours."""
    year = title_year(item["title"])
    province = TJCN_FOLDERS.get(item["folder"])
    if year is None or province is None:
        return None, year
    title = item["title"]
    name = title[: _TITLE.search(title).start()]
    if not name:  # "2023年石家庄市国民经济…" form
        name = re.sub(r"^20\d\d年(?:度)?", "", title).split("国民经济")[0]
    return matcher.find_in(name, province), year


# ------------------------------------------------------------------ the source


class TjcnBulletins(Source):
    info = SourceInfo(
        id="tjcn_bulletins",
        title="国民经济和社会发展统计公报（2020–2023 年；全国、各省级与地级行政区；中国统计信息网转载）",
        publisher="国家统计局；各省、自治区、直辖市统计局；各市（州、盟）统计局（各页“来源”所注的原发布机关）。"
        "经中国统计信息网（tjcn.org）转载",
        homepage="http://www.tjcn.org/tjgbsy/",
        license="政府公开统计资料（统计公报为各级统计局依法公开发布的政府信息）",
        description="全国、31 个省级行政区与 333 个地级行政区 2020–2023 年的《国民经济和社会发展统计公报》全文，"
        "取自中国统计信息网按年度整理的公报索引及各省公报列表，每篇注明原发布统计局与发布时间。"
        "从正文中逐句提取地区生产总值、三次产业增加值、经济增速、年末常住人口、城镇化率、居民人均可支配收入、"
        "一般公共预算收入和社会消费品零售总额，每个数值都保留原句；公报只有图片或附件的，只记录图片与附件地址，"
        "不做识别。缺失的数值保持为空，不以其他年份替代。",
        used_for=["城市档案：历年经济与人口指标（附原句出处）", "与第一阶段 chinaciv 汇编的 2023 年数值互校"],
    )

    def __init__(self):
        self._last = 0.0  # time.monotonic() of the last request to tjcn
        self._errors: dict[str, dict] = {}  # rel path → error of this fetch run

    # -------------------------------------------------- polite cached GET

    def _get(self, path: str, rel: str, *, force: bool = False) -> Path | None:
        """Cached download of BASE+path → raw/<id>/<rel>; waits DELAY s between network requests. None on HTTP 4xx."""
        dest = self.raw_dir / rel
        if dest.exists() and not force:
            return dest
        wait = self._last + DELAY - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return self.download(BASE + path, rel, force=force)
        except urllib.error.HTTPError as exc:
            exc.close()
            self._errors[rel] = {"url": BASE + path, "error": f"HTTP {exc.code}"}
            print(f"      ! HTTP {exc.code}: {BASE + path}")
            return None
        finally:
            self._last = time.monotonic()

    def _read(self, rel: str) -> str:
        return decode((self.raw_dir / rel).read_bytes())

    @staticmethod
    def page_rel(href: str) -> str:
        """/tjgb/03hb/37692.html → pages/03hb/37692.html (sub-pages keep their _2 suffix)."""
        return "pages/" + href.removeprefix("/tjgb/")

    # -------------------------------------------------- fetch

    def fetch(self, force: bool = False) -> None:
        self._errors: dict[str, dict] = {}
        matcher = PlaceMatcher()
        hrefs: dict[str, None] = {}  # bulletin pages to get, in order
        for year, path in YEAR_INDEX.items():
            p = self._get(path, f"index/{year}.html", force=force)
            for link in parse_year_index(self._read(p.relative_to(self.raw_dir).as_posix())):
                hrefs[link["href"]] = None
        for item in self._crawl_lists(force):
            code, year = match_list_item(item, matcher)
            if code and year in YEAR_INDEX:
                hrefs[item["href"]] = None
        print(f"    {len(hrefs)} bulletin pages listed")
        for n, href in enumerate(hrefs, 1):
            rel = self.page_rel(href)
            p = self._get(href, rel, force=force)
            if p is None:
                continue
            for sub in subpage_hrefs(self._read(rel), href):
                self._get(sub, self.page_rel(sub), force=force)
            if n % 100 == 0:
                print(f"    … {n}/{len(hrefs)} bulletin pages")
        errors_file = self.raw_dir / "fetch_errors.json"
        old = json.loads(errors_file.read_text()) if errors_file.exists() else {}
        old.update(self._errors)
        for rel in [r for r in old if (self.raw_dir / r).exists()]:
            old.pop(rel)  # fixed since
        atomic_write_text(errors_file, json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True))

    def _crawl_lists(self, force: bool = False) -> list[dict]:
        """Entries of every province folder's list pages, down to the first page older than YEARS[0]."""
        items: list[dict] = []
        for folder in TJCN_FOLDERS:
            last = None
            for n in range(1, MAX_LIST_PAGES + 1):
                rel = f"list/{folder}_{n}.html"
                path = f"/tjgb/{folder}/" if n == 1 else f"/tjgb/{folder}/index_{n}.html"
                if self.offline and not (self.raw_dir / rel).exists():
                    break  # --offline: use the list pages that are cached
                p = self._get(path, rel, force=force)
                if p is None:
                    break
                page, last = parse_list_page(self._read(rel))
                items += page
                years = [y for y in (title_year(i["title"]) for i in page) if y]
                if not page or (years and max(years) < YEARS[0]) or n >= last:
                    break
        return items

    # -------------------------------------------------- process

    def links(self) -> tuple[dict[int, dict[str, dict]], dict[int, list[dict]]]:
        """{year: {code: link}} from the indexes, completed from the list pages; and the unmatched index links."""
        matcher = PlaceMatcher()
        by_year: dict[int, dict[str, dict]] = {}
        unmatched: dict[int, list[dict]] = {}
        for year in YEARS:
            links = parse_year_index(self._read(f"index/{year}.html"))
            by_year[year], unmatched[year] = match_index(links, matcher)
            for link in by_year[year].values():
                link["via"] = "index"
        for rel in sorted((self.raw_dir / "list").glob("*.html")):
            page, _ = parse_list_page(decode(rel.read_bytes()))
            for item in page:
                code, year = match_list_item(item, matcher)
                if not code or year not in by_year:
                    continue
                known = by_year[year].get(code)
                if known is None:
                    by_year[year][code] = {**item, "text": item["title"], "via": "list"}
                elif known["href"] != item["href"]:
                    alts = known.setdefault("alternates", [])
                    if item["href"] not in alts:
                        alts.append(item["href"])
        return by_year, unmatched

    def read_bulletin(self, href: str) -> dict | None:
        """Header of page 1 plus the bodies of all cached pages, or None if page 1 is not cached."""
        rel = self.page_rel(href)
        if not (self.raw_dir / rel).exists():
            return None
        html = self._read(rel)
        page = parse_page(html)
        rels = [rel]
        bodies = [page["body_html"]]
        for sub in subpage_hrefs(html, href):
            srel = self.page_rel(sub)
            if (self.raw_dir / srel).exists():
                rels.append(srel)
                bodies.append(parse_page(self._read(srel))["body_html"])
            else:
                page.setdefault("missing_pages", []).append(BASE + sub)
        page["body_html"] = "\n".join(bodies)
        page["files"] = rels
        return page

    def process(self) -> dict:
        matcher = PlaceMatcher()
        by_year, unmatched = self.links()
        units = bulletin_units(matcher.names)
        out_years: dict[int, list[dict]] = {}
        files = [f"index/{y}.html" for y in YEARS] + sorted(
            p.relative_to(self.raw_dir).as_posix() for p in (self.raw_dir / "list").glob("*.html"))
        for year in YEARS:
            recs = []
            for code in units:
                link = by_year[year].get(code)
                base = {"code": code, "name": matcher.label(code), "year": year, "source": self.id}
                if link is None:
                    recs.append(records.missing_record(base, note="tjcn.org 未转载该年公报"))
                    continue
                page = self.read_bulletin(link["href"])
                url = BASE + link["href"]
                if page is None:
                    recs.append(records.missing_record({**base, "url": url}, note="页面未下载（见 fetch_errors.json）"))
                    continue
                files += page["files"]
                rec = records.build_record(
                    base,
                    url=url,
                    title=page["title"],
                    bureau=page["bureau"],
                    published=page["published"],
                    body_html=page["body_html"],
                    base_url=url,
                    files=[f"{self.id}/{f}" for f in page["files"]],
                    names=matcher.names,
                )
                rec["tjcn"] = {"via": link["via"], "link_text": link["text"],
                               **({"alternates": [BASE + a for a in link["alternates"]]} if link.get("alternates") else {}),
                               **({"missing_pages": page["missing_pages"]} if page.get("missing_pages") else {})}
                recs.append(rec)
            out_years[year] = recs
        records.save_source_years(self.id, out_years)
        summary = records.write_outputs(matcher)
        cross = records.crosscheck_chinaciv(RAW / "city_stats", out_years.get(2023, []))
        return {
            "vintage": f"统计公报 {YEARS[0]}–{YEARS[-1]}（tjcn.org 转载）",
            "years": list(YEARS),
            "coverage": {str(y): records.status_counts(out_years[y]) for y in YEARS},
            "unmatched_links": {str(y): [{"text": u["text"], "href": BASE + u["href"], "reason": u["reason"]}
                                         for u in unmatched[y]] for y in YEARS},
            "outputs": summary,
            "crosscheck_2023": cross,
            "_files": sorted(set(files)),
        }
