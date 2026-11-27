"""parse/bulletin.py on real sentences from city, province and national bulletins (quoted verbatim; the bulletin is
named in each case). Run: python -m pytest tests/"""

import pytest

from pipeline.parse.bulletin import FIELDS, normalize, parse_fields, validate


def values(text, year):
    return {k: v["value"] for k, v in parse_fields(text, year).items() if v}


# 石家庄市2023年国民经济和社会发展统计公报 (tjcn 03hb/37692)
SJZ = (
    "初步核算，全年全市生产总值7534.2亿元，按不变价格计算，比上年增长6.1%。其中，第一产业增加值576.9亿元，增长4.1%；"
    "第二产业增加值2309.2亿元，增长7.2%；第三产业增加值4648.1亿元，增长5.9%。第一产业增加值占生产总值比重为7.7%；"
    "第二产业增加值比重为30.6%；第三产业增加值比重为61.7%。全年人均生产总值67099元，比上年增长6.0%。\n"
    "全年全市民营经济增加值4338.3 亿元，按不变价格计算，比上年增长6.0%，占生产总值的比重为57.6%。\n"
    "年末全市常住总人口1123.35万人，比上年末增加1万人。其中，城镇常住人口811.92万人，比上年末增加10.13万人；"
    "占总人口比重（常住人口城镇化率）为72.28%，比上年末提高0.84个百分点。\n"
    "全年全市社会消费品零售总额实现2751.2亿元，比上年增长12.9%。\n"
    "全年全市一般公共预算收入737.9亿元，比上年增长6.6%。一般公共预算支出1274.8亿元，比上年增长2.0%。\n"
    "全年全市居民人均可支配收入37735元，比上年增长7.0%。按常住地分，城镇居民人均可支配收入47564元，增长6.3%；"
    "农村居民人均可支配收入21242元，增长7.1%。\n"
    "[3]按照我国地区生产总值统一核算和数据发布制度规定，地区生产总值核算包括初步核算和最终核实两个步骤。"
    "最终核实数据确定后，初步核算数据不再使用。经最终核实，2022年，全市生产总值现价总量为7080.8亿元，"
    "按不变价格计算，比上年增长6.2%。"
)


def test_full_city_bulletin():
    f = parse_fields(SJZ, 2023)
    assert {k: v["value"] for k, v in f.items() if v} == {
        "gdp": 7534.2, "gdp_growth": 6.1, "gdp_primary": 576.9, "gdp_secondary": 2309.2, "gdp_tertiary": 4648.1,
        "population": 1123.35, "urbanization": 72.28, "gdp_per_capita": 67099.0, "income": 37735, "income_urban": 47564, "income_rural": 21242,
        "budget_revenue": 737.9, "retail_sales": 2751.2,
    }
    assert set(f) == set(FIELDS)
    # every value keeps its whole sentence, verbatim
    assert f["gdp"]["quote"] == "初步核算，全年全市生产总值7534.2亿元，按不变价格计算，比上年增长6.1%。"
    assert f["population"]["quote"] == "年末全市常住总人口1123.35万人，比上年末增加1万人。"
    assert f["gdp"]["unit"] == "亿元" and f["population"]["unit"] == "万人" and f["income"]["unit"] == "元"
    assert f["population_registered"] is None  # the bulletin gives no 户籍 figure
    assert all(v["quote"] in SJZ for v in f.values() if v)
    assert validate(f, "city") == []


def test_revised_previous_year_is_not_taken():
    # only the 最终核实 note on 2022 states GDP: it must not become the 2023 value
    note = SJZ[SJZ.index("[3]"):]
    assert parse_fields(note, 2023)["gdp"] is None


def test_wan_yuan_converted_to_yi_yuan():
    # 伊春市2021年国民经济和社会发展统计公报 (tjcn 08hlj/37162)
    t = "初步核算，全年全市实现地区生产总值（GDP）3186933万元，按可比价格计算，同比增长7.3%。"
    f = parse_fields(t, 2021)
    assert f["gdp"]["value"] == pytest.approx(318.6933)
    assert f["gdp"]["raw"] == "3186933万元"
    assert f["gdp_growth"]["value"] == 7.3


def test_budget_revenue_in_wan_yuan():
    # 西双版纳州2020年国民经济和社会发展统计公报 (tjcn 25yn/36823)
    assert values("一般公共预算收入358147万元，增长3.1%。", 2020) == {"budget_revenue": pytest.approx(35.8147)}


