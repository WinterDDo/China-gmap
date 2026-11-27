#!/usr/bin/env python3
"""江山图鉴 · 统计公报本地采集脚本（只用 Python 3.8+ 标准库）

为 targets.json 中的每一项（地区代码 + 年份）在搜索引擎上查找官方的《国民经济和社会发展统计公报》，下载文章页面
及其中的附件（PDF/Word/Excel/图片），保存到 out/<年份>/<代码>/，每个文件夹附 manifest.json（网址、最终网址、
下载时间、HTTP 状态、sha256、标题、搜索词、搜索引擎）。最后打包为 jiangshan_bulletins_<日期>.zip。

    python fetch_bulletins.py --dry-run          只打印搜索词，不联网
    python fetch_bulletins.py --limit 5          先试 5 项
    python fetch_bulletins.py                    全部（可随时 Ctrl+C 中断，再次运行会接着做）
    python fetch_bulletins.py --years 2025 --codes 130100 130200
    python fetch_bulletins.py --zip-only         只打包已下载的结果

下载的内容一律当作数据保存，脚本从不打开、执行或解压它们。用法详见同目录 README.md。
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import html
import http.client
import http.cookiejar
import json
import os
import random
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from html.parser import HTMLParser

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".wps", ".et", ".ofd", ".csv", ".txt")
IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff")
SAFE_EXT = set(DOC_EXT + IMG_EXT + (".html", ".htm"))
MAX_IMAGES = 80
MAX_ATTACHMENTS = 12
MAX_SUBPAGES = 15
MAX_BYTES = 60 * 1024 * 1024  # skip any single file larger than this
TIMEOUT = 30
REJECT_TITLE = re.compile(r"解读|图解|一图读懂|图说|新闻发布会|答记者问|问答|视频|直播|快讯|摘要|简析|分析|对比|排行|排名")
DECOR = re.compile(r"(?i)logo|icon|banner|qrcode|qr_?code|ewm|erweima|gzh|wza|jiucuo|zhaocuo|dzjg|gh\.png|share|weixin|wechat|"
                   r"weibo|arrow|bg[_\-.]|button|btn|print|close|search|top\.|blank\.gif|spacer|pixel|footer|header|nav")
CONTENT_HINT = re.compile(r"(?i)TRS_Editor|TRS_UEDITOR|trs_paper|article|content|zoom|detail|xwnr|main-?t?xt|con_?txt|"
                          r"news_?con|xxgk_?con|view|pages_content|wenzhang|zw|text|cont|bt_?content|Custom_UnionStyle")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def say(*parts) -> None:
    print(*parts, flush=True)


# =============================================================================== targets

def load_targets(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["targets"] if isinstance(data, dict) else data


def select_targets(targets: list, years=None, codes=None) -> list:
    out = []
    for t in targets:
        if years and int(t["year"]) not in years:
            continue
        if codes and t["code"] not in codes:
            continue
        out.append(t)
    return out


def queries_for(t: dict) -> list:
    """Search phrases, most specific first."""
    name, year = t["zh_full"], t["year"]
    return [f'"{name}{year}年国民经济和社会发展统计公报"',
            f'"{year}年{name}国民经济和社会发展统计公报"',
            f"{name} {year}年 国民经济和社会发展统计公报"]


# =============================================================================== title checks

def title_match(title: str, t: dict) -> str:
    """'strict' (the unit's name sits right next to the year), 'loose', or '' (not this bulletin)."""
    s = re.sub(r"\s+", "", html.unescape(title or ""))
    year = str(t["year"])
    names = t.get("names") or [t["zh_full"]]
    if "公报" not in s or f"{year}年" not in s or not any(n in s for n in names):
        return ""
    if REJECT_TITLE.search(s):
        return ""
    for m in re.finditer(year + "年", s):
        before = s[: m.start()].rstrip("（(《“\"'：:　 ")
        after = s[m.end():]
        if any(before.endswith(n) for n in names):
            return "strict"
        if (not before or before.endswith(("《", "关于"))) and any(after.startswith((n, "度" + n)) for n in names):
            return "strict"
    # a district/county bulletin (…区2024年, …县2024年) is never the city's
    if re.search(r"(?:区|县|旗|镇|乡|市)" + year + "年", s) and not any(n.endswith(("区", "市")) and (n + year) in s
                                                                    for n in names):
        return ""
    return "loose"


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def host_score(url: str, t: dict, any_host: bool) -> int:
    """3 = the hint host (where the unit published before), 2 = a gov.cn site, 1 = other (only with --any-host)."""
    h = host_of(url)
    hints = [x.lower() for x in ([t.get("hint_host")] + list(t.get("hint_hosts") or [])) if x]
    if h and any(h == x or h.endswith("." + x) for x in hints):
        return 3
    if h.endswith(".gov.cn") or h == "gov.cn":
        return 2
    return 1 if any_host else 0


def rank_results(results: list, t: dict, any_host: bool = False) -> list:
    """Acceptable results, best first: (score, result) with result = {url, title, …, match}."""
    ranked = []
    for r in results:
        m = title_match(r.get("title", ""), t)
        hs = host_score(r.get("url", ""), t, any_host)
        if not m or not hs:
            continue
        ranked.append((hs * 10 + (2 if m == "strict" else 0), dict(r, match=m, host_score=hs)))
    ranked.sort(key=lambda x: -x[0])
    return [r for _, r in ranked]


# =============================================================================== HTML helpers (data only)

class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []  # _Node and str (text), in document order


class _Tree(HTMLParser):
    """A forgiving element tree: enough to find the content block and its links."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
        self.cur = self.root
        self.skip = 0
        self.title = []
        self.in_title = False

    AUTOCLOSE = {"p", "li", "tr", "td", "th", "dt", "dd", "option"}

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == "title":
            self.in_title = True
        if tag in self.AUTOCLOSE and self.cur.tag == tag and self.cur.parent is not None:
            self.cur = self.cur.parent  # <p>a<p>b: the second <p> closes the first
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in self.VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        if tag not in self.SKIP:
            self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "title":
            self.in_title = False
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.cur.children.append(flow(data))


_WRAP_CJK = re.compile(r"(?<=[\u3000-\u9fff\uff00-\uffef])[ \t\r]*\n\s*(?=[\u3000-\u9fff\uff00-\uffef])")


def flow(data: str) -> str:
    """Line breaks in the HTML source are whitespace: none between Chinese characters, a space elsewhere."""
    return re.sub(r"\s*\n\s*", " ", _WRAP_CJK.sub("", data))


def parse_tree(page: str) -> _Tree:
    t = _Tree()
    try:
        t.feed(page)
        t.close()
    except Exception:  # noqa: BLE001 - malformed markup: keep what was parsed
        pass
    return t


def _walk(node):
    """Elements under `node` (itself included), pre-order, iteratively (malformed pages nest very deep)."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in reversed(n.children) if not isinstance(c, str))


def _stats(node, memo):
    """(chinese chars of text outside links, number of <img>) under `node`, memoised for every descendant."""
    if id(node) in memo:
        return memo[id(node)]
    for n in reversed(list(_walk(node))):  # children before parents
        own, imgs = 0, 1 if n.tag == "img" else 0
        for c in n.children:
            if isinstance(c, str):
                own += 0 if n.tag == "a" else len(re.findall(r"[\u4e00-\u9fff]", c))
            else:
                ct, ci = memo[id(c)]
                own += 0 if n.tag == "a" else ct
                imgs += ci
        memo[id(n)] = (own, imgs)
    return memo[id(node)]


BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "ul", "ol",
         "dd", "dt", "blockquote", "hr", "center", "pre"}


