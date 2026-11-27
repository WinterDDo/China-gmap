"""tools/local_fetch: everything but the live search and gov.cn downloads, which only work on the owner's network.

The end-to-end test serves a small article site from 127.0.0.1 and replaces the search engine with a stub; the ingest
test then feeds the resulting zip to pipeline/sources/local_bulletins.py."""

import hashlib
import http.server
import json
import threading
import zipfile

import fetch_bulletins as fb
import pytest
from conftest import FIXTURES, ROOT

SJZ = {"code": "130100", "zh_full": "石家庄市", "names": ["石家庄市"], "province": "河北省", "year": 2025,
       "reason": "not_on_tjcn", "hint_host": "tjj.sjz.gov.cn", "hint_hosts": ["tjj.sjz.gov.cn"]}
HAINAN_ZHOU = {"code": "632500", "zh_full": "海南藏族自治州", "names": ["海南藏族自治州", "海南州"], "year": 2024}
JILIN_PROV = {"code": "220000", "zh_full": "吉林省", "names": ["吉林省"], "year": 2024}
JILIN_CITY = {"code": "220200", "zh_full": "吉林市", "names": ["吉林市"], "year": 2024}


# ------------------------------------------------------------------ titles, ranking, queries

def test_title_match():
    assert fb.title_match("石家庄市2025年国民经济和社会发展统计公报_石家庄市统计局", SJZ) == "strict"
    assert fb.title_match("2025年石家庄市国民经济和社会发展统计公报", SJZ) == "strict"
    assert fb.title_match("石家庄市统计局 2025年统计公报", SJZ) == "loose"
    assert fb.title_match("石家庄市2024年国民经济和社会发展统计公报", SJZ) == ""  # wrong year
    assert fb.title_match("石家庄市长安区2025年国民经济和社会发展统计公报", SJZ) == ""  # a district
    assert fb.title_match("图解：石家庄市2025年国民经济和社会发展统计公报", SJZ) == ""  # an explainer
    assert fb.title_match("海南省2024年国民经济和社会发展统计公报", HAINAN_ZHOU) == ""
    assert fb.title_match("海南州2024年国民经济和社会发展统计公报", HAINAN_ZHOU) == "strict"
    assert fb.title_match("吉林市2024年国民经济和社会发展统计公报", JILIN_PROV) == ""
    assert fb.title_match("吉林省2024年国民经济和社会发展统计公报", JILIN_CITY) == ""


def test_rank_prefers_hint_host_then_gov_cn():
    results = [
        {"url": "https://www.tjcn.org/tjgb/03hb/1.html", "title": "石家庄市2025年国民经济和社会发展统计公报"},
        {"url": "https://www.sjz.gov.cn/a.html", "title": "石家庄市2025年国民经济和社会发展统计公报"},
        {"url": "https://tjj.sjz.gov.cn/b.html", "title": "石家庄市统计局2025年统计公报"},
        {"url": "https://tjj.sjz.gov.cn/c.html", "title": "石家庄市2023年国民经济和社会发展统计公报"},
    ]
    ranked = fb.rank_results(results, SJZ)
    assert [r["url"] for r in ranked] == ["https://tjj.sjz.gov.cn/b.html", "https://www.sjz.gov.cn/a.html"]
    assert [r["url"] for r in fb.rank_results(results, SJZ, any_host=True)][-1] == "https://www.tjcn.org/tjgb/03hb/1.html"


def test_queries():
    assert fb.queries_for(SJZ)[0] == '"石家庄市2025年国民经济和社会发展统计公报"'
    assert len(fb.queries_for(SJZ)) == 3


def test_select_targets():
    ts = [dict(SJZ, year=2024), SJZ, dict(HAINAN_ZHOU)]
    assert fb.select_targets(ts, {2025}) == [SJZ]
    assert fb.select_targets(ts, set(), {"632500"}) == [HAINAN_ZHOU]


# ------------------------------------------------------------------ search result pages (markup as served by the engines)

BING = """<ol id="b_results">
<li class="b_algo" data-tag=""><div class="b_tpcn"></div><h2><a target="_blank"
 href="https://cn.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly90amouc2p6Lmdvdi5jbi9jb2wvMjAyNS90XzEuaHRtbA&amp;ntb=1"
 h="ID=SERP,5.1"><strong>石家庄市2025年国民经济和社会发展统计公报</strong> - 石家庄市统计局</a></h2>
 <div class="b_caption"><p>初步核算，全年全市生产总值…</p></div></li>
<li class="b_algo b_vtl_deeplinks"><h2><a href="https://www.example.com/x">别的</a></h2></li>
</ol>"""

