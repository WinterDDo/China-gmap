"""Population and GDP of every prefecture-level unit, province and the nation (2020 census; 2023 bulletins).

Phase-1 upstream: the figures compiled by the open-source project chinaciv (MIT) from the 2023 国民经济和社会发展
统计公报 of each city/prefecture and province (as republished by 中国统计信息网 tjcn.org, with the bureau's own
attachments where the page text lacked a value), provincial 统计年鉴2024 city tables, and 国家统计局's 第七次全国
人口普查公报. chinaciv's sources.json, fetched alongside, lists every original bulletin URL it read; the Almanac shows
that chain. A later phase replaces this with our own collection straight from the bureaus.

Pinned to one chinaciv commit so the numbers cannot change under us.
"""

from __future__ import annotations

import json

from ..core.source import Source, SourceInfo

COMMIT = "386760928b3c6615fb44e4a8fb4fbebb5489f3d5"
BASE = f"https://raw.githubusercontent.com/threeaus/chinaciv/{COMMIT}/web/data"
FILES = ["cities.json", "states.json", "nation.json", "sources.json"]
KEEP_CITY = ["id", "name", "full", "kind", "kind_label", "states", "capital", "province_capital", "population",
             "population_year", "pop_census_2020", "gdp", "gdp_year", "gdp_by_industry", "growth", "growth_years", "note"]
KEEP_PROV = ["fips", "name", "full", "kind", "population", "population_year", "pop_census_2020", "gdp", "gdp_year",
             "gdp_by_industry", "growth", "growth_years", "note"]


class CityStats(Source):
    info = SourceInfo(
        id="city_stats",
        title="地级行政区、省级行政区与全国的人口和地区生产总值（七普 2020；2023 年统计公报）",
        publisher="国家统计局；各省、市（州、盟）统计局（2023 年国民经济和社会发展统计公报、统计年鉴2024）；香港特区政府统计处；"
        "台湾地区内政部户政司。第一阶段经开源项目 chinaciv 汇编（其 sources.json 逐条列出所读取的公报原文网址）",
        homepage="https://www.stats.gov.cn/",
        license="政府公开统计资料；汇编代码 MIT（chinaciv）",
        description="每个地级行政区（含直辖市、香港、澳门）与省级行政区的：第七次全国人口普查常住人口（2020-11-01）、2023 年末常住人口、"
        "2023 年地区生产总值（现价）及三次产业增加值。全国为国家统计局 2023 年统计公报（31 个省区市合计，不含港澳台）。"
        f"本项目第一阶段直接使用 chinaciv 在提交 {COMMIT[:7]} 中整理好的数值，不做任何改动；缺失的数据保持为空，不以其他年份替代。"
        "后续阶段将由本项目自己的管线从各统计局原文重新采集。",
        used_for=["城市人口、GDP、人均 GDP、产业结构", "人口增长（2020→2023）", "省级与全国合计", "透镜"],
    )

    def fetch(self, force: bool = False) -> None:
        for name in FILES:
            self.download(f"{BASE}/{name}", name, force=force)

    def process(self) -> dict:
        load = lambda n: json.loads((self.raw_dir / n).read_text(encoding="utf-8"))  # noqa: E731
        cities = [{k: c.get(k) for k in KEEP_CITY} for c in load("cities.json")]
        provinces = [{k: s.get(k) for k in KEEP_PROV} for s in load("states.json")]
        nation = load("nation.json")
        upstream = [s for s in load("sources.json") if s.get("id") == "cn_stats_city"]
        bulletin_files = upstream[0]["files"] if upstream else []
        return {
            "vintage": "七普 2020；2023 年统计公报",
            "year": nation.get("year"),
            "census_year": nation.get("census_year"),
            "scope": nation.get("scope"),
            "nation": {k: nation["nation"].get(k) for k in ("population", "population_year", "pop_census_2020", "gdp",
                                                             "gdp_year", "gdp_by_industry", "growth", "growth_years")},
            "cities": cities,
            "provinces": provinces,
            "upstream_description": upstream[0].get("description") if upstream else None,
            "upstream_files": [{"file": f.get("file"), "url": f.get("url"), "retrieved": f.get("retrieved")} for f in bulletin_files],
            "_files": FILES,
        }
