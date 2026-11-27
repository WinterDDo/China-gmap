"""Bulletin text → headline fields, each with the exact sentence it came from.

parse_fields(text, year) returns {field: {value, unit, raw, quote} | None} for FIELDS. `value` is in the field's
canonical unit (亿元, 万人, 元, %); `raw` is the number and unit as printed ("1234567万元"); `quote` is the whole
sentence of `text` that holds it, verbatim (full-width digits and all). A field the text does not state is None –
never 0, never taken from another year.

How a value is found: the first sentence (in reading order) where the field's keyword is followed, within the same
clause, by a number with an acceptable unit. Sentences about another period are skipped: the 最终核实/修订 notes on
the previous year, anything dated to a different year before the keyword, quarters and half-years. Words that are not
the field are excluded by their prefix (人均地区生产总值, 城镇常住人口, 户籍人口, 万元地区生产总值能耗 …) or by a stop
word in between (中位数, 占…比重). Values introduced by 突破/超过 ("突破5000亿元，达到5123.4亿元") are skipped in favour of
the next number. Growth is read in the GDP sentence after the GDP figure ("比上年增长6.1%", "下降2.0%", "持平"). Table
rows (" | "-separated lines from htmltext.to_text) are a fallback for the money and population fields.

validate(fields, level) returns flags: the three industries must add up to GDP within 1%, and every value must lie in
a plausible range for a city, province or the nation.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from functools import lru_cache

FIELDS = {
    # key: (label, canonical unit)
    "gdp": ("地区生产总值", "亿元"),
    "gdp_primary": ("第一产业增加值", "亿元"),
    "gdp_secondary": ("第二产业增加值", "亿元"),
    "gdp_tertiary": ("第三产业增加值", "亿元"),
    "gdp_growth": ("地区生产总值实际增长", "%"),
    "population": ("年末常住人口", "万人"),
    "population_registered": ("年末户籍人口", "万人"),
    "urbanization": ("常住人口城镇化率", "%"),
    "income": ("全体居民人均可支配收入", "元"),
    "income_urban": ("城镇居民人均可支配收入", "元"),
    "income_rural": ("农村居民人均可支配收入", "元"),
    "budget_revenue": ("一般公共预算收入", "亿元"),
    "retail_sales": ("社会消费品零售总额", "亿元"),
}

# --------------------------------------------------------------------- normalisation

# one-to-one character replacements only, so indices into the normalised text are indices into the original;
# U+00B7 (·) is sometimes typed for a decimal point ("7534·2亿元")
_FULLWIDTH = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH.update({ord("．"): ord("."), ord("％"): ord("%"), ord("﹪"): ord("%"), ord("　"): ord(" "),
                   ord("\xa0"): ord(" "), ord("﹒"): ord("."), ord("·"): ord("."), ord("（"): ord("("),
                   ord("）"): ord(")"), ord("："): ord(":"), ord("～"): ord("~"), ord("－"): ord("-")})
_FULLWIDTH.update({ord("Ａ") + i: ord("A") + i for i in range(26)})
_FULLWIDTH.update({ord("ａ") + i: ord("a") + i for i in range(26)})
_NOTE_MARK = re.compile(r"\[\d{1,2}\]|［\d{1,2}］|〔\d{1,2}〕")  # footnote markers: 第一产业[3]增加值


def normalize(text: str) -> str:
    """Same length as `text`: full-width digits, letters, %, ., parentheses and spaces become ASCII, and footnote
    markers ("[3]") become spaces, so indices into the normalised text are indices into the original."""
    return _NOTE_MARK.sub(lambda m: " " * len(m.group()), text.translate(_FULLWIDTH))


NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"  # 4338.3 / 1,234.5 (thousands commas)
_SENT_END = "。！？!?\n"


def to_number(raw: str) -> float:
    return float(raw.replace(",", ""))


MONEY = {"万亿元": 10000.0, "亿元": 1.0, "万元": 1e-4, "元": 1e-8}  # → 亿元
PEOPLE = {"万人": 1.0, "人": 1e-4}  # → 万人
YUAN = {"元": 1.0, "万元": 1e4}  # → 元
PERCENT = {"%": 1.0}

_STOP_BETWEEN = re.compile(r"中位数|占|比重|比上年|同比|增长|下降|增加|减少|其中|人均|平均|累计|季度|上半年|月份|能耗|"
                           r"税收|非税|个百分点|分别|户籍|城镇|农村|乡村|城市|总值的|出生|死亡|迁入|迁出|自然增长")
# sentences (text before the keyword) about something else than this year's figure: revision notes on the previous
# year, census results ("第七次全国人口普查结果显示，…", but not "比2020年第七次人口普查增加…"), quarters, months
_SKIP_SENT = re.compile(r"最终核实|核实|修订|修正为|普查(?:结果|数据|显示|公报|登记|主要)|根据[^，。]{0,20}普查|"
                        r"上半年|前三季度|一季度|二季度|三季度|四季度|1-\d+月|1～\d+月")
_BREAKTHROUGH = re.compile(r"(?:突破|超过|超|迈上|跨越|跃上|站上|跨上|越过|过)\s*$")
# "突破千亿元大关，达到…", "首次迈入千亿大关,达…", "突破700亿，达到…", "突破四千亿大关、达到…"
_MILESTONE = re.compile(r"\s*(?:经济)?(?:总量)?(?:首次|再次|成功|一举)?(?:实现|完成)?(?:突破|超过|迈上|迈入|迈过|跨越|跃上|站上|跨上|越过)"
                        r"[^，,、。；]{1,12}[，,、]\s*(?:总量)?(?:达到|达|为|实现|完成)\s*")


def sentences(text: str):
    """(start, end) spans of the sentences of `text` (split after 。！？ and at line breaks)."""
    start = 0
    for i, ch in enumerate(text):
        if ch in _SENT_END:
            if i + 1 > start:
                yield start, i + 1 if ch != "\n" else i
            start = i + 1
    if start < len(text):
        yield start, len(text)


@lru_cache(maxsize=4)
def _spans(text: str) -> tuple[list[int], list[tuple[int, int]]]:
    spans = list(sentences(text))
    return [a for a, _ in spans], spans


def _sentence_at(text: str, pos: int) -> tuple[int, int]:
    starts, spans = _spans(text)
    i = bisect_right(starts, pos) - 1
    if i >= 0 and spans[i][0] <= pos < spans[i][1]:
        return spans[i]
    return 0, len(text)


def _quote(orig: str, a: int, b: int) -> str:
    return orig[a:b].strip()


def _other_year_before(norm: str, sent_start: int, pos: int, year: int | None) -> bool:
    """True if the clause before `pos` is dated to another year ("2022年，全市生产总值…")."""
    if year is None:
        return False
    # a year after 比/较/与/同 is a comparison ("比2020年第七次人口普查增加…"), not the date of the figure
    years = [int(y) for y in re.findall(r"(?<![比较与同从])(20\d\d)年", norm[sent_start:pos])]
    return bool(years) and years[-1] != year


def _find_value(norm: str, keyword: str, units: dict[str, float], *, year: int | None, exclude_before: str = "",
                filler: int = 12, allow_stop: str | None = None, extra_stop: str | None = None, start: int = 0,
                end: int | None = None):
    """First (sentence span, match span, value, raw) where `keyword` is followed in its clause by NUM+unit.

    `exclude_before`: regex of prefixes that disqualify the keyword (tested against the 6 preceding characters).
    The text between keyword and number ("gap") may hold up to `filler` characters, no comma and none of the stop
    words (except those matching `allow_stop`; `extra_stop` adds field-specific ones). A number introduced by
    突破/超过 is replaced by the next one. Only keywords starting in norm[start:end] are considered."""
    unit_re = "|".join(sorted((re.escape(u) for u in units), key=len, reverse=True))
    num_unit = re.compile(NUM + r"\s*(" + unit_re + r")(?!\s*(?:台阶|大关|关口))")
    for m in re.compile(keyword).finditer(norm, start, len(norm) if end is None else end):
        if exclude_before and re.search(f"(?:{exclude_before})$", norm[max(0, m.start() - 6): m.start()]):
            continue
        sa, sb = _sentence_at(norm, m.start())
        if _SKIP_SENT.search(norm[sa: m.start()]) or _other_year_before(norm, sa, m.start(), year):
            continue
        clause_end = min([i for i in (norm.find(c, m.end(), sb) for c in "；;") if i != -1] + [sb])
        nm = num_unit.search(norm, m.end(), clause_end)
        if not nm:
            continue
        gap = norm[m.end(): nm.start()]
        if _MILESTONE.fullmatch(gap):  # "突破千亿元大关，达到1041.7亿元": the milestone has no digits
            gap = ""
        stops = [w for w in _STOP_BETWEEN.findall(gap) if not (allow_stop and re.fullmatch(allow_stop, w))]
        if extra_stop and re.search(extra_stop, gap):
            stops.append(gap)
        if len(gap) > filler or re.search(r"[，,、]", gap) or stops:
            continue
        if _BREAKTHROUGH.search(gap):  # "突破5000亿元，达到5123.4亿元": the figure is the next number
            nxt = num_unit.search(norm, nm.end(), clause_end)
            between = norm[nm.end(): nxt.start()] if nxt else ""
            if not nxt or len(between) > 12 or _STOP_BETWEEN.search(between):
                continue
            nm = nxt
        raw_num, unit = nm.group(1), nm.group(2)
        return (sa, sb), (m.start(), nm.end()), to_number(raw_num) * units[unit], f"{raw_num}{unit}"
    return None


def _field(orig: str, hit, unit: str, digits: int = 6) -> dict | None:
    if not hit:
        return None
    (sa, sb), _span, value, raw = hit
    return {"value": round(value, digits), "unit": unit, "raw": raw.replace(" ", ""), "quote": _quote(orig, sa, sb)}


# --------------------------------------------------------------------- field finders

_GDP_KW = r"(?:地区|国内)?生产总值(?:\s*\((?:GDP)\))?|GDP"
_GDP_EXCL = r"人均|人均地区|单位|万元|每万元|亿元|季度|半年|民营经济|县域|数字经济|海洋|旅游"


_GDP_GROWTH_FIRST = re.compile(
    r"(?:地区|国内)?生产总值(?:\s*\(GDP\))?(?:按[^，。]{2,8}计算[，,]?)?(?:比上年|同比)?(增长|下降)" + NUM + r"\s*%[，,]\s*"
    r"(?:经济)?(?:总量)?(?:达到|达|为|实现|完成)?\s*" + NUM + r"\s*(万亿元|亿元|万元)")


def _gdp(norm: str, orig: str, year: int | None):
    """GDP and the hit (spans) it came from; also returns the growth when it is printed before the value."""
    hit = _find_value(norm, _GDP_KW, MONEY, year=year, exclude_before=_GDP_EXCL, filler=16)
    m = _GDP_GROWTH_FIRST.search(norm)
    if m and (hit is None or m.start() < hit[1][0]):
        sa, sb = _sentence_at(norm, m.start())
        before = norm[max(0, m.start() - 6): m.start()]
        if not (re.search(f"(?:{_GDP_EXCL})$", before) or _SKIP_SENT.search(norm[sa: m.start()])
                or _other_year_before(norm, sa, m.start(), year)):
            g = to_number(m.group(2)) * (-1 if m.group(1) == "下降" else 1)
            growth = {"value": round(g, 3), "unit": "%", "raw": f"{m.group(1)}{m.group(2)}%", "quote": _quote(orig, sa, sb)}
            value = to_number(m.group(3)) * MONEY[m.group(4)]
            return None, {"value": round(value, 6), "unit": "亿元", "raw": f"{m.group(3)}{m.group(4)}",
                          "quote": _quote(orig, sa, sb)}, growth
    return hit, _field(orig, hit, "亿元"), None


def _growth_after(norm: str, orig: str, hit) -> dict | None:
    """Real growth of GDP: the first 增长/下降 x% (or 持平) after the GDP figure, before the industries."""
    if not hit:
        return None
    (sa, sb), (_ka, kb), _v, _raw = hit
    seg_end = sb
    m_ind = re.search(r"第[一二三]产业|一产|其中", norm[kb:sb])
    if m_ind:
        seg_end = kb + m_ind.start()
    seg = norm[kb:seg_end]
    m = re.search(r"(增长|下降|回落|减少)\s*" + NUM + r"\s*%", seg)
    # a nominal rate is not the real growth; "（现价）" right after the value labels the value, not the rate
    if m and not re.search(r"名义|现价", re.split(r"[，,]", seg[: m.start()])[-1]):
        v = to_number(m.group(2)) * (-1 if m.group(1) in ("下降", "回落", "减少") else 1)
        return {"value": round(v, 3), "unit": "%", "raw": m.group(0).replace(" ", ""), "quote": _quote(orig, sa, sb)}
    if re.search(r"(?:与上年|同比)?持平", seg):
        return {"value": 0.0, "unit": "%", "raw": "持平", "quote": _quote(orig, sa, sb)}
    return None


_IND_KW = {"gdp_primary": "一", "gdp_secondary": "二", "gdp_tertiary": "三"}


INDUSTRY_WINDOW = 800  # characters after the GDP sentence where its breakdown by industry is looked for


def _industries(norm: str, orig: str, year: int | None, gdp_at: int | None = None) -> dict[str, dict | None]:
    """The three industries. With `gdp_at` (start of the GDP sentence) only the passage that follows it is read, so
    a county's or district's breakdown further down is never taken for the whole unit's."""
    out: dict[str, dict | None] = {}
    start, end = (0, None) if gdp_at is None else (gdp_at, gdp_at + INDUSTRY_WINDOW)
    # "第一、二、三产业增加值分别为a亿元、b亿元和c亿元"
    m = re.search(r"第一(?:产业)?[、，和]\s*(?:第)?二(?:产业)?[、，和]\s*(?:第)?三产业(?:的)?增加值分别(?:为|是|达到|实现|完成)?\s*"
                  + NUM + r"\s*(亿元|万元)?\s*[、，,]\s*" + NUM + r"\s*(亿元|万元)?\s*[、，,和及]\s*" + NUM + r"\s*(亿元|万元)",
                  norm[start:end] if end else norm[start:])
    if m:
        m_start = start + m.start()
        sa, sb = _sentence_at(norm, m_start)
        if not _other_year_before(norm, sa, m_start, year):
            for i, key in enumerate(("gdp_primary", "gdp_secondary", "gdp_tertiary")):
                raw, unit = m.group(1 + 2 * i), m.group(2 + 2 * i) or m.group(6)  # "2332、33953和46268亿元"
                out[key] = {"value": round(to_number(raw) * MONEY[unit], 6), "unit": "亿元",
                            "raw": f"{raw.strip()}{unit}", "quote": _quote(orig, sa, sb)}
            return out
    for key, n in _IND_KW.items():
        kw = (rf"第{n}产业\s*(?:\([^)]{{1,6}}\))?\s*(?:实现|完成)?(?:的)?\s*增加值"  # 第三产业（服务业）实现增加值
              rf"|第{n}产业(?=\s*(?:实现|完成)?\s*\d)|{n}产(?:业)?增加值")
        hit = _find_value(norm, kw, MONEY, year=year, exclude_before=r"季度|半年", filler=8, start=start, end=end)
        out[key] = _field(orig, hit, "亿元")
    return out


