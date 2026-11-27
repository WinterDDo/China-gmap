"""The data rules of docs/DATA-COLLECTION.md「原则」, checked over everything collected.

    python -m pipeline check          (also the last step of `all`)

1. Our own bulletin records, data/interim/bulletins/<year>.json: every record, every number.
   - Numbers come only from text bulletins: image-only, attachment-only and missing records carry none.
   - Every number has its unit, the number as printed (`raw`) and the whole sentence (`quote`); the printed number
     is in the sentence, and the stored value is that number in the field's unit.
   - 0 only when the bulletin says so (持平, or a printed 0), never as a stand-in for "not found".
   - A text record names its page (`url`) and the original publisher (`bureau`).
   - The record's year is the file's year; `fields_found` agrees with the fields.
2. The design-freeze prototype's city data, explorations/design-freeze/data/cities.json: every city.
   - No 0 standing in for missing.
   - Bulletin numbers are 2023 numbers from a 2023 bulletin; no other year fills a gap.
   - A derived number (per head, change since 2020) is empty whenever an input is empty.
   - A number shown next to its own sentence (GDP next to the GDP sentence, …) is the number in that sentence.
     Known disagreements are listed one by one in PROTOTYPE_KNOWN_MISMATCH, and each entry must still exist.
   - Numbers found in none of the city's sentences are counted per field. Those counts may only go down:
     PROTOTYPE_UNQUOTED is the ceiling, and a change that adds sentences lowers it.

Exit status 1 when any rule is broken. tests/test_data_rules.py runs the same checks on every commit.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .core.paths import INTERIM, ROOT
from .parse.bulletin import FIELDS, MONEY, NUM, PEOPLE, PERCENT, YUAN, normalize, to_number

BULLETINS = INTERIM / "bulletins"
PROTOTYPE_CITIES = ROOT / "explorations" / "design-freeze" / "data" / "cities.json"

ZERO_WORDS = ("持平",)
UNIT_TABLES = {"亿元": MONEY, "万人": PEOPLE, "元": YUAN, "%": PERCENT}

# ------------------------------------------------------------------------------ 1. bulletin records


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-3)


def check_field(key: str, f: dict) -> list[str]:
    """Problems with one parsed number (empty list = fine)."""
    unit = FIELDS[key][1]
    value, raw, quote = f.get("value"), (f.get("raw") or "").strip(), (f.get("quote") or "").strip()
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return [f"{key}: 数值不是有限数字（{value!r}）"]
    if f.get("unit") != unit:
        return [f"{key}: 单位应为 {unit}，记录里是 {f.get('unit')!r}"]
    if not raw or not quote:
        return [f"{key}: 缺{'原样数字' if not raw else '原句'}"]
    flat_quote = normalize(quote).replace(" ", "").replace(",", "")
    flat_raw = normalize(raw).replace(" ", "").replace(",", "")
    num = re.search(NUM, flat_raw)
    if not num:
        if not any(w in flat_raw and w in flat_quote for w in ZERO_WORDS):
            return [f"{key}: 原样数字「{raw}」里没有数字"]
        return [] if value == 0 else [f"{key}: 「{raw}」应记为 0，记录里是 {value}"]
    if num.group(0) not in flat_quote:
        return [f"{key}: 原句里找不到「{raw}」"]
    printed = to_number(num.group(0))
    if value == 0 and printed != 0:
        return [f"{key}: 记成了 0，原文是「{raw}」"]
    printed_unit = flat_raw[num.end():]
    factor = UNIT_TABLES[unit].get(printed_unit) if printed_unit else 1.0
    if factor is not None and not _same(abs(value), printed * factor):
        return [f"{key}: 数值 {value} 与原文「{raw}」换算到 {unit} 后不一致"]
    return []


def check_record(rec: dict, year: int) -> list[str]:
    where = f"{rec.get('name') or rec.get('code')} {year}"
    problems = []
    fields = rec.get("fields") or {}
    if rec.get("year") != year:
        problems.append(f"记录年份 {rec.get('year')} 与文件年份不符")
    if set(fields) != set(FIELDS):
        problems.append("指标清单与 FIELDS 不一致")
    present = {k: f for k, f in fields.items() if f is not None}
    if rec.get("status") != "text" and present:
        problems.append(f"状态为 {rec.get('status')}（不是正文公报），却有数字：{', '.join(present)}")
    if rec.get("status") == "text":
        if not rec.get("url"):
            problems.append("正文公报没有来源网址")
        if not rec.get("bureau"):
            problems.append("正文公报没有原发布机关")
    if rec.get("fields_found") != len(present):
        problems.append(f"fields_found={rec.get('fields_found')}，实际有 {len(present)} 项")
    for key, f in present.items():
        if key in FIELDS:
            problems.extend(check_field(key, f))
    return [f"{where}：{p}" for p in problems]


def check_bulletin_file(path: Path) -> tuple[int, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    year = payload.get("year")
    problems = []
    for rec in payload.get("records", []):
        problems.extend(check_record(rec, year))
    return len(payload.get("records", [])), problems


# ------------------------------------------------------------------------------ 2. prototype city data

PROTOTYPE_YEAR = 2023
# Numbers shown in the prototype that come from a source document, with their unit there.
PROTOTYPE_SOURCED = {
    "gdp": "元", "p1": "元", "p2": "元", "p3": "元", "gg": "%", "pop": "人", "pop20": "人", "popReg": "人",
    "urb": "%", "inc": "元", "incU": "元", "incR": "元",
}
# Computed from other fields: must be empty when an input is.
PROTOTYPE_DERIVED = {"pc": ("gdp", "pop"), "growth": ("pop", "pop20"), "sv": ("p1", "p2", "p3")}
# The sentence each of these numbers is shown with (src.q key).
PROTOTYPE_HOME_QUOTE = {"gdp": "gdp", "pop": "population", "popReg": "population_registered", "inc": "income",
                        "incU": "income_urban"}
# Numbers that disagree with their own sentence. Fix the data, then delete the entry; never add one silently.
PROTOTYPE_KNOWN_MISMATCH = {
    ("330500", "gdp"): "2026-11-27 发现：原型显示 3849.6 亿元，湖州 2023 年公报原句是 4015.1 亿元（疑为 2022 年数值）",
}
# Ceiling of numbers found in none of their city's sentences (2026-11-27). Only ever lower these.
PROTOTYPE_UNQUOTED = {
    "gdp": 86, "p1": 272, "p2": 272, "p3": 272, "gg": 1, "pop": 72, "pop20": 338, "popReg": 0,
    "urb": 120, "inc": 0, "incU": 0, "incR": 67,
}
_QUOTE_NUMBER = re.compile(NUM + r"\s*(万亿元|亿元|万元|元|万人|人|%)")
_TO_BASE = {"万亿元": 1e12, "亿元": 1e8, "万元": 1e4, "元": 1.0, "万人": 1e4, "人": 1.0, "%": 1.0}


def _quoted_numbers(quotes: dict | None) -> list[tuple[float, str]]:
    """Every (number in base units, kind) printed in a city's quotes; kind is 元, 人 or %."""
    out = []
    for q in (quotes or {}).values():
        for m in _QUOTE_NUMBER.finditer(normalize(q or "").replace(",", "")):
            unit = m.group(2)
            kind = "%" if unit == "%" else ("人" if unit.endswith("人") else "元")
            out.append((to_number(m.group(1)) * _TO_BASE[unit], kind))
    return out


