"""Census flow tables: the .xls reader (on a workbook built here), HTML table grids, and the matrix reader and its checks
(on small grids laid out like 《中国人口普查年鉴-2020》 tables 7-3 and 7-7)."""

import struct

import pytest

from pipeline.parse import htmltext, xls
from pipeline.sources.census_flows import NATION, check_matrix, count, parse_toc, read_matrix, read_population

CODES = {"北京": "110000", "天津": "120000", "河北": "130000"}


# --------------------------------------------------------------------- a minimal BIFF8 workbook in an OLE2 file


def _rec(rtype: int, body: bytes) -> bytes:
    return struct.pack("<HH", rtype, len(body)) + body


def _workbook() -> bytes:
    """Globals (BOF, BOUNDSHEET, SST split by a CONTINUE inside a wide string, EOF) and one sheet with every cell kind."""
    bof = lambda kind: _rec(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0, 0, 0, 0))  # noqa: E731
    name = "Sheet1".encode("latin-1")
    first = "现住地北京".encode("utf-16-le")  # split after two characters; the CONTINUE restarts with a flags byte
    sst = _rec(0x00FC, struct.pack("<IIHB", 3, 2, 5, 1) + first[:4])
    cont = _rec(0x003C, b"\x01" + first[4:] + struct.pack("<HB", 2, 1) + "合计".encode("utf-16-le"))
    head = bof(0x0005)
    boundsheet_len = 4 + 6 + 2 + len(name)
    sheet_at = len(head) + boundsheet_len + len(sst) + len(cont) + 4
    globals_ = head + _rec(0x0085, struct.pack("<IBBBB", sheet_at, 0, 0, len(name), 0) + name) + sst + cont + _rec(0x000A, b"")
    assert len(globals_) == sheet_at
    sheet = (bof(0x0010)
             + _rec(0x00FD, struct.pack("<HHHI", 0, 0, 0, 0))  # LABELSST → 现住地北京
             + _rec(0x00FD, struct.pack("<HHHI", 0, 1, 0, 1))  # 合计
             + _rec(0x0203, struct.pack("<HHHd", 1, 0, 0, 124837153.0))  # NUMBER
             + _rec(0x027E, struct.pack("<HHHI", 1, 1, 0, (470339 << 2) | 2))  # RK integer
             + _rec(0x027E, struct.pack("<HHHI", 1, 2, 0, (1234 << 2) | 3))  # RK integer / 100
             + _rec(0x00BD, struct.pack("<HHHIHIH", 2, 0, 0, (7 << 2) | 2, 0, (8 << 2) | 2, 1))  # MULRK
             + _rec(0x0204, struct.pack("<HHHHB", 3, 0, 0, 2, 0) + b"ab")  # LABEL (compressed)
             + _rec(0x0006, struct.pack("<HHHd", 3, 1, 0, 2.5) + b"\0" * 6)  # FORMULA, cached number
             + _rec(0x000A, b""))
    return (globals_ + sheet).ljust(4096, b"\0")  # ≥ the mini-stream cutoff: stored in ordinary sectors