# residents counted by a service, not the residents: "常住人口签约251.67万人" (family-doctor sign-ups), 建档, 体检, 参保
_POP_STOP = r"签约|建档|体检|参保"


def _population(norm: str, orig: str, year: int | None):
    kw = r"常住(?:总)?人口(?:总量|总数|规模)?|总人口\s*\(常住人口\)|年末全国(?:大陆)?(?:总)?人口(?!普查)"
    excl = r"城镇|城市|乡村|农村|外来|户籍|流动|市区|县城|中心城区|城区|镇|新增|每千|每万|每百|每|按"
    hit = _find_value(norm, kw, PEOPLE, year=year, exclude_before=excl, filler=8, extra_stop=_POP_STOP)
    if hit is None:  # "年末全市常住人口230.56万户，646.83万人" (households first)
        m = re.search(r"(?:" + kw + r")(?:为|共)?\s*\d+(?:\.\d+)?\s*万户[，,]\s*" + NUM + r"\s*(万人|人)", norm)
        if m and not re.search(f"(?:{excl})$", norm[max(0, m.start() - 6): m.start()]):
            sa, sb = _sentence_at(norm, m.start())
            if not (_SKIP_SENT.search(norm[sa: m.start()]) or _other_year_before(norm, sa, m.start(), year)):
                hit = ((sa, sb), (m.start(), m.end()), to_number(m.group(1)) * PEOPLE[m.group(2)],
                       f"{m.group(1)}{m.group(2)}")
    if hit is None:  # "年末全省总人口为2347.69万人，其中城镇常住人口1496.18万人…": a total broken down by 常住
        kw2 = r"(?<![户籍口])年末(?:全省|全市|全区|全州|全盟|全地区)?(?:总)?人口(?:总数|总量)?"
        for cand in re.finditer(kw2, norm):
            got = _find_value(norm, kw2, PEOPLE, year=year, filler=4, start=cand.start(), end=cand.end())
            if not got:
                continue
            para_end = norm.find("\n", cand.start())
            after = norm[cand.start(): min(cand.start() + 300, len(norm) if para_end == -1 else para_end)]
            m_res = re.search(r"城镇常住人口|常住人口城镇化率", after)
            if m_res and not re.search(r"户籍|户口|公安", after[: m_res.start()]):
                hit = got
                break
    return _field(orig, hit, "万人", digits=4)