def _is_quoted(value: float, unit: str, printed: list[tuple[float, str]]) -> bool:
    for n, kind in printed:
        if kind != unit:
            continue
        if unit == "%" and (_same(value, n) or _same(value, n / 100)):
            return True
        if unit != "%" and math.isclose(value, n, rel_tol=1e-6):
            return True
    return False


def check_prototype(cities: list[dict]) -> tuple[list[str], dict[str, int]]:
    """(broken rules, per-field count of numbers with no sentence)."""
    problems = []
    unquoted = {k: 0 for k in PROTOTYPE_SOURCED}
    mismatches = set()
    for c in cities:
        name = c.get("n") or c.get("id")
        src = c.get("src") or {}
        quotes = src.get("q") or {}
        printed = _quoted_numbers(quotes)
        for key, unit in PROTOTYPE_SOURCED.items():
            v = c.get(key)
            if v is None:
                continue
            if v == 0:
                problems.append(f"{name}：{key} 记成了 0（缺失应为空）")
            home = quotes.get(PROTOTYPE_HOME_QUOTE.get(key))
            if home and not _is_quoted(v, unit, _quoted_numbers({key: home})):
                mismatches.add((c.get("id"), key))
                if (c.get("id"), key) not in PROTOTYPE_KNOWN_MISMATCH:
                    problems.append(f"{name}：{key}={v} 与它自己的原句对不上：{home}")
            elif not _is_quoted(v, unit, printed):
                unquoted[key] += 1
        for key, inputs in PROTOTYPE_DERIVED.items():
            if c.get(key) is not None and any(c.get(i) is None for i in inputs):
                problems.append(f"{name}：{key} 由 {'、'.join(inputs)} 算出，但输入有空值")
        if (c.get("pop") is None) != (c.get("popYear") is None) or c.get("popYear") not in (None, PROTOTYPE_YEAR):
            problems.append(f"{name}：人口年份是 {c.get('popYear')}，应为 {PROTOTYPE_YEAR}（不拿别的年份补）")
        if src.get("url") and str(PROTOTYPE_YEAR) not in (src.get("title") or ""):
            problems.append(f"{name}：出处标题不是 {PROTOTYPE_YEAR} 年公报（{src.get('title')}）")
    for (cid, key), note in PROTOTYPE_KNOWN_MISMATCH.items():
        if (cid, key) not in mismatches:
            problems.append(f"已知问题 {cid} {key} 已经不存在了，从 PROTOTYPE_KNOWN_MISMATCH 里删掉：{note}")
    for key, n in unquoted.items():
        if n > PROTOTYPE_UNQUOTED[key]:
            problems.append(f"{key}：没有原句的数字有 {n} 个，超过上限 {PROTOTYPE_UNQUOTED[key]}（只许减少）")
    return problems, unquoted


