"""City View data for the design prototype: each prefecture's counties and the sites inside it.

counties  DataV.GeoAtlas infos.json (areas_v3/bound/infos.json): every county-level unit's name and centre, projected
          with the prototype's own Albers equal-area (lat1 25, lat2 47, lon0 105, km) into its map frame.
sites     chinaciv's compiled public lists (MIT, Karpathy's usaciv adapted to China), each with its own source:
          UNESCO World Heritage, national parks, 5A scenic areas and Double First-Class universities (wonders.json),
          civil airports with 2025 passenger numbers and major ports (infrastructure.json), and large power plants and
          mines (resources.json). chinaciv's frame differs from ours by a constant shift, measured here on the cities
          both share.

English names: chinaciv's own name_en where it has one (World Heritage sites, most plants and mines), the
universities', scenic areas' and national parks' official English names below, airports as "<city> <terminal> (IATA)",
and for counties the project's own pipeline/reference/names.json first, pinyin only where it has no entry (it lists
prefectures and municipal districts; elsewhere minority-language spellings such as Barkol for 巴里坤 are still missing,
see TODOS.md). Pinyin also names the wind and solar clusters, which are named after their county.

Usage: python build_cityview.py <infos.json> <chinaciv web/data dir> <design data dir>   (needs pypinyin)
"""
import json
import math
import os
import statistics
import re
import sys

from pypinyin import Style, lazy_pinyin, load_phrases_dict

infos_p, cc_dir, out_dir = sys.argv[1:4]
geo = json.load(open(os.path.join(out_dir, "geo.json"), encoding="utf-8"))
ours = {c["id"]: c for c in json.load(open(os.path.join(out_dir, "cities.json"), encoding="utf-8"))}
FR = geo["frame"]
D = math.pi / 180
Rr, P1, P2, L0 = 6371.0088, 25 * D, 47 * D, 105 * D
N = (math.sin(P1) + math.sin(P2)) / 2
C = math.cos(P1) ** 2 + 2 * N * math.sin(P1)
RHO0 = Rr * math.sqrt(C) / N


def proj(lon, lat):
    rho = Rr * math.sqrt(C - 2 * N * math.sin(lat * D)) / N
    th = N * (lon * D - L0)
    return round(rho * math.sin(th) - FR["x0"], 1), round(FR["y1"] - (RHO0 - rho * math.cos(th)), 1)


HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = json.load(open(os.path.join(HERE, "..", "..", "pipeline", "reference", "names.json"), encoding="utf-8"))
ETH = ("土家 苗 侗 瑶 壮 彝 藏 羌 回 满 蒙古 哈萨克 维吾尔 柯尔克孜 塔吉克 锡伯 达斡尔 鄂温克 鄂伦春 朝鲜 布依 水 仡佬 黎 畲 纳西 傈僳 拉祜 佤 傣 "
       "哈尼 景颇 白 普米 怒 独龙 阿昌 德昂 布朗 基诺 仫佬 毛南 京 土 撒拉 东乡 保安 裕固 门巴 珞巴 塔塔尔 俄罗斯 乌孜别克 赫哲").split()