_REG_KW = r"户籍(?:登记)?(?:总)?人(?:口)?(?:总数|总量|数)?|(?:总)?人口\s*\(户籍(?:人口)?\)"
# a part of the registered population, or another population: 城镇户籍人口, 常住户籍人口 (Shenzhen: the residents who
# hold a local hukou – not the registered total), 非户籍人口, 市辖区户籍人口, "按户籍人口计算"
_REG_EXCL = (r"城镇|城市|乡村|农村|非农|农业|市区|市辖区|城区|县城|主城区|中心城区|镇|常住|非|外来|流动|暂住|新增|净增|迁入|迁出|"
             r"出生|死亡|每千|每万|每百|每|按|占")
_REG_STOP = r"中|男|女|净|户数|迁|岁|老年|少年|儿童|劳动|就业|参保|失业|登记失业|覆盖"
_REG_TOTAL = re.compile(r"(?:年末)?(?:全市|全省|全区|全州|全盟|全地区)?(?:年末)?总人口(?:总数|总量)?")
_REG_LEADIN = re.compile(r"户籍|公安")  # 从户籍看 / 根据户籍人口统计 / 按公安户籍人口统计 / 据公安部门统计 / 公安年报数据显示
_REG_HOUSEHOLDS = re.compile(r"户籍(?:人口)?(?:登记)?(?:总)?户数\s*" + NUM + r"\s*万?户[，,]\s*(?:户籍)?(?:总)?人口(?:为|达|共)?\s*"
                             + NUM + r"\s*(万人|人)")