def test_decline_is_negative():
    # 鄂尔多斯市2020年国民经济和社会发展统计公报 (tjcn 05nmg/36573)
    t = "初步核算，2020年全市完成地区生产总值3533.66亿元，按可比价计算，比上年下降2.9%。"
    assert values(t, 2020) == {"gdp": 3533.66, "gdp_growth": -2.9}
    # the same sentence in a 2021 bulletin speaks of another year: skipped
    assert values(t, 2021) == {}


def test_full_width_digits_and_percent():
    # 辽阳市2020年: "全年城镇常住居民人均可支配收入[19]34814元，比上年增长0.7％" – plus full-width digits
    t = "全年城镇常住居民人均可支配收入[19]34814元，比上年增长0.7％；农村常住居民人均可支配收入１７６６６元，增长8.7％。"
    f = parse_fields(t, 2020)
    assert f["income_urban"]["value"] == 34814
    assert f["income_rural"]["value"] == 17666
    assert f["income_rural"]["quote"] == t  # the quote is the original text, full-width digits and all
    assert normalize("１２３．４％") == "123.4%"


def test_footnote_marker_inside_keyword():
    # 安徽省2020年国民经济和社会发展统计公报 (tjcn 12ah)
    t = ("分产业看，第一产业[3]增加值3184.7亿元，增长2.2%；第二产业增加值15671.7亿元，增长5.2%，其中工业增加值11662.2亿元，"
         "增长5.1%；第三产业增加值19824.2亿元，增长2.8%。")
    assert values(t, 2020) == {"gdp_primary": 3184.7, "gdp_secondary": 15671.7, "gdp_tertiary": 19824.2}


def test_industries_with_wancheng():
    # 阳泉市2020年国民经济和社会发展统计公报
    t = "其中，第一产业完成增加值10.5亿元，增长3.5%；第二产业完成增加值334.4亿元，增长5.7%；第三产业完成增加值397.3亿元，增长1.7%。"
    assert values(t, 2020) == {"gdp_primary": 10.5, "gdp_secondary": 334.4, "gdp_tertiary": 397.3}


def test_incomes_fenbie():
    # 浙江省2020年 (first 元 left out) and 浙江省2021年 (all, urban, rural in one sentence)
    t20 = "按常住地分，城镇和农村居民人均可支配收入分别为62699和31930元，增长4.2%和6.9%，扣除价格因素分别增长2.1%和4.0%。"
    assert values(t20, 2020) == {"income_urban": 62699, "income_rural": 31930}
    t21 = ("根据城乡一体化住户调查，全年全体及城乡居民人均可支配收入分别为57541元、68487元和35247元，"
           "比上年名义增长9.8%、9.2%和10.4%。")
    assert values(t21, 2021) == {"income": 57541, "income_urban": 68487, "income_rural": 35247}


def test_median_income_is_not_income():
    # 中华人民共和国2021年国民经济和社会发展统计公报
    assert values("全国居民人均可支配收入中位数[53]29975元，增长8.8%。", 2021) == {}


def test_registered_population_is_not_resident_population():
    # 大连市2020年 / 延边州2020年: 户籍 figures never become the resident population (only population_registered)
    assert values("年末全市户籍人口601.6万人，比上年末增加2.9万人。", 2020) == {"population_registered": 601.6}
    t = ("年末户籍总人口204.66万人，比上年末减少2.55万人，其中城镇人口142.16万人，占总人口比重（户籍人口城镇化率）为69.5%，"
         "比上年末提高0.1个百分点。")
    assert values(t, 2020) == {"population_registered": 204.66}


def test_national_population_and_urbanisation():
    # 中华人民共和国2021年国民经济和社会发展统计公报
    t = "年末全国人口[7]141260万人，比上年末增加48万人，其中城镇常住人口91425万人。年末全国常住人口城镇化率为64.72%，比上年末提高0.83个百分点。"
    assert values(t, 2021) == {"population": 141260, "urbanization": 64.72}


def test_inexact_values_are_skipped():
    # 中国2020年: "超过60%" is not a figure; 苏州市2021年: "突破3300亿元" (and not GDP anyway)
    assert values("年末常住人口城镇化率超过60%。", 2020) == {}
    assert values("全市数字经济核心产业增加值突破3300亿元。", 2021) == {}
    # constructed: a 突破 milestone followed by the actual figure
    assert values("全年全市地区生产总值突破5000亿元，达到5123.4亿元，比上年增长5.2%。", 2023)["gdp"] == 5123.4


