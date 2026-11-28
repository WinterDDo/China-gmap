"""Food for the hometown card, second source: China's geographical indications protected under the China-EU agreement.

There is no single official list of all of China's geographical-indication products (they are announced notice by
notice). The Ministry of Commerce does publish, product by product with its place of origin, the Chinese names
protected in the EU under the 2020 agreement: https://ipr.mofcom.gov.cn/hwwq_2/chn_eu_gi/ . These are the best-known
ones (安吉白茶, 五常大米, 烟台苹果 ...), and each page gives "原产地：浙江省湖州市安吉县", so a product can be filed under
its prefecture without guessing.

Reads the category pages saved from that site and writes sources/gi_cn_eu.tsv:
    city <tab> name <tab> origin as printed <tab> registration lines <tab> page <tab> name as registered in the EU

Flowers are left out (this face is about food and drink). A product whose origin names no prefecture or county of ours
(a whole province, or several cities) is left out and printed, never guessed.

Usage   python3 build_gi.py <dir with chn-cat-*.html> data
"""
import glob
import html
import json
import os
import re
import sys

BASE = "https://ipr.mofcom.gov.cn/hwwq_2/chn_eu_gi/chn/"
SKIP_PAGES = ("chn-cat-02-2.13",)   # 花卉和观赏植物


def entries(path):
    s = open(path, "rb").read().decode("utf-8", "ignore")
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", t)
    lines = [re.sub(r"\s+", " ", x).strip() for x in html.unescape(re.sub(r"<[^>]+>", "", t)).split("\n")]
    lines = [x for x in lines if x]
    out, cur = [], None
    for x in lines:
        m = re.match(r"^(\d+)[．.]\s*(.+)$", x)
        if m and len(m.group(2)) <= 20:
            cur = {"name": m.group(2).strip(), "origin": "", "reg": [], "en": ""}
            out.append(cur)
        elif cur is not None:
            if x.startswith("原产地"):
                cur["origin"] = x.split("：", 1)[-1].strip()
            elif x.startswith("欧盟注册") and re.search(r"[／/]", x):   # 中文名／拉丁字母名; one page uses a half-width slash
                cur["en"] = re.split(r"[／/]", x, maxsplit=1)[1].strip()
            elif "地理标志产品保护" in x or "农产品地理标志" in x or "证明商标" in x or "集体商标" in x:
                cur["reg"].append(re.sub(r"^（\d+）", "", x.replace("注册类型：", "")).strip())
    return [e for e in out if e["origin"]]


def place_index(out_dir):
    cities = json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))
    cv = json.load(open(os.path.join(out_dir, "cityview.json"), encoding="utf-8"))
    full = {(c.get("full") or c["n"]): c for c in cities}
    counties = {}
    for cid, rows in cv["counties"].items():
        for r in rows:
            counties.setdefault(r[1], set()).add(cid)
    return cities, full, counties, {c["id"]: c for c in cities}


def city_of(origin, full, counties, by_id):
    """The one prefecture an origin names: 浙江省湖州市安吉县 -> 湖州. None when it names none, or more than one."""
    hits = {c["id"] for name, c in full.items() if name in origin}
    if not hits:
        tail = re.sub(r"^.*?(省|自治区)", "", origin)
        for name, ids in counties.items():
            if name in tail and len(ids) == 1:
                hits |= ids
    return by_id[next(iter(hits))] if len(hits) == 1 else None


def build(src, out_dir):
    cities, full, counties, by_id = place_index(out_dir)
    rows, left = [], []
    for path in sorted(glob.glob(os.path.join(src, "chn-cat-*.html"))):
        page = os.path.basename(path)[:-5]
        if page in SKIP_PAGES:
            continue
        for e in entries(path):
            c = city_of(e["origin"], full, counties, by_id)
            if c is None:
                left.append((e["name"], e["origin"]))
                continue
            rows.append([c["n"], e["name"], e["origin"], "；".join(e["reg"]) or "地理标志", BASE + page + ".html", e["en"]])
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "sources", "gi_cn_eu.tsv"), "w", encoding="utf-8") as f:
        f.write("# 中欧地理标志协定保护的中国地理标志产品（商务部 中国保护知识产权网 逐个产品页面，含原产地）。由 build_gi.py 生成，不要手改。\n")
        f.write("# 列：城市、产品名、原产地原文、国内注册类型、页面、欧盟注册名\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"{len(rows)} products filed under {len({r[0] for r in rows})} cities; left out (no single prefecture): {left}")
    return rows


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
