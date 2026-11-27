"""tools/local_fetch/fetch_osm_lines.py: everything but the live Overpass servers, which only answer on the owner's network.

A small Overpass stand-in on 127.0.0.1 answers the province queries, so the whole run (query, thinning, files, zip)
is exercised offline."""

import gzip
import http.server
import json
import threading
import zipfile

import fetch_osm_lines as fo


def test_queries_ask_for_the_three_kinds_by_province_code():
    q = fo.query_for("SC", "51", "rail")
    assert 'area["ISO3166-2"~"^CN-(SC|51)$"]' in q and '"highspeed"="yes"' in q and '"usage"="main"' in q
    assert '[!"service"]' in q and "out tags geom" in q and "motorway" not in q
    r = fo.query_for("SC", "51", "road")
    assert '"highway"="motorway"' in r and "railway" not in r
    assert 'area["ISO3166-1"="TW"]' in fo.query_for("TW", "71", "road")
    assert len(fo.PROVINCES) == 34 and len({p[0] for p in fo.PROVINCES}) == 34


def test_simplify_keeps_bends_and_drops_points_on_a_straight_line():
    straight = [(104.0 + i * 0.001, 30.0) for i in range(50)]
    assert fo.simplify(straight) == [straight[0], straight[-1]]
    bend = [(104.0, 30.0), (104.01, 30.0), (104.01, 30.01)]  # a right angle about 1 km on each side
    assert fo.simplify(bend) == bend
    wiggle = [(104.0, 30.0), (104.005, 30.0005), (104.01, 30.0)]  # 55 m off the chord: under 150 m, dropped
    assert fo.simplify(wiggle) == [wiggle[0], wiggle[-1]]


def test_compact_classifies_and_keeps_only_useful_tags():
    answer = {"elements": [
        {"type": "way", "tags": {"railway": "rail", "highspeed": "yes", "name": "成渝高速铁路", "maxspeed": "350",
                                 "gauge": "1435"}, "geometry": [{"lat": 30.6, "lon": 104.1}, {"lat": 29.6, "lon": 106.5}]},
        {"type": "way", "tags": {"railway": "rail", "usage": "main", "name": "宝成铁路"}, "geometry": [{"lat": 30.7, "lon": 104.0}, {"lat": 31.0, "lon": 104.2}]},
        {"type": "way", "tags": {"highway": "motorway", "ref": "G5", "name": "京昆高速"}, "geometry": [{"lat": 30.7, "lon": 104.0}, {"lat": 31.5, "lon": 104.7}]},
        {"type": "way", "tags": {"highway": "motorway"}, "geometry": [{"lat": 30.7, "lon": 104.0}]},  # one point: dropped
    ]}
    rows = fo.compact(answer)
    assert [r[0] for r in rows] == ["hsr", "rail", "exp"]
    assert rows[0][1] == {"name": "成渝高速铁路", "maxspeed": "350", "highspeed": "yes"}  # gauge dropped
    assert rows[2][1]["ref"] == "G5" and rows[2][2] == [104.0, 30.7, 104.7, 31.5]


class Overpass(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        Overpass.calls.append(body)
        rail = "railway" in body
        els = [{"type": "way", "tags": {"railway": "rail", "highspeed": "yes", "name": "成渝高速铁路"} if rail else
                {"highway": "motorway", "ref": "G5"}, "geometry": [{"lat": 30.6, "lon": 104.1}, {"lat": 29.6, "lon": 106.5}]}]
        out = json.dumps({"osm3s": {"timestamp_osm_base": "2026-11-27T00:00:00Z"}, "elements": els}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_a_province_run_writes_files_and_a_zip(tmp_path, monkeypatch):
    srv = http.server.HTTPServer(("127.0.0.1", 0), Overpass)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(fo, "MIRRORS", [f"http://127.0.0.1:{srv.server_port}/api/interpreter"])
    monkeypatch.setattr(fo, "OUT", str(tmp_path / "osm_lines"))
    monkeypatch.setattr(fo, "ZIP", str(tmp_path / "out.zip"))
    monkeypatch.setattr(fo.time, "sleep", lambda s: None)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    try:
        assert fo.main(["--only", "SC"]) == 0
    finally:
        srv.shutdown()
    with zipfile.ZipFile(tmp_path / "out.zip") as z:
        names = sorted(z.namelist())
        assert names == ["osm_lines/SC-rail.json.gz", "osm_lines/SC-road.json.gz", "osm_lines/manifest.json"]
        rec = json.loads(gzip.decompress(z.read("osm_lines/SC-rail.json.gz")))
        assert rec["ways"][0][0] == "hsr" and rec["osm_base"] == "2026-11-27T00:00:00Z" and "ODbL" in rec["license"]
        assert json.loads(z.read("osm_lines/manifest.json"))["failed"] == []
    # a second run resumes: nothing is asked again
    n = len(Overpass.calls)
    monkeypatch.setattr(fo, "MIRRORS", ["http://127.0.0.1:9/never"])
    assert fo.main(["--only", "SC"]) == 0 and len(Overpass.calls) == n
