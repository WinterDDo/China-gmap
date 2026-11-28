"""Culture for the hometown card: national intangible cultural heritage, filed under the city that declared it.

The State Council has published five lists (2006, 2008, 2011, 2014, 2021). Each row gives the item's code, its name
and the place or body that declared it ("申报地区或单位"). This reads the first four notices as saved from www.gov.cn,
and the fifth, which is published as pictures of tables, from a transcription (sources/feiyi_b5.tsv, see fifth()),
and writes sources/feiyi_all.tsv:

    city <tab> category <tab> name shown <tab> batch and code <tab> item name as printed @ declaring places <tab> declared by

Filing rules, strict on purpose ("宁少勿错"):
  - a declaring place counts only when it names a prefecture of ours, or a county that belongs to exactly one of our
    prefectures within the province named before it. A whole province, a ministry, a renamed county: left out.
  - "name shown" is the sub-item named after the place (武山旋鼓舞 for 武山县) when the row lists sub-items; when the
    sub-items and the places are the same number, the one in the same position, unless it names another place of the
    row; otherwise the item's own name.
The counts are checked against the totals each notice states.

Usage   python3 build_feiyi.py <dir with the notices> data
"""
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict

NOTICES = [  # file, batch, lists in order with the number of rows the notice states
    ("content_297946.htm", "B1", "text", [518]),
    ("content_1016331.htm", "B2", "text", [510, 147]),
    ("content_1880635.htm", "B3", "table", [191, 164]),
    ("content_9286.htm", "B4", "table", [153, 153]),
]
CATS = {"Ⅰ": "民间文学", "Ⅱ": "传统音乐", "Ⅲ": "传统舞蹈", "Ⅳ": "传统戏剧", "Ⅴ": "曲艺", "Ⅵ": "传统体育、游艺与杂技", "Ⅶ": "传统美术", "Ⅷ": "传统技艺", "Ⅸ": "传统医药", "Ⅹ": "民俗"}
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
# rows the saved page prints in a way an independent reader doubted: left out until checked against another copy
# the fifth list, section by section as pictured: its numeral and the number of items the notice states
FIFTH = [("Ⅰ", 12), ("Ⅱ", 19), ("Ⅲ", 13), ("Ⅳ", 9), ("Ⅴ", 18), ("Ⅵ", 27), ("Ⅶ", 17), ("Ⅷ", 46), ("Ⅹ", 24),
         ("Ⅰ", 9), ("Ⅱ", 8), ("Ⅲ", 9), ("Ⅳ", 14), ("Ⅴ", 2), ("Ⅵ", 13), ("Ⅶ", 22), ("Ⅷ", 36), ("Ⅸ", 11), ("Ⅹ", 16)]
DOUBT = {("B2x", "Ⅶ-50", "镇江")}
WAS_PREFECTURE = {"思茅市", "莱芜市"}   # prefecture-level when the notice was printed: the city is right, no one county declared it
COUNTY_DOUBT = {("揭阳", "揭东区"), ("杭州", "余杭区")}   # the county has been split since; which part holds the item is not checked   # 灯彩: the page prints 江苏省句容市 where 秦淮灯彩 (南京) is expected
LATIN = dict(zip(["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"], ROMAN))
WS = " \t 　"
HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = os.path.join(HERE, "..", "..", "pipeline", "reference", "names.json")


def width(s):
    return sum(2 if ch == "　" else 1 for ch in s)