def test_per_capita_and_energy_intensity_are_not_gdp():
    # 北京市2021年 / 中华人民共和国2021年
    assert values("按常住人口计算，全市人均地区生产总值为18.4万元。", 2021) == {"gdp_per_capita": 184000.0}  # per head, never the GDP itself
    assert values("全年全国万元国内生产总值能耗[22]比上年下降2.7%。", 2021) == {}


def test_old_budget_names_and_other_aggregates():
    # 承德市2020年 (公共财政预算收入 = the old name of 一般公共预算收入) vs 长春市2020年 (全口径 – another aggregate)
    assert values("全年公共财政预算收入116.1亿元，比上年增长3.3%。", 2020) == {"budget_revenue": 116.1}
    assert values("全市一般预算全口径财政收入1129.5亿元，增长0.3%。", 2020) == {}


def test_growth_only_retail_sales_stays_null():
    # 哈尔滨市2020年: only the growth rate is printed
    assert values("全年社会消费品零售总额比上年下降11.3%。", 2020) == {}


def test_table_row_fallback():
    t = "表1 主要指标\n指标 | 单位 | 绝对数 | 比上年增长(%)\n地区生产总值 | 亿元 | 1234.5 | 5.1\n社会消费品零售总额 | 亿元 | 456.7 | 3.2"
    f = parse_fields(t, 2024)
    assert f["gdp"]["value"] == 1234.5 and f["gdp"]["from_table"]
    assert f["retail_sales"]["value"] == 456.7
    assert f["gdp"]["quote"] == "地区生产总值 | 亿元 | 1234.5 | 5.1"


def test_missing_is_none_never_zero():
    f = parse_fields("全年全市粮食总产量438.2万吨，比上年增长0.4%。", 2023)
    assert all(v is None for v in f.values())


def test_validate_flags():
    f = parse_fields(SJZ, 2023)
    f["gdp_tertiary"] = dict(f["gdp_tertiary"], value=4900.0)  # breaks the sum by 3.3%
    assert validate(f, "city") == ["sum:+3.3%"]
    bad = {k: None for k in FIELDS}
    bad["population"] = {"value": 99999.0}
    bad["income_urban"], bad["income_rural"] = {"value": 20000.0}, {"value": 30000.0}
    flags = validate(bad, "city")
    assert "range:population" in flags and "order:income_rural>urban" in flags


def test_service_sector_parenthesis_and_no_county_breakdown():
    # 达州市2020年国民经济和社会发展统计公报 (tjcn 23sc/36796); the second paragraph is a county-level breakdown
    # (shortened) that must not be taken for the city's 第三产业
    t = ("经四川省统计局核定，2020年达州实现地区生产总值（GDP）2117.8亿元，按可比价格计算，同比增长4.1%。其中，第一产业实现增加值"
         "393.57亿元，增长5.5%；第二产业实现增加值720.30亿元，增长4.8%；第三产业（服务业）实现增加值1003.93亿元，增长2.9%。\n"
         + "全市各县（市、区）经济稳步发展。" * 60 + "\n"
         "其中，第一产业增加值106.25亿元，下降5.5%；第二产业增加值522.18亿元，增长4.2%；第三产业增加值642.03亿元，增长2.5%。")
    f = parse_fields(t, 2020)
    assert [f[k]["value"] for k in ("gdp", "gdp_primary", "gdp_secondary", "gdp_tertiary")] == [2117.8, 393.57, 720.3, 1003.93]
    assert validate(f, "city") == []


def test_per_thousand_residents_is_not_population():
    # 六安市2020年国民经济和社会发展统计公报 (tjcn 12ah/36656)
    t = "全市医疗机构床位总数26758张，医疗卫生人员23583人；每千常住人口执业（助理）医师2.53人，每千常住人口床位5.49张。"
    assert values(t, 2020) == {}


def test_households_before_population_and_urbanisation_level():
    # 邵阳市2021年国民经济和社会发展统计公报 (shortened)
    t = ("年末全市常住人口230.56万户，646.83万人，其中男性335.38万人，女性311.45万人，城镇人口和乡村人口分别为343.05万人和"
         "303.78万人；城镇化水平为53.04%，比上年提高0.88个百分点。")
    assert values(t, 2021) == {"population": 646.83, "urbanization": 53.04}


