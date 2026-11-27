#!/usr/bin/env python3
"""Generate the bilingual (Simplified Chinese / English) place-name reference.

    python pipeline/reference/make_names.py \
        --provinces <DataV 100000_full.json> --children-dir <dir of <adcode>.json>

Writes, next to this script:
  names.json         {"<adcode>": {zh, zh_full, en, en_full, [en_disambig], level, parent}}
  names_review.csv   one row per unit for human review (source = pypinyin | override)

Scope: the 34 provincial-level units, every prefecture-level unit (地级市/地区/
自治州/盟), the districts and counties of the 4 municipalities, the county-level
units governed directly by a province (省直辖县级行政单位, adcode xx90xx; level
"county_direct"), and Taiwan's six cities under this project's own ids 710100…710600.
Hong Kong and Macao districts are out of scope.

Input: Alibaba DataV boundary GeoJSON (only the feature properties are read).
  --provinces      100000_full.json (named china_full.json in some caches)
  --children-dir   one file per province: <adcode>.json or <adcode>_full.json
                   (none is needed for 710000; missing ones are downloaded from
                   https://geo.datav.aliyun.com/areas_v3/bound/<adcode>_full.json
                   only with --fetch)

Romanization policy
-------------------
* Base: Hanyu Pinyin per GB/T 16159 (via pypinyin, reviewed): no tone marks,
  syllables joined, first letter capitalised, apostrophe before a non-initial
  syllable starting with a/o/e (Xi'an, Ma'anshan, Pu'er, Nan'an).
  A monosyllabic specific name is written joined to its generic (忠县 Zhongxian,
  en_full "Zhongxian County"), as on Chinese official maps.
* ü is kept as ü (吕梁 Lüliang) - never "v" or "yu".
* Names of minority-language origin use the transliteration of Chinese official
  maps / 国家地名信息库 (少数民族语地名汉语拼音字母音译转写法), keeping their
  diacritics (Ürümqi, Xigazê, Garzê, Dêqên). Every such override is listed in
  OVERRIDES below with a comment; pinyin-reading corrections are in PINYIN_FIX.
* Provinces use the established English names (Inner Mongolia, Shaanxi, Hong
  Kong, Macao, Xizang).
* Taiwan cities: conventional romanizations as used in PRC English-language media
  (Taipei, Kaohsiung ...) by default; --taiwan-pinyin switches to GB/T 16159 pinyin
  (Taibei, Gaoxiong ...).
* en_full: 地级市/县级市 = bare name; 地区 "Prefecture"; 自治州 "<Ethnic> Autonomous
  Prefecture"; 盟 "League"; 区 "District"; 新区 "New Area"; 县 "County"; 自治县
  "<Ethnic> Autonomous County"; 林区 "Forestry District".
* en_disambig only where two units share an `en`: "<en> (<province>)"; a province
  gets its en_full ("Hebei Province"); a city named like its own province gets
  "<en> City" (Jilin City).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

from pypinyin import Style, lazy_pinyin

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATAV_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{}_full.json"

MUNICIPALITIES = {"110000", "120000", "310000", "500000"}
SKIP_CHILDREN = {"810000", "820000", "710000"}  # HK/Macao districts out of scope; no DataV children for Taiwan

# ---------------------------------------------------------------------------
# Provincial level: short label and English name are fixed by the project.
# ---------------------------------------------------------------------------
PROVINCES = {
    # adcode: (zh, en)
    "110000": ("北京", "Beijing"),
    "120000": ("天津", "Tianjin"),
    "130000": ("河北", "Hebei"),
    "140000": ("山西", "Shanxi"),
    "150000": ("内蒙古", "Inner Mongolia"),  # override: English exonym (official map romanization: Nei Mongol)
    "210000": ("辽宁", "Liaoning"),
    "220000": ("吉林", "Jilin"),
    "230000": ("黑龙江", "Heilongjiang"),
    "310000": ("上海", "Shanghai"),
    "320000": ("江苏", "Jiangsu"),
    "330000": ("浙江", "Zhejiang"),
    "340000": ("安徽", "Anhui"),
    "350000": ("福建", "Fujian"),
    "360000": ("江西", "Jiangxi"),
    "370000": ("山东", "Shandong"),
    "410000": ("河南", "Henan"),
    "420000": ("湖北", "Hubei"),
    "430000": ("湖南", "Hunan"),
    "440000": ("广东", "Guangdong"),
    "450000": ("广西", "Guangxi"),
    "460000": ("海南", "Hainan"),
    "500000": ("重庆", "Chongqing"),
    "510000": ("四川", "Sichuan"),
    "520000": ("贵州", "Guizhou"),
    "530000": ("云南", "Yunnan"),
    "540000": ("西藏", "Xizang"),
    "610000": ("陕西", "Shaanxi"),  # override: official special spelling, distinguishes it from 山西 Shanxi
    "620000": ("甘肃", "Gansu"),
    "630000": ("青海", "Qinghai"),
    "640000": ("宁夏", "Ningxia"),
    "650000": ("新疆", "Xinjiang"),
    "710000": ("台湾", "Taiwan"),
    "810000": ("香港", "Hong Kong"),  # override: name fixed by the Basic Law (pinyin Xianggang)
    "820000": ("澳门", "Macao"),  # override: name fixed by the Basic Law, PRC spelling (pinyin Aomen)
}

# Taiwan's six cities; the ids are this project's own (GB/T 2260 only has 710000).
TAIWAN_CITIES = {
    # adcode: (zh_full, conventional, pinyin)
    "710100": ("台北市", "Taipei", "Taibei"),
    "710200": ("新北市", "New Taipei", "Xinbei"),
    "710300": ("桃园市", "Taoyuan", "Taoyuan"),
    "710400": ("台中市", "Taichung", "Taizhong"),
    "710500": ("台南市", "Tainan", "Tainan"),
    "710600": ("高雄市", "Kaohsiung", "Gaoxiong"),
}

# ---------------------------------------------------------------------------
# Non-pinyin overrides: specific name (generic and ethnic words removed) → en.
# Forms of Chinese official maps / 国家地名信息库 transliteration from the
# minority language; pinyin of the characters in the comment.
# ---------------------------------------------------------------------------
OVERRIDES = {
    # Inner Mongolia - Mongolian names
    "呼和浩特": "Hohhot",  # Mongolian Kökeqota (pinyin Huhehaote)
    "鄂尔多斯": "Ordos",  # Mongolian (pinyin E'erduosi)
    "呼伦贝尔": "Hulunbuir",  # Mongolian; also written Hulun Buir (pinyin Hulunbei'er)
    "巴彦淖尔": "Bayannur",  # Mongolian; also Bayan Nur (pinyin Bayannao'er)
    "乌兰察布": "Ulanqab",  # Mongolian (pinyin Wulanchabu)
    "兴安": "Hinggan",  # 兴安盟, from Manchu/Mongolian Khingan (pinyin Xing'an)
    "锡林郭勒": "Xilingol",  # Mongolian; official maps also Xilin Gol (pinyin Xilinguole)
    "阿拉善": "Alxa",  # Mongolian (pinyin Alashan)
    # Heilongjiang - Manchu / Daur names
    "哈尔滨": "Harbin",  # Manchu (pinyin Ha'erbin)
    "齐齐哈尔": "Qiqihar",  # Daur (pinyin Qiqiha'er)
    "大兴安岭": "Da Hinggan Ling",  # official map form of the range; pinyin Daxing'anling
    # Sichuan / Yunnan - Tibetan names
    "阿坝": "Ngawa",  # Tibetan rnga ba (pinyin Aba)
    "甘孜": "Garzê",  # Tibetan dkar mdzes (pinyin Ganzi)
    "迪庆": "Dêqên",  # Tibetan bde chen (pinyin Diqing)
    # Xizang - Tibetan names
    "拉萨": "Lhasa",  # (pinyin Lasa)
    "日喀则": "Xigazê",  # Tibetan gzhis ka rtse (pinyin Rikaze)
    "昌都": "Qamdo",  # Tibetan chab mdo (pinyin Changdu)
    "林芝": "Nyingchi",  # Tibetan nying khri (pinyin Linzhi)
    "那曲": "Nagqu",  # Tibetan nag chu (pinyin Naqu)
    "阿里": "Ngari",  # Tibetan mnga' ris (pinyin Ali)
    # Qinghai - Tibetan names
    "果洛": "Golog",  # Tibetan mgo log (pinyin Guoluo)
    # Xinjiang - Uygur / Mongolian / Kazak / Kirgiz names
    "乌鲁木齐": "Ürümqi",  # Mongolian/Uygur (pinyin Wulumuqi)
    "克拉玛依": "Karamay",  # Uygur (pinyin Kelamayi)
    "吐鲁番": "Turpan",  # Uygur (pinyin Tulufan)
    "博尔塔拉": "Bortala",  # Mongolian (pinyin Bo'ertala)
    "巴音郭楞": "Bayingolin",  # Mongolian (pinyin Bayinguoleng)
    "阿克苏": "Aksu",  # Uygur (pinyin Akesu)
    "克孜勒苏": "Kizilsu",  # Kirgiz (pinyin Kezilesu)
    "和田": "Hotan",  # Uygur (pinyin Hetian)
    "伊犁": "Ili",  # (pinyin Yili)
    "阿勒泰": "Altay",  # Mongolian/Kazak (pinyin Aletai)
    # Xinjiang - XPCC cities governed directly by the region (county_direct)
    "阿拉尔": "Aral",  # Uygur (pinyin A'la'er)
    "图木舒克": "Tumxuk",  # Uygur (pinyin Tumushuke)
    "可克达拉": "Kokdala",  # Kazak (pinyin Kekedala)
}

# Pinyin corrections where pypinyin picks the wrong reading of a polyphone.
# These are still pinyin; they are reported with source "override".
PINYIN_FIX = {
    "朝阳": "chao yang",  # 朝 cháo (Beijing district and Liaoning city); pypinyin: zhao
    "长治": "chang zhi",  # 长 cháng; pypinyin: zhang
    "长宁": "chang ning",  # 长 cháng (Shanghai); pypinyin: zhang
    "闵行": "min hang",  # 行 háng (Shanghai); pypinyin: xing
    "漯河": "luo he",  # 漯 luò (Henan); pypinyin: ta
    "丰都": "feng du",  # 都 dū (Chongqing); pypinyin: dou
    # Overridden names: only the pinyin echoed in the review note uses these.
    "锡林郭勒": "xi lin guo le",  # 勒 lè; pypinyin: lei
    "克孜勒苏": "ke zi le su",  # 勒 lè; pypinyin: lei
    "阿勒泰": "a le tai",  # 勒 lè; pypinyin: lei
    "昌都": "chang du",  # 都 dū; pypinyin: dou
}

# Characters with more than one reading that occur in scope: the chosen
# syllable is echoed in the review note so a reader can check it at a glance.
POLYPHONES = set("长重朝行乐六丽蚌亳厦莆宿济莞澄都漯台吕坻虹沈藏尾华兴万屯石色曲和单会番")

# Ethnic words in autonomous-unit names (longest first) and their English forms.
ETHNIC = [
    ("柯尔克孜族", "Kirgiz"), ("柯尔克孜", "Kirgiz"),
    ("哈萨克族", "Kazak"), ("哈萨克", "Kazak"),
    ("维吾尔族", "Uygur"), ("维吾尔", "Uygur"),
    ("蒙古族", "Mongol"), ("蒙古", "Mongol"),
    ("朝鲜族", "Korean"), ("土家族", "Tujia"), ("布依族", "Bouyei"), ("哈尼族", "Hani"),
    ("景颇族", "Jingpo"), ("傈僳族", "Lisu"),
    ("苗族", "Miao"), ("藏族", "Tibetan"), ("羌族", "Qiang"), ("彝族", "Yi"), ("侗族", "Dong"),
    ("壮族", "Zhuang"), ("傣族", "Dai"), ("白族", "Bai"), ("回族", "Hui"), ("黎族", "Li"),
]

# Generic (通名) suffixes, longest first, with the en_full pattern.
GENERICS = [
    ("特别行政区", "{} Special Administrative Region"),
    ("自治区", "{} Autonomous Region"),
    ("自治州", "{} Autonomous Prefecture"),
    ("自治县", "{} Autonomous County"),
    ("地区", "{} Prefecture"),
    ("林区", "{} Forestry District"),
    ("新区", "{} New Area"),
    ("省", "{} Province"),
    ("盟", "{} League"),
    ("市", "{}"),  # municipalities get "{} Municipality" (below)
    ("区", "{} District"),
    ("县", "{} County"),
]

# Review notes (by adcode), for things a reader should double-check.
NOTES = {
    "150000": "official map romanization: Nei Mongol",
    "540000": "formerly Tibet in English; current PRC usage Xizang",
    "650000": "en_full uses PRC spelling Uygur (also Uyghur)",
    "820000": "PRC official spelling Macao (also Macau)",
    "150700": "also written Hulun Buir",
    "150800": "also written Bayan Nur",
    "152500": "also written Xilin Gol (official maps, Inner Mongolia govt)",
    "232700": "official map form; also Daxing'anling (pinyin) / Greater Khingan",
    "513200": "the form Aba (pinyin) is also used by Sichuan sources",
    "513300": "diacritic kept (ASCII Garze); Ganzi also seen",
    "533400": "diacritics kept (ASCII Deqen); Diqing also seen",
    "540200": "diacritic kept (ASCII Xigaze)",
    "540500": "Chinese-origin name, pinyin (Tibetan Lhoka not used on official maps)",
    "632700": "Chinese-origin name, pinyin (seat Gyêgu)",
    "650100": "diacritic kept (ASCII Urumqi)",
    "650500": "official maps use Hami (Uygur Kumul)",
    "653100": "official maps use Kashi (conventional Kashgar)",
    "654200": "official maps use Tacheng (Chinese name)",
    "659001": "XPCC city",
    "659002": "XPCC city",
    "659003": "XPCC city",
    "659008": "XPCC city",
    "141100": "ü kept (ASCII fallbacks Lyuliang / Lvliang)",
    "500233": "monosyllabic name joined with generic (Zhongxian); zh keeps 县",
    "710200": "en_full kept bare like other cities (commonly New Taipei City)",
}

TAIWAN_NOTE = {
    "conventional": "conventional romanization as in PRC English-language media; GB/T 16159 pinyin: {}",
    "pinyin": "GB/T 16159 pinyin; conventional romanization: {}",
    "same": "conventional and GB/T 16159 pinyin forms coincide",
}


# ---------------------------------------------------------------------------
def join_pinyin(syllables: list[str]) -> str:
    """GB/T 16159: join syllables, apostrophe before a/o/e, capitalise the first letter."""
    out = ""
    for i, s in enumerate(syllables):
        if not s or set(s) - set("abcdefghijklmnopqrstuvwxyzü"):
            raise ValueError(f"not a pinyin syllable: {s!r}")
        out += ("'" if i and s[0] in "aoe" else "") + s
    return out[:1].upper() + out[1:]


def pinyin_of(text: str) -> list[str]:
    return lazy_pinyin(text, style=Style.NORMAL, v_to_u=True, errors=lambda x: [f"?{x}"])


def fold(s: str) -> str:
    """Accent- and case-insensitive key (ü→u, ê→e) for spotting duplicate romanizations."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)).lower()