def text_rows(doc, find_prov):
    """Lists laid out with spaces: number, code, name, place; long names and place lists wrap onto following lines.
    The section heading (十、民俗（共计70项）) gives the category and the number of rows to expect: the first notice
    prints the numeral Ⅸ on every row of its tenth section, so the numeral is taken from the section, not the row."""
    body = re.sub(r"(?is)<(script|style).*?</\1>", "", doc)
    body = re.sub(r"(?i)<br\s*/?>|</p>", "\n", body)
    lines = html.unescape(re.sub(r"<[^>]+>", "", body)).split("\n")
    def cut(piece):   # a name and a place set with a single space between them: the place starts at the province
        m = find_prov(piece)
        return (piece[:m.start()].strip(WS), piece[m.start():]) if m else (piece, "")

    rows, cur, sec, stated = [], None, None, []
    head = re.compile(r"^[\s\u3000\u00a0]*([一二三四五六七八九十])、.*?共计[\s\u00a0]*(\d+)[\s\u00a0]*项")
    start = re.compile(rf"^[{WS}]*(\d+)[{WS}]+([{ROMAN}]+)[{WS}]*[—\-－–][{WS}]*(\d+)[{WS}]+(.*)$")
    for raw in lines:
        if not raw.strip(WS):
            continue
        h = head.match(raw)
        if h:
            sec, cur = "一二三四五六七八九十".index(h.group(1)), None
            stated.append([sec, int(h.group(2)), 0])
            continue
        m = start.match(raw)
        if m:
            cur = {"no": int(m.group(1)), "code": f"{ROMAN[sec]}-{m.group(3)}", "name": "", "place": []}
            rows.append(cur)
            stated[-1][2] += 1
            parts = [p.strip(WS) for p in re.split(rf"[{WS}]{{2,}}", m.group(4).strip(WS)) if p.strip(WS)]
            cur["name"], tail = cut(parts[0])
            if tail or len(parts) > 1:
                cur["place"].append(tail + "".join(parts[1:]))
            continue
        if cur is None or not raw[0] in WS or re.search(r"共计\d+项|序号|项目名称", raw):
            cur = None if re.search(r"共计\d+项|序号|名录", raw) else cur
            continue
        lead = width(raw[:len(raw) - len(raw.lstrip(WS))])
        parts = [p.strip(WS) for p in re.split(rf"[{WS}]{{2,}}", raw.strip(WS)) if p.strip(WS)]
        if len(parts) == 1 and lead >= 30:   # a line set in the place column is all place, even with a second province in it
            cur["place"].append(parts[0])
            continue
        front, tail = cut(parts[0])
        if tail or len(parts) >= 2:     # a province marks a declaring place, wherever it sits on the line
            cur["name"] += front
            cur["place"].append(tail + "".join(parts[1:]))
        else:
            cur["name"] += parts[0]
    for sec, want, got in stated:
        assert want == got, f"section {sec + 1}: the notice states {want} rows, read {got}"
    return rows


def table_rows(doc):
    rows = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", doc):
        cells = [re.sub(r"\s+", "", html.unescape(re.sub(r"(?is)<[^>]+>", "", td))) for td in re.findall(r"(?is)<td[^>]*>(.*?)</td>", tr)]
        m = len(cells) == 4 and re.fullmatch(r"\d+", cells[0]) and re.fullmatch(rf"([{ROMAN}]|[IVX]+)[—\-－–](\d+)", cells[1])
        if m:   # some rows of the third notice type the numeral in Latin letters (IV-91)
            rows.append({"no": int(cells[0]), "code": f"{LATIN.get(m.group(1), m.group(1))}-{m.group(2)}", "name": cells[2], "place": [cells[3]]})
    return rows


def split_lists(rows, sizes):
    """A notice prints its new items first (numbers run on), then the extension list (numbers of earlier items)."""
    if len(sizes) == 1:
        return [rows]
    return [rows[:sizes[0]], rows[sizes[0]:]]


class Places:
    def __init__(self, out_dir):
        names = json.load(open(NAMES, encoding="utf-8"))
        self.provs = {v["zh_full"]: k[:2] for k, v in names.items() if v.get("level") == "province"}
        self.cities = json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))
        self.by_prov = defaultdict(list)
        for c in self.cities:
            self.by_prov[c["prov"]].append(c)
        cv = json.load(open(os.path.join(out_dir, "cityview.json"), encoding="utf-8"))
        self.counties = defaultdict(lambda: defaultdict(set))   # province -> county full name -> prefectures
        self.cores = defaultdict(set)                           # prefecture -> short names of itself and its counties
        for c in self.cities:
            self.cores[c["id"]].add(c["n"])
            for r in cv["counties"].get(c["id"], []):
                self.counties[c["prov"]][r[1]].add(c["id"])
                core = r[6] if len(r) > 6 and r[6] else re.sub(r"(自治县|县|区|市|旗)$", "", r[1])
                if len(core) >= 2:
                    self.cores[c["id"]].add(core)
        self.renamed = {}                                       # old county name as printed -> its name today
        self.prov_re = re.compile("|".join(sorted(map(re.escape, self.provs), key=len, reverse=True)))

    def segments(self, text):
        """[(province code, text after its name up to the next province)]"""
        ms = list(self.prov_re.finditer(text))
        return [(self.provs[m.group(0)], m.group(0), text[m.end():(ms[i + 1].start() if i + 1 < len(ms) else len(text))]) for i, m in enumerate(ms)]

    def tokens(self, text):
        """Every declaring place of a row, in order: (prefecture id or None, the words as printed, core name)."""
        out = []
        for prov, pname, seg in self.segments(text):
            direct = [c for c in self.by_prov[prov] if c["full"] == pname]   # a municipality is its own prefecture
            toks = [t for t in re.split(r"[、，,；;。\s]+", seg) if t]
            if not toks:
                out.append((direct[0]["id"] if direct else None, pname, pname if direct else ""))
                continue
            last = None
            for t in toks:
                cid, core = None, t
                # the prefecture must open the token: 眉山市 is inside 峨眉山市, which belongs to 乐山
                pref = sorted((c for c in self.by_prov[prov] if t.startswith(c["full"])), key=lambda c: -len(c["full"]))
                if not pref:    # a prefecture the notice still calls 地区: 铜仁地区, 哈密地区
                    old = [c for c in self.by_prov[prov] if t.startswith(c["n"] + "地区")]
                    if len(old) == 1:
                        pref, t = old, t.replace(old[0]["n"] + "地区", old[0]["full"], 1)
                if direct:
                    cid, last = direct[0]["id"], direct[0]["id"]
                elif pref:
                    cid, last = pref[0]["id"], pref[0]["id"]
                    core = t.replace(pref[0]["full"], "") or t
                else:
                    owners = {o for name, ids in self.counties[prov].items() if t.startswith(name) for o in ids}
                    if not owners:      # a county since made a district or a city keeps its name: 湟中县 is 湟中区, 同仁县 is 同仁市
                        m = re.fullmatch(r"(.{2,}?)(自治县|县|市|区|旗)", t)
                        now = {name: ids for name, ids in self.counties[prov].items() if m and re.fullmatch(re.escape(m.group(1)) + r"(县|市|区|旗)", name)}
                        if len(now) == 1 and len(next(iter(now.values()))) == 1:
                            owners, self.renamed[t] = next(iter(now.values())), next(iter(now))
                    if len(owners) == 1:
                        cid = next(iter(owners))
                    elif last and last in owners:
                        cid = last          # 甘肃省武威市凉州区、古浪县: the county follows its prefecture
                out.append((cid, t, re.sub(r"(自治县|自治州|地区|县|区|市|旗|盟)$", "", core)))
        return out


