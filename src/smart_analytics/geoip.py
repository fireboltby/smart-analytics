"""离线 GeoIP 国家/省份/城市识别（不依赖 Cloudflare 头）。

数据库文件（.mmdb）不随仓库分发，需自行下载：
    scripts/fetch_geoip.py          # 默认下载 DB-IP city-lite（含省份/城市）
默认从 DB-IP 免费库（CC-BY 4.0，无需 license key）拉取。

解析结果统一返回中文名：
- 国家：内置 COUNTRY_NAMES（ISO 3166-1 alpha-2 -> 中文）
- 省份：中国用内置 PROVINCE_NAMES（ISO 3166-2 CN -> 中文），其余国家回退库自带名
- 城市：优先库自带 zh-CN 名，否则用内置 CITY_NAMES（英文 -> 中文）兜底，再否则英文

数据库缺失/不可用时优雅降级为 None（与历史行为一致）。
"""

from __future__ import annotations

import os
import threading

try:
    import geoip2.database

    _GEOIP_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖缺失时降级
    _GEOIP_AVAILABLE = False

_reader = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 中文名映射
# ---------------------------------------------------------------------------

# 国家（ISO 3166-1 alpha-2 -> 中文）
COUNTRY_NAMES = {
    "AD": "安道尔", "AE": "阿联酋", "AF": "阿富汗", "AG": "安提瓜和巴布达", "AI": "安圭拉",
    "AL": "阿尔巴尼亚", "AM": "亚美尼亚", "AO": "安哥拉", "AQ": "南极洲", "AR": "阿根廷",
    "AS": "美属萨摩亚", "AT": "奥地利", "AU": "澳大利亚", "AW": "阿鲁巴", "AX": "奥兰群岛",
    "AZ": "阿塞拜疆", "BA": "波斯尼亚和黑塞哥维那", "BB": "巴巴多斯", "BD": "孟加拉国", "BE": "比利时",
    "BF": "布基纳法索", "BG": "保加利亚", "BH": "巴林", "BI": "布隆迪", "BJ": "贝宁",
    "BL": "圣巴泰勒米", "BM": "百慕大", "BN": "文莱", "BO": "玻利维亚", "BQ": "荷兰加勒比区",
    "BR": "巴西", "BS": "巴哈马", "BT": "不丹", "BV": "布韦岛", "BW": "博茨瓦纳",
    "BY": "白俄罗斯", "BZ": "伯利兹", "CA": "加拿大", "CC": "科科斯群岛", "CD": "刚果（金）",
    "CF": "中非共和国", "CG": "刚果（布）", "CH": "瑞士", "CI": "科特迪瓦", "CK": "库克群岛",
    "CL": "智利", "CM": "喀麦隆", "CN": "中国", "CO": "哥伦比亚", "CR": "哥斯达黎加",
    "CU": "古巴", "CV": "佛得角", "CW": "库拉索", "CX": "圣诞岛", "CY": "塞浦路斯",
    "CZ": "捷克", "DE": "德国", "DJ": "吉布提", "DK": "丹麦", "DM": "多米尼克",
    "DO": "多米尼加", "DZ": "阿尔及利亚", "EC": "厄瓜多尔", "EE": "爱沙尼亚", "EG": "埃及",
    "EH": "西撒哈拉", "ER": "厄立特里亚", "ES": "西班牙", "ET": "埃塞俄比亚", "FI": "芬兰",
    "FJ": "斐济", "FK": "福克兰群岛", "FM": "密克罗尼西亚", "FO": "法罗群岛", "FR": "法国",
    "GA": "加蓬", "GB": "英国", "GD": "格林纳达", "GE": "格鲁吉亚", "GF": "法属圭亚那",
    "GG": "根西", "GH": "加纳", "GI": "直布罗陀", "GL": "格陵兰", "GM": "冈比亚",
    "GN": "几内亚", "GP": "瓜德罗普", "GQ": "赤道几内亚", "GR": "希腊", "GS": "南乔治亚和南桑威奇群岛",
    "GT": "危地马拉", "GU": "关岛", "GW": "几内亚比绍", "GY": "圭亚那", "HK": "中国香港",
    "HM": "赫德岛和麦克唐纳群岛", "HN": "洪都拉斯", "HR": "克罗地亚", "HT": "海地", "HU": "匈牙利",
    "ID": "印度尼西亚", "IE": "爱尔兰", "IL": "以色列", "IM": "马恩岛", "IN": "印度",
    "IO": "英属印度洋领地", "IQ": "伊拉克", "IR": "伊朗", "IS": "冰岛", "IT": "意大利",
    "JE": "泽西", "JM": "牙买加", "JO": "约旦", "JP": "日本", "KE": "肯尼亚",
    "KG": "吉尔吉斯斯坦", "KH": "柬埔寨", "KI": "基里巴斯", "KM": "科摩罗", "KN": "圣基茨和尼维斯",
    "KP": "朝鲜", "KR": "韩国", "KW": "科威特", "KY": "开曼群岛", "KZ": "哈萨克斯坦",
    "LA": "老挝", "LB": "黎巴嫩", "LC": "圣卢西亚", "LI": "列支敦士登", "LK": "斯里兰卡",
    "LR": "利比里亚", "LS": "莱索托", "LT": "立陶宛", "LU": "卢森堡", "LV": "拉脱维亚",
    "LY": "利比亚", "MA": "摩洛哥", "MC": "摩纳哥", "MD": "摩尔多瓦", "ME": "黑山",
    "MF": "圣马丁", "MG": "马达加斯加", "MH": "马绍尔群岛", "MK": "北马其顿", "ML": "马里",
    "MM": "缅甸", "MN": "蒙古", "MO": "中国澳门", "MP": "北马里亚纳群岛", "MQ": "马提尼克",
    "MR": "毛里塔尼亚", "MR?": "毛里塔尼亚", "MS": "蒙特塞拉特", "MT": "马耳他", "MU": "毛里求斯",
    "MV": "马尔代夫", "MW": "马拉维", "MX": "墨西哥", "MY": "马来西亚", "MZ": "莫桑比克",
    "NA": "纳米比亚", "NC": "新喀里多尼亚", "NE": "尼日尔", "NF": "诺福克岛", "NG": "尼日利亚",
    "NI": "尼加拉瓜", "NL": "荷兰", "NO": "挪威", "NP": "尼泊尔", "NR": "瑙鲁",
    "NU": "纽埃", "NZ": "新西兰", "OM": "阿曼", "PA": "巴拿马", "PE": "秘鲁",
    "PF": "法属波利尼西亚", "PG": "巴布亚新几内亚", "PH": "菲律宾", "PK": "巴基斯坦", "PL": "波兰",
    "PM": "圣皮埃尔和密克隆", "PN": "皮特凯恩群岛", "PR": "波多黎各", "PS": "巴勒斯坦", "PT": "葡萄牙",
    "PW": "帕劳", "PY": "巴拉圭", "QA": "卡塔尔", "RE": "留尼汪", "RO": "罗马尼亚",
    "RS": "塞尔维亚", "RU": "俄罗斯", "RW": "卢旺达", "SA": "沙特阿拉伯", "SB": "所罗门群岛",
    "SC": "塞舌尔", "SD": "苏丹", "SE": "瑞典", "SG": "新加坡", "SH": "圣赫勒拿",
    "SI": "斯洛文尼亚", "SJ": "斯瓦尔巴和扬马延", "SK": "斯洛伐克", "SL": "塞拉利昂", "SM": "圣马力诺",
    "SN": "塞内加尔", "SO": "索马里", "SR": "苏里南", "SS": "南苏丹", "ST": "圣多美和普林西比",
    "SV": "萨尔瓦多", "SX": "圣马丁（荷属）", "SY": "叙利亚", "SZ": "斯威士兰", "TC": "特克斯和凯科斯群岛",
    "TD": "乍得", "TF": "法属南部领地", "TG": "多哥", "TH": "泰国", "TJ": "塔吉克斯坦",
    "TK": "托克劳", "TL": "东帝汶", "TM": "土库曼斯坦", "TN": "突尼斯", "TO": "汤加",
    "TR": "土耳其", "TT": "特立尼达和多巴哥", "TV": "图瓦卢", "TW": "中国台湾", "TZ": "坦桑尼亚",
    "UA": "乌克兰", "UG": "乌干达", "UM": "美国本土外小岛屿", "US": "美国", "UY": "乌拉圭",
    "UZ": "乌兹别克斯坦", "VA": "梵蒂冈", "VC": "圣文森特和格林纳丁斯", "VE": "委内瑞拉",
    "VG": "英属维尔京群岛", "VI": "美属维尔京群岛", "VN": "越南", "VU": "瓦努阿图",
    "WF": "瓦利斯和富图纳", "WS": "萨摩亚", "YE": "也门", "YT": "马约特", "ZA": "南非",
    "ZM": "赞比亚", "ZW": "津巴布韦",
}