def _population_registered(norm: str, orig: str, year: int | None):
    """户籍人口 (公安 household registration): 户籍人口, 户籍总人口, 户籍人口数, 总人口（户籍人口）. Kept apart from the
    resident population of the same sentence ("年末全市常住人口391.01万人，户籍人口为387.89万人"), and never a part of it
    (城镇户籍人口, 户籍人口中男性…) or the residents holding a local hukou (常住户籍人口, 户籍常住人口)."""
    hit = _find_value(norm, _REG_KW, PEOPLE, year=year, exclude_before=_REG_EXCL, filler=10, extra_stop=_REG_STOP)
    if hit is None:  # "户籍人口总户数155.58万户，总人口434.04万人" (households first)
        for m in _REG_HOUSEHOLDS.finditer(norm):
            sa, sb = _sentence_at(norm, m.start())
            if _SKIP_SENT.search(norm[sa: m.start()]) or _other_year_before(norm, sa, m.start(), year):
                continue
            hit = ((sa, sb), (m.start(), m.end()), to_number(m.group(2)) * PEOPLE[m.group(3)],
                   f"{m.group(2)}{m.group(3)}")
            break
    if hit is None:  # "根据户籍人口统计，年末总人口229.1万人": a 总人口 the same sentence says is a registration count
        for cand in _REG_TOTAL.finditer(norm):
            if re.search(f"(?:{_REG_EXCL}|户籍)$", norm[max(0, cand.start() - 6): cand.start()]):
                continue
            sa, _sb = _sentence_at(norm, cand.start())
            if not _REG_LEADIN.search(norm[sa: cand.start()]):
                continue
            hit = _find_value(norm, _REG_TOTAL.pattern, PEOPLE, year=year, filler=4, extra_stop=_REG_STOP,
                              start=cand.start(), end=cand.end())
            if hit:
                break
    return _field(orig, hit, "万人", digits=4)