def split_item(name):
    """(item, [sub-items]) for a name that ends in a bracketed list; (name, []) for any other name.
    Brackets nest: 剪纸（…、泉州（李尧宝）刻纸、…）; and an item can carry its own: 抬阁（芯子、铁枝、飘色）（葛渔城重阁会、…）."""
    if not name or name[-1] not in "）)":
        return name, []
    depth = 0
    for k in range(len(name) - 1, -1, -1):
        depth += (name[k] in "）)") - (name[k] in "（(")
        if depth == 0:
            break
    if depth or k == 0:
        return name, []
    subs, cur, d = [], "", 0
    for ch in name[k + 1:-1]:
        d += (ch in "（(") - (ch in "）)")
        if ch in "、，," and d == 0:
            subs.append(cur)
            cur = ""
        else:
            cur += ch
    return name[:k], [x for x in subs + [cur] if x]


def shown(name, toks, i, places):
    """The words to print for the i-th declaring place of a row.

    An independent read of every row with sub-items (2026-11-28) found position reliable and name-matching not:
    黄山区 declared 太平猴魁, yet "黄山" also occurs in 黄山毛峰. So position decides first, a name only after it."""
    main, subs = split_item(name)
    if not subs:
        return name
    cid, _, core = toks[i]

    def label(sub):   # as the list prints it, 豫剧（桑派）; the sub-item alone when it carries the item's own word (武山旋鼓舞) or is long
        return sub if main in sub or sub[-2:] == main[-2:] or "（" in main + sub or len(main) + len(sub) > 12 else f"{main}（{sub}）"

    if len(toks) == 1:                                  # one place: its one sub-item, or the item itself when it lists several
        return label(subs[0]) if len(subs) == 1 else main
    if len(subs) == len(toks):                          # as many sub-items as places: the one in the same position,
        foreign = {t[2] for t in toks if t[0] != cid and len(t[2]) >= 2}
        if not any(o in subs[i] for o in foreign):      # unless it carries the name of a place in another city
            return label(subs[i])
    own = [x for x in subs if len(core) >= 2 and core in x]
    if len(own) == 1:                                   # 武山旋鼓舞 for 武山县
        return label(own[0])
    claimed = {x for j, t in enumerate(toks) if j != i for x in subs if len(t[2]) >= 2 and t[2] in x}
    wide = [x for x in subs if x not in claimed and any(len(k) >= 2 and k in x for k in places.cores[cid])]
    if len(wide) == 1:                                  # named after the city or another of its counties
        return label(wide[0])
    return main