def test_urban_share_of_resident_population():
    # 北京市2021年 / 杭州市2021年 / 新余市2021年 (resident population in the sentence before)
    assert values("其中，城镇人口1916.1万人，占常住人口的比重为87.5%；常住外来人口834.8万人，占常住人口的比重为38.1%。", 2021) \
        == {"urbanization": 87.5}
    t = "年末全市常住人口1220.4万人，比上年末增加23.9万人，其中城镇人口1020.3万人，占常住人口的83.6%，比上年末提高0.3个百分点。"
    assert values(t, 2021) == {"population": 1220.4, "urbanization": 83.6}
    t = "年末全市常住人口120.2万人。其中,城镇人口89.12万人,占总人口的比重为74.14%,比上年末提高0.55个百分点。"
    assert values(t, 2021) == {"population": 120.2, "urbanization": 74.14}
    # 辽源市2021年: a registered-population share stays null
    assert values("按户口所在地划分，全市城镇人口为568146人，占总人口的49.95%。", 2021) == {}


def test_comparison_with_census_year_does_not_block():
    # 宿州市2021年国民经济和社会发展统计公报
    t = "年末全市常住人口532.5万人，比2020年第七次人口普查增加0.06万人，城镇化率45.03%，比上年提高1.24个百分点。"
    assert values(t, 2021) == {"population": 532.5, "urbanization": 45.03}
    assert values("第七次全国人口普查结果显示，全市常住人口924.26万人。", 2020) == {}


def test_milestone_without_digits():
    # 枣庄市2021年国民经济和社会发展统计公报
    assert values("社会消费品零售总额突破千亿元大关，达到1041.7亿元，增长16.0%。", 2021) == {"retail_sales": 1041.7}


def test_budget_revenue_name_variants():
    # 广安市2021年 / 黄南州2021年 / 厦门市2021年 (district level, not the city's)
    assert values("全年一般地方公共预算收入93.6亿元，增长8.8%。", 2021) == {"budget_revenue": 93.6}
    assert values("——全州地方财政公共预算收入4.86亿元，比上年增长2.41%。", 2021) == {"budget_revenue": 4.86}
    assert values("全年区级公共财政预算收入（不含市本级）273.72亿元，比上年增长15.5%。", 2021) == {}


def test_milestone_phrasings():
    # 景德镇市2021年 / 海西州2021年 / 菏泽市2021年
    t = "经省统计局统一核算,全年地区生产总值首次迈入千亿大关,达1102.31亿元,比上年增长8.7%,两年平均增长6.2%。"
    assert values(t, 2021) == {"gdp": 1102.31, "gdp_growth": 8.7}
    t = "根据地区生产总值统一核算结果，全年生产总值[2]突破700亿，达到713.78亿元，按可比价格计算，增长4.1%，2020年-2021年两年平均增长0.9%。"
    assert values(t, 2021) == {"gdp": 713.78, "gdp_growth": 4.1}
    t = "初步核算，全市地区生产总值（GDP）突破四千亿大关、达到4205.34亿元，按不变价格计算，比上年增长4.2%。"
    assert values(t, 2021) == {"gdp": 4205.34, "gdp_growth": 4.2}


def test_current_price_label_on_value_not_rate():
    # 黄冈市2020年 / 克拉玛依市2020年
    t = "经初步核算，2020年全市实现生产总值（GDP）2169.55亿元（现价），按可比价格计算，下降6.6%。"
    assert values(t, 2020) == {"gdp": 2169.55, "gdp_growth": -6.6}
    t = "根据地区生产总值统一核算结果，全年实现地区生产总值（GDP）886.9亿元（现价，下同），较上年增长2.3%（按不变价计算，下同）。"
    assert values(t, 2020) == {"gdp": 886.9, "gdp_growth": 2.3}
    # constructed: an explicitly nominal rate is not the real growth
    assert values("全年全市生产总值1000亿元，名义增长8.0%。", 2023) == {"gdp": 1000.0}


def test_urban_share_variants():
    # 贵州省2022年 / 中山市2022年 (with the bulletin's own typo 镇化率)
    t = "年末常住人口3856万人。其中，城镇常住人口2114万人，占年末常住人口的比重为54.81%，比上年末提高0.48个百分点。"
    assert values(t, 2022) == {"population": 3856, "urbanization": 54.81}
    t = "2022年末，全市常住人口443.11万人，其中城镇常住人口385.59万人，占常住人口比重（常住人口镇化率）87.02%，比上年末提高0.02个百分点。"
    assert values(t, 2022) == {"population": 443.11, "urbanization": 87.02}


