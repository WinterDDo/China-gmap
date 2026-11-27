"""Licence-plate prefix of each city for the hometown card ("川R，到家了。"): data/plates.json.

The card stays lean and must not be wrong (owner, 2026-11-27: 「你写得多容易错得多，只要精简」), so a city gets a
prefix only when two things agree, and none otherwise:

  1. Wikidata's "licence plate code" (P395) for the prefecture, fetched from query.wikidata.org. Wikidata is a compiled
     copy; the issuing authority is the Ministry of Public Security (standard GA 36, 发牌机关代号).
  2. A second reading: the table in RECALL below, written down independently. It is compare-only and never a source.

Where Wikidata lists several prefixes for a city (成都 川A/川G, 苏州 苏E/苏U) the card shows the long-standing first
one, which is the one both readings share. Where Wikidata has no value, or the two disagree, the city is in VERIFIED
with the page that confirms it (checked 2026-11-27), or it gets nothing. The four municipalities show their
one-character abbreviation, since their letters do not stand for places.

Left out on purpose: area codes and postcodes. Wikidata has several wrong or outdated area codes (营口, 七台河, 萍乡,
抚顺, 铁岭) and the ministry's own lookup site could not be reached from the cloud, so they wait for an official table
(TODOS.md). The ID-number prefix is out too: see docs/DECISIONS.md.

Usage   python3 build_plates.py <wikidata result .json> data
        The query is in QUERY; run it against https://query.wikidata.org/sparql with Accept: application/sparql-results+json.
"""
import json
import os
import re
import sys

QUERY = """SELECT ?item ?itemLabel ?code (GROUP_CONCAT(DISTINCT ?plate; separator="|") AS ?plates) WHERE {
  ?item wdt:P442 ?code . FILTER(REGEX(?code, "^[0-9]{2}( ?[0-9]{2})?$"))
  OPTIONAL { ?item wdt:P395 ?plate }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "zh-cn,zh-hans,zh,en". }
} GROUP BY ?item ?itemLabel ?code"""

PROV = {"13": "冀", "14": "晋", "15": "蒙", "21": "辽", "22": "吉", "23": "黑", "32": "苏", "33": "浙", "34": "皖", "35": "闽", "36": "赣",
        "37": "鲁", "41": "豫", "42": "鄂", "43": "湘", "44": "粤", "45": "桂", "46": "琼", "51": "川", "52": "贵", "53": "云", "54": "藏",
        "61": "陕", "62": "甘", "63": "青", "64": "宁", "65": "新"}
