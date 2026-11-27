"""Chinese place names in English for the design prototype: the project's names.json first, else corrected pinyin.

Shared by build_cityview.py (county names) and build_transport.py (railway and expressway names). pypinyin reads some
characters wrongly in place names (长宁 as Zhangning, 闵行 as Minxing, 丰都 as Fengdou, 川藏 as Chuancang); the readings
below fix those, and every Han-name prefecture and district in names.json comes out the same as its entry there.
"""
import json
import os
import re

from pypinyin import Style, lazy_pinyin, load_phrases_dict

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
        syl = ["zang" if ch == "藏" else x for ch, x in zip(c, syl)]
    out = syl[0]
    for x in syl[1:]:
        out += ("'" if x[:1] in "aoe" else "") + x
    return out.capitalize()