def split_name(zh_full: str) -> tuple[str, str, list[str]]:
    """'延边朝鲜族自治州' → ('延边', '自治州', ['朝鲜族'])."""
    for generic, _ in GENERICS:
        if zh_full.endswith(generic) and len(zh_full) > len(generic):
            base = zh_full[: -len(generic)]
            break
    else:
        raise ValueError(f"no generic in {zh_full!r}")
    ethnic: list[str] = []
    if generic.startswith("自治"):
        stripped = True
        while stripped:
            stripped = False
            for word, _ in ETHNIC:
                if base.endswith(word) and len(base) - len(word) >= 2:
                    ethnic.insert(0, word)
                    base = base[: -len(word)]
                    stripped = True
                    break
    return base, generic, ethnic


def ethnic_en(words: list[str]) -> str:
    names = [dict(ETHNIC)[w] for w in words]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def romanize(base: str, generic: str) -> tuple[str, str, str]:
    """→ (en, source, note) for a specific name."""
    if base in OVERRIDES:
        syl = PINYIN_FIX[base].split() if base in PINYIN_FIX else pinyin_of(base)
        return OVERRIDES[base], "override", f"official transliteration (pinyin {join_pinyin(syl)})"
    if base in PINYIN_FIX:
        syl = PINYIN_FIX[base].split()
        got = pinyin_of(base)
        if syl == got:
            print(f"  ! PINYIN_FIX[{base}] no longer needed (pypinyin agrees)", file=sys.stderr)
        return join_pinyin(syl), "override", f"polyphone fix (pypinyin: {' '.join(got)})"
    word = base if len(base) > 1 else base + generic[-1]  # 忠县 → Zhongxian
    syl = pinyin_of(word)
    if any(s.startswith("?") for s in syl):
        raise ValueError(f"pypinyin cannot read {word!r}: {syl}")
    checks = [f"{c}={s}" for c, s in zip(word, syl) if c in POLYPHONES]
    return join_pinyin(syl), "pypinyin", ("polyphone checked: " + ", ".join(checks)) if checks else ""