MUNICIPAL = {"110000": "京", "120000": "津", "310000": "沪", "500000": "渝"}
RECALL = {  # compare-only second reading, first letter listed is the long-standing one
    "冀": "A石家庄 B唐山 C秦皇岛 D邯郸 E邢台 F保定 G张家口 H承德 J沧州 R廊坊 T衡水",
    "晋": "A太原 B大同 C阳泉 D长治 E晋城 F朔州 H忻州 J吕梁 K晋中 L临汾 M运城",
    "蒙": "A呼和浩特 B包头 C乌海 D赤峰 E呼伦贝尔 F兴安 G通辽 H锡林郭勒 J乌兰察布 K鄂尔多斯 L巴彦淖尔 M阿拉善",
    "辽": "A沈阳 B大连 C鞍山 D抚顺 E本溪 F丹东 G锦州 H营口 J阜新 K辽阳 L盘锦 M铁岭 N朝阳 P葫芦岛",
    "吉": "A长春 B吉林 C四平 D辽源 E通化 F白山 G白城 H延边 J松原",
    "黑": "A哈尔滨 L哈尔滨 B齐齐哈尔 C牡丹江 D佳木斯 E大庆 F伊春 G鸡西 H鹤岗 J双鸭山 K七台河 M绥化 N黑河 P大兴安岭",
    "苏": "A南京 B无锡 C徐州 D常州 E苏州 U苏州 F南通 G连云港 H淮安 J盐城 K扬州 L镇江 M泰州 N宿迁",
    "浙": "A杭州 B宁波 C温州 D绍兴 E湖州 F嘉兴 G金华 H衢州 J台州 K丽水 L舟山",
    "皖": "A合肥 B芜湖 C蚌埠 D淮南 E马鞍山 F淮北 G铜陵 H安庆 J黄山 K阜阳 L宿州 M滁州 N六安 P宣城 R池州 S亳州",
    "闽": "A福州 B莆田 C泉州 D厦门 E漳州 F龙岩 G三明 H南平 J宁德",
    "赣": "A南昌 M南昌 B赣州 C宜春 D吉安 E上饶 F抚州 G九江 H景德镇 J萍乡 K新余 L鹰潭",
    "鲁": "A济南 B青岛 U青岛 C淄博 D枣庄 E东营 F烟台 Y烟台 G潍坊 V潍坊 H济宁 J泰安 K威海 L日照 M滨州 N德州 P聊城 Q临沂 R菏泽",
    "豫": "A郑州 V郑州 B开封 C洛阳 D平顶山 E安阳 F鹤壁 G新乡 H焦作 J濮阳 K许昌 L漯河 M三门峡 N商丘 P周口 Q驻马店 R南阳 S信阳",
    "鄂": "A武汉 B黄石 C十堰 D荆州 E宜昌 F襄阳 G鄂州 H荆门 J黄冈 K孝感 L咸宁 Q恩施 S随州",
    "湘": "A长沙 B株洲 C湘潭 D衡阳 E邵阳 F岳阳 G张家界 H益阳 J常德 K娄底 L郴州 M永州 N怀化 U湘西",
    "粤": "A广州 B深圳 C珠海 D汕头 E佛山 X佛山 Y佛山 F韶关 G湛江 H肇庆 J江门 K茂名 L惠州 M梅州 N汕尾 P河源 Q阳江 R清远 S东莞 T中山 U潮州 V揭阳 W云浮",
    "桂": "A南宁 B柳州 C桂林 H桂林 D梧州 E北海 F崇左 G来宾 J贺州 K玉林 L百色 M河池 N钦州 P防城港 R贵港",
    "琼": "A海口 B三亚 F儋州",
    "川": "A成都 G成都 B绵阳 C自贡 D攀枝花 E泸州 F德阳 H广元 J遂宁 K内江 L乐山 M资阳 Q宜宾 R南充 S达州 T雅安 U阿坝 V甘孜 W凉山 X广安 Y巴中 Z眉山",
    "贵": "A贵阳 B六盘水 C遵义 D铜仁 E黔西南 F毕节 G安顺 H黔东南 J黔南",
    "云": "A昆明 C昭通 D曲靖 E楚雄 F玉溪 G红河 H文山 J普洱 K西双版纳 L大理 M保山 N德宏 P丽江 Q怒江 R迪庆 S临沧",
    "藏": "A拉萨 B昌都 C山南 D日喀则 E那曲 F阿里 G林芝",
    "陕": "A西安 U西安 B铜川 C宝鸡 D咸阳 E渭南 F汉中 G安康 H商洛 J延安 K榆林",
    "甘": "A兰州 B嘉峪关 C金昌 D白银 E天水 F酒泉 G张掖 H武威 J定西 K陇南 L平凉 M庆阳 N临夏 P甘南",
    "青": "A西宁 B海东 C海北 D黄南 E海南 F果洛 G玉树 H海西",
    "宁": "A银川 B石嘴山 C吴忠 D固原 E中卫",
    "新": "A乌鲁木齐 B昌吉 E博尔塔拉 F伊犁 G塔城 H阿勒泰 J克拉玛依 K吐鲁番 L哈密 M巴音郭楞 N阿克苏 P克孜勒苏 Q喀什 R和田",
}
ICAUTO, ZHIHU = "https://www.icauto.com.cn/baike/chepai/", "https://www.zhihu.com/tardis/jm/art/2032037417838965185"
VERIFIED = {  # Wikidata empty or wrong; each confirmed on the page named (2026-11-27). 拉萨 found no confirming page: left out.
    "济南": ("鲁A", "https://www.sohu.com/a/73677058_390941"), "青岛": ("鲁B", "https://www.sohu.com/a/73677058_390941"),
    "黄石": ("鄂B", "https://www.icauto.com.cn/baike/70/708990.html"), "荆州": ("鄂D", "https://www.icauto.com.cn/baike/70/708990.html"),
    "荆门": ("鄂H", "https://www.icauto.com.cn/baike/70/708990.html"), "黄冈": ("鄂J", "https://www.icauto.com.cn/baike/70/708990.html"),
    "咸宁": ("鄂L", "https://www.icauto.com.cn/baike/70/708990.html"),
    "张家界": ("湘G", "https://www.icauto.com.cn/baike/chepai/430000/"), "益阳": ("湘H", "https://www.icauto.com.cn/baike/chepai/430000/"),
    "永州": ("湘M", "https://www.icauto.com.cn/baike/chepai/430000/"),
    "北海": ("桂E", ZHIHU), "来宾": ("桂G", ZHIHU), "贺州": ("桂J", ZHIHU), "百色": ("桂L", ZHIHU), "河池": ("桂M", ZHIHU),
    "景德镇": ("赣H", ZHIHU), "新余": ("赣K", ZHIHU), "鹰潭": ("赣L", ZHIHU),
    "武威": ("甘H", "https://www.icauto.com.cn/baike/52/529237.html"),  # Wikidata says 甘F, which is 酒泉
    "舟山": ("浙L", ICAUTO), "亳州": ("皖S", "https://www.icauto.com.cn/baike/70/708951.html"),
    "濮阳": ("豫J", "https://www.icauto.com.cn/baike/52/529038.html"), "鹤壁": ("豫F", "https://www.icauto.com.cn/baike/70/709097.html"),
    "三亚": ("琼B", ZHIHU), "儋州": ("琼F", ZHIHU), "海东": ("青B", "https://chejiahao.autohome.com.cn/info/25012678"),
}


