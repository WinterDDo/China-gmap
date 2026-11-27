"""pipeline/check.py: the data rules, over real samples, deliberate violations and all committed data."""

import copy
import json

import pytest

from pipeline import check
from test_records import _rec

GOOD = _rec("tjcn_shijiazhuang_2023_text.html", "130100")
CITIES = json.loads(check.PROTOTYPE_CITIES.read_text(encoding="utf-8"))


def _problems(mutate, year=2023):
    rec = copy.deepcopy(GOOD)
    mutate(rec)
    return " | ".join(check.check_record(rec, year))


def test_real_samples_keep_every_rule():
    assert check.check_record(GOOD, 2023) == []
    assert GOOD["fields_found"] == 13  # incl. GDP per head as printed
    assert check.check_record(_rec("tjcn_taiyuan_2023_image_only.html", "140100"), 2023) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda r: r["fields"]["gdp"].update(value=0.0), "记成了 0"),
    (lambda r: r["fields"]["gdp"].update(quote=""), "缺原句"),
    (lambda r: r["fields"]["gdp"].update(raw=""), "缺原样数字"),
    (lambda r: r["fields"]["gdp"].update(value=753.42), "不一致"),
    (lambda r: r["fields"]["gdp"].update(quote="全年全市生产总值稳步增长。"), "原句里找不到"),
    (lambda r: r["fields"]["population"].update(unit="人"), "单位应为 万人"),
    (lambda r: r["fields"]["gdp_growth"].update(raw="持平", quote="比上年持平。"), "应记为 0"),
    (lambda r: r.update(status="image_only"), "不是正文公报"),
    (lambda r: r.update(bureau=None), "没有原发布机关"),
    (lambda r: r.update(url=None), "没有来源网址"),
    (lambda r: r.update(fields_found=3), "fields_found=3"),
])
def test_each_bulletin_rule_catches_its_violation(mutate, expected):
    assert expected in _problems(mutate)


def test_flat_growth_may_be_zero():
    assert _problems(lambda r: r["fields"]["gdp_growth"].update(value=0.0, raw="持平", quote="比上年持平。")) == ""


def test_record_from_another_year_is_caught():
    assert "与文件年份不符" in " | ".join(check.check_record(GOOD, 2022))


def test_every_prototype_city_keeps_the_rules_and_the_ceilings_hold():
    problems, unquoted = check.check_prototype(CITIES)
    assert problems == []
    assert all(unquoted[k] <= check.PROTOTYPE_UNQUOTED[k] for k in unquoted)


@pytest.mark.parametrize("mutate, expected", [
    (lambda c: c.update(gdp=0), "记成了 0"),
    (lambda c: c.update(pop=None, popYear=None), "输入有空值"),  # per-head GDP left behind
    (lambda c: c.update(popYear=2022), "人口年份是 2022"),
    (lambda c: c["src"].update(title="上海市2022年国民经济和社会发展统计公报"), "不是 2023 年公报"),
    (lambda c: c.update(inc=85000.0), "与它自己的原句对不上"),
])
def test_each_prototype_rule_catches_its_violation(mutate, expected):
    cities = copy.deepcopy(CITIES)
    mutate(next(c for c in cities if c["id"] == "310000"))
    assert expected in " | ".join(check.check_prototype(cities)[0])


def test_fixed_known_problem_must_leave_the_list(monkeypatch):
    # Shanghai's GDP matches its sentence, so a known-problem entry for it is stale and must be deleted.
    monkeypatch.setitem(check.PROTOTYPE_KNOWN_MISMATCH, ("310000", "gdp"), "stale entry")
    assert "已经不存在了" in " | ".join(check.check_prototype(CITIES)[0])


def test_more_numbers_without_a_sentence_fail():
    cities = copy.deepcopy(CITIES)
    next(c for c in cities if c["id"] == "310000")["src"]["q"].pop("income")
    assert "超过上限" in " | ".join(check.check_prototype(cities)[0])


@pytest.mark.skipif(not list(check.BULLETINS.glob("[0-9][0-9][0-9][0-9].json")),
                    reason="no collected bulletins here (data/interim is not in git); `python -m pipeline all` checks them")
def test_all_collected_bulletins_keep_every_rule():
    for path in sorted(check.BULLETINS.glob("[0-9][0-9][0-9][0-9].json")):
        assert check.check_bulletin_file(path)[1] == [], path.name