# 中国省级行政区（ISO 3166-2 CN -> 中文）
PROVINCE_NAMES = {
    "CN-11": "北京", "CN-12": "天津", "CN-13": "河北", "CN-14": "山西", "CN-15": "内蒙古",
    "CN-21": "辽宁", "CN-22": "吉林", "CN-23": "黑龙江", "CN-31": "上海", "CN-32": "江苏",
    "CN-33": "浙江", "CN-34": "安徽", "CN-35": "福建", "CN-36": "江西", "CN-37": "山东",
    "CN-41": "河南", "CN-42": "湖北", "CN-43": "湖南", "CN-44": "广东", "CN-45": "广西",
    "CN-46": "海南", "CN-50": "重庆", "CN-51": "四川", "CN-52": "贵州", "CN-53": "云南",
    "CN-54": "西藏", "CN-61": "陕西", "CN-62": "甘肃", "CN-63": "青海", "CN-64": "宁夏",
    "CN-65": "新疆",     "CN-71": "台湾", "CN-81": "香港", "CN-82": "澳门",
}

# 英文省/州名 -> 中文（覆盖中国全部省级 + 主要外国一级行政区）。
# 注意：DB-IP city-lite 的 subdivisions.iso_code 为 None，只能靠英文名兜底，
# 故此处用英文名作为主映射来源；库自带 zh-CN 时优先用库。
EN_PROVINCE_NAMES = {
    # 中国（省级行政区，34 个）
    "Beijing": "北京", "Tianjin": "天津", "Hebei": "河北", "Shanxi": "山西",
    "Inner Mongolia": "内蒙古", "Liaoning": "辽宁", "Jilin": "吉林", "Heilongjiang": "黑龙江",
    "Shanghai": "上海", "Jiangsu": "江苏", "Zhejiang": "浙江", "Anhui": "安徽",
    "Fujian": "福建", "Jiangxi": "江西", "Shandong": "山东", "Henan": "河南",
    "Hubei": "湖北", "Hunan": "湖南", "Guangdong": "广东", "Guangxi": "广西",
    "Hainan": "海南", "Chongqing": "重庆", "Sichuan": "四川", "Guizhou": "贵州",
    "Yunnan": "云南", "Tibet": "西藏", "Shaanxi": "陕西", "Gansu": "甘肃",
    "Qinghai": "青海", "Ningxia": "宁夏", "Xinjiang": "新疆", "Taiwan": "台湾",
    "Hong Kong": "香港", "Kowloon": "九龙", "Macau": "澳门",
    # 美国主要州
    "California": "加利福尼亚", "New York": "纽约州", "Texas": "得克萨斯", "Florida": "佛罗里达",
    "Illinois": "伊利诺伊", "Washington": "华盛顿州", "Massachusetts": "马萨诸塞",
    "Pennsylvania": "宾夕法尼亚", "Ohio": "俄亥俄", "Georgia": "佐治亚", "Michigan": "密歇根",
    "North Carolina": "北卡罗来纳", "Virginia": "弗吉尼亚", "Arizona": "亚利桑那",
    "Indiana": "印第安纳", "Tennessee": "田纳西", "Missouri": "密苏里", "Maryland": "马里兰",
    "Wisconsin": "威斯康星", "Colorado": "科罗拉多", "Minnesota": "明尼苏达",
    "South Carolina": "南卡罗来纳", "Alabama": "亚拉巴马", "Louisiana": "路易斯安那",
    "Kentucky": "肯塔基", "Oregon": "俄勒冈", "Oklahoma": "俄克拉荷马", "Connecticut": "康涅狄格",
    "Iowa": "艾奥瓦", "Mississippi": "密西西比", "Arkansas": "阿肯色", "Kansas": "堪萨斯",
    "Utah": "犹他", "Nevada": "内华达", "Nebraska": "内布拉斯加", "New Mexico": "新墨西哥",
    "West Virginia": "西弗吉尼亚", "Idaho": "爱达荷", "Hawaii": "夏威夷", "Maine": "缅因",
    "New Hampshire": "新罕布什尔", "Rhode Island": "罗得岛", "Montana": "蒙大拿",
    "Delaware": "特拉华", "South Dakota": "南达科他", "North Dakota": "北达科他",
    "Alaska": "阿拉斯加", "Vermont": "佛蒙特", "Wyoming": "怀俄明",
    # 加拿大
    "Ontario": "安大略", "Quebec": "魁北克", "British Columbia": "不列颠哥伦比亚",
    "Alberta": "阿尔伯塔", "Manitoba": "曼尼托巴", "Saskatchewan": "萨斯喀彻温",
    "Nova Scotia": "新斯科舍", "New Brunswick": "新不伦瑞克",
    "Newfoundland and Labrador": "纽芬兰与拉布拉格", "Prince Edward Island": "爱德华王子岛",
    # 澳大利亚
    "New South Wales": "新南威尔士", "Victoria": "维多利亚", "Queensland": "昆士兰",
    "Western Australia": "西澳大利亚", "South Australia": "南澳大利亚",
    "Tasmania": "塔斯马尼亚", "Australian Capital Territory": "澳大利亚首都领地",
    "Northern Territory": "北领地",
    # 英国
    "England": "英格兰", "Scotland": "苏格兰", "Wales": "威尔士", "Northern Ireland": "北爱尔兰",
    # 日本
    "Tokyo": "东京都", "Osaka": "大阪府", "Hokkaido": "北海道", "Aichi": "爱知县",
    "Kanagawa": "神奈川县", "Fukuoka": "福冈县", "Hyogo": "兵库县", "Saitama": "埼玉县",
    "Chiba": "千叶县", "Shizuoka": "静冈县", "Kyoto": "京都府", "Hiroshima": "广岛县",
    "Miyagi": "宫城县", "Okayama": "冈山县", "Kumamoto": "熊本县", "Niigata": "新潟县",
    # 德国
    "Bavaria": "巴伐利亚", "Berlin": "柏林", "Hamburg": "汉堡", "Hessen": "黑森",
    "Saxony": "萨克森", "Baden-Wurttemberg": "巴登-符腾堡",
    "North Rhine-Westphalia": "北莱茵-威斯特法伦", "Lower Saxony": "下萨克森",
    "Rhineland-Palatinate": "莱茵兰-普法尔茨", "Thuringia": "图林根",
    # 法国
    "Ile-de-France": "法兰西岛",
    "Provence-Alpes-Cote d'Azur": "普罗旺斯-阿尔卑斯-蓝色海岸",
    "Occitanie": "奥克西塔尼", "Auvergne-Rhone-Alpes": "奥弗涅-罗讷-阿尔卑斯",
    "Hauts-de-France": "上法兰西",
    # 韩国
    "Seoul": "首尔", "Gyeonggi": "京畿道", "Busan": "釜山", "Incheon": "仁川", "Daegu": "大邱",
    # 印度
    "Maharashtra": "马哈拉施特拉", "Karnataka": "卡纳塔克", "Tamil Nadu": "泰米尔纳德",
    "Delhi": "德里", "Uttar Pradesh": "北方邦", "West Bengal": "西孟加拉",
    # 巴西
    "Sao Paulo": "圣保罗", "Rio de Janeiro": "里约热内卢", "Minas Gerais": "米纳斯吉拉斯",
    # 俄罗斯
    "Moscow": "莫斯科", "Saint Petersburg": "圣彼得堡",
    # 其他城邦
    "Singapore": "新加坡", "Central": "中部",
}