BAIDU = """<div class="result c-container xpath-log new-pmd" srcid="1599" id="1" tpl="se_com_default"
 mu="https://tjj.sjz.gov.cn/col/2025/t_1.html" data-op=""><h3 class="c-title t t tts-title"><a
 href="http://www.baidu.com/link?url=AbC" target="_blank">石家庄市<em>2025年国民经济和社会发展统计公报</em></a></h3></div>
<div class="result c-container" id="2"><h3 class="t"><a href="http://www.baidu.com/link?url=XyZ">其他</a></h3></div>"""


def test_parse_bing_decodes_click_redirect():
    rs = fb.parse_bing(BING)
    assert rs[0]["url"] == "https://tjj.sjz.gov.cn/col/2025/t_1.html"
    assert rs[0]["title"] == "石家庄市2025年国民经济和社会发展统计公报 - 石家庄市统计局"
    assert rs[1]["url"] == "https://www.example.com/x"
    assert fb.captcha_page('<div class="b_captcha">') and not fb.captcha_page(BING)


def test_parse_baidu_uses_mu():
    rs = fb.parse_baidu(BAIDU)
    assert rs[0]["url"] == "https://tjj.sjz.gov.cn/col/2025/t_1.html" and not rs[0]["redirect"]
    assert rs[1]["url"].startswith("http://www.baidu.com/link") and rs[1]["redirect"]


# ------------------------------------------------------------------ link extraction on saved tjcn pages

def test_extract_links_image_only_tjcn_page():
    page = fb.decode_page((FIXTURES / "tjcn_taiyuan_2023_image_only.html").read_bytes(), "text/html")
    links = fb.extract_links(page, "http://www.tjcn.org/tjgb/04sx/38004.html")
    assert links["title"].startswith("太原市2023年国民经济和社会发展统计公报")
    assert len(links["images"]) == 20  # the article's images, not tjcn's logo or QR code
    assert all(u.startswith("https://stats.taiyuan.gov.cn/") for u in links["images"])
    assert links["attachments"] == [] and links["pages"] == []


def test_article_text_of_saved_tjcn_page():
    page = fb.decode_page((FIXTURES / "tjcn_shijiazhuang_2023_text.html").read_bytes(), "text/html; charset=gb2312")
    art = fb.article_text(page)
    assert "全年全市生产总值7534.2亿元" in art["text"] and "中国统计信息网" not in art["text"]


@pytest.mark.skipif(not (ROOT / "data/raw/tjcn_bulletins/pages").exists(), reason="tjcn cache not present")
def test_extract_links_on_cached_tjcn_pages():
    """Every cached image-only/attachment-only tjcn page: the collector finds the same files the pipeline does."""
    from pipeline.parse import htmltext
    from pipeline.sources.tjcn_bulletins import decode, parse_page
    checked = 0
    for p in sorted((ROOT / "data/raw/tjcn_bulletins/pages").glob("*/*.html"))[:400]:
        html = decode(p.read_bytes())
        body = parse_page(html)["body_html"]
        if htmltext.to_text(body):
            continue
        ours = htmltext.media(body, "http://www.tjcn.org/x/1.html")
        theirs = fb.extract_links(html, "http://www.tjcn.org/x/1.html")
        assert set(ours["attachments"]) <= set(theirs["attachments"])
        assert set(ours["images"]) == set(theirs["images"]) or not ours["images"]
        checked += 1
    assert checked >= 0


def test_html_tree_survives_deep_nesting():
    page = "<div>" + "<font>" * 5000 + "全年全市生产总值100亿元。" * 20 + "</div>"
    assert "生产总值100亿元" in fb.article_text(page)["text"]


def test_flow_joins_wrapped_chinese_lines():
    assert fb.flow("年末全市常住\n   总人口") == "年末全市常住总人口"
    assert fb.flow("GDP\n 1234") == "GDP 1234"


def test_write_file_refuses_server_names(tmp_path):
    fb.write_file(str(tmp_path), "att_01.pdf", b"%PDF")
    for bad in ("../x.pdf", "a b.pdf", "report.exe.", "x/y.png"):
        with pytest.raises(AssertionError):
            fb.write_file(str(tmp_path), bad, b"")


