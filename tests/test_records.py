"""parse/records.py: building records, merging sources, coverage.csv and the chinaciv cross-check (in a temp dir)."""

import csv
import json

from conftest import FIXTURES

from pipeline.parse import records
from pipeline.parse.places import PlaceMatcher
from pipeline.sources.tjcn_bulletins import decode, parse_page

M = PlaceMatcher()


def _rec(fixture, code, year=2023, source="tjcn_bulletins"):
    page = parse_page(decode((FIXTURES / fixture).read_bytes()))
    url = "http://www.tjcn.org/tjgb/x/1.html"
    return records.build_record({"code": code, "name": M.label(code), "year": year, "source": source}, url=url,
                                title=page["title"], bureau=page["bureau"], published=page["published"],
                                body_html=page["body_html"], base_url=url, names=M.names)


def test_text_record():
    r = _rec("tjcn_shijiazhuang_2023_text.html", "130100")
    assert r["status"] == "text" and r["level"] == "city" and r["province"] == "130000"
    assert r["bureau"] == "石家庄市统计局" and r["dated"] == "2024-03-11"
    assert r["fields"]["gdp"]["value"] == 7534.2 and r["fields_found"] == 12
    assert r["flags"] == []


def test_image_only_record_keeps_urls_and_parses_nothing():
    r = _rec("tjcn_taiyuan_2023_image_only.html", "140100")
    assert r["status"] == "image_only"
    assert len(r["images"]) == 20 and r["images"][0].startswith("https://stats.taiyuan.gov.cn/")
    assert r["fields_found"] == 0 and all(v is None for v in r["fields"].values())


def test_title_mismatch_flag():
    r = _rec("tjcn_shijiazhuang_2023_text.html", "130200")  # the page is 石家庄's, not 唐山's
    assert "title_mismatch" in r["flags"]


def test_merge_prefers_text_then_more_fields_then_official_page():
    tj = _rec("tjcn_taiyuan_2023_image_only.html", "140100")
    loc = dict(_rec("tjcn_shijiazhuang_2023_text.html", "130100"), code="140100", source="local_bulletins")
    best = records.merge([tj, loc])
    assert best["source"] == "local_bulletins" and best["other_sources"][0]["status"] == "image_only"
    a = _rec("tjcn_shijiazhuang_2023_text.html", "130100")
    b = dict(a, source="local_bulletins")
    assert records.merge([a, b])["source"] == "local_bulletins"  # same quality: the bureau's own page


def test_write_outputs_and_crosscheck(tmp_path):
    root = tmp_path / "bulletins"
    r = _rec("tjcn_shijiazhuang_2023_text.html", "130100")
    miss = records.missing_record({"code": "130200", "name": "唐山市", "year": 2023, "source": "tjcn_bulletins"})
    payload = {"source": "tjcn_bulletins", "year": 2023, "records": [r, miss]}
    (root / "sources" / "tjcn_bulletins").mkdir(parents=True)
    (root / "sources" / "tjcn_bulletins" / "2023.json").write_text(json.dumps(payload, ensure_ascii=False))
    summary = records.write_outputs(M, root=root)
    assert summary["2023"]["text"] == 1 and summary["2023"]["missing"] == 1
    merged = json.loads((root / "2023.json").read_text())
    assert [x["code"] for x in merged["records"]] == ["130100", "130200"]
    rows = list(csv.DictReader((root / "coverage.csv").open(encoding="utf-8")))
    assert rows[0]["status"] == "text" and rows[0]["fields_found"] == "12" and rows[1]["status"] == "missing"

    civ = tmp_path / "city_stats"
    civ.mkdir()
    (civ / "cities.json").write_text(json.dumps([{"id": "130100", "kind": "city", "population": 11233500,
                                                  "population_year": 2023, "gdp": 753420000000, "gdp_year": 2023,
                                                  "gdp_by_industry": {"primary": 57690000000, "secondary": 230920000000,
                                                                      "tertiary": 470000000000}}]))
    (civ / "states.json").write_text("[]")
    (civ / "nation.json").write_text(json.dumps({"nation": {}}))
    out = records.crosscheck_chinaciv(civ, [r, miss], out_dir=root)
    assert out["compared"] == 5 and out["agree"] == 4 and out["differ"] == 1
    assert out["worst"][0]["field"] == "gdp_tertiary" and out["worst"][0]["rel_diff"] < 0
    assert (root / "crosscheck_2023.csv").exists()