def node_text(node) -> str:
    """Plain text of an element in reading order: blocks become lines, table cells are joined with " | "."""
    parts = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, str):
            parts.append(n)
            continue
        if n.tag in BLOCK:
            parts.append("\n")
        elif n.tag in ("td", "th"):
            parts.append(" | ")
        stack.append("\n" if n.tag in BLOCK else "")
        stack.extend(reversed(n.children))
    lines = []
    for line in "".join(parts).split("\n"):
        line = re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip().strip("|").strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def article_text(page: str) -> dict:
    """{title, text, node}: the readable text of an article page's content block."""
    tree = parse_tree(page)
    node = content_node(tree)
    return {"title": re.sub(r"\s+", " ", "".join(tree.title)).strip(), "text": node_text(node)}


def content_node(tree: _Tree):
    """The element that holds the article: a known content container if one has real text or images, else the
    block with the most text that is not the whole page."""
    memo = {}
    total, _ = _stats(tree.root, memo)
    best, best_score = None, -1
    for n in _walk(tree.root):
        if n.tag not in ("div", "td", "article", "section", "main", "span", "font", "p", "table", "tbody"):
            continue
        txt, imgs = _stats(n, memo)
        key = " ".join(filter(None, [n.attrs.get("id"), n.attrs.get("class")]))
        hinted = bool(key and CONTENT_HINT.search(key))
        if txt < 30 and imgs == 0:
            continue
        if total and txt > 0.97 * total and not hinted:
            continue  # a wrapper of the whole page
        score = txt + 150 * imgs + (5000 if hinted and (txt >= 200 or imgs >= 1) else 0)
        # prefer the smallest hinted block that still holds nearly all of the article
        if score > best_score or (hinted and score >= best_score * 0.95 and best is not None and _inside(n, best)):
            best, best_score = n, score
    return best or tree.root