def test_safe_ext():
    assert fb.safe_ext("https://a.gov.cn/f/1.PDF", "application/pdf", ".bin") == ".pdf"
    assert fb.safe_ext("https://a.gov.cn/download?fileName=2025%E5%B9%B4.docx", "", ".bin") == ".docx"
    assert fb.safe_ext("https://a.gov.cn/f/run.exe", "application/octet-stream", ".bin") == ".bin"
    assert fb.safe_ext("https://a.gov.cn/img/x", "image/png", ".img") == ".png"


# ------------------------------------------------------------------ end to end against a local site

ARTICLE = """<html><head><meta charset="utf-8"><title>石家庄市2025年国民经济和社会发展统计公报_石家庄市统计局</title></head>
<body><div class="header"><img src="/img/logo.png"><a href="/">首页</a></div>
<div class="info">来源：石家庄市统计局　发布时间：2026-03-20</div>
<div class="TRS_Editor"><p>石家庄市统计局</p>
<p>初步核算，全年全市生产总值8123.4亿元，按不变价格计算，比上年增长5.6%。其中，第一产业增加值600.1亿元，增长3.0%；
第二产业增加值2400.2亿元，增长6.0%；第三产业增加值5123.1亿元，增长5.5%。</p>
<p>年末全市常住总人口1125.10万人，比上年末增加1.75万人。常住人口城镇化率为73.10%。</p>
<p>全年全市居民人均可支配收入40100元，比上年增长5.0%。按常住地分，城镇居民人均可支配收入50200元，增长4.5%；
农村居民人均可支配收入22600元，增长6.0%。</p>
<p>全年全市一般公共预算收入760.5亿元，比上年增长3.1%。全年全市社会消费品零售总额2900.3亿元，比上年增长4.2%。</p>
<p>全年粮食播种面积67.0万公顷，粮食总产量440.1万吨，比上年增长0.4%。</p>
<p><img src="chart1.png"></p>
<p>附件：<a href="/files/gb2025.pdf">2025年统计公报.pdf</a></p>
</div>
<div class="page"><a href="t2026_1_2.html">下一页</a></div>
<div class="footer"><img src="/img/qrcode.png"> 版权所有</div></body></html>"""
SUBPAGE = """<html><head><meta charset="utf-8"><title>石家庄市2025年统计公报（2）</title></head><body>
<div class="TRS_Editor"><p>十二、资源和环境。全年全市完成造林面积9.11万公顷，森林覆盖率为42.6%，各项工作稳步推进，生态环境持续改善。</p>
<p><img src="chart2.png"></p></div></body></html>"""
SITE = {"/col/t2026_1.html": ("text/html; charset=utf-8", ARTICLE.encode()),
        "/col/t2026_1_2.html": ("text/html; charset=utf-8", SUBPAGE.encode()),
        "/col/chart1.png": ("image/png", b"\x89PNG\r\n\x1a\nchart-one"),
        "/col/chart2.png": ("image/png", b"\x89PNG\r\n\x1a\nchart-two"),
        "/files/gb2025.pdf": ("application/pdf", b"%PDF-1.4 fake"),
        "/img/logo.png": ("image/png", b"logo"), "/img/qrcode.png": ("image/png", b"qr")}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        ctype, body = SITE.get(self.path, ("text/html", None))
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body or b"not found")

    def log_message(self, *a):
        pass


@pytest.fixture()
def site(monkeypatch):
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _fake_search(base, calls):
    def search(http_, engine, query):
        calls.append((engine, query))
        if engine == "bing":
            return [], "captcha"  # the first engine refuses: the collector must move on to the next
        return [{"url": f"{base}/col/t2026_1.html", "title": "石家庄市2025年国民经济和社会发展统计公报"},
                {"url": "https://www.tjcn.org/x.html", "title": "石家庄市2025年国民经济和社会发展统计公报"}], None
    return search


