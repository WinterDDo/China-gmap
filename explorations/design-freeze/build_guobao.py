"""全国重点文物保护单位, as the State Council listed them: sources/guobao_all.tsv

The owner's rule is that every name on a card can be traced to the official original. Until 2026-11-28 the names of
protected sites were Wikidata labels (a compiled copy); an independent read found 79 of 2,832 wrong. This reads the
lists themselves. Each row of a list gives a number, the unit's name, its era and its address.

  batch  year  where the original is                                           how it is read
  1      1961  国务院公报 1961 年第 4 号, pp. 80–89 (scan, www.gov.cn/gongbao/shuju)   sources/guobao_b1.tsv, transcribed
  2      1982  国务院公报 1982 年第 7 号, pp. 278–281 (scan)                          sources/guobao_b2.tsv, transcribed
  3      1988  国务院公报 1988 年第 4 号, pp. 104–116 (scan)                          sources/guobao_b3.tsv, transcribed
  4      1996  国务院公报 1996 年第 36 号, pp. 1458–1468 (scan)                       sources/guobao_b4.tsv, transcribed
  5      2001  国务院公报 2001 年第 24 号 (one tall picture on the gazette's page)     sources/guobao_b5.tsv, transcribed
  6      2006  国发〔2006〕19号, www.gov.cn/zwgk/2006-06/02/content_297818.htm         this program (b6.htm)
  7      2013  国发〔2013〕13号: no official copy within reach of this machine         see MISSING
  8      2019  国发〔2019〕22号, www.gov.cn/zhengce/content/2019-10/16/content_5440577.htm   this program (b8.htm)

A transcription is two readers working apart from the same pictures; where they differ the picture decides.
Items a later list folds into an earlier unit ("归入…", "与…合并") are parts of that unit, not units: left out.

Output, one line per listed unit:
    batch <tab> number in the batch <tab> code as printed <tab> section <tab> name <tab> era <tab> address <tab> cities
"cities" is where the address puts it, by the same strict reading as the heritage lists (build_feiyi.Places): a
prefecture named outright, or a county that belongs to exactly one prefecture of the province named before it.
An address of a whole province, or of a county since abolished, files nowhere: the column is empty and the unit
can still be placed by build_pride.py when a mapped site of the same name lies in that province.

Usage   python3 build_guobao.py <dir with b6.htm b8.htm> data
"""
import html
import os
import re
import sys
from collections import Counter

from build_feiyi import Places

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = "ⅠⅡⅢⅣⅤⅥ"
SECS = "一二三四五六"
# what each list states: the sections in order with the number of units, checked on every build
TOTALS = {
    6: [("古遗址", 220), ("古墓葬", 77), ("古建筑", 513), ("石窟寺及石刻", 63), ("近现代重要史迹及代表性建筑", 206), ("其他", 1)],
    8: [("古遗址", 167), ("古墓葬", 30), ("古建筑", 280), ("石窟寺及石刻", 39), ("近现代重要史迹及代表性建筑", 234), ("其他", 12)],
}
MISSING = {7: "国发〔2013〕13号 (1,943 units): the State Council's own page for it is gone and the heritage administration's site is not reachable from the cloud machine"}
# prefectures a list calls by an earlier name
OLD_PREF = {"襄樊市": "襄阳市", "思茅市": "普洱市", "思茅地区": "普洱市", "大庸市": "张家界市", "淮阴市": "淮安市", "锦西市": "葫芦岛市"}
PROV_NAMES = ["北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省", "黑龙江省", "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",
              "河南省", "湖北省", "湖南省", "广东省", "广西壮族自治区", "海南省", "重庆市", "四川省", "贵州省", "云南省", "西藏自治区", "陕西省", "甘肃省", "青海省",
              "宁夏回族自治区", "新疆维吾尔自治区"]
PROV_CODE = dict(zip(PROV_NAMES, ["11", "12", "13", "14", "15", "21", "22", "23", "31", "32", "33", "34", "35", "36", "37", "41", "42", "43", "44", "45", "46",
                                  "50", "51", "52", "53", "54", "61", "62", "63", "64", "65"]))
PROVS = re.compile("|".join(PROV_NAMES))
RARE = re.compile(r"字旁加|[\ue000-\uf8ff]|[\U00020000-\U0003ffff]")   # a name the page spells out because it cannot print it