# 主要城市（英文 -> 中文）；DB 自带 zh-CN 时优先用库，否则用此表兜底
CITY_NAMES = {
    "Beijing": "北京", "Shanghai": "上海", "Guangzhou": "广州", "Shenzhen": "深圳",
    "Hangzhou": "杭州", "Chengdu": "成都", "Wuhan": "武汉", "Nanjing": "南京",
    "Xi'an": "西安", "Xian": "西安", "Chongqing": "重庆", "Tianjin": "天津",
    "Suzhou": "苏州", "Qingdao": "青岛", "Dalian": "大连", "Xiamen": "厦门",
    "Fuzhou": "福州", "Jinan": "济南", "Zhengzhou": "郑州", "Changsha": "长沙",
    "Kunming": "昆明", "Hefei": "合肥", "Nanchang": "南昌", "Haikou": "海口",
    "Shenyang": "沈阳", "Harbin": "哈尔滨", "Changchun": "长春", "Taiyuan": "太原",
    "Shijiazhuang": "石家庄", "Lanzhou": "兰州", "Guiyang": "贵阳", "Nanning": "南宁",
    "Yinchuan": "银川", "Xining": "西宁", "Urumqi": "乌鲁木齐", "Hohhot": "呼和浩特",
    "Lhasa": "拉萨", "Hong Kong": "香港", "Macau": "澳门", "Taipei": "台北",
    "Kaohsiung": "高雄", "Taichung": "台中", "Taoyuan": "桃园", "Tokyo": "东京",
    "Osaka": "大阪", "Yokohama": "横滨", "Nagoya": "名古屋", "Singapore": "新加坡",
    "Bangkok": "曼谷", "Seoul": "首尔", "Busan": "釜山", "New York": "纽约",
    "Los Angeles": "洛杉矶", "San Francisco": "旧金山", "Chicago": "芝加哥",
    "Boston": "波士顿", "Seattle": "西雅图", "Washington": "华盛顿", "London": "伦敦",
    "Paris": "巴黎", "Sydney": "悉尼", "Melbourne": "墨尔本", "Toronto": "多伦多",
    "Vancouver": "温哥华", "Berlin": "柏林", "Munich": "慕尼黑", "Frankfurt": "法兰克福",
    "Moscow": "莫斯科", "Dubai": "迪拜", "Kuala Lumpur": "吉隆坡", "Jakarta": "雅加达",
    "Manila": "马尼拉", "Hanoi": "河内", "Ho Chi Minh City": "胡志明市", "Mumbai": "孟买",
    "Delhi": "德里", "Bangalore": "班加罗尔", "Sao Paulo": "圣保罗", "Mexico City": "墨西哥城",
}