def test_total_population_broken_down_by_residence():
    # 吉林省2022年 / 抚州市2022年: the breakdown into 城镇常住人口 makes the total a resident figure
    t = ("年末全省总人口为2347.69万人，其中城镇常住人口1496.18万人，占总人口比重（常住人口城镇化率）为63.73%，"
         "比上年末提高0.37个百分点。")
    assert values(t, 2022) == {"population": 2347.69, "urbanization": 63.73}
    assert values("年末全市人口357.90万人，比上年末减少0.04万人，其中城镇常住人口209.67万人。", 2022) == {"population": 357.9}
    # 大连市2020年: a registered total is not the resident population
    assert values("年末全市户籍人口601.6万人，比上年末增加2.9万人，其中城镇人口400万人。", 2020) == {"population_registered": 601.6}


def test_births_are_not_population():
    # 达州市2023年国民经济和社会发展统计公报 (found by the cross-check against chinaciv)
    t = ("根据2023年全国人口变动情况抽样调查资料测算，全年全市常住人口出生人口3.07万人，人口出生率5.73‰；"
         "死亡人口3.89万人，人口死亡率7.28‰。")
    assert values(t, 2023) == {}


def test_2023_patterns_found_by_review():
    # 吉林省2023年: the 常住 breakdown comes two sentences after the total
    t = ("年末全省总人口为2339.41万人，人口减少数量由上年的27.68万人下降至8.28万人，人口跨省净流入4.34万人。全年出生人口8.84万人，"
         "出生率为3.77‰；死亡人口21.46万人，死亡率为9.16‰；自然增长率为-5.39‰。城镇常住人口1514.07万人，"
         "占总人口比重（常住人口城镇化率）为64.72%，比上年末提高0.99个百分点。户籍人口城镇化率为60.1%。")
    assert values(t, 2023) == {"population": 2339.41, "urbanization": 64.72}
    # 陕西省2023年: "城镇人口2575万人，占65.16%" in a paragraph about the resident population
    t = ("2023年末，全省常住人口3952万人，比上年减少4万人。其中，男性2017万人，占51.04%；女性1935万人，占48.96%，性别比为104.24。"
         "出生人口27万人，出生率为6.83‰；死亡人口32.2万人，死亡率为8.14‰；自然增长率为-1.31‰。城镇人口2575万人，占65.16%；"
         "乡村人口1377万人，占34.84%。")
    assert values(t, 2023) == {"population": 3952, "urbanization": 65.16}
    # 浙江省2023年 / 定西市2023年: the unit is printed once, after the last figure
    t = "分产业看，第一、二、三产业增加值分别为2332、33953和46268亿元，分别增长4.2%、5.0%和6.7%，三次产业结构为2.8:41.1:56.1。"
    assert values(t, 2023) == {"gdp_primary": 2332, "gdp_secondary": 33953, "gdp_tertiary": 46268}
    t = "其中，第一、二、三产业增加值分别为123.7、105.8、370.6亿元，分别比上年增长5.5%、11.0%、5.9%。"
    assert values(t, 2023) == {"gdp_primary": 123.7, "gdp_secondary": 105.8, "gdp_tertiary": 370.6}
    # 湖州市2023年
    t = "初步核算，2023年GDP总量迈上4千亿台阶，达到4015.1亿元，按可比价计算，比上年增长5.8%。"
    assert values(t, 2023) == {"gdp": 4015.1, "gdp_growth": 5.8}


# --------------------------------------------------------------------- 户籍人口 (population_registered)


def test_registered_and_resident_in_one_sentence():
    # 十堰市2021年 (tjcn 17hb/37060) / 宜昌市2021年 (17hb/37210) / 荆门市2021年 (17hb/37087): both figures, kept apart
    t = ("年末全市户籍人口339.95万人，常住人口315.82万人，其中城镇常住人口195.93万人，占常住总人口比重（常住人口城镇化率）为62.04%，"
         "比上年末提高0.1个百分点。")
    f = parse_fields(t, 2021)
    assert values(t, 2021) == {"population": 315.82, "population_registered": 339.95, "urbanization": 62.04}
    assert f["population_registered"]["quote"] == t and f["population_registered"]["raw"] == "339.95万人"
    assert values("年末全市常住人口391.01万人，户籍人口为387.89万人。", 2021) == {"population": 391.01,
                                                                    "population_registered": 387.89}
    t = "年末全市常住人口254.67万人，常住人口城镇化率59.76%；户籍人口285.69万人，户籍人口城镇化率43.42%。"
    assert values(t, 2021) == {"population": 254.67, "population_registered": 285.69, "urbanization": 59.76}