def text_of(doc):
    """The page as lines; a table row becomes one line with its cells set apart by wide spaces, like the rest."""
    doc = re.sub(r"(?is)<(script|style).*?</\1>", "", doc)
    cell = lambda c: re.sub(r"[\s\u3000]+", "", html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", ""))
    # innermost rows only: the whole page sits in a layout table of its own
    doc = re.sub(r"(?is)<tr[^>]*>((?:(?!<tr).)*?)</tr>",
                 lambda m: "<br>" + "\u3000\u3000".join(cell(c) for c in re.findall(r"(?is)<td[^>]*>((?:(?!<td).)*?)</td>", m.group(1))) + "<br>", doc)
    doc = re.sub(r"(?i)<br\s*/?>|</p>", "\n", doc)
    return html.unescape(re.sub(r"<[^>]+>", "", doc)).replace("\xa0", " ")


ERA = re.compile(r"(?:(?:旧石器|新石器|青铜|铁器)(?:时代)?|时代|夏|商|西周|东周|周|春秋|战国|秦|西汉|东汉|汉|三国|魏|蜀|吴|西晋|东晋|晋|十六国|南北朝|南朝|北朝|"
                 r"北魏|东魏|西魏|北齐|北周|隋|唐|五代|十国|北宋|南宋|宋|辽|金|西夏|元|明|清|民国|近代|现代|[0-9]{2,4}|年|世纪|公元前|公元|[至、～~—－-])+$")


def sixth(path, prov_re):
    """Set with wide spaces in columns: number, code, name, era, address. Where a column is full the next one starts
    with no space between (新石器至青铜时代青海省乐都县), and eight entries run onto a second line, set under the
    name column or under the address column."""
    t = text_of(open(path, encoding="utf-8", errors="replace").read())
    t = t[t.index("第六批全国重点文物保护单位名单"):]
    t = t[:t.index("与现有全国重点文物保护单位合并")] if "与现有全国重点文物保护单位合并" in t else t
    rows, heads, sec = [], [], None
    for raw in t.split("\n"):
        line = raw.strip(" \u3000\t")
        if not line:
            continue
        m = re.match(r"([一二三四五六])、(.+?)（共计?(\d+)处）", line)
        if m:
            sec = m.group(2)
            heads.append((sec, int(m.group(3))))
            continue
        m = re.match(rf"(\d+)[\s\u3000]*([{ROM}])[\s\u3000]*[－\-—][\s\u3000]*(\d+)[\s\u3000]*(.*)$", line)
        if not m:
            if rows and sec and not re.match(r"序[\s\u3000]*号|编[\s\u3000]*号", line):
                indent = sum(2 if ch == "\u3000" else 1 for ch in raw[:len(raw) - len(raw.lstrip(" \u3000\t"))])
                piece = re.sub(r"[\s\u3000]+", "", line)
                rows[-1][6 if indent > 44 else 4] += piece      # under the address column, or under the name column
            continue
        toks = [x for x in re.split(r"[\s\u3000]+", m.group(4)) if x]
        # the address is the last piece that opens with a province (山西省立第三中学旧址 is a name)
        i = next((k for k in range(len(toks) - 1, 0, -1) if prov_re.match(toks[k])), None)
        if i is None:                       # era and address with no space between
            k = len(toks) - 1
            cut = [m.start() for m in prov_re.finditer(toks[k]) if m.start()][-1]
            toks[k:k + 1] = [toks[k][:cut], toks[k][cut:]]
            i = k + 1
        addr, front = "".join(toks[i:]), toks[:i]
        if len(front) == 1:                 # name and era with no space between
            cut = ERA.search(front[0]).start()
            cut += len(front[0][cut:]) - len(front[0][cut:].lstrip("、至～~—－-"))    # 万斯同、|明至民国
            front = [front[0][:cut], front[0][cut:]]
        assert len(front) == 2 and front[0] and front[1], line
        rows.append([6, int(m.group(1)), f"{m.group(2)}-{m.group(3)}", sec, front[0], front[1], addr])
    assert heads == TOTALS[6], heads
    return rows


def eighth(path):
    """A table: 序号, 编号 (8-0001-1-001), 名称, 时代, 地址; one table per section, the merged items in a last one."""
    doc = open(path, encoding="utf-8", errors="replace").read()
    doc = doc[doc.index("第八批全国重点文物保护单位名单"):]
    rows, heads, sec = [], [], None
    for part in re.split(r"(?i)<tr[^>]*>", doc):
        cells = [re.sub(r"[\s\u3000]+", "", html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", "")) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", part)]
        if len(cells) == 5 and re.fullmatch(r"8-\d{4}-\d-\d{3}", cells[1]):     # merged items carry 8-0000 and a sixth cell
            assert SECS[int(cells[1][7]) - 1] == SECS[len(heads) - 1], cells    # the code's own section digit
            rows.append([8, int(cells[0]), cells[1], sec, cells[2], cells[3], cells[4]])
        # a heading printed after this row's table belongs to the rows that follow
        for m in re.finditer(r"([一二三四五六])、([^（<]+)（共计(\d+)处）", re.sub(r"<[^>]+>", "", part)):
            sec = m.group(2)
            heads.append((sec, int(m.group(3))))
    assert heads == TOTALS[8], heads
    return rows


def transcribed(batch):
    """sources/guobao_b<n>.tsv: section numeral, number, number in section, name, era, address, note; '#' lines are
    the file's own account of how it was made, and '#HEAD numeral title count' lines the section headings."""
    path = os.path.join(HERE, "sources", f"guobao_b{batch}.tsv")
    if not os.path.exists(path):
        return None
    rows, heads = [], {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#HEAD"):
            _, num, title, n = line.split("\t")
            heads[num] = (title, int(n))
        elif line and not line.startswith("#"):
            sec, seq, cat, name, era, addr = (line.split("\t") + [""])[:6]
            if sec in heads:                # merged items (并) are parts of older units
                rows.append([batch, int(seq), f"{sec}-{cat}", heads[sec][0], name, era, addr])
    for num, (title, n) in heads.items():
        got = [r for r in rows if r[3] == title]
        assert len(got) == n, f"batch {batch} {title}: {len(got)} rows, the list states {n}"
    return rows


def checked(rows, batch):
    assert [r[1] for r in rows] == list(range(1, len(rows) + 1)), f"batch {batch}: numbers do not run 1..{len(rows)}"
    for sec in dict.fromkeys(r[3] for r in rows):
        nos = [int(re.split(r"-", r[2])[-1]) for r in rows if r[3] == sec]
        assert nos == list(range(1, len(nos) + 1)), f"batch {batch} {sec}: numbers in the section do not run 1..{len(nos)}"
    for r in rows:
        assert r[4] and r[6] and not re.search(r"\s", "".join(map(str, r))), r
    return rows


class Addresses(Places):
    def filed(self, addr):
        """Short names of the prefectures an address names, in order, each once. A line across the country
        (京杭大运河: six provinces) is no one city's own: three provinces or more files nowhere."""
        if len(self.segments(addr)) > 2:
            return []
        for prov, pname, seg in self.segments(addr):
            for c in self.by_prov[prov]:
                for old in (c["n"] + "盟", c["n"] + "行署", c["n"] + "专区"):     # 呼伦贝尔盟 is 呼伦贝尔市 now
                    if old != c["full"] and old in seg:
                        addr = addr.replace(old, c["full"])
        for old, new in OLD_PREF.items():
            addr = addr.replace(old, new)
        by_id = {c["id"]: c["n"] for c in self.cities}
        return list(dict.fromkeys(by_id[cid] for cid, _, _ in self.tokens(addr) if cid))


def build(src, out_dir):
    places = Addresses(out_dir)
    rows = []
    for batch in range(1, 9):
        got = transcribed(batch) if batch <= 5 else sixth(os.path.join(src, "b6.htm"), places.prov_re) if batch == 6 else eighth(os.path.join(src, "b8.htm")) if batch == 8 else None
        if got is None:
            print(f"batch {batch}: not in hand" + (f" — {MISSING[batch]}" if batch in MISSING else ""))
            continue
        rows += checked(got, batch)
    out, nowhere = [], Counter()
    for r in rows:
        cities = [] if RARE.search(r[4]) else places.filed(r[6])
        nowhere[r[0]] += not cities
        out.append("\t".join(map(str, r)) + "\t" + "、".join(cities))
    head = ["# 全国重点文物保护单位，按国务院公布名单原文。build_guobao.py 生成，不要手改。",
            "# 批次 <tab> 批内序号 <tab> 名单上的编号 <tab> 类别 <tab> 名称 <tab> 时代 <tab> 地址 <tab> 按地址归到的地级市（归不了的留空）"]
    head += [f"# 第 {b} 批还没读进来：{why}" for b, why in MISSING.items() if not any(r[0] == b for r in rows)]
    open(os.path.join(HERE, "sources", "guobao_all.tsv"), "w", encoding="utf-8").write("\n".join(head + out) + "\n")
    per = Counter(r[0] for r in rows)
    print("units:", dict(per), "total", len(rows))
    print("filed nowhere by address:", dict(nowhere), "renamed counties recognised:", len(places.renamed))
    return rows


def listed():
    """sources/guobao_all.tsv as rows: batch, number, code, section, name, era, address, [cities]"""
    rows = []
    for line in open(os.path.join(HERE, "sources", "guobao_all.tsv"), encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            r = line.rstrip("\n").split("\t")
            rows.append([int(r[0]), int(r[1])] + r[2:7] + [[c for c in r[7].split("、") if c]])
    return rows


def plain(name):
    """A name stripped for comparing: no brackets, no dashes or commas."""
    return re.sub(r"[（(].*?[）)]|[\s\u3000—－\-–、，,·・：:“”\"《》]", "", name)


def sounds(name):
    from pypinyin import lazy_pinyin
    return tuple(lazy_pinyin(name))


def alike(label, name):
    """How a mapped site's label stands to a listed name: ("same" | "same sound" | "inside" | "part" | "alike", score)."""
    a, b = plain(label), plain(name)
    if a == b:
        return "same", 1.0
    if len(a) == len(b) and sounds(a) == sounds(b):      # a label in traditional characters: 潮音橋 / 潮音桥
        return "same sound", 0.98
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 2 and short in long_:
        return "inside", 0.6 + 0.35 * len(short) / len(long_)
    parts = [plain(t) for t in re.split(r"[—－–、]", name)]      # 万里长城—八达岭
    if any(len(t) >= 3 and t in a for t in parts):
        return "part", 0.7
    import difflib
    return "alike", 0.8 * difflib.SequenceMatcher(None, a, b).ratio()


def names(found, cities, pairs=None):
    """Give each mapped site that carries the protected-site mark the row of the lists it is.
    found: city id -> {wikidata id -> {"name", "kinds", ...}} as build_pride gathers them.
    A site takes a listed row when the names are the same (or the same in sound, for a label in traditional
    characters) and the row's address puts it in that city — or names only the province, or a county since
    abolished there. Any looser likeness counts only when the pair is in sources/guobao_pairs.tsv, which was read
    by a person. Returns ({(city id, wikidata id): row}, [looser candidates for review])."""
    rows = listed()
    by_n = {c["n"]: cid for cid, c in cities.items()}
    by_city, loose = {}, {}
    for r in rows:
        if RARE.search(r[4]):
            continue
        for n in r[7]:
            by_city.setdefault(by_n[n], []).append(r)
        if not r[7]:
            for m in PROVS.finditer(r[6]):
                loose.setdefault(m.group(0), []).append(r)
    pairs = pairs if pairs is not None else read_pairs()
    sure, review = {}, []                 # listed row -> [(city id, wikidata id, links)] with the same name
    for cid in sorted(found):
        c = cities[cid]
        cands = by_city.get(cid, []) + [r for full, rs in loose.items() if c["prov"] == PROV_CODE[full] for r in rs]
        for q, e in found[cid].items():
            if "guobao" not in e["kinds"]:
                continue
            best = []
            for r in cands:
                how, sc = ("read", 2.0) if (q, r[0], r[1]) in pairs else alike(e["name"], r[4])
                if how in ("same", "same sound", "read"):
                    sure.setdefault((r[0], r[1]), []).append((cid, q, e["links"], r))
                elif sc >= 0.5:
                    best.append((sc, how, r))
            for sc, how, r in sorted(best, key=lambda t: -t[0])[:2]:
                review.append((c["n"], q, e["name"], r[0], r[1], r[4], r[6], how, round(sc, 2)))
    out, by_site = {}, {}
    for key, hits in sure.items():
        r = hits[0][3]
        if not r[7] and len({h[0] for h in hits}) > 1:      # the address names no city and two cities have a site of that name
            review += [(cities[cid]["n"], q, r[4], r[0], r[1], r[4], r[6], "two cities", 1.0) for cid, q, _, _ in hits]
            continue
        for cid in dict.fromkeys(h[0] for h in hits):       # one mapped site in each city the unit lies in: the best known
            cid, q, links, _ = max((h for h in hits if h[0] == cid), key=lambda h: h[2])
            by_site.setdefault((cid, q), []).append(r)
    for (cid, q), rs in by_site.items():
        if len(rs) == 1:
            out[(cid, q)] = rs[0]
        else:                                               # two listed units of one name in one city
            review += [(cities[cid]["n"], q, r[4], r[0], r[1], r[4], r[6], "two units", 1.0) for r in rs]
    done = {(cid, q) for cid, q in out}
    review = [v for v in review if (by_n[v[0]], v[1]) not in done or v[7] in ("two cities", "two units")]
    return out, review


def read_pairs():
    """sources/guobao_pairs.tsv: wikidata id <tab> label <tab> batch <tab> number <tab> listed name — pairs a reader approved."""
    path = os.path.join(HERE, "sources", "guobao_pairs.tsv")
    out = set()
    for line in open(path, encoding="utf-8") if os.path.exists(path) else ():
        if line.strip() and not line.startswith("#"):
            q, _, batch, seq = line.rstrip("\n").split("\t")[:4]
            out.add((q, int(batch), int(seq)))
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
