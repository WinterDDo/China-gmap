"""The owner's local collection of bulletins (tools/local_fetch/fetch_bulletins.py) → bulletin records.

The collector runs on the owner's own computer (government sites and search engines are not reachable from the
build machine) and produces jiangshan_bulletins_<date>.zip: out/<year>/<code>/ with the article page (page.html,
page_2.html …), its attachments (att_01.pdf …), images (img_001.png …), files already known from tjcn.org
(known_001.png …) and a manifest.json (url, final_url, fetched_at, http status, sha256, title, query, engine).

Put the zip (one or several) into data/raw/local_bulletins/. fetch() downloads nothing: it records each zip's sha256
in this source's manifest and unpacks it to data/raw/local_bulletins/unpacked/<zip name>/, keeping only entries of the
expected shape (out/<year>/<code>/<file name chosen by the collector>) and refusing absolute paths, "..", links and
oversized members. The files are data: they are read as bytes, never executed or opened by other programs.

process(): one record per collected (code, year) in the shared format of parse/records.py, from the official page
itself: the text of the article's content block (the same heuristic the collector used to choose its images), or,
when the page has no text, the text of a .docx attachment (stdlib) or a .pdf attachment (only if the optional pypdf
package is installed). Records are saved as source "local_bulletins" and merged with tjcn.org's into
data/interim/bulletins/<year>.json and coverage.csv, preferring the better record for each code and year.
"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..core import fetch
from ..core.paths import RAW, ROOT
from ..core.source import Source, SourceInfo
from ..core.store import atomic_write_text
from ..parse import records
from ..parse.places import PlaceMatcher, bulletin_units

TOOL = ROOT / "tools" / "local_fetch" / "fetch_bulletins.py"
MEMBER = re.compile(r"out/(20\d\d)/(\d{6})/([a-z]+(?:_\d+)?\.[a-z0-9]+)")  # what the collector writes
MAX_MEMBER = 80 * 1024 * 1024
MAX_XML = 50 * 1024 * 1024


def _tool():
    """The collector module, for its content-block heuristic (it is standard-library only and has no side effects)."""
    spec = importlib.util.spec_from_file_location("jiangshan_fetch_bulletins", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def safe_members(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Members shaped like the collector's output; anything else (absolute paths, "..", odd names, links, huge
    files) is skipped."""
    out = []
    for info in z.infolist():
        name = info.filename
        if info.is_dir() or name == "out/summary.csv":
            continue
        if not MEMBER.fullmatch(name) or info.file_size > MAX_MEMBER:
            print(f"    ! skipped zip member {name!r}")
            continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000:  # a symlink
            print(f"    ! skipped symlink {name!r}")
            continue
        out.append(info)
    return out


def docx_text(path: Path) -> str:
    """Paragraph text of a .docx (word/document.xml), read with regular expressions – no XML entity expansion."""
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_XML:
                return ""
            xml = z.read(info).decode("utf-8", errors="replace")
    except (KeyError, zipfile.BadZipFile, OSError):
        return ""
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        cells = re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", p, re.S)
        line = html.unescape("".join(cells)).strip()
        if line:
            paras.append(line)
    return "\n".join(paras)


def pdf_text(path: Path) -> str:
    """Text of a .pdf if the optional pypdf package is installed, else ""."""
    try:
        from pypdf import PdfReader  # optional
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:80])
    except Exception as exc:  # noqa: BLE001 - a broken PDF is just unreadable data
        print(f"    ! {path.name}: {exc}")
        return ""


_BUREAU = re.compile(r"(?:来源|发布机构|发布单位|信息来源)[:：]\s*([一-鿿（）()]{2,30}?(?:统计局|调查队|人民政府|政府办公室|"
                     r"政府办公厅|发展和改革委员会))")
_DATE = re.compile(r"(?:发布时间|发布日期|时间|日期)[:：]\s*(20\d\d[-/年.]\d{1,2}[-/月.]\d{1,2})")


def page_meta(text: str) -> dict:
    """Bureau and posting date as printed on a government page ("来源：XX市统计局", "发布时间：2025-03-20")."""
    b = _BUREAU.search(text)
    d = _DATE.search(text)
    date = None
    if d:
        y, m, dd = re.split(r"[-/年.月]", d[1])[:3]
        date = f"{y}-{int(m):02d}-{int(dd):02d}"
    return {"bureau": b[1] if b else None, "published": date}