def recall():
    out = {}
    for ch, s in RECALL.items():
        for tok in s.split():
            out.setdefault((ch, tok[1:]), []).append(ch + tok[0])
    return out


def wikidata(path):
    rows = {}
    for b in json.load(open(path, encoding="utf-8"))["results"]["bindings"]:
        code = b["code"]["value"].replace(" ", "")
        vals = set()
        for p in b.get("plates", {}).get("value", "").split("|"):
            vals.update(m.group(1) + m.group(2) for m in re.finditer(r"([一-鿿])\s?([A-Z])", p))
        rows[code] = (b["item"]["value"].split("/")[-1], vals)
    return rows


def build(wd_path, out_dir):
    cities = json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))
    wd, mine, out, left = wikidata(wd_path), recall(), {}, []
    for c in cities:
        cid, ch = c["id"], PROV.get(c["id"][:2])
        if cid in MUNICIPAL:
            out[cid] = {"plate": MUNICIPAL[cid], "src": "省级行政区简称"}
            continue
        if ch is None or cid.endswith("0000"):
            continue  # 港澳台: no mainland plate
        q, vals = wd.get(cid[:4], (None, set()))
        both = [p for p in mine.get((ch, c["n"]), []) if p in vals]
        if both and c["n"] not in VERIFIED:
            out[cid] = {"plate": both[0], "src": f"wikidata {q} P395"}
        elif c["n"] in VERIFIED and VERIFIED[c["n"]][0] in mine.get((ch, c["n"]), []):
            out[cid] = {"plate": VERIFIED[c["n"]][0], "src": VERIFIED[c["n"]][1]}
        else:
            left.append(c["n"])
    # no two cities of a province may share a prefix
    seen = {}
    for cid, v in out.items():
        assert seen.setdefault((cid[:2], v["plate"]), cid) == cid or cid in MUNICIPAL, (cid, v, seen[(cid[:2], v["plate"])])
    doc = {"note": "发牌机关代号：公安部 GA 36；经维基数据（P395）与第二份读数互校，缺的逐条查证，查不到的留空", "plates": out}
    json.dump(doc, open(os.path.join(out_dir, "plates.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} of {len(cities)} cities have a plate prefix; left empty: {left}")
    return doc


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