def test_process_target_manifest_and_zip(site, tmp_path):
    out = tmp_path / "out"
    target = dict(SJZ, hint_host="127.0.0.1", hint_hosts=["127.0.0.1"], known_urls=[f"{site}/col/chart1.png"])
    calls = []
    m = fb.process_target(fb.Http(delay=(0, 0)), target, str(out), ["bing", "baidu"], search_fn=_fake_search(site, calls))
    assert m["status"] == "done" and m["engine"] == "baidu" and m["query"] == fb.queries_for(target)[0]
    assert calls == [("bing", fb.queries_for(target)[0]), ("baidu", fb.queries_for(target)[0])]
    assert m["searches"][0]["problem"] == "captcha"
    folder = out / "2025" / "130100"
    saved = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert saved == m
    by_role = {}
    for f in m["files"]:
        by_role.setdefault(f["role"], []).append(f)
    assert [f["path"] for f in by_role["page"]] == ["page.html"]
    assert [f["path"] for f in by_role["subpage"]] == ["page_2.html"]
    assert [f["path"] for f in by_role["attachment"]] == ["att_01.pdf"]
    assert [f["path"] for f in by_role["image"]] == ["img_001.png", "img_002.png"]  # no logo, no QR code
    assert [f["path"] for f in by_role["known"]] == ["known_001.png"]
    for f in m["files"]:
        data = (folder / f["path"]).read_bytes()
        assert f["sha256"] == hashlib.sha256(data).hexdigest() and f["bytes"] == len(data)
        assert f["http_status"] == 200 and f["fetched_at"] and f["final_url"].startswith(site)
    assert m["page_title_match"] == "strict" and m["chosen"]["host_score"] == 3

    z = fb.make_zip(str(out), str(tmp_path), date="20261201")
    assert z.endswith("jiangshan_bulletins_20261201.zip")
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
        assert {"out/2025/130100/manifest.json", "out/2025/130100/page.html", "out/2025/130100/att_01.pdf",
                "out/summary.csv"} <= names
        assert "done" in zf.read("out/summary.csv").decode("utf-8-sig")


def test_not_found_and_resume(site, tmp_path, capsys):
    out = tmp_path / "out"
    t2 = dict(SJZ, code="130200", zh_full="唐山市", names=["唐山市"])
    m = fb.process_target(fb.Http(delay=(0, 0)), t2, str(out), ["baidu"], search_fn=_fake_search(site, []))
    assert m["status"] == "not_found" and m["files"] == []
    targets = tmp_path / "targets.json"
    targets.write_text(json.dumps({"targets": [SJZ, t2, dict(SJZ, year=2024)]}, ensure_ascii=False), encoding="utf-8")
    fb.write_manifest(str(out / "2025" / "130100"), {"status": "done"})
    fb.main(["--targets", str(targets), "--out", str(out), "--dry-run"])
    printed = capsys.readouterr().out
    assert "本次处理 1 项" in printed  # done and not_found are skipped
    assert '"石家庄市2024年国民经济和社会发展统计公报"' in printed
    fb.main(["--targets", str(targets), "--out", str(out), "--dry-run", "--retry"])
    assert "本次处理 2 项" in capsys.readouterr().out


# ------------------------------------------------------------------ the zip drops into the pipeline

def test_local_ingest(site, tmp_path, monkeypatch):
    import pipeline.core.fetch as core_fetch
    import pipeline.core.source as core_source
    import pipeline.parse.records as records
    import pipeline.sources.local_bulletins as lb

    raw, interim = tmp_path / "raw", tmp_path / "interim" / "bulletins"
    for mod in (core_fetch, core_source, lb):
        monkeypatch.setattr(mod, "RAW", raw)
    monkeypatch.setattr(records, "BULLETINS", interim)
    out = tmp_path / "out"
    fb.process_target(fb.Http(delay=(0, 0)), dict(SJZ, hint_host="127.0.0.1"), str(out), ["baidu"],
                      search_fn=_fake_search(site, []))
    (raw / "local_bulletins").mkdir(parents=True)
    zpath = fb.make_zip(str(out), str(raw / "local_bulletins"), date="20261201")
    with zipfile.ZipFile(zpath, "a") as z:  # members the collector never writes must be ignored
        z.writestr("out/2025/130100/../../evil.py", "print('x')")
        z.writestr("out/2025/130100/run.exe.", "x")
    src = lb.LocalBulletins()
    src.fetch()
    assert not (raw / "local_bulletins" / "unpacked" / "evil.py").exists()
    assert "jiangshan_bulletins_20261201.zip" in json.loads((raw / "local_bulletins" / "manifest.json").read_text())
    result = src.process()
    assert result["coverage"]["2025"]["text"] == 1
    rec = json.loads((interim / "2025.json").read_text(encoding="utf-8"))["records"][0]
    assert rec["code"] == "130100" and rec["source"] == "local_bulletins" and rec["status"] == "text"
    assert rec["url"] == f"{site}/col/t2026_1.html"
    assert rec["bureau"] == "石家庄市统计局" and rec["published"] == "2026-03-20"
    v = {k: f["value"] for k, f in rec["fields"].items() if f}
    assert v == {"gdp": 8123.4, "gdp_growth": 5.6, "gdp_primary": 600.1, "gdp_secondary": 2400.2,
                 "gdp_tertiary": 5123.1, "population": 1125.1, "urbanization": 73.1, "income": 40100,
                 "income_urban": 50200, "income_rural": 22600, "budget_revenue": 760.5, "retail_sales": 2900.3}
    assert rec["flags"] == [] and rec["attachments"] == [f"{site}/files/gb2025.pdf"]
    assert any(f.endswith("out/2025/130100/page.html") for f in rec["files"])