class LocalBulletins(Source):
    info = SourceInfo(
        id="local_bulletins",
        title="国民经济和社会发展统计公报（2024–2025 年及缺漏年份；各地统计局官方网站，本地采集）",
        publisher="国家统计局；各省、自治区、直辖市统计局；各市（州、盟）统计局（以各页面所注发布机关为准）",
        homepage="https://www.stats.gov.cn/",
        license="政府公开统计资料（统计公报为各级统计局依法公开发布的政府信息）",
        description="项目负责人在中国大陆网络环境下，用本项目的本地采集脚本（tools/local_fetch）经必应/百度检索，"
        "从各地统计局或政府官方网站（gov.cn）下载的统计公报原文页面及其附件，每个文件记录原网址、下载时间与 sha256。"
        "按与中国统计信息网转载件相同的规则逐句提取指标并保留原句；图片不做识别，缺失的数值保持为空。",
        used_for=["城市档案：2024、2025 年经济与人口指标（附原句出处）", "补齐中国统计信息网未转载或只有图片的年份"],
    )

    @property
    def unpacked(self) -> Path:
        return self.raw_dir / "unpacked"

    # -------------------------------------------------- fetch: register and unpack the owner's zips

    def fetch(self, force: bool = False) -> None:
        zips = sorted(self.raw_dir.glob("jiangshan_bulletins_*.zip"))
        if not zips:
            print(f"    no jiangshan_bulletins_*.zip in {self.raw_dir} (run tools/local_fetch on a computer in mainland "
                  "China and copy the zip here); nothing to do")
            return
        manifest = fetch.read_manifest(self.id)
        for zp in zips:
            sha = hashlib.sha256(zp.read_bytes()).hexdigest()
            dest = self.unpacked / zp.stem
            marker = dest / ".sha256"
            if marker.exists() and marker.read_text().strip() == sha and not force:
                continue
            n = 0
            with zipfile.ZipFile(zp) as z:
                for info in safe_members(z):
                    target = dest / info.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src:
                        data = src.read(MAX_MEMBER + 1)
                    if len(data) > MAX_MEMBER:
                        continue
                    target.write_bytes(data)
                    n += 1
            atomic_write_text(marker, sha)
            manifest[zp.name] = {"url": f"local:{zp.name}", "sha256": sha, "bytes": zp.stat().st_size,
                                 "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "note": "collected by tools/local_fetch/fetch_bulletins.py on the owner's computer; "
                                         "per-file URLs and sha256 in out/<year>/<code>/manifest.json"}
            print(f"    {zp.name}: {n} files unpacked")
        atomic_write_text(fetch.manifest_path(self.id), json.dumps(manifest, indent=2, sort_keys=True))

    # -------------------------------------------------- process

    def folders(self) -> dict[tuple[str, int], Path]:
        """(code, year) → the newest collected folder that finished ("done") or, failing that, any folder."""
        best: dict[tuple[str, int], tuple[tuple, Path]] = {}
        roots = [p for p in sorted(self.unpacked.glob("*/out"))] if self.unpacked.exists() else []
        if (self.raw_dir / "out").is_dir():
            roots.append(self.raw_dir / "out")
        for root in roots:
            for mf in root.glob("20[0-9][0-9]/[0-9][0-9][0-9][0-9][0-9][0-9]/manifest.json"):
                try:
                    m = json.loads(mf.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                key = (mf.parent.name, int(mf.parent.parent.name))
                score = (m.get("status") == "done", m.get("finished_at") or "")
                if key not in best or score > best[key][0]:
                    best[key] = (score, mf.parent)
        return {k: v[1] for k, v in best.items()}

    def read_folder(self, folder: Path, code: str, year: int, matcher: PlaceMatcher, tool) -> dict:
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        base = {"code": code, "name": matcher.label(code), "year": year, "source": self.id}
        rel = lambda p: (folder / p).relative_to(RAW).as_posix()  # noqa: E731
        files = [f for f in m.get("files", []) if f.get("path") and (folder / f["path"]).exists()]
        media = {"images": [f["final_url"] or f["url"] for f in files if f["role"] in ("image", "known")
                            and not f["path"].endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".wps", ".ofd"))],
                 "attachments": [f["final_url"] or f["url"] for f in files if f["role"] == "attachment"
                                 or (f["role"] == "known" and f["path"].endswith((".pdf", ".doc", ".docx", ".xls",
                                                                                  ".xlsx", ".wps", ".ofd")))]}
        pages = [f for f in files if f["role"] in ("page", "subpage")]
        if m.get("status") != "done" and not files:
            return records.missing_record(base, note=f"本地采集：{m.get('status')}")
        texts, title, meta = [], m.get("page_title") or (m.get("chosen") or {}).get("title"), {}
        for f in pages:
            raw = (folder / f["path"]).read_bytes()
            page = tool.decode_page(raw, f.get("content_type") or "")
            art = tool.article_text(page)
            texts.append(art["text"])
            if f["role"] == "page":
                meta = page_meta(tool.node_text(tool.parse_tree(page).root))
        text = "\n".join(texts)
        used = [rel(f["path"]) for f in pages]
        if records.classify(text, [], []) != "text":
            for f in files:
                if f["role"] not in ("attachment", "known"):
                    continue
                p = folder / f["path"]
                doc = docx_text(p) if p.suffix == ".docx" else pdf_text(p) if p.suffix == ".pdf" else ""
                if records.classify(doc, [], []) == "text":
                    text, used = doc, used + [rel(f["path"])]
                    break
        page_url = next((f.get("final_url") or f["url"] for f in pages if f["role"] == "page"), None)
        rec = records.build_record(
            base, url=page_url or (m.get("chosen") or {}).get("url"), title=title, bureau=meta.get("bureau"),
            published=meta.get("published"), text=text, media=media,
            files=used + [rel("manifest.json")], names=matcher.names)
        rec["local"] = {"engine": m.get("engine"), "query": m.get("query"), "status": m.get("status"),
                        "fetched_at": next((f.get("fetched_at") for f in pages), None),
                        "page_title_match": m.get("page_title_match"),
                        "folder": folder.relative_to(RAW).as_posix()}
        return rec

    def process(self) -> dict:
        matcher = PlaceMatcher()
        units = set(bulletin_units(matcher.names))
        tool = _tool()
        by_year: dict[int, list[dict]] = {}
        for (code, year), folder in sorted(self.folders().items()):
            if code not in units:
                continue
            by_year.setdefault(year, []).append(self.read_folder(folder, code, year, matcher, tool))
        records.save_source_years(self.id, by_year)
        summary = records.write_outputs(matcher)
        return {
            "vintage": "统计公报（本地采集）" + (f" {min(by_year)}–{max(by_year)}" if by_year else "：尚无"),
            "years": sorted(by_year),
            "coverage": {str(y): records.status_counts(r) for y, r in sorted(by_year.items())},
            "outputs": summary,
            "_files": sorted(p.name for p in self.raw_dir.glob("jiangshan_bulletins_*.zip")),
        }