def _inside(n, other) -> bool:
    p = n.parent
    while p is not None:
        if p is other:
            return True
        p = p.parent
    return False


def unwrap_viewer(url: str) -> str:
    """The document behind an online viewer link (pdf.js "viewer.html?file=/atm/7/x.pdf") – else `url` itself."""
    split = urllib.parse.urlsplit(url)
    if "viewer" in split.path.lower():
        f = (urllib.parse.parse_qs(split.query).get("file") or [""])[0]
        if f and f.split("?")[0].lower().endswith(DOC_EXT):
            return urllib.parse.urljoin(url, f)
    return url


def _is_doc(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path.lower()
    if path.endswith(DOC_EXT):
        return True
    q = urllib.parse.unquote(urllib.parse.urlsplit(url).query).lower()
    return bool(re.search(r"(?:filename|file|name|path)=[^&]*\.(?:pdf|docx?|xlsx?|wps|ofd|et)(?:&|$)", q))


def extract_links(page: str, base_url: str) -> dict:
    """From an article page: its <title>, the content images, the attached documents and further pages.

    Images come from the content block only (logos, QR codes and icons are dropped); documents from anywhere in the
    page (attachments often sit just below the article)."""
    tree = parse_tree(page)
    node = content_node(tree)
    images, docs, pages = [], [], []

    def add(lst, u):
        if u and u not in lst:
            lst.append(u)

    for n in _walk(node):
        if n.tag == "img":
            src = n.attrs.get("src") or n.attrs.get("data-src") or n.attrs.get("original") or ""
            if not src or src.startswith("data:"):
                continue
            u = urllib.parse.urljoin(base_url, src.strip())
            if DECOR.search(urllib.parse.urlsplit(u).path):
                continue
            add(images, u)
    stem, ext = os.path.splitext(urllib.parse.urlsplit(base_url).path)
    for n in _walk(tree.root):
        if n.tag != "a":
            continue
        href = (n.attrs.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        u = unwrap_viewer(urllib.parse.urljoin(base_url, href))
        if urllib.parse.urlsplit(u).scheme not in ("http", "https"):
            continue
        path = urllib.parse.urlsplit(u).path
        if _is_doc(u):
            add(docs, u)
        elif path.lower().endswith(IMG_EXT) and _inside_or_is(n, node):
            add(images, u)
        elif stem and re.fullmatch(re.escape(stem) + r"_(\d{1,2})" + re.escape(ext), path) \
                and host_of(u) == host_of(base_url):
            add(pages, u)
    pages.sort(key=lambda u: int(re.search(r"_(\d+)\.[a-z]+$", u).group(1)) if re.search(r"_(\d+)\.[a-z]+$", u) else 0)
    title = re.sub(r"\s+", " ", "".join(tree.title)).strip()
    return {"title": title, "images": images[:MAX_IMAGES], "attachments": docs[:MAX_ATTACHMENTS],
            "pages": pages[:MAX_SUBPAGES]}


def _inside_or_is(n, node) -> bool:
    return n is node or _inside(n, node)


def decode_page(raw: bytes, content_type: str = "") -> str:
    """Bytes → text: charset from the header, then <meta>, then utf-8, then gb18030."""
    cands = []
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        cands.append(m.group(1))
    m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.I)
    if m:
        cands.append(m.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "gb18030"]
    for c in cands:
        c = c.lower()
        if c in ("gb2312", "gbk", "x-gbk"):
            c = "gb18030"
        try:
            return raw.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


# =============================================================================== search engines

def parse_bing(page: str) -> list:
    """Results of a cn.bing.com result page: [{url, title, snippet}]."""
    out = []
    starts = [m.start() for m in re.finditer(r'<li class="b_algo[^"]*"', page)]
    for a, b in zip(starts, starts[1:] + [len(page)]):
        block = page[a:b]
        m = re.search(r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S)
        if not m:
            continue
        url = bing_target(html.unescape(m.group(1)))
        title = re.sub(r"<[^>]+>", "", m.group(2))
        snip = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        out.append({"url": url, "title": html.unescape(title).strip(),
                    "snippet": html.unescape(re.sub(r"<[^>]+>", "", snip.group(1))).strip() if snip else ""})
    return out


def bing_target(url: str) -> str:
    """Undo Bing's click-tracking redirect (…/ck/a?…&u=a1<base64url>…)."""
    if "bing.com/ck/a" not in url:
        return url
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    u = (q.get("u") or [""])[0]
    if u.startswith("a1"):
        b = u[2:]
        try:
            return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return url
    return url


def parse_baidu(page: str) -> list:
    """Results of a www.baidu.com result page; the real URL is in the container's mu="" when Baidu gives it."""
    out = []
    heads = list(re.finditer(r'<div[^>]+class="[^"]*\bresult\b[^"]*"[^>]*>', page))
    for h, nxt in zip(heads, heads[1:] + [None]):
        attrs, block = h.group(0), page[h.end(): nxt.start() if nxt else len(page)]
        a = re.search(r"<h3[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S)
        if not a:
            continue
        mu = re.search(r'\bmu="([^"]+)"', attrs)
        url = html.unescape(mu.group(1)) if mu else html.unescape(a.group(1))
        title = html.unescape(re.sub(r"<[^>]+>", "", a.group(2))).strip()
        out.append({"url": url, "title": title, "snippet": "", "redirect": "baidu.com/link" in url})
    return out


def captcha_page(page: str) -> bool:
    return bool(re.search(r"b_captcha|captcha|安全验证|验证码|请输入验证|异常流量|unusual traffic", page[:20000], re.I))


# =============================================================================== HTTP

class Http:
    """One cookie-keeping opener, polite random delays, gzip handling and an http:// retry for broken TLS."""

    def __init__(self, delay=(2.0, 5.0), timeout=TIMEOUT):
        self.delay, self.timeout = delay, timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last = 0.0

    def pause(self):
        lo, hi = self.delay
        wait = self.last + random.uniform(lo, hi) - time.time()
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, referer: str | None = None, max_bytes: int = MAX_BYTES) -> dict:
        """GET → {url, final_url, status, content_type, body (bytes), error, fetched_at, tls}."""
        self.pause()
        res = {"url": url, "final_url": None, "status": None, "content_type": "", "body": b"", "error": None,
               "fetched_at": now_iso(), "tls": None}
        tries = [url]
        if url.startswith("https://"):
            tries.append("http://" + url[len("https://"):])
        for i, u in enumerate(tries):
            req = urllib.request.Request(u, headers={
                "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9", "Accept-Encoding": "gzip, deflate",
                **({"Referer": referer} if referer else {})})
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    body = r.read(max_bytes + 1)
                    res.update(final_url=r.geturl(), status=r.status,
                               content_type=r.headers.get("Content-Type") or "", error=None)
                    enc = (r.headers.get("Content-Encoding") or "").lower()
                    body = _decompress(body, enc)
                    if len(body) > max_bytes:
                        res.update(error=f"larger than {max_bytes // 1048576} MB, skipped", body=b"")
                    else:
                        res["body"] = body
                    res["tls"] = "http_fallback" if i else None
                    break
            except urllib.error.HTTPError as e:
                res.update(status=e.code, final_url=e.geturl(), error=f"HTTP {e.code}")
                e.close()
                break
            except (ssl.SSLError, ssl.CertificateError) as e:
                res["error"] = f"TLS: {e}"
                continue  # try plain http
            except urllib.error.URLError as e:
                reason = getattr(e, "reason", e)
                res["error"] = f"{type(reason).__name__}: {reason}"
                if isinstance(reason, ssl.SSLError):
                    continue
                break
            except (socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException, OSError) as e:
                res["error"] = f"{type(e).__name__}: {e}"
                break
        self.last = time.time()
        return res


def _decompress(body: bytes, enc: str) -> bytes:
    try:
        if enc == "gzip" or body[:2] == b"\x1f\x8b":
            return gzip.decompress(body)
        if enc == "deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except (OSError, zlib.error, EOFError):
        pass
    return body


def search(http_: Http, engine: str, query: str) -> tuple:
    """(results, problem): problem is None, 'captcha' or an error text."""
    if engine == "bing":
        url = "https://cn.bing.com/search?" + urllib.parse.urlencode({"q": query, "ensearch": "0", "FORM": "BESBTB"})
    else:
        url = "https://www.baidu.com/s?" + urllib.parse.urlencode({"wd": query, "ie": "utf-8"})
    r = http_.get(url)
    if r["error"]:
        return [], r["error"]
    page = decode_page(r["body"], r["content_type"])
    results = parse_bing(page) if engine == "bing" else parse_baidu(page)
    if not results and captcha_page(page):
        return [], "captcha"
    if engine == "baidu":
        for res in results:
            if res.pop("redirect", False):
                res["url"] = resolve_redirect(res["url"]) or res["url"]
    return results, None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_redirect(url: str) -> str | None:
    """Location of a search engine's redirect link, without following it."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT) as r:
            return r.geturl()
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        e.close()
        return urllib.parse.urljoin(url, loc) if loc else None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        return None


# =============================================================================== saving (data only, our own file names)

def safe_ext(url: str, content_type: str, default: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    ext = os.path.splitext(path)[1]
    if ext not in SAFE_EXT:
        q = urllib.parse.unquote(urllib.parse.urlsplit(url).query).lower()
        m = re.search(r"\.(pdf|docx?|xlsx?|wps|ofd|et|jpe?g|png|gif)(?:&|$)", q)
        ext = "." + m.group(1) if m else ""
    ct = (content_type or "").split(";")[0].strip().lower()
    by_ct = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
             "application/msword": ".doc", "text/html": ".html",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
             "application/vnd.ms-excel": ".xls",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx"}
    if ct in by_ct and (ext not in SAFE_EXT or (ext in (".htm", ".html")) != (by_ct[ct] == ".html")):
        ext = by_ct[ct]  # no usable extension, or the server says it is something else
    ext = ext if ext in SAFE_EXT else default
    return ".html" if ext == ".htm" else ext


def write_file(folder: str, name: str, body: bytes) -> str:
    """Write bytes to folder/name atomically. Names are always chosen by this script, never by the server."""
    assert re.fullmatch(r"[a-z]+(?:_\d+)?\.[a-z0-9]+", name), name
    path = os.path.join(folder, name)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)
    return path


def file_entry(role: str, res: dict, path: str | None, title: str | None = None) -> dict:
    body = res.get("body") or b""
    return {"role": role, "url": res["url"], "final_url": res.get("final_url"), "fetched_at": res.get("fetched_at"),
            "http_status": res.get("status"), "content_type": res.get("content_type"), "error": res.get("error"),
            "sha256": hashlib.sha256(body).hexdigest() if body else None, "bytes": len(body),
            "path": os.path.basename(path) if path else None, "title": title,
            **({"tls": res["tls"]} if res.get("tls") else {})}


def write_manifest(folder: str, manifest: dict) -> None:
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, "manifest.json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(folder, "manifest.json"))


def read_manifest(folder: str) -> dict | None:
    p = os.path.join(folder, "manifest.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# =============================================================================== one target

def fetch_article(http_: Http, folder: str, url: str, t: dict, manifest: dict, images_mode: str = "all") -> dict:
    """Download the article page, its further pages and the documents/images it links; returns a summary.

    images_mode "needed": download the article's images only when the page has (almost) no text, i.e. when the
    bulletin itself is published as images; their URLs are recorded in the manifest either way."""
    res = http_.get(url)
    if res["error"] or not res["body"]:
        manifest["files"].append(file_entry("page", res, None))
        return {"ok": False, "error": res["error"] or "empty page"}
    page_html = decode_page(res["body"], res["content_type"])
    path = write_file(folder, "page.html", res["body"])
    links = extract_links(page_html, res["final_url"] or url)
    manifest["files"].append(file_entry("page", res, path, links["title"]))
    manifest["page_title"] = links["title"]
    manifest["page_title_match"] = title_match(links["title"], t)
    images, docs = list(links["images"]), list(links["attachments"])
    for i, sub in enumerate(links["pages"], 2):
        r = http_.get(sub, referer=url)
        p = write_file(folder, f"page_{i}.html", r["body"]) if r["body"] and not r["error"] else None
        manifest["files"].append(file_entry("subpage", r, p))
        if p:
            more = extract_links(decode_page(r["body"], r["content_type"]), r["final_url"] or sub)
            images += [u for u in more["images"] if u not in images]
            docs += [u for u in more["attachments"] if u not in docs]
    for i, u in enumerate(docs[:MAX_ATTACHMENTS], 1):
        r = http_.get(u, referer=url)
        ok = r["body"] and not r["error"] and not looks_like_html(r)
        p = write_file(folder, f"att_{i:02d}{safe_ext(u, r['content_type'], '.bin')}", r["body"]) if ok else None
        manifest["files"].append(file_entry("attachment", r, p))
    text_chars = len(re.findall(r"[\u4e00-\u9fff]", article_text(page_html)["text"]))
    manifest["page_text_chars"] = text_chars
    if images_mode == "needed" and text_chars >= 200:
        manifest["images_not_downloaded"] = images[:MAX_IMAGES]
        images = []
    for i, u in enumerate(images[:MAX_IMAGES], 1):
        r = http_.get(u, referer=url)
        ok = r["body"] and not r["error"] and not looks_like_html(r)
        p = write_file(folder, f"img_{i:03d}{safe_ext(u, r['content_type'], '.img')}", r["body"]) if ok else None
        manifest["files"].append(file_entry("image", r, p))
    return {"ok": True, "images": len(images), "attachments": len(docs), "pages": 1 + len(links["pages"])}


def looks_like_html(res: dict) -> bool:
    """A server that answers a missing file with an HTML page (200)."""
    return (res.get("content_type") or "").lower().startswith("text/html") or res["body"][:200].lstrip().lower() \
        .startswith((b"<!doctype html", b"<html"))


def fetch_known(http_: Http, folder: str, t: dict, manifest: dict) -> int:
    """Files already known from tjcn.org (the bureau's own image/attachment URLs of an image-only bulletin)."""
    n = 0
    for i, u in enumerate((t.get("known_urls") or [])[:MAX_IMAGES], 1):
        r = http_.get(u)
        ok = r["body"] and not r["error"] and not looks_like_html(r)
        p = write_file(folder, f"known_{i:03d}{safe_ext(u, r['content_type'], '.bin')}", r["body"]) if ok else None
        manifest["files"].append(file_entry("known", r, p))
        n += bool(p)
    return n


def process_target(http_: Http, t: dict, out_dir: str, engines: list, any_host: bool = False,
                   search_fn=search, images_mode: str = "all") -> dict:
    folder = os.path.join(out_dir, str(t["year"]), t["code"])
    os.makedirs(folder, exist_ok=True)
    manifest = {"code": t["code"], "name": t["zh_full"], "province": t.get("province"), "year": t["year"],
                "reason": t.get("reason"), "hint_host": t.get("hint_host"), "status": "running",
                "started_at": now_iso(), "script_version": VERSION, "searches": [], "files": []}
    write_manifest(folder, manifest)
    if t.get("known_urls"):
        got = fetch_known(http_, folder, t, manifest)
        say(f"      已知图片/附件 {got}/{len(t['known_urls'])} 个")
    chosen = None
    for engine in engines:
        for q in queries_for(t):
            results, problem = search_fn(http_, engine, q)
            ranked = rank_results(results, t, any_host)
            manifest["searches"].append({"engine": engine, "query": q, "at": now_iso(), "problem": problem,
                                         "results": [{"url": r["url"], "title": r["title"]} for r in results[:10]],
                                         "accepted": [r["url"] for r in ranked[:3]]})
            if problem == "captcha":
                say(f"      {engine} 要求验证（验证码）。稍后再试，或换网络；先跳过 {engine}。")
                break
            if ranked:
                chosen = dict(ranked[0], engine=engine, query=q)
                break
        if chosen:
            break
    if not chosen:
        manifest.update(status="not_found", finished_at=now_iso())
        write_manifest(folder, manifest)
        return manifest
    manifest["chosen"] = {k: chosen[k] for k in ("url", "title", "engine", "query", "match", "host_score")}
    manifest["query"], manifest["engine"] = chosen["query"], chosen["engine"]
    say(f"      找到：{chosen['title'][:40]}  {host_of(chosen['url'])}")
    summary = fetch_article(http_, folder, chosen["url"], t, manifest, images_mode)
    manifest.update(status="done" if summary["ok"] else "error", summary=summary, finished_at=now_iso())
    write_manifest(folder, manifest)
    return manifest


# =============================================================================== zip

def make_zip(out_dir: str, dest_dir: str, date: str | None = None) -> str:
    """Pack out_dir into jiangshan_bulletins_<date>.zip (paths inside: out/<year>/<code>/<file>), plus summary.csv."""
    date = date or datetime.now().strftime("%Y%m%d")
    path = os.path.join(dest_dir, f"jiangshan_bulletins_{date}.zip")
    rows = ["year,code,name,status,engine,url,files"]
    with zipfile.ZipFile(path + ".part", "w", zipfile.ZIP_DEFLATED) as z:
        for year in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
            ydir = os.path.join(out_dir, year)
            if not (os.path.isdir(ydir) and year.isdigit()):
                continue
            for code in sorted(os.listdir(ydir)):
                cdir = os.path.join(ydir, code)
                if not os.path.isdir(cdir):
                    continue
                m = read_manifest(cdir) or {}
                files = [f for f in sorted(os.listdir(cdir)) if not f.endswith(".part")]
                for f in files:
                    z.write(os.path.join(cdir, f), f"out/{year}/{code}/{f}")
                chosen = m.get("chosen") or {}
                rows.append(",".join(_csv(x) for x in (year, code, m.get("name", ""), m.get("status", ""),
                                                        chosen.get("engine", ""), chosen.get("url", ""),
                                                        str(len(files)))))
        z.writestr("out/summary.csv", "﻿" + "\n".join(rows) + "\n")
    os.replace(path + ".part", path)
    return path


def _csv(x) -> str:
    x = str(x)
    return '"' + x.replace('"', '""') + '"' if any(c in x for c in ',"\n') else x


# =============================================================================== main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="下载各地统计公报（江山图鉴）")
    ap.add_argument("--targets", default=os.path.join(HERE, "targets.json"), help="目标清单（默认同目录 targets.json）")
    ap.add_argument("--out", default=os.path.join(HERE, "out"), help="保存目录（默认同目录 out）")
    ap.add_argument("--dry-run", action="store_true", help="只打印搜索词，不联网")
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理几项（0 = 不限）")
    ap.add_argument("--years", type=int, nargs="*", help="只处理这些年份，例如 --years 2024 2025")
    ap.add_argument("--codes", nargs="*", help="只处理这些地区代码，例如 --codes 130100 440300")
    ap.add_argument("--engine", choices=["bing", "baidu", "both"], default="both",
                    help="搜索引擎：bing（必应）、baidu（百度）或 both（先必应，找不到再百度；默认）")
    ap.add_argument("--retry", action="store_true", help="重新尝试上次没找到或出错的项")
    ap.add_argument("--any-host", action="store_true", help="也接受非 gov.cn 网站（结果会标注，默认只要政府网站）")
    ap.add_argument("--images", choices=["all", "needed"], default="all",
                    help="all：下载正文里的全部图片（默认）；needed：只在公报本身是图片时才下载（快很多）")
    ap.add_argument("--min-delay", type=float, default=2.0)
    ap.add_argument("--max-delay", type=float, default=5.0)
    ap.add_argument("--zip-only", action="store_true", help="不下载，只把已有结果打包")
    a = ap.parse_args(argv)

    if a.zip_only:
        say("打包：", make_zip(a.out, os.path.dirname(os.path.abspath(a.out))))
        return 0
    targets = select_targets(load_targets(a.targets), set(a.years or []), set(a.codes or []))
    engines = ["bing", "baidu"] if a.engine == "both" else [a.engine]
    todo = []
    for t in targets:
        m = read_manifest(os.path.join(a.out, str(t["year"]), t["code"]))
        if m and m.get("status") == "done":
            continue
        if m and m.get("status") in ("not_found", "error") and not a.retry:
            continue
        todo.append(t)
    if a.limit:
        todo = todo[: a.limit]
    say(f"共 {len(targets)} 项，已完成 {len(targets) - len(todo)} 项（含跳过），本次处理 {len(todo)} 项。")
    if a.dry_run:
        for t in todo:
            say(f"{t['year']} {t['code']} {t['zh_full']}  [{t.get('reason', '')}]  hint={t.get('hint_host') or '-'}")
            for q in queries_for(t):
                say("    ", q)
        return 0
    http_ = Http(delay=(a.min_delay, a.max_delay))
    counts = {"done": 0, "not_found": 0, "error": 0}
    try:
        for i, t in enumerate(todo, 1):
            say(f"[{i}/{len(todo)}] {t['year']} {t['zh_full']}（{t['code']}）")
            m = process_target(http_, t, a.out, engines, a.any_host, images_mode=a.images)
            counts[m["status"]] = counts.get(m["status"], 0) + 1
            mark = {"done": "完成", "not_found": "未找到", "error": "出错"}.get(m["status"], m["status"])
            say(f"      → {mark}")
    except KeyboardInterrupt:
        say("\n已中断。再次运行会从中断处继续。")
    say(f"本次：完成 {counts['done']}，未找到 {counts['not_found']}，出错 {counts['error']}。")
    z = make_zip(a.out, os.path.dirname(os.path.abspath(a.out)))
    say("结果已打包：", z)
    return 0


if __name__ == "__main__":
    sys.exit(main())