def test_resident_hukou_holders_are_not_the_registered_population():
    # 深圳市2021年 (19gd/37215) / 上海市2021年 (09sh/36960): 常住户籍人口 / 户籍常住人口 are the residents holding a local
    # hukou, a part of the resident population – not the registered total
    assert values("其中，常住户籍人口556.39万人，占常住人口比重31.5%；常住非户籍人口1211.77万人，占比重68.5%。", 2021) == {}
    assert values("其中，户籍常住人口1457.44万人，外来常住人口1031.99万人。", 2021) == {}


def test_registered_population_in_persons_and_in_parentheses():
    # 迪庆州2021年 (25yn/37282) / 甘南州2021年 (28gs/37189)
    assert values("2021年末，全州常住总人口38.9万人；户籍人口371448人。", 2021) == {"population": 38.9,
                                                                  "population_registered": 37.1448}
    t = "年末全州总人口（户籍人口）75.34万人，比上年末增加0.12万人，其中藏族人口42.94万人，增加0.22万人，占总人口数的56.99%。"
    assert values(t, 2021) == {"population_registered": 75.34}


def test_births_sexes_and_rates_are_not_the_registered_population():
    # 济宁市2021年 (15sd/37026) / 广州市2022年 (19gd/37586) / 厦门市2020年 (13fj/36662) / 镇江市2020年 (10js/36628) /
    # 景德镇市2021年 (14jx/37256)
    assert values("全年出生户籍人口7.1万人，死亡人口3.9万人，净增户籍人口0.4万人。", 2021) == {}
    t = ("年末户籍人口1034.91万人，其中，户籍出生人口10.96万人，出生率10.71‰；死亡人口5.74万人，死亡率5.61‰；"
         "自然增长人口5.22万人，自然增长率5.10‰。")
    assert values(t, 2022) == {"population_registered": 1034.91}
    assert values("户籍人口中，男性人口和女性人口分别为133.80万人、139.34万人，性别比为96.00（女性为100）。", 2020) == {}
    assert values("户籍人口中男性132.82万人，减少0.52人；女性136.43万人，减少0.39万人。", 2020) == {}
    assert values("户籍人口城镇化率为49.4%,比上年末提高0.2个百分点。", 2021) == {}


def test_registered_total_after_households_or_labelled_by_its_source():
    # 淄博市2021年 (15sd/37054): households first
    assert values("户籍人口总户数155.58万户，总人口434.04万人，其中，男性215.37万人，女性218.66万人。", 2021) \
        == {"population_registered": 434.04}
    # 丹东市2021年 (06ln/37080) / 葫芦岛市2020年 (06ln/36593) / 楚雄州2021年 (25yn/37038) / 黑河市2020年 (08hlj/36611):
    # a 总人口 that its own sentence attributes to the household registration (户籍 / 公安)
    assert values("根据户籍人口统计，年末总人口229.1万人，其中城镇人口105.4万人。", 2021) == {"population_registered": 229.1}
    assert values("从户籍看，年末全市总户数98.9万户，总人口272.4万人。", 2020) == {"population_registered": 272.4}
    assert values("按公安户籍人口统计，年末全州总人口2655301人，比上年末减少5108人。", 2021) \
        == {"population_registered": 265.5301}
    t = "据公安部门统计，年末，全市总人口155.5万人，其中，男性人口78.2万人，女性人口77.3万人；城镇人口90.7万人，乡村人口64.8万人。"
    assert values(t, 2020) == {"population_registered": 155.5}
    # 四平市2021年 (07jl/37277): an unlabelled 总人口 is neither
    assert values("年末全市总人口209.4万人，市区人口66.1万人，占总人口31.6%。", 2021) == {}


def test_registered_population_of_another_year_is_skipped():
    # 鞍山市2020年国民经济和社会发展统计公报; read as if a 2021 bulletin restated it, the figure is not 2021's
    assert values("2020年全市户籍总人口336.4万人。", 2020) == {"population_registered": 336.4}
    assert values("2020年全市户籍总人口336.4万人。", 2021) == {}


def test_gdp_per_capita_as_stated():
    assert values("按常住人口计算，全市人均GDP为43335元，增长6.6%。", 2023)["gdp_per_capita"] == 43335
    assert values("全年人均地区生产总值达到62771元，比上年增长5.1%。", 2023)["gdp_per_capita"] == 62771
    # income per head is a different keyword and must not leak into it
    assert "gdp_per_capita" not in values("全年全体居民人均可支配收入35339元，比上年增长5.2%。", 2023)
