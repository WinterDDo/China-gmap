"""HTML → plain text, element extraction and media links, with the standard library only.

to_text() keeps the reading order and turns block elements (p, div, br, li, tr, h1–h6, table) into line breaks and
table cells into " | ", so a bulletin's sentences stay on their own lines and table rows never run into prose.
"""

from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tbody", "section", "article",
         "ul", "ol", "dd", "dt", "blockquote", "hr", "center", "pre"}
CELL = {"td", "th"}
SKIP = {"script", "style", "noscript", "template", "head", "title", "iframe", "object"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".wps", ".et", ".ofd", ".zip", ".rar", ".7z", ".txt", ".csv")
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff")


_WRAP_CJK = re.compile(r"(?<=[\u3000-\u9fff\uff00-\uffef])[ \t\r]*\n\s*(?=[\u3000-\u9fff\uff00-\uffef])")


def flow(data: str) -> str:
    """Line breaks in the HTML source are whitespace: none between Chinese characters, a space elsewhere."""
    return re.sub(r"\s*\n\s*", " ", _WRAP_CJK.sub("", data))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")
        elif tag in CELL:
            self.parts.append(" | ")

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(flow(data))


def to_text(html: str) -> str:
    """Readable text of an HTML fragment: one line per block, spaces collapsed, blank lines dropped."""
    p = _Text()
    p.feed(html or "")
    p.close()
    lines = []
    for line in "".join(p.parts).split("\n"):
        line = re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip(" |")
        line = line.strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


class _Element(HTMLParser):
    """Finds the first element with a given id (or class token) and records the source span of its content."""

    def __init__(self, id_: str | None, cls: str | None):
        super().__init__(convert_charrefs=False)
        self.id_, self.cls = id_, cls
        self.depth = 0  # >0 while inside the target element
        self.tag: str | None = None
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None

    def _hit(self, attrs) -> bool:
        a = dict(attrs)
        if self.id_ is not None and a.get("id") == self.id_:
            return True
        return self.cls is not None and self.cls in (a.get("class") or "").split()

    def handle_starttag(self, tag, attrs):
        if self.end is not None:
            return
        if self.depth == 0:
            if self._hit(attrs) and tag not in VOID:
                self.tag, self.depth = tag, 1
                line, col = self.getpos()
                self.start = (line, col + len(self.get_starttag_text() or ""))
        elif tag == self.tag:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth and tag == self.tag:
            self.depth -= 1
            if self.depth == 0:
                self.end = self.getpos()


def _offset(text: str, pos: tuple[int, int]) -> int:
    line, col = pos
    idx = 0
    for _ in range(line - 1):
        idx = text.index("\n", idx) + 1
    return idx + col


def element_html(html: str, *, id_: str | None = None, cls: str | None = None) -> str | None:
    """Inner HTML of the first element with id `id_` (or class token `cls`); nested same-name tags are balanced.

    An element left open at the end of the document runs to the end."""
    p = _Element(id_, cls)
    try:
        p.feed(html)
        p.close()
    except AssertionError:  # malformed markup the parser gives up on
        pass
    if p.start is None:
        return None
    a = _offset(html, p.start)
    b = _offset(html, p.end) if p.end else len(html)
    return html[a:b]


class _Media(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, link text)
        self._a: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("original")
            if src:
                self.images.append(src.strip())
        elif tag == "a" and a.get("href"):
            self._href, self._a = a["href"].strip(), []

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        if self._a is not None:
            self._a.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._a or []).strip()))
            self._href, self._a = None, None


def unwrap_viewer(url: str) -> str:
    """The document behind an online viewer link (pdf.js "viewer.html?file=/atm/7/x.pdf") – else `url` itself."""
    split = urlsplit(url)
    if "viewer" in split.path.lower():
        f = (parse_qs(split.query).get("file") or [""])[0]
        if f and f.split("?")[0].lower().endswith(DOC_EXT):
            return urljoin(url, f)
    return url


def _is_doc(url: str) -> bool:
    path = url.split("?")[0].split("#")[0].lower()
    if path.endswith(DOC_EXT):
        return True
    q = _html.unescape(url).lower()  # download?fileName=xxx.pdf
    return bool(re.search(r"(?:filename|file|name)=[^&]*\.(?:pdf|docx?|xlsx?|wps|ofd)(?:&|$)", q))


def media(html: str, base_url: str | None = None) -> dict[str, list[str]]:
    """Absolute URLs of the images and of the attached documents (pdf/doc/xls/…) linked in an HTML fragment."""
    p = _Media()
    p.feed(html or "")
    p.close()
    absolute = (lambda u: urljoin(base_url, u)) if base_url else (lambda u: u)
    images, docs = [], []
    for src in p.images:
        if src.startswith("data:"):
            continue
        u = absolute(src)
        if u not in images:
            images.append(u)
    for href, _text in p.links:
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        u = unwrap_viewer(absolute(href))
        if _is_doc(u) and u not in docs:
            docs.append(u)
        elif u.split("?")[0].lower().endswith(IMG_EXT) and u not in images:
            images.append(u)
    return {"images": images, "attachments": docs}


class _Tables(HTMLParser):
    """Rows of every <table>: [[(text, colspan, rowspan), …], …] per table (nested tables are flattened)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, int, int]]]] = []
        self.depth = 0
        self.row: list[tuple[str, int, int]] | None = None
        self.cell: list[str] | None = None
        self.spans = (1, 1)
        self.skip = 0

    @staticmethod
    def _span(attrs, name: str) -> int:
        v = dict(attrs).get(name) or "1"
        m = re.match(r"\s*(\d+)", v)
        return max(1, min(int(m.group(1)), 1000)) if m else 1

    def _end_cell(self):
        if self.cell is not None and self.row is not None:
            self.row.append((re.sub(r"\s+", " ", "".join(self.cell)).strip(), *self.spans))
        self.cell = None

    def _end_row(self):
        self._end_cell()
        if self.row is not None and self.tables:
            self.tables[-1].append(self.row)
        self.row = None

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.tables.append([])
        elif tag == "tr" and self.depth:
            self._end_row()
            self.row = []
        elif tag in CELL and self.depth:
            self._end_cell()
            if self.row is None:
                self.row = []
            self.cell = []
            self.spans = (self._span(attrs, "colspan"), self._span(attrs, "rowspan"))
        elif tag == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in CELL:
            self._end_cell()
        elif tag == "tr":
            self._end_row()
        elif tag == "table" and self.depth:
            if self.depth == 1:
                self._end_row()
            self.depth -= 1

    def handle_data(self, data):
        if self.cell is not None and not self.skip:
            self.cell.append(data)


def table_grids(html: str) -> list[list[list[str | None]]]:
    """Every table of `html` as a rectangular grid: row and column spans are laid out as in a spreadsheet, the text
    sits in the top-left cell of a merged block and the rest of the block is None (empty cells are "")."""
    p = _Tables()
    p.feed(html or "")
    p.close()
    p._end_row()
    grids = []
    for rows in p.tables:
        taken: dict[tuple[int, int], str | None] = {}
        for r, row in enumerate(rows):
            c = 0
            for text, colspan, rowspan in row:
                while (r, c) in taken:
                    c += 1
                for dr in range(rowspan):
                    for dc in range(colspan):
                        taken[r + dr, c + dc] = text if dr == dc == 0 else None
                c += colspan
        n_rows = max((r for r, _ in taken), default=-1) + 1
        n_cols = max((c for _, c in taken), default=-1) + 1
        grids.append([[taken.get((r, c)) for c in range(n_cols)] for r in range(n_rows)])
    return grids