def _urbanization(norm: str, orig: str, year: int | None):
    hit = _find_value(norm, r"城镇化(?:率|水平)(?:\s*\))?", PERCENT, year=year, exclude_before=r"户籍(?:人口)?", filler=6)
    if not hit:
        kw = r"城镇(?:常住)?人口占(?:全市|全省|全区|全州|全盟|全国)?(?:常住|总)?(?:总)?人口(?:的)?比重(?:\s*\([^)]*\))?"
        hit = _find_value(norm, kw, PERCENT, year=year, filler=6, allow_stop=r"占|比重|城镇")
    if not hit:
        hit = _urban_share(norm, year)
    return _field(orig, hit, "%", digits=3)


_URBAN_SHARE = re.compile(r"城镇(?:常住)?人口(?:为|达到|达)?\s*" + NUM + r"\s*(?:万人|人)[，,]\s*(?:比上年末?[增减][加少]" + NUM
                          + r"\s*万人[；;，,]\s*)?占(?:(?:全市|全省|全区|全州|全盟|全国)?(?:年末)?(常住|总)?人口(?:数)?(?:的)?(?:比重)?)?"
                          r"(?:\s*\([^)]{0,12}\))?(?:为|达到|是)?\s*" + NUM + r"\s*%")


def _urban_share(norm: str, year: int | None):
    """"城镇人口1916.1万人，占常住人口的比重为87.5%": a share of the *resident* population only – the denominator says
    常住, or the paragraph (up to 300 characters back; the one before if this one starts here) is about 常住人口, and
    户籍/户口 is not mentioned in between."""
    for m in _URBAN_SHARE.finditer(norm):
        sa, sb = _sentence_at(norm, m.start())
        if _SKIP_SENT.search(norm[sa: m.start()]) or _other_year_before(norm, sa, m.start(), year):
            continue
        para = norm.rfind("\n", 0, sa)
        if para == sa - 1:  # the sentence opens its paragraph: look into the previous one
            para = norm.rfind("\n", 0, para)
        context = norm[max(para + 1, m.start() - 300): m.end()]
        if re.search(r"户籍|户口", context):
            continue
        if m.group(3) == "常住" or "常住人口" in context:
            return (sa, sb), (m.start(), m.end()), to_number(m.group(4)), f"{m.group(4)}%"
    return None


