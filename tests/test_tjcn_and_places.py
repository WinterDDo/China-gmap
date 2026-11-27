"""Place-name matching and the tjcn.org page parsers (on trimmed copies of real tjcn pages in tests/fixtures)."""

from conftest import FIXTURES

from pipeline.parse import htmltext
from pipeline.parse.places import PlaceMatcher, bulletin_units, clean
from pipeline.sources.tjcn_bulletins import (
    decode,
    match_index,
    match_list_item,
    parse_list_page,
    parse_page,
    parse_year_index,
    subpage_hrefs,
    title_year,
)

M = PlaceMatcher()


def test_name_traps():
    assert M.city("海南州", "630000") == "632500"  # 青海 海南藏族自治州
    assert M.province("海南省") == "460000"
    assert M.city("海南州", "460000") is None
    assert M.city("吉林市", "220000") == "220200"
    assert M.province("吉林省") == "220000" and M.province("吉林") == "220000"
    assert M.city("吉林", "220000") is None  # a bare 吉林 is the province, never the city
    assert M.city("延边州", "220000") == "222400"
    assert M.city("迪庆州", "530000") == "533400"
    assert M.city("兴安盟", "150000") == "152200"
    assert M.city("阿克苏地区", "650000") == "652900"
    assert M.city("大兴安岭地区", "230000") == "232700"
    assert M.city("朝阳市", "210000") == "211300"  # not 北京 朝阳区
    assert M.province("广　西") == "450000" and M.province("内蒙古") == "150000"
    assert M.province("中　国") == "100000"
    assert clean("新　疆 ") == "新疆"


def test_find_in_titles():
    assert M.find_in("鹰潭市", "360000") == "360600"
    assert M.find_in("江西省", "360000") == "360000"
    assert M.find_in("吉林市船营区", "220000") is None  # a district's bulletin
    assert M.find_in("海南藏族自治州", "630000") == "632500"


def test_bulletin_units():
    units = bulletin_units()
    assert len(units) == 1 + 31 + 333  # nation, provinces (no HK/MO/TW), prefecture-level units (no Taiwan cities)
    assert "100000" in units and "710100" not in units and "810000" not in units


INDEX_ROWS = """
<table><tr>
  <td width="6%"><a href="/tjgb/00zg/37659.html">中　国</a></td>
  <td><a href="/tjgb/01bj/37689.html">北京市</a>　<a href="/tjgb/22cq/37934.html">重庆市</a></td>
</tr>
<tr><td><a href="/tjgb/07jl/37722.html">吉林省</a></td>
  <td><a href="/tjgb/08jl/37723.html">吉林市</a>　<a href="/tjgb/07jl/37724.html">延边州</a></td></tr>
<tr><td><a href="/tjgb/29qh/37685.html">青海省</a></td><td><a href="/tjgb/29qh/37686.html">海南州</a></td></tr>
<tr><td><a href="/tjgb/21hn/37850.html">海南省</a></td><td><a href="/tjgb/21hn/37851.html">海口市</a></td></tr>
<tr><td><a href="/tjgb/31xj/37580.html">新　疆</a></td><td><a href="/tjgb/31xj/37599.html">新疆生产建设兵团</a></td></tr>
</table>"""


def test_year_index_rows_and_matching():
    links = parse_year_index(INDEX_ROWS)
    assert [link["text"] for link in links if link["row_head"]] == ["中国", "吉林省", "青海省", "海南省", "新疆"]
    matched, unmatched = match_index(links, M)
    assert {c: m["href"] for c, m in matched.items()} == {
        "100000": "/tjgb/00zg/37659.html", "110000": "/tjgb/01bj/37689.html", "500000": "/tjgb/22cq/37934.html",
        "220000": "/tjgb/07jl/37722.html", "220200": "/tjgb/08jl/37723.html",  # 吉林市 filed under 08jl in 2022
        "222400": "/tjgb/07jl/37724.html", "630000": "/tjgb/29qh/37685.html", "632500": "/tjgb/29qh/37686.html",
        "460000": "/tjgb/21hn/37850.html", "460100": "/tjgb/21hn/37851.html", "650000": "/tjgb/31xj/37580.html",
    }
    assert [u["text"] for u in unmatched] == ["新疆生产建设兵团"]


LIST_PAGE = """<a href="/tjgb/14jx/37977.html" title="鹰潭市2023年国民经济和社会发展统计公报">鹰潭市2023年…</a>
<a href="/tjgb/14jx/37760.html" title="江西省2023年国民经济和社会发展统计公报">江西省2023年…</a>
<a href="/tjgb/14jx/37001.html" title="南昌县2021年国民经济和社会发展统计公报">南昌县…</a>
<a href="/tjgb/14jx/37002.html" title="2021年九江市国民经济和社会发展统计公报">…</a>
<a href="/tjgb/14jx/37003.html" title="江西省第七次全国人口普查公报">…</a>
<div class="epages"><a href="/tjgb/14jx/index_2.html">下一页</a>&nbsp;<a href="/tjgb/14jx/index_14.html">尾页</a></div>"""


def test_list_page():
    items, last = parse_list_page(LIST_PAGE)
    assert last == 14 and len(items) == 5
    assert [match_list_item(i, M) for i in items] == [
        ("360600", 2023), ("360000", 2023), (None, 2021), ("360400", 2021), (None, None)]
    assert title_year("吉林市2022年国民经济和社会发展统计公报") == 2022


def test_text_page_header_and_body():
    page = parse_page(decode((FIXTURES / "tjcn_shijiazhuang_2023_text.html").read_bytes()))
    assert page["title"] == "石家庄市2023年国民经济和社会发展统计公报"
    assert page["bureau"] == "石家庄市统计局"
    assert page["published"] == "2024-04-07 13:33:40"
    text = htmltext.to_text(page["body_html"])
    assert "全年全市生产总值7534.2亿元" in text
    assert "中国统计信息网" not in text  # the footer is outside td#text


def test_image_only_page():
    html = decode((FIXTURES / "tjcn_taiyuan_2023_image_only.html").read_bytes())
    page = parse_page(html)
    assert page["bureau"] == "太原市统计局"
    found = htmltext.media(page["body_html"], "http://www.tjcn.org/tjgb/04sx/38004.html")
    assert len(found["images"]) == 20
    assert all(u.startswith("https://stats.taiyuan.gov.cn/u/cms/site36/202407/") for u in found["images"])
    assert htmltext.to_text(page["body_html"]) == ""


def test_subpages():
    html = ('<p class="pageLink"><b>1</b>&nbsp;<a href="/tjgb/03hb/37692_2.html">2</a>&nbsp;'
            '<a href="/tjgb/03hb/37692_3.html">3</a>&nbsp;<a href="/tjgb/03hb/37692_2.html">下一页</a></p>')
    assert subpage_hrefs(html, "/tjgb/03hb/37692.html") == ["/tjgb/03hb/37692_2.html", "/tjgb/03hb/37692_3.html"]
    assert subpage_hrefs("<p></p>", "/tjgb/03hb/37692.html") == []


def test_element_html_balances_nested_cells():
    html = '<table><tr><td id="text">a<table><tr><td>b</td></tr></table>c</td><td>footer</td></tr></table>'
    assert htmltext.element_html(html, id_="text") == "a<table><tr><td>b</td></tr></table>c"