def fifth(path):
    """The fifth list (国发〔2021〕8号) is published as pictures of tables. sources/feiyi_b5.tsv is a transcription made by
    two readers working apart, with every difference between them settled against the picture. In these tables each row
    carries its own name, 中医诊疗法（丁氏推拿疗法）, and its own place, so nothing has to be paired up by position.
    Returns [(batch label, [rows])], after checking each section against the total the notice states."""
    by_sec = defaultdict(list)
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        sec, no, code, name, place = (line.rstrip("\n").split("\t") + [""])[:5]
        by_sec[sec].append({"no": int(no), "code": code, "name": name, "place": [place]})
    parts = {"B5": [], "B5x": []}
    for k, (numeral, stated) in enumerate(FIFTH):
        sec, rows = f"p{k + 1:02d}", by_sec[f"p{k + 1:02d}"]
        assert len({r["no"] for r in rows}) == stated, f"fifth list {sec}: the notice states {stated} items, the transcription has {len({r['no'] for r in rows})}"
        assert all(r["code"].startswith(numeral + "-") for r in rows), f"fifth list {sec}: a code outside {numeral}"
        parts["B5" if k < 9 else "B5x"] += rows
    nos = sorted({r["no"] for r in parts["B5"]})
    assert nos == list(range(1373, 1558)), "fifth list: the new items' numbers do not run 1373 to 1557"
    return list(parts.items())


def build(src, out_dir):
    places = Places(out_dir)
    by_id = {c["id"]: c for c in places.cities}
    out, seen, lost, stats = [], set(), Counter(), []

    def file_rows(label, part):
        filed = 0
        for r in part:
            assert r["name"] and r["code"][0] in CATS, (label, r)
            text = ""
            for piece in r["place"]:
                text += ("；" if text and places.prov_re.match(piece) else "") + piece
            toks = places.tokens(text)
            for i, (cid, word, core) in enumerate(toks):
                if not cid:
                    lost[word] += 1
                    continue
                name = shown(r["name"], toks, i, places)
                # not fit to show: the page spells out a character it cannot print (蚂虫另（虫字旁加另）节) or uses a
                # private-use one (阿坝's 㑇舞); or the saved page is in doubt (see DOUBT)
                if "字旁加" in name or re.search("[\ue000-\uf8ff]", name) or (label, r["code"], by_id[cid]["n"]) in DOUBT:
                    lost["（" + name + "）"] += 1
                    continue
                key = (cid, name)
                if key in seen:
                    continue
                seen.add(key)
                filed += 1
                rest = word.replace(by_id[cid]["full"], "")
                by = next((n for n in sorted(places.counties[by_id[cid]["prov"]], key=len, reverse=True) if rest.startswith(n) and cid in places.counties[by_id[cid]["prov"]][n]), "")
                by = by or places.renamed.get(rest, "")
                if rest in WAS_PREFECTURE or (by_id[cid]["n"], by) in COUNTY_DOUBT:
                    by = ""
                out.append([by_id[cid]["n"], CATS[r["code"][0]], name, f"{label} {r['code']}", f"{r['name']} @ {text}", by])
        stats.append((label, len({r["no"] for r in part}), filed))

    for fname, batch, kind, sizes in NOTICES:
        doc = open(os.path.join(src, fname), "rb").read().decode("utf-8")
        rows = text_rows(doc, places.prov_re.search) if kind == "text" else table_rows(doc)
        assert len(rows) == sum(sizes), f"{fname}: read {len(rows)} rows, the notice states {sizes}"
        for which, part in enumerate(split_lists(rows, sizes)):
            if which == 0:
                nos = [r["no"] for r in part]
                assert nos == list(range(nos[0], nos[0] + len(nos))), f"{fname}: numbers do not run on"
            file_rows(batch + ("x" if which else ""), part)
    b5 = os.path.join(HERE, "sources", "feiyi_b5.tsv")
    for label, part in fifth(b5) if os.path.exists(b5) else []:
        file_rows(label, part)
    with open(os.path.join(HERE, "sources", "feiyi_all.tsv"), "w", encoding="utf-8") as f:
        f.write("# 国家级非物质文化遗产代表性项目名录，按申报地区归到地级市。由 build_feiyi.py 从国务院五批公布通知（www.gov.cn）读出，不要手改。\n")
        f.write("# 第五批（国发〔2021〕8号）以图片公布，抄录在 sources/feiyi_b5.tsv；批次后带 x 的是扩展项目名录。出处网址见 sources/feiyi_food.tsv 文件头。\n")
        f.write("# 第一批通知的网页把第十部分（民俗）每一行的编号印成 Ⅸ，这里按所在部分记为 Ⅹ。\n")
        f.write("# 列：城市、门类、卡上显示的名字、批次与项目编号、名录原文（项目名 @ 申报地区或单位）、申报的县区（地级市本身申报则空）\n")
        for r in out:
            f.write("\t".join(r) + "\n")
    for st in stats:
        print("%s: %d items in the notice, %d filings under a city" % st)
    per = Counter(r[0] for r in out)
    print(f"{len(out)} filings, {len(per)} cities; without any: {[c['n'] for c in places.cities if c['n'] not in per]}")
    print("counties matched under today's name:", sorted(places.renamed.items()))
    print("declaring places left out, most frequent:", lost.most_common(40))
    return out


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