def _incomes(norm: str, orig: str, year: int | None) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    # "全体及城乡居民人均可支配收入分别为57541元、68487元和35247元" (all, urban, rural)
    m = re.search(r"全体(?:居民)?(?:及|和|、|与)城乡居民(?:的)?人均可支配收入分别(?:为|是|达到|达)?\s*" + NUM
                  + r"\s*元?\s*[、，,]\s*" + NUM + r"\s*元?\s*(?:和|、|及)\s*" + NUM + r"\s*元", norm)
    if m:
        sa, sb = _sentence_at(norm, m.start())
        if not _other_year_before(norm, sa, m.start(), year):
            for key, g in (("income", 1), ("income_urban", 2), ("income_rural", 3)):
                out[key] = {"value": to_number(m.group(g)), "unit": "元", "raw": f"{m.group(g)}元",
                            "quote": _quote(orig, sa, sb)}
            return out
    # "城镇和农村居民人均可支配收入分别为62699和31930元" (the first 元 may be left out)
    m = re.search(r"城(?:镇|市)(?:常住)?(?:居民)?(?:和|与|、|及)农村(?:常住)?居民(?:的)?人均可支配收入分别(?:为|是|达到|达)?\s*"
                  + NUM + r"\s*元?\s*(?:和|、|，|及)\s*" + NUM + r"\s*元", norm)
    if m:
        sa, sb = _sentence_at(norm, m.start())
        if not _other_year_before(norm, sa, m.start(), year):
            for key, g in (("income_urban", 1), ("income_rural", 2)):
                out[key] = {"value": to_number(m.group(g)), "unit": "元", "raw": f"{m.group(g).strip()}元",
                            "quote": _quote(orig, sa, sb)}
    kw_all = r"(?:全体|全市|全省|全区|全州|全盟|全国|常住|城乡)?居民\s*(?:年)?人均可支配收入"
    hit = _find_value(norm, kw_all, YUAN, year=year, exclude_before=r"城镇|城市|农村|乡村|牧区|农牧|常住|城镇常住|农村常住",
                      filler=6)
    out["income"] = _field(orig, hit, "元", digits=2)
    if "income_urban" not in out:
        hit = _find_value(norm, r"城(?:镇|市)(?:常住)?居民(?:的)?人均可支配收入", YUAN, year=year, filler=6,
                          allow_stop=r"城镇|城市")
        out["income_urban"] = _field(orig, hit, "元", digits=2)
    if "income_rural" not in out:
        hit = _find_value(norm, r"(?:农村(?:牧区)?|农牧区?|乡村)(?:常住)?居民(?:的)?人均可支配收入|农(?:牧)?民人均可支配收入", YUAN,
                          year=year, filler=6, allow_stop=r"农村|乡村")
        out["income_rural"] = _field(orig, hit, "元", digits=2)
    return out