# ------------------------------------------------------------------------------ report

SHOW = 30  # problems listed per section; the count is always complete


def main() -> int:
    failed = False
    files = sorted(BULLETINS.glob("[0-9][0-9][0-9][0-9].json"))
    print("一、我们自己的公报采集结果")
    if not files:
        print(f"    没有找到 {BULLETINS.relative_to(ROOT)}/<年份>.json：先运行 python -m pipeline all。本项跳过。")
    for path in files:
        n, problems = check_bulletin_file(path)
        print(f"    {path.stem} 年：{n} 条记录，{'全部守规则' if not problems else f'{len(problems)} 处违反'}")
        for p in problems[:SHOW]:
            print(f"      ! {p}")
        failed |= bool(problems)

    print("二、设计定稿原型的城市数据")
    cities = json.loads(PROTOTYPE_CITIES.read_text(encoding="utf-8"))
    problems, unquoted = check_prototype(cities)
    print(f"    {len(cities)} 座城市，{'全部守规则' if not problems else f'{len(problems)} 处违反'}")
    for p in problems[:SHOW]:
        print(f"      ! {p}")
    for note in PROTOTYPE_KNOWN_MISMATCH.values():
        print(f"    已知问题：{note}")
    print("    还没有原句的数字（上限只降不升）：" + "，".join(f"{k} {n}" for k, n in unquoted.items() if n))
    lower = {k: n for k, n in unquoted.items() if n < PROTOTYPE_UNQUOTED[k]}
    if lower:
        print("    这些已经比上限少了，把 PROTOTYPE_UNQUOTED 调低到：" + "，".join(f"{k}={n}" for k, n in lower.items()))
    failed |= bool(problems)
    return 1 if failed else 0