# readings pypinyin gets wrong in place names (checked against names.json: every Han-name prefecture and district matches)
load_phrases_dict({k: [[x] for x in v.split()] for k, v in {
    "长宁": "cháng níng", "长沙": "cháng shā", "长春": "cháng chūn", "长治": "cháng zhì", "长子": "zhǎng zǐ", "闵行": "mǐn háng", "朝阳": "cháo yáng",
    "重庆": "chóng qìng", "乐山": "lè shān", "乐清": "yuè qīng", "乐亭": "lào tíng", "六安": "lù ān", "六合": "lù hé", "蚌埠": "bèng bù", "番禺": "pān yú",
    "厦门": "xià mén", "亳州": "bó zhōu", "莘县": "shēn xiàn", "泌阳": "bì yáng", "犍为": "qián wéi", "尉氏": "wèi shì", "东阿": "dōng ē", "洪洞": "hóng tóng",
    "铅山": "yán shān", "单县": "shàn xiàn", "会理": "huì lǐ", "会同": "huì tóng", "会东": "huì dōng", "会泽": "huì zé", "会宁": "huì níng", "会昌": "huì chāng",
    "台州": "tāi zhōu", "天台": "tiān tāi", "调兵山": "diào bīng shān", "莎车": "shā chē", "柞水": "zhà shuǐ", "华蓥": "huá yíng", "阆中": "làng zhōng",
    "濮阳": "pú yáng", "曲阜": "qū fù", "曲靖": "qǔ jìng", "曲沃": "qǔ wò", "曲周": "qǔ zhōu", "曲阳": "qǔ yáng", "大足": "dà zú", "綦江": "qí jiāng", "漯河": "luò hé",
}.items()})


def core(name):
    """Drop the administrative suffix, and for autonomous counties the people's names before it: 石柱土家族自治县 -> 石柱."""
    m = re.match(r"^(.+?)(自治县|自治旗|自治州直辖|自治州|地区|林区|特区|新区|矿区|盟|区|县|市|旗)$", name)
    if not m:
        return name, ""
    c, suf = m.groups()
    if suf.startswith("自治"):
        cut = True
        while cut:
            cut = False
            for e in sorted(ETH, key=len, reverse=True):
                for t in ((e + "族", e) if len(e) > 1 else (e + "族",)):
                    if c.endswith(t) and len(c) > len(t):
                        c, cut = c[:-len(t)], True
                        break
                if cut:
                    break
    return c, suf


def py(name, code=None):
    """English for a place: names.json when it has the code, else pinyin (锦江区 -> Jinjiang, 静安区 -> Jing'an, 忠县 -> Zhongxian)."""
    if code and code in NAMES:
        return NAMES[code]["en"]
    c, suf = core(name)
    if len(c) == 1 and suf in ("区", "县", "市", "旗"):
        c += suf
    syl = lazy_pinyin(c, style=Style.NORMAL, v_to_u=True)
    if len(syl) == len(c):
        syl = ["du" if ch == "都" else x for ch, x in zip(c, syl)]
        if c[0] == "长" and not c.startswith("长子"):
            syl[0] = "chang"
    out = syl[0]
    for x in syl[1:]:
        out += ("'" if x[:1] in "aoe" else "") + x
    return out.capitalize()