def _budget_revenue(norm: str, orig: str, year: int | None):
    # 一般公共预算收入; older names of the same budget line: 公共财政预算收入, (财政)一般预算收入. Not 全口径财政收入,
    # 财政总收入 or 地方财政收入, which are other aggregates.
    kw = (r"一般(?:地方)?公共预算(?:地方级)?(?:财政)?收入|(?:地方)?(?:公共财政|财政公共)(?:预算)?收入|(?:财政)?一般预算收入")
    hit = _find_value(norm, kw, MONEY, year=year, exclude_before=r"上划|省级|市级|县级|区级|本级|乡镇|中央|占|全口径",
                      filler=12)
    return _field(orig, hit, "亿元")


def _retail(norm: str, orig: str, year: int | None):
    hit = _find_value(norm, r"社会消费品零售(?:总)?额", MONEY, year=year, exclude_before=r"限额以上|限上|城镇|乡村|农村|网上",
                      filler=12)
    return _field(orig, hit, "亿元")


# --------------------------------------------------------------------- table fallback

def _table_value(orig: str, norm: str, keyword: str, units: dict[str, float], canon: str, digits: int = 6):
    """'地区生产总值 | 亿元 | 7534.2 | 6.1' rows (htmltext.to_text output): keyword cell, unit cell, value cell."""
    unit_re = "|".join(sorted((re.escape(u) for u in units), key=len, reverse=True))
    rx = re.compile(r"^\s*(?:" + keyword + r")\s*(?:\((" + unit_re + r")\))?\s*\|\s*(?:(" + unit_re + r")\s*\|\s*)?" + NUM + r"\s*(?:\||$)",
                    re.M)
    for m in rx.finditer(norm):
        unit = m.group(1) or m.group(2)
        if not unit:
            continue
        a = norm.rfind("\n", 0, m.start()) + 1
        b = norm.find("\n", m.end())
        b = len(norm) if b == -1 else b
        raw = m.group(3)
        return {"value": round(to_number(raw) * units[unit], digits), "unit": canon, "raw": f"{raw.strip()}{unit}",
                "quote": orig[a:b].strip(), "from_table": True}
    return None


_TABLE_KW = {
    "gdp": (r"(?:地区|国内)?生产总值(?:\s*\(GDP\))?", MONEY, "亿元"),
    "gdp_primary": (r"第一产业(?:增加值)?", MONEY, "亿元"),
    "gdp_secondary": (r"第二产业(?:增加值)?", MONEY, "亿元"),
    "gdp_tertiary": (r"第三产业(?:增加值)?", MONEY, "亿元"),
    "population": (r"年末常住人口|常住人口", PEOPLE, "万人"),
    "population_registered": (r"(?:年末)?(?:全市|全省|全区|全州)?户籍(?:总)?人口(?:数)?", PEOPLE, "万人"),
    "budget_revenue": (r"一般公共预算收入", MONEY, "亿元"),
    "retail_sales": (r"社会消费品零售总额", MONEY, "亿元"),
}