# ---------------------------------------------------------------------------
# 读取器（懒加载，带缓存）
# ---------------------------------------------------------------------------

def _open_reader() -> "geoip2.database.Reader | None":
    """按优先级解析 .mmdb 路径并打开（带缓存）。"""
    global _reader
    if not _GEOIP_AVAILABLE:
        return None
    with _lock:
        if _reader is not None:
            return _reader
        path = _resolve_db_path()
        if path and os.path.exists(path):
            try:
                _reader = geoip2.database.Reader(path)
            except Exception:
                _reader = None
        return _reader


def _resolve_db_path() -> str | None:
    """解析 .mmdb 路径：环境变量优先，其次与 sqlite 库同目录下的 GeoIP.mmdb。"""
    env = os.environ.get("SMART_ANALYTICS_GEOIP_DB")
    if env:
        return env
    db_path = os.environ.get("SMART_ANALYTICS_DB_PATH")
    base_dir = (
        os.path.dirname(db_path)
        if db_path
        else os.path.join(os.path.dirname(__file__), "..", "..", "data")
    )
    candidate = os.path.join(base_dir, "GeoIP.mmdb")
    # 优先 city 库（含省份/城市），回退 country 库
    for name in ("GeoIP-city.mmdb", "GeoIP.mmdb"):
        cand = os.path.join(base_dir, name)
        if os.path.exists(cand):
            return cand
    return None