EN = {  # official English names of the listed universities, 5A scenic areas and national parks
    "北京大学": "Peking University", "中国人民大学": "Renmin University of China", "清华大学": "Tsinghua University",
    "北京航空航天大学": "Beihang University", "北京理工大学": "Beijing Institute of Technology", "中国农业大学": "China Agricultural University",
    "北京师范大学": "Beijing Normal University", "中央民族大学": "Minzu University of China", "南开大学": "Nankai University",
    "天津大学": "Tianjin University", "大连理工大学": "Dalian University of Technology", "吉林大学": "Jilin University",
    "哈尔滨工业大学": "Harbin Institute of Technology", "复旦大学": "Fudan University", "同济大学": "Tongji University",
    "上海交通大学": "Shanghai Jiao Tong University", "华东师范大学": "East China Normal University", "南京大学": "Nanjing University",
    "东南大学": "Southeast University", "浙江大学": "Zhejiang University", "中国科学技术大学": "University of Science and Technology of China",
    "厦门大学": "Xiamen University", "山东大学": "Shandong University", "中国海洋大学": "Ocean University of China",
    "武汉大学": "Wuhan University", "华中科技大学": "Huazhong University of Science and Technology", "中南大学": "Central South University",
    "中山大学": "Sun Yat-sen University", "华南理工大学": "South China University of Technology", "四川大学": "Sichuan University",
    "重庆大学": "Chongqing University", "电子科技大学": "University of Electronic Science and Technology of China",
    "西安交通大学": "Xi'an Jiaotong University", "西北工业大学": "Northwestern Polytechnical University", "兰州大学": "Lanzhou University",
    "东北大学": "Northeastern University", "郑州大学": "Zhengzhou University", "湖南大学": "Hunan University", "云南大学": "Yunnan University",
    "西北农林科技大学": "Northwest A&F University", "新疆大学": "Xinjiang University",
    "天津古文化街": "Tianjin Ancient Culture Street", "盘山": "Mount Panshan", "白洋淀": "Baiyangdian Lake", "沈阳植物园": "Shenyang Botanical Garden",
    "老虎滩": "Tiger Beach", "长白山": "Changbai Mountain", "伪满皇宫": "Museum of the Imperial Palace of Manchukuo", "太阳岛": "Sun Island",
    "东方明珠": "Oriental Pearl Tower", "上海野生动物园": "Shanghai Wild Animal Park", "周庄": "Zhouzhuang Water Town", "钟山": "Purple Mountain",
    "三国水浒城": "Three Kingdoms and Water Margin City", "雁荡山": "Yandang Mountain", "普陀山": "Mount Putuo", "九华山": "Mount Jiuhua",
    "井冈山": "Jinggang Mountains", "蓬莱阁": "Penglai Pavilion", "云台山": "Yuntai Mountain", "黄鹤楼": "Yellow Crane Tower",
    "三峡大坝": "Three Gorges Dam", "衡山": "Mount Heng", "长隆": "Chimelong", "华侨城": "Overseas Chinese Town", "三亚南山": "Nanshan, Sanya",
    "大小洞天": "Daxiaodongtian", "黄果树瀑布": "Huangguoshu Waterfall", "龙宫": "Dragon Palace Cave", "玉龙雪山": "Jade Dragon Snow Mountain",
    "华清宫": "Huaqing Palace", "黄帝陵": "Mausoleum of the Yellow Emperor", "崆峒山": "Mount Kongtong", "沙湖": "Sand Lake",
    "沙坡头": "Shapotou", "葡萄沟": "Grape Valley", "喀纳斯": "Kanas Lake",
    "三江源": "Sanjiangyuan National Park", "大熊猫": "Giant Panda National Park", "东北虎豹": "Northeast China Tiger and Leopard National Park",
    "海南热带雨林": "Hainan Tropical Rainforest National Park", "武夷山": "Wuyishan National Park",
}
RES_EN = {"nuclear": "nuclear plant", "hydro": "hydropower", "coal_mine": "coal mine", "rare_earths": "rare earths", "lithium": "lithium",
          "tungsten": "tungsten", "antimony": "antimony", "gold": "gold", "copper": "copper", "lead_zinc": "lead and zinc", "bauxite": "bauxite",
          "iron": "iron ore", "coal_plant": "coal power", "gas_plant": "gas power", "geothermal": "geothermal", "pumped_storage": "pumped storage",
          "wind": "wind farms", "solar": "solar farms", "oil": "oilfield", "gas": "gas field"}

infos = json.load(open(infos_p, encoding="utf-8"))
counties, checks = {}, []
for cid, c in ours.items():
    node = infos.get(cid) or {}
    kids = []
    for k in node.get("children") or []:
        if k.get("level") not in ("district", "county"):
            continue
        lon, lat = k.get("centroid") or k.get("center")
        x, y = proj(lon, lat)
        kids.append([str(k["adcode"]), k["name"], k["level"][0], x, y, py(k["name"], str(k["adcode"]))])
    if kids:
        counties[cid] = kids
    parent = next((p for p in (infos.get(cid[:2] + "0000") or {}).get("children") or [] if str(p.get("adcode")) == cid), None)
    if parent and parent.get("center"):
        x, y = proj(*parent["center"])
        checks.append(math.hypot(x - c["x"], y - c["y"]))