@pytest.mark.skipif(not (ROOT / "tools/local_fetch/targets.json").exists(), reason="targets.json not generated yet")
def test_generated_targets_file():
    data = json.loads((ROOT / "tools/local_fetch/targets.json").read_text(encoding="utf-8"))
    ts = data["targets"]
    assert data["count"] == len(ts)
    for year in (2024, 2025):
        assert len({t["code"] for t in ts if t["year"] == year}) == 365
    for t in ts:
        assert {"code", "zh_full", "names", "province", "year", "reason", "hint_host"} <= set(t)
        assert t["reason"] == "not_on_tjcn" or t["year"] <= 2023
    jl = next(t for t in ts if t["code"] == "220000")
    assert jl["names"] == ["吉林省"]
    hn = next(t for t in ts if t["code"] == "632500")
    assert "海南州" in hn["names"] and "海南省" not in hn["names"]
    assert next(t for t in ts if t["code"] == "100000")["hint_host"] == "www.stats.gov.cn"


def test_pdf_viewer_links_are_unwrapped():
    # 石家庄市2022年 on tjcn links the bureau's pdf.js viewer, not the file
    from pipeline.parse import htmltext
    link = '<a href="http://tjj.sjz.gov.cn/pdf/html5-online-pdf-viewer/web/viewer.html?file=/atm/7/2023030313384188.pdf">附件</a>'
    want = ["http://tjj.sjz.gov.cn/atm/7/2023030313384188.pdf"]
    assert fb.extract_links(f"<html><body><div>{link}</div></body></html>", "http://www.tjcn.org/x.html")["attachments"] == want
    assert htmltext.media(link, "http://www.tjcn.org/x.html")["attachments"] == want


def test_images_needed_mode_skips_charts_of_text_bulletins(site, tmp_path):
    m = fb.process_target(fb.Http(delay=(0, 0)), dict(SJZ, hint_host="127.0.0.1"), str(tmp_path / "out"), ["baidu"],
                          search_fn=_fake_search(site, []), images_mode="needed")
    assert m["status"] == "done" and not [f for f in m["files"] if f["role"] == "image"]
    assert len(m["images_not_downloaded"]) == 2 and m["page_text_chars"] >= 200


def test_known_only_needs_no_search(site, tmp_path, capsys):
    out = tmp_path / "out"
    known = dict(SJZ, year=2023, reason="attachment_only_on_tjcn", known_urls=[f"{site}/files/gb2025.pdf"])
    calls = []
    m = fb.process_target(fb.Http(delay=(0, 0)), known, str(out), ["bing", "baidu"],
                          search_fn=_fake_search(site, calls), use_search=False)
    assert m["status"] == "done" and m["mode"] == "known_only" and calls == []
    assert [f["path"] for f in m["files"]] == ["known_001.pdf"]
    dead = dict(known, code="130200", zh_full="唐山市", names=["唐山市"], known_urls=[f"{site}/nothing.pdf"])
    assert fb.process_target(fb.Http(delay=(0, 0)), dead, str(out), [], use_search=False)["status"] == "error"
    # the flag keeps only targets with known addresses, and retries ones an earlier *search* run gave up on
    targets = tmp_path / "targets.json"
    other = dict(SJZ, code="130300", zh_full="秦皇岛市", names=["秦皇岛市"])
    targets.write_text(json.dumps({"targets": [known, other, dict(known, code="130400")]}, ensure_ascii=False), encoding="utf-8")
    fb.write_manifest(str(out / "2023" / "130400"), {"status": "not_found"})
    fb.main(["--targets", str(targets), "--out", str(out), "--dry-run", "--known-only"])
    assert "共 2 项" in capsys.readouterr().out