# --------------------------------------------------------------------- public API

def parse_fields(text: str, year: int | None = None) -> dict[str, dict | None]:
    """All FIELDS from a bulletin's plain text (see the module docstring). `year`: the bulletin's year."""
    orig = text or ""
    norm = normalize(orig)
    out: dict[str, dict | None] = {k: None for k in FIELDS}
    hit, out["gdp"], growth = _gdp(norm, orig, year)
    out["gdp_growth"] = growth or _growth_after(norm, orig, hit)
    gdp_at = None
    if out["gdp"] is not None:
        gdp_at = hit[0][0] if hit else norm.find(normalize(out["gdp"]["quote"]))
    out.update(_industries(norm, orig, year, gdp_at if gdp_at is not None and gdp_at >= 0 else None))
    out["population"] = _population(norm, orig, year)
    out["population_registered"] = _population_registered(norm, orig, year)
    out["urbanization"] = _urbanization(norm, orig, year)
    out.update(_incomes(norm, orig, year))
    out["budget_revenue"] = _budget_revenue(norm, orig, year)
    out["retail_sales"] = _retail(norm, orig, year)
    for key, (kw, units, canon) in _TABLE_KW.items():
        if out[key] is None:
            out[key] = _table_value(orig, norm, kw, units, canon, digits=4 if canon == "万人" else 6)
    return out


# plausible ranges by level (inclusive); anything outside is flagged, never dropped
RANGES = {
    "city": {"gdp": (5, 60000), "gdp_growth": (-25, 30), "population": (0.05, 4000), "population_registered": (0.05, 4000),
             "urbanization": (5, 100),
             "income": (5000, 120000), "income_urban": (10000, 130000), "income_rural": (3000, 70000),
             "budget_revenue": (0.05, 5000), "retail_sales": (0.5, 20000)},
    "province": {"gdp": (100, 200000), "gdp_growth": (-25, 30), "population": (100, 15000),
                 "population_registered": (100, 15000), "urbanization": (15, 100),
                 "income": (8000, 120000), "income_urban": (15000, 130000), "income_rural": (5000, 70000),
                 "budget_revenue": (10, 30000), "retail_sales": (50, 70000)},
    "nation": {"gdp": (500000, 2000000), "gdp_growth": (-10, 20), "population": (130000, 150000),
               "population_registered": (130000, 150000),
               "urbanization": (50, 100), "income": (20000, 100000), "income_urban": (30000, 120000),
               "income_rural": (10000, 60000), "budget_revenue": (100000, 400000), "retail_sales": (200000, 800000)},
}
SUM_TOLERANCE = 0.01


def validate(fields: dict[str, dict | None], level: str = "city") -> list[str]:
    """Flags for a parsed record: "sum:+1.8%" (industries vs GDP), "range:<field>", "order:income"."""
    flags = []
    val = {k: (f or {}).get("value") for k, f in fields.items()}
    parts = [val.get(k) for k in ("gdp_primary", "gdp_secondary", "gdp_tertiary")]
    if val.get("gdp") and all(p is not None for p in parts):
        diff = (sum(parts) - val["gdp"]) / val["gdp"]
        if abs(diff) > SUM_TOLERANCE:
            flags.append(f"sum:{diff * 100:+.1f}%")
    for key, (lo, hi) in RANGES.get(level, RANGES["city"]).items():
        v = val.get(key)
        if v is not None and not lo <= v <= hi:
            flags.append(f"range:{key}")
    for k in ("gdp_primary", "gdp_secondary", "gdp_tertiary"):
        if val.get(k) is not None and val.get("gdp") and val[k] > val["gdp"]:
            flags.append(f"range:{k}>gdp")
    i, iu, ir = val.get("income"), val.get("income_urban"), val.get("income_rural")
    if iu is not None and ir is not None and ir > iu:
        flags.append("order:income_rural>urban")
    if i is not None and iu is not None and ir is not None and not ir <= i <= iu:
        flags.append("order:income_all")
    return flags


def fields_found(fields: dict[str, dict | None]) -> int:
    return sum(1 for f in fields.values() if f is not None)