def _ole(stream: bytes) -> bytes:
    """A compound file holding one "Workbook" stream: sector 0 = FAT, 1 = directory, 2… = the stream."""
    n = -(-len(stream) // 512)
    fat = [0xFFFFFFFD, 0xFFFFFFFE] + [3 + i for i in range(n - 1)] + [0xFFFFFFFE]
    fat += [0xFFFFFFFF] * (128 - len(fat))
    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 0x2C, 1, 1, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0, 0)
    header[0x4C:0x200] = b"\xff" * (0x200 - 0x4C)
    struct.pack_into("<I", header, 0x4C, 0)

    def entry(name: str, kind: int, start: int, size: int) -> bytes:
        e = bytearray(128)
        raw = (name + "\0").encode("utf-16-le")
        e[: len(raw)] = raw
        struct.pack_into("<HB", e, 64, len(raw), kind)
        struct.pack_into("<III", e, 68, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
        struct.pack_into("<II", e, 116, start, size)
        return bytes(e)

    directory = entry("Root Entry", 5, 0xFFFFFFFE, 0) + entry("Workbook", 2, 2, len(stream)) + bytes(256)
    return bytes(header) + struct.pack("<128I", *fat) + directory + stream.ljust(n * 512, b"\0")


def test_xls_cells():
    [(name, cells)] = xls.sheets(_ole(_workbook()))
    assert name == "Sheet1"
    assert cells[0, 0] == "现住地北京" and cells[0, 1] == "合计"
    assert cells[1, 0] == 124837153.0 and cells[1, 1] == 470339.0 and cells[1, 2] == pytest.approx(12.34)
    assert cells[2, 0] == 7.0 and cells[2, 1] == 8.0
    assert cells[3, 0] == "ab" and cells[3, 1] == 2.5
    assert xls.grid(cells)[2] == [7.0, 8.0, None]


def test_xls_rejects_other_files():
    with pytest.raises(xls.XlsError):
        xls.sheets(b"<html><table></table></html>")


# --------------------------------------------------------------------- HTML tables (the 2010 yearbook's Excel exports)


def test_table_grids_lay_out_spans():
    html = ("<table><tr><td rowspan=2>现 住 地</td><td colspan=3>户口登记地</td></tr>"
            "<tr><td>合计</td><td>北京</td><td>天津</td></tr>"
            "<tr><td>北 京</td><td>5</td><td></td><td>5</td></tr></table>")
    assert htmltext.table_grids(html) == [[
        ["现 住 地", "户口登记地", None, None],
        [None, "合计", "北京", "天津"],
        ["北 京", "5", "", "5"],
    ]]


# --------------------------------------------------------------------- matrices


def _stock_grid():
    """Shaped like 7-3: origins in groups of (小计, 男, 女), blank diagonal, a 全国 row of column totals."""
    head = [["7-3  全国按现住地、性别分的户口登记地在外省的人口"], [None, "单位：人"], ["现 住 地", "户口登记地"],
            [None, "合    计", None, None, "北    京", None, None, "天    津", None, None, "河    北", None, None],
            [None, "合计", "男", "女"] + ["小计", "男", "女"] * 3]
    rows = [["全    国", 60, 36, 24, 10, 6, 4, 20, 12, 8, 30, 18, 12],
            ["北    京", 40, 24, 16, None, None, None, 15, 9, 6, 25, 15, 10],
            ["天    津", 13, 7, 6, 8, 4, 4, None, None, None, 5, 3, 2],
            ["河    北", 7, 5, 2, 2, 2, 0, 5, 3, 2, None, None, None]]
    return head + [[None] * 13] + rows


def test_stock_matrix_and_checks():
    m = read_matrix(_stock_grid(), CODES)
    assert m["title"] == "7-3 全国按现住地、性别分的户口登记地在外省的人口"
    assert m["flows"][("110000", "120000")] == 8 and m["flows"][("120000", "110000")] == 15
    assert ("110000", "110000") not in m["flows"] and len(m["flows"]) == 6
    assert m["nation_row"]["130000"] == 30 and m["nation_total"] == 60
    c = check_matrix(m)
    assert c["rows_ok"] and c["columns_ok"] and c["grand_total_ok"] and c["diagonal_empty"] and c["sex_split_ok"]
    assert c["sum_of_flows"] == 60


def test_check_catches_a_misread_cell():
    g = _stock_grid()
    g[-1][7] = 50  # 天津 → 河北 misread (5): its row, its column and the sexes no longer add up
    c = check_matrix(read_matrix(g, CODES))
    assert not c["rows_ok"] and not c["columns_ok"] and not c["grand_total_ok"] and not c["sex_split_ok"]
    assert c["row_mismatches"] == [{"d": "130000", "table": 7, "sum_of_flows": 52}]
    assert c["column_mismatches"] == [{"o": "120000", "table": 20, "sum_of_flows": 65}]


def test_five_years_ago_matrix_with_within_and_abroad():
    """Shaped like 7-7: 合计, 本县市区, 本省其他县市区, the provinces, 港澳台或国外."""
    g = [["7-7  全国按现住地和五年前常住地分的人口"], [None, "单位：人"], ["现 住 地", "五年前常住地"],
         [None, "合计", "省      内", None, "省      外", None, None, "港澳台\n或国外"],
         [None, None, "本县市区", "本省其他", "北京", "天津", "河北"],
         [None, None, None, "县市区"],
         ["全    国", 1000, 850, 50, 10, "20", "30", 40],
         ["北    京", 500, 430, 20, None, "15", "25", 10],
         ["天    津", 300, 270, 15, "6", "", "5", 4],
         ["河    北", "200", 200 - 15 - 4 - 5 - 26, 15, 4, "5", None, 26]]
    m = read_matrix(g, CODES)
    assert m["within"]["110000"] == {"same_county": 430, "other_county": 20} and m["abroad"]["130000"] == 26
    assert m["flows"][("130000", "110000")] == 25 and ("120000", "120000") not in m["flows"]
    c = check_matrix(m)
    assert c["rows_ok"] and c["columns_ok"] and c["grand_total_ok"] and "sex_split_ok" not in c
    assert NATION not in m["row_total"]


def test_counts():
    assert count(None) is None and count("") is None and count("　") is None
    assert count("1,234") == 1234 and count(5480251.0) == 5480251 and count(" 83050 ") == 83050
    with pytest.raises(ValueError):
        count("12.5%")


def test_table_of_contents():
    html = ("<a href='html/ge08.jpg'><li id=\"foldheader\">第七卷　户口登记状况</li></a> <ul>"
            "<li><a href='html/A0703.jpg'>7-3 全国按现住地、性别分的户口登记地在外省的人口</a></li></ul>"
            "<a href='html/ge10.jpg'><li id=\"foldheader\">第二部分　长表数据资料</li></a>"
            "<a href='html/ge17.jpg'><li id=\"foldheader\">第七卷　迁移和户口登记地</li></a> <ul>"
            "<li><a href='html/B0707.jpg'>7-7 全国按现住地和五年前常住地分的人口</a></li></ul>")
    toc = parse_toc(html)
    assert toc["A0703"] == {"title": "7-3 全国按现住地、性别分的户口登记地在外省的人口", "part": None, "volume": "第七卷 户口登记状况"}
    assert toc["B0707"]["part"] == "第二部分 长表数据资料" and toc["B0707"]["volume"] == "第七卷 迁移和户口登记地"


def test_birthplace_matrix_keeps_the_diagonal_out_of_flows_but_in_the_totals():
    """Shaped like 7-6 (现住地 × 出生地). Here 北京's own column holds 7 people (the 2020 tables print 0 there, the 2010
    ones leave it blank): not a flow, but part of the row, the column and the grand total."""
    g = [["7-6  全国按现住地和出生地分的人口"], [None, "单位：人"], ["现 住 地", "出  生  地"],
         [None, "合计", "省      内", None, "省      外", None, None, "港澳台\n或国外"],
         [None, None, "本县市区", "本省其他", "北京", "天津", "河北"],
         [None, None, None, "县市区"],
         ["全    国", 1007, 850, 50, 17, 20, 30, 40],
         ["北    京", 507, 430, 20, 7, 15, 25, 10],
         ["天    津", 300, 270, 15, 6, 0, 5, 4],
         ["河    北", 200, 150, 15, 4, 5, None, 26]]
    m = read_matrix(g, CODES)
    assert m["diagonal"] == {"110000": 7, "120000": 0} and ("110000", "110000") not in m["flows"]
    assert m["flows"][("110000", "120000")] == 6 and len(m["flows"]) == 6
    c = check_matrix(m)
    assert c["rows_ok"] and c["columns_ok"] and c["grand_total_ok"]
    assert not c["diagonal_empty"] and c["diagonal_total"] == 7 and c["sum_of_flows"] == 60
    g[7][4] = 0  # without the 7, 北京's row and column and the grand total no longer reconcile
    c = check_matrix(read_matrix(g, CODES))
    assert not c["rows_ok"] and not c["columns_ok"] and not c["grand_total_ok"] and c["diagonal_empty"]


def test_population_for_the_sample_scale_is_the_people_not_the_households():
    """Table 1-1 各地区户数、人口数和性别比: 户数 合计 comes first, the 人口数 合计 is under 合计 | 男 | 女 | 性别比."""
    g = [["1-1  各地区户数、人口数和性别比"], [None, "单位：户、人"],
         ["地    区", "户       数", None, None, "人          口          数"],
         [None, "合计", "家庭户", "集体户", "合          计", None, None, None],
         [None, None, None, None, "合计", "男", "女", "性别比"],
         ["全    国", 522689264.0, 494157423.0, 28531841.0, 1409778724.0, 721416394.0, 688362330.0, 104.8],
         ["北    京", "8230000", "", "", "21893095", "11197000", "10696095", "104.7"]]
    assert read_population(g, {"北京": "110000"}) == {NATION: 1409778724, "110000": 21893095}