# ---------------------------------------------------------------------------
def load_features(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [ft["properties"] for ft in json.load(f)["features"]]


def child_file(children_dir: Path, adcode: str, fetch: bool) -> Path:
    for name in (f"{adcode}.json", f"{adcode}_full.json"):
        if (children_dir / name).exists():
            return children_dir / name
    if not fetch:
        raise FileNotFoundError(f"no DataV children file for {adcode} in {children_dir} (use --fetch)")
    dest = children_dir / f"{adcode}_full.json"
    req = urllib.request.Request(DATAV_URL.format(adcode), headers={"User-Agent": "map-names/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    return dest


def collect(provinces_file: Path, children_dir: Path, fetch: bool) -> list[dict]:
    """Raw units: adcode, zh_full, level, parent, province."""
    units = []
    for p in load_features(provinces_file):
        if p.get("level") != "province":
            continue  # e.g. the 100000_JD nine-dash-line feature
        pcode = str(p["adcode"])
        units.append({"adcode": pcode, "zh_full": p["name"], "level": "province", "parent": "100000", "province": pcode})
        if pcode in SKIP_CHILDREN:
            continue
        for c in load_features(child_file(children_dir, pcode, fetch)):
            code = str(c["adcode"])
            if pcode in MUNICIPALITIES:
                level = "district"
            elif code[2:4] == "90":
                level = "county_direct"  # 省直辖县级行政单位 (xx90xx)
            else:
                level = "city"
            units.append({"adcode": code, "zh_full": c["name"], "level": level, "parent": pcode, "province": pcode})
    for code, (zh_full, *_rest) in TAIWAN_CITIES.items():
        units.append({"adcode": code, "zh_full": zh_full, "level": "city", "parent": "710000", "province": "710000"})
    codes = [u["adcode"] for u in units]
    dupes = {c for c in codes if codes.count(c) > 1}
    if dupes:
        raise ValueError(f"duplicate adcodes: {sorted(dupes)}")
    return sorted(units, key=lambda u: u["adcode"])


def build(units: list[dict], taiwan_style: str) -> list[dict]:
    rows = []
    for u in units:
        code, zh_full, level = u["adcode"], u["zh_full"], u["level"]
        base, generic, ethnic = split_name(zh_full)
        pattern = dict(GENERICS)[generic]
        if level == "province":
            zh, en = PROVINCES[code]
            if generic == "市":
                pattern = "{} Municipality"
            py = join_pinyin(pinyin_of(zh))
            source = "pypinyin" if py == en else "override"
            note = "" if source == "pypinyin" else f"established English name (pinyin {py})"
        elif code in TAIWAN_CITIES:
            zh = base
            _, conv, py = TAIWAN_CITIES[code]
            en = conv if taiwan_style == "conventional" else py
            other = py if taiwan_style == "conventional" else conv
            source = "pypinyin" if en == join_pinyin(pinyin_of(base)) else "override"
            note = "project id; " + TAIWAN_NOTE["same" if conv == py else taiwan_style].format(other)
        else:
            zh = base if len(base) > 1 else zh_full  # keep 忠县, never a 1-character label
            en, source, note = romanize(base, generic)
        if ethnic:
            pattern = pattern.replace("Autonomous", ethnic_en(ethnic) + " Autonomous")
        en_full = pattern.format(en)
        extra = NOTES.get(code, "")
        note = "; ".join(n for n in (note, extra) if n)
        rows.append({**u, "zh": zh, "en": en, "en_full": en_full, "source": source, "note": note})
    add_disambig(rows)
    return rows


def add_disambig(rows: list[dict]) -> None:
    prov_en = {r["adcode"]: r["en"] for r in rows if r["level"] == "province"}
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(fold(r["en"]), []).append(r)
    for group in groups.values():
        if len(group) < 2:
            continue
        for r in group:
            if r["level"] == "province":
                r["en_disambig"] = r["en_full"]
            elif prov_en[r["province"]] == r["en"]:
                r["en_disambig"] = f"{r['en']} City"
            else:
                r["en_disambig"] = f"{r['en']} ({prov_en[r['province']]})"
        labels = [r["en_disambig"] for r in group]
        if len(set(labels)) != len(labels):
            raise ValueError(f"en_disambig not unique: {labels}")
        for r in group:
            others = ", ".join(f"{o['zh_full']} {o['adcode']}" for o in group if o is not r)
            r["note"] = "; ".join(n for n in (r["note"], f"shares en with {others}") if n)


# ---------------------------------------------------------------------------
def write_outputs(rows: list[dict], out_dir: Path) -> None:
    keys = ("zh", "zh_full", "en", "en_full", "en_disambig", "level", "parent")
    lines = []
    for r in rows:
        entry = {k: r[k] for k in keys if k in r}
        lines.append(f'"{r["adcode"]}":' + json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    (out_dir / "names.json").write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")

    buf = io.StringIO()
    cols = ["adcode", "zh_full", "zh", "en", "en_full", "level", "source", "note"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    (out_dir / "names_review.csv").write_text(buf.getvalue(), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provinces", type=Path, default=ROOT / "data/raw/datav/100000_full.json")
    ap.add_argument("--children-dir", type=Path, default=ROOT / "data/raw/datav")
    ap.add_argument("--out-dir", type=Path, default=HERE)
    ap.add_argument("--fetch", action="store_true", help="download missing DataV children files")
    ap.add_argument("--taiwan-pinyin", action="store_true", help="GB/T 16159 pinyin for Taiwan cities (Taibei ...)")
    args = ap.parse_args(argv)

    units = collect(args.provinces, args.children_dir, args.fetch)
    rows = build(units, "pinyin" if args.taiwan_pinyin else "conventional")
    write_outputs(rows, args.out_dir)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["level"]] = counts.get(r["level"], 0) + 1
    n_over = sum(r["source"] == "override" for r in rows)
    n_dis = sum("en_disambig" in r for r in rows)
    print(f"{len(rows)} units {counts}; {n_over} overrides; {n_dis} with en_disambig → {args.out_dir}")


if __name__ == "__main__":
    main()