def _subdiv_key(country_code: str | None, subdiv_code: str | None) -> str | None:
    if country_code and subdiv_code:
        return f"{country_code}-{subdiv_code}"
    return subdiv_code


# ---------------------------------------------------------------------------
# 对外解析函数
# ---------------------------------------------------------------------------

def ip_to_country(ip: str | None) -> str | None:
    """根据 IP 返回 ISO 3166-1 alpha-2 国家码，失败/未知返回 None。"""
    if not ip:
        return None
    reader = _open_reader()
    if reader is None:
        return None
    try:
        code = reader.country(ip).country.iso_code
        return code if code and code != "XX" else None
    except Exception:
        return None


def ip_to_location(ip: str | None) -> dict | None:
    """根据 IP 返回 {country_code, country, region, city}（均为中文名/代码）。

    国家：中文国名（COUNTRY_NAMES）；
    省份：中国用 PROVINCE_NAMES，其余国家回退库自带名；
    城市：优先库自带 zh-CN 名，否则 CITY_NAMES 兜底，再否则英文原名。
    失败/未知返回 None。
    """
    if not ip:
        return None
    reader = _open_reader()
    if reader is None:
        return None
    try:
        c = reader.city(ip)
    except Exception:
        return None

    cc = c.country.iso_code
    country = COUNTRY_NAMES.get(cc, cc) if cc else None

    region = None
    if c.subdivisions:
        sd = c.subdivisions[0]
        key = _subdiv_key(cc, sd.iso_code)
        region = (
            PROVINCE_NAMES.get(key)
            or EN_PROVINCE_NAMES.get(sd.name)
            or sd.names.get("zh-CN")
            or sd.name
            or None
        )

    city = None
    if c.city:
        city = c.city.names.get("zh-CN") or CITY_NAMES.get(c.city.name) or c.city.name or None

    return {
        "country_code": cc if cc and cc != "XX" else None,
        "country": country,
        "region": region,
        "city": city,
    }


def is_available() -> bool:
    """GeoIP 数据库是否就绪（用于前端提示/管理页）。"""
    return _open_reader() is not None