cities_cc = json.load(open(os.path.join(cc_dir, "cities.json"), encoding="utf-8"))
cities_cc = cities_cc if isinstance(cities_cc, list) else cities_cc.get("cities", [])
dx = statistics.median(ours[x["id"]]["x"] - x["x"] for x in cities_cc if x.get("id") in ours)
dy = statistics.median(ours[x["id"]]["y"] - x["y"] for x in cities_cc if x.get("id") in ours)
shift = lambda o: (round(o["x"] + dx, 1), round(o["y"] + dy, 1))  # noqa: E731

sites = {}
def add(cid, row):
    if cid in ours:
        sites.setdefault(cid, []).append(row)

w = json.load(open(os.path.join(cc_dir, "wonders.json"), encoding="utf-8"))
KIND = {"unesco_whs": "whs", "national_park": "park", "scenic_5a": "a5", "university": "uni"}
for o in w["wonders"]:
    if o.get("x") is None or not o.get("cbsa"):
        continue
    nm = o.get("short") or o["name"]
    add(o["cbsa"], [KIND.get(o["rule"], "site"), nm, *shift(o), (o.get("metrics") or {}).get("inscribed") or o.get("rank"), None,
                    o.get("name_en") or EN.get(nm) or EN.get(o["name"]) or py(nm), None])
inf = json.load(open(os.path.join(cc_dir, "infrastructure.json"), encoding="utf-8"))
for a in inf["airports"]:
    if a.get("cbsa"):
        city, _, term = a["name"].partition("/")
        en = (ours.get(a["cbsa"]) or {}).get("en") or py(city)
        add(a["cbsa"], ["air", a["name"].split("/")[-1] + ("机场" if not a["name"].endswith("机场") else ""), *shift(a), a.get("passengers"), None,
                        f"{en} {py(term)} ({a['id']})" if term and py(term) != en else f"{en} ({a['id']})", None])
for pt in inf["ports"]:
    if pt.get("cbsa"):
        add(pt["cbsa"], ["port", pt.get("name"), *shift(pt), pt.get("cargo_t"), None, "Port of " + pt["id"].replace("-", "-").title(), None])
res = json.load(open(os.path.join(cc_dir, "resources.json"), encoding="utf-8"))
rtype = {t["id"]: t["name"] for t in res["types"]}
by_city = {}
for r in res["items"]:
    if r.get("cbsa"):
        by_city.setdefault(r["cbsa"], []).append(r)
for cid, items in by_city.items():
    for r in sorted(items, key=lambda r: -(r.get("value") or 0))[:5]:
        en = r.get("name_en") or f'{py(re.sub(r"(风电场群|光伏电站群|光伏电站|风电场)$", "", r["name"]))} {RES_EN.get(r["type"], r["type"])}'
        add(cid, ["res:" + r["type"], r["name"], *shift(r), r.get("value"), rtype.get(r["type"], r["type"]), en, RES_EN.get(r["type"], r["type"])])

out = {"counties": counties, "sites": sites,
       "sources": {"counties": "阿里云 DataV.GeoAtlas 行政区划（infos.json）；英文名取 names.json，没有的用拼音", "sites": "chinaciv 汇编（MIT）：联合国教科文组织世界遗产名录、国家公园、5A 景区、双一流高校、民航机场生产统计公报 2025、主要港口、Global Energy Monitor 电厂与矿山"},
       "shift": [round(dx, 2), round(dy, 2)]}
json.dump(out, open(os.path.join(out_dir, "cityview.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("counties for", len(counties), "cities,", sum(len(v) for v in counties.values()), "units; sites for", len(sites), "cities,",
      sum(len(v) for v in sites.values()), "sites; chinaciv shift", round(dx, 2), round(dy, 2),
      "; city-centre check: median", round(statistics.median(checks), 1) if checks else None, "km, max", round(max(checks), 1) if checks else None, "km")
