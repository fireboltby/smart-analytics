"""smart-analytics 查询与领域层。

集中所有对 pageviews 的读取计算，并强制注入 site_id，
避免在多站点改造中遗漏 WHERE site_id 导致串站/数据泄漏（核心防御点）。
所有函数均以 (conn, site_id, ...) 为签名，site_id 参与每条 SQL 的过滤。
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Request

# ---------------------------------------------------------------------------
# 时区（全系统统一北京时间 UTC+8）
# ---------------------------------------------------------------------------

BEIJING = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Bot 识别
# ---------------------------------------------------------------------------

BOT_PATTERNS = re.compile(
    r"bot|crawler|spider|scraper|curl|wget|python-requests|httpx|aiohttp|"
    r"googlebot|bingbot|yandex|baidu|duckduckbot|slurp|facebookexternalhit|"
    r"twitterbot|linkedinbot|embedly|quora|pinterest|redditbot|applebot|"
    r"semrushbot|ahrefsbot|mj12bot|dotbot|petalbot|bytespider|gptbot|"
    r"claudebot|anthropic|openai|headless|phantom|selenium|puppeteer|playwright",
    re.IGNORECASE,
)


def is_bot(user_agent: str) -> bool:
    """Return True if user-agent looks like a bot."""
    if not user_agent:
        return True
    return bool(BOT_PATTERNS.search(user_agent))


# ---------------------------------------------------------------------------
# 设备识别
# ---------------------------------------------------------------------------

MOBILE_PATTERNS = re.compile(
    r"Mobile|Android.*Mobile|iPhone|iPod|BlackBerry|IEMobile|Opera Mini|"
    r"Windows Phone|webOS|Symbian|Nokia|Samsung.*Mobile",
    re.IGNORECASE,
)

TABLET_PATTERNS = re.compile(
    r"iPad|Android(?!.*Mobile)|Tablet|PlayBook|Silk|Kindle",
    re.IGNORECASE,
)


def detect_device(user_agent: str) -> str:
    """Detect device type from user agent."""
    if not user_agent:
        return "unknown"
    if TABLET_PATTERNS.search(user_agent):
        return "tablet"
    if MOBILE_PATTERNS.search(user_agent):
        return "mobile"
    return "desktop"


def get_country(request: Request, ip: str | None = None) -> str | None:
    """Get country code.

    优先用 Cloudflare 的 CF-IPCountry 头；否则用已采集的访客 IP 查本地 GeoIP 库。
    """
    cf_country = request.headers.get("cf-ipcountry")
    if cf_country and cf_country != "XX":
        return cf_country
    from .geoip import ip_to_country

    return ip_to_country(ip)


# ---------------------------------------------------------------------------
# 会话重建（启发式）
# ---------------------------------------------------------------------------

# 相邻两次访问间隔超过此阈值（秒）即视为一次新会话——30 分钟是 Web 分析的常见启发式
SESSION_TIMEOUT = 30 * 60


def detect_browser(user_agent: str) -> str:
    """粗粒度浏览器识别（仅用于统计，不做设备指纹采集）。"""
    if not user_agent:
        return "未知"
    ua = user_agent.lower()
    if "edg/" in ua or "edge" in ua:
        return "Edge"
    if "opr/" in ua or "opera" in ua:
        return "Opera"
    if "samsungbrowser" in ua:
        return "三星浏览器"
    if "huaweibrowser" in ua:
        return "华为浏览器"
    if "micromessenger" in ua:
        return "微信内置"
    if "qqbrowser" in ua or "mqqbrowser" in ua:
        return "QQ浏览器"
    if "ucbrowser" in ua:
        return "UC浏览器"
    if "qihu" in ua or "360se" in ua or "360ee" in ua:
        return "360浏览器"
    if "baidubrowser" in ua or "baiduboxapp" in ua:
        return "百度浏览器"
    if "firefox" in ua or "fxios" in ua:
        return "Firefox"
    if "chrome" in ua or "crios" in ua:
        return "Chrome"
    if "safari" in ua:
        return "Safari"
    return "其他"


def detect_os(user_agent: str) -> str:
    """粗粒度操作系统识别（仅用于统计，不做设备指纹采集）。"""
    if not user_agent:
        return "未知"
    ua = user_agent.lower()
    if "windows nt" in ua:
        return "Windows"
    if "iphone" in ua or "ipad" in ua or "ipod" in ua:
        return "iOS"
    if "mac os x" in ua or "macintosh" in ua:
        return "macOS"
    if "android" in ua:
        return "Android"
    if "chrome os" in ua or "cros" in ua:
        return "Chrome OS"
    if "harmonyos" in ua or "harmony" in ua:
        return "鸿蒙"
    if "linux" in ua:
        return "Linux"
    return "其他"


def reconstruct_sessions(rows):
    """按 visitor_hash 分组、以 30 分钟为超时重建会话序列。

    rows：含 ts / url / visitor_hash / duration_sec 的 sqlite3.Row 列表（顺序不限）。
    返回会话列表，每个会话是按 ts 升序排列的 row 列表。

    说明：这是启发式重建。visitor_hash 已包含 site_id（见 app.py 采集端），
    因此同一人在不同站点不会误并会话；在单站点内，NAT / 共享出口 IP 仍可能
    让多个真实用户共用同一个 hash，故会话级指标应标注「估算」。
    """
    by_visitor: dict[str, list] = {}
    for r in rows:
        by_visitor.setdefault(r["visitor_hash"], []).append(r)

    sessions: list[list] = []
    for vrows in by_visitor.values():
        vrows.sort(key=lambda x: x["ts"])
        cur: list = []
        prev_ts = None
        for r in vrows:
            ts_epoch = datetime.fromisoformat(r["ts"].replace("Z", "+00:00")).timestamp()
            if prev_ts is not None and (ts_epoch - prev_ts) > SESSION_TIMEOUT:
                sessions.append(cur)
                cur = []
            cur.append(r)
            prev_ts = ts_epoch
        if cur:
            sessions.append(cur)
    return sessions


# ---------------------------------------------------------------------------
# 时间分桶
# ---------------------------------------------------------------------------

def bucket_timestamp(ts_str: str, interval: str) -> str:
    """Bucket a timestamp string into the specified interval."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if interval == "1m":
        return dt.strftime("%Y-%m-%d %H:%M")
    elif interval == "5m":
        minute = (dt.minute // 5) * 5
        return dt.strftime(f"%Y-%m-%d %H:{minute:02d}")
    elif interval == "15m":
        minute = (dt.minute // 15) * 15
        return dt.strftime(f"%Y-%m-%d %H:{minute:02d}")
    elif interval == "1h":
        return dt.strftime("%Y-%m-%d %H:00")
    else:
        return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 展示用映射
# ---------------------------------------------------------------------------

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
    "MR": "毛里塔尼亚", "MS": "蒙特塞拉特", "MT": "马耳他", "MU": "毛里求斯", "MV": "马尔代夫",
    "MW": "马拉维", "MX": "墨西哥", "MY": "马来西亚", "MZ": "莫桑比克", "NA": "纳米比亚",
    "NC": "新喀里多尼亚", "NE": "尼日尔", "NF": "诺福克岛", "NG": "尼日利亚", "NI": "尼加拉瓜",
    "NL": "荷兰", "NO": "挪威", "NP": "尼泊尔", "NR": "瑙鲁", "NU": "纽埃",
    "NZ": "新西兰", "OM": "阿曼", "PA": "巴拿马", "PE": "秘鲁", "PF": "法属波利尼西亚",
    "PG": "巴布亚新几内亚", "PH": "菲律宾", "PK": "巴基斯坦", "PL": "波兰", "PM": "圣皮埃尔和密克隆",
    "PN": "皮特凯恩群岛", "PR": "波多黎各", "PS": "巴勒斯坦", "PT": "葡萄牙", "PW": "帕劳",
    "PY": "巴拉圭", "QA": "卡塔尔", "RE": "留尼汪", "RO": "罗马尼亚", "RS": "塞尔维亚",
    "RU": "俄罗斯", "RW": "卢旺达", "SA": "沙特阿拉伯", "SB": "所罗门群岛", "SC": "塞舌尔",
    "SD": "苏丹", "SE": "瑞典", "SG": "新加坡", "SH": "圣赫勒拿", "SI": "斯洛文尼亚",
    "SJ": "斯瓦尔巴和扬马延", "SK": "斯洛伐克", "SL": "塞拉利昂", "SM": "圣马力诺", "SN": "塞内加尔",
    "SO": "索马里", "SR": "苏里南", "SS": "南苏丹", "ST": "圣多美和普林西比", "SV": "萨尔瓦多",
    "SX": "圣马丁（荷属）", "SY": "叙利亚", "SZ": "斯威士兰", "TC": "特克斯和凯科斯群岛", "TD": "乍得",
    "TF": "法属南部领地", "TG": "多哥", "TH": "泰国", "TJ": "塔吉克斯坦", "TK": "托克劳",
    "TL": "东帝汶", "TM": "土库曼斯坦", "TN": "突尼斯", "TO": "汤加", "TR": "土耳其",
    "TT": "特立尼达和多巴哥", "TV": "图瓦卢", "TW": "中国台湾", "TZ": "坦桑尼亚", "UA": "乌克兰",
    "UG": "乌干达", "UM": "美国本土外小岛屿", "US": "美国", "UY": "乌拉圭", "UZ": "乌兹别克斯坦",
    "VA": "梵蒂冈", "VC": "圣文森特和格林纳丁斯", "VE": "委内瑞拉", "VG": "英属维尔京群岛", "VI": "美属维尔京群岛",
    "VN": "越南", "VU": "瓦努阿图", "WF": "瓦利斯和富图纳", "WS": "萨摩亚", "YE": "也门",
    "YT": "马约特", "ZA": "南非", "ZM": "赞比亚", "ZW": "津巴布韦",
}

DEVICE_NAMES = {
    "desktop": "桌面端",
    "mobile": "移动端",
    "tablet": "平板",
    "unknown": "未知",
}


SEARCH_ENGINES = ("google", "baidu", "bing", "yahoo", "yandex",
                  "duckduckgo", "sogou", "so.com", "ask")


# ---------------------------------------------------------------------------
# 仪表盘计算（强制 site_id 隔离）
# ---------------------------------------------------------------------------

def compute_dashboard(conn, site_id: int, hours: int, interval: str) -> dict:
    """Compute all dashboard metrics for a single site within [now-hours, now].

    所有 SQL 均带 `site_id = ?` 过滤——这是多站点隔离的唯一出口，
    任何新增指标都必须经此函数或复用其查询模式，禁止在别处裸写 pageviews 查询。
    """
    if interval not in ("1m", "5m", "15m", "1h", "1d"):
        interval = "1h"

    now = datetime.now(BEIJING)
    since = (now - timedelta(hours=hours)).isoformat()

    # 聚合统计
    stats = conn.execute("""
        SELECT
            COUNT(DISTINCT visitor_hash) as uniques,
            COUNT(*) as views,
            AVG(CASE WHEN duration_sec IS NOT NULL AND duration_sec > 0 THEN duration_sec END) as avg_duration
        FROM pageviews WHERE site_id = ? AND ts >= ?
    """, (site_id, since)).fetchone()

    total_uniques = stats["uniques"]
    total_views = stats["views"]
    avg_duration = int(stats["avg_duration"] or 0)

    # 环比：上一等长周期 [since*2, since)
    prev_since = (now - timedelta(hours=hours * 2)).isoformat()
    prev_stats = conn.execute("""
        SELECT
            COUNT(DISTINCT visitor_hash) as uniques,
            COUNT(*) as views,
            AVG(CASE WHEN duration_sec IS NOT NULL AND duration_sec > 0 THEN duration_sec END) as avg_duration
        FROM pageviews WHERE site_id = ? AND ts >= ? AND ts < ?
    """, (site_id, prev_since, since)).fetchone()
    prev_uniques = prev_stats["uniques"]
    prev_views = prev_stats["views"]
    prev_avg = int(prev_stats["avg_duration"] or 0)

    def _pct(cur, prev):
        return None if not prev else round((cur - prev) / prev * 100, 1)

    deltas = {
        "uniques": _pct(total_uniques, prev_uniques),
        "views": _pct(total_views, prev_views),
        "duration": _pct(avg_duration, prev_avg),
    }

    # 实时在线（近 5 分钟去重访客）
    online_since = (now - timedelta(minutes=5)).isoformat()
    online_now = conn.execute(
        "SELECT COUNT(DISTINCT visitor_hash) FROM pageviews WHERE site_id = ? AND ts >= ?",
        (site_id, online_since),
    ).fetchone()[0]

    # 新/老访客：以 visitor_hash 在该站的首访时间是否在当前窗口内判定
    nr = conn.execute("""
        SELECT
            SUM(CASE WHEN first_seen >= ? THEN 1 ELSE 0 END) AS new_v,
            SUM(CASE WHEN first_seen < ? THEN 1 ELSE 0 END) AS ret_v
        FROM (
            SELECT visitor_hash, MIN(ts) AS first_seen
            FROM pageviews
            WHERE site_id = ?
            GROUP BY visitor_hash
            HAVING MAX(ts) >= ?
        )
    """, (since, since, site_id, since)).fetchone()
    new_visitors = nr["new_v"] or 0
    returning_visitors = nr["ret_v"] or 0

    # 拉取窗口内明细行，单次遍历完成所有拆解
    rows = conn.execute("""
        SELECT ts, url, referrer, visitor_hash, user_agent, country, device, duration_sec, ip
        FROM pageviews WHERE site_id = ? AND ts >= ?
    """, (site_id, since)).fetchall()

    # 会话重建——向前多取一个超时窗口，减少跨边界会话被截断
    session_since = (now - timedelta(hours=hours, seconds=SESSION_TIMEOUT)).isoformat()
    session_rows = conn.execute("""
        SELECT ts, url, visitor_hash, duration_sec
        FROM pageviews WHERE site_id = ? AND ts >= ?
    """, (site_id, session_since)).fetchall()

    # 累加器
    bucket_humans: dict[str, set[str]] = {}
    bucket_bots: dict[str, set[str]] = {}
    country_counts: dict[str, int] = {}
    device_counts = {"desktop": 0, "mobile": 0, "tablet": 0, "unknown": 0}

    # 高频 IP（复用真人过滤；跳过无法解析/隐私占位）
    ip_views: dict[str, int] = {}
    ip_visitors: dict[str, set] = {}

    page_stats: dict[str, dict] = {}
    referrer_counts: dict[str, int] = {}
    keyword_counts: dict[str, int] = {}
    hour_counts = [0] * 24
    weekday_counts = [0] * 7

    utm_source_counts: dict[str, int] = {}
    utm_medium_counts: dict[str, int] = {}
    utm_campaign_counts: dict[str, int] = {}

    browser_counts: dict[str, int] = {}
    os_counts: dict[str, int] = {}

    for r in rows:
        bucket = bucket_timestamp(r["ts"], interval)
        vh = r["visitor_hash"]
        ua = r["user_agent"] or ""
        country = r["country"] or "未知"
        device = r["device"] or "unknown"
        duration = r["duration_sec"]
        url = r["url"]
        referrer = r["referrer"] or ""

        if is_bot(ua):
            bucket_bots.setdefault(bucket, set()).add(vh)
            continue

        bucket_humans.setdefault(bucket, set()).add(vh)
        country_counts[country] = country_counts.get(country, 0) + 1
        device_counts[device] = device_counts.get(device, 0) + 1
        browser_counts[detect_browser(ua)] = browser_counts.get(detect_browser(ua), 0) + 1
        os_counts[detect_os(ua)] = os_counts.get(detect_os(ua), 0) + 1

        ip_addr = r["ip"] or ""
        if ip_addr and ip_addr not in ("unknown", "未知"):
            ip_views[ip_addr] = ip_views.get(ip_addr, 0) + 1
            ip_visitors.setdefault(ip_addr, set()).add(vh)

        ps = page_stats.setdefault(url, {"views": 0, "visitors": set(), "durations": []})
        ps["views"] += 1
        ps["visitors"].add(vh)
        if duration and duration > 0:
            ps["durations"].append(duration)

        if referrer:
            host = urlparse(referrer).netloc.lower()
            domain = host[4:] if host.startswith("www.") else host
            if domain:
                referrer_counts[domain] = referrer_counts.get(domain, 0) + 1
                q = urlparse(referrer).query
                if q:
                    try:
                        params = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
                        kw = next((params[k] for k in ("q", "wd", "query", "p") if k in params and params[k].strip()), None)
                        if kw and any(se in domain for se in SEARCH_ENGINES):
                            keyword_counts[kw.strip()] = keyword_counts.get(kw.strip(), 0) + 1
                    except Exception:
                        pass

        utm_q = urlparse(url).query
        if utm_q:
            from urllib.parse import parse_qs
            utm_q = parse_qs(utm_q)
            src = (utm_q.get("utm_source") or ["未知"])[0] or "未知"
            med = (utm_q.get("utm_medium") or ["未知"])[0] or "未知"
            cmpn = (utm_q.get("utm_campaign") or ["未知"])[0] or "未知"
            utm_source_counts[src] = utm_source_counts.get(src, 0) + 1
            utm_medium_counts[med] = utm_medium_counts.get(med, 0) + 1
            utm_campaign_counts[cmpn] = utm_campaign_counts.get(cmpn, 0) + 1

        try:
            dt = datetime.fromisoformat(r["ts"].replace("Z", "+00:00"))
            hour_counts[dt.hour] += 1
            wd = int(dt.strftime("%w"))  # 0=周日
            weekday_counts[(wd + 6) % 7] += 1  # 周一=0
        except Exception:
            pass

    # 会话重建 → 跳出率 / 会话时长 / 入口页 / 出口页（均标「估算」）
    sessions = reconstruct_sessions(session_rows)
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    window_sessions = [
        s for s in sessions
        if datetime.fromisoformat(s[-1]["ts"].replace("Z", "+00:00")) >= since_dt
    ]
    total_sessions = len(window_sessions)
    bounces = sum(1 for s in window_sessions if len(s) == 1)
    bounce_rate = round(bounces / total_sessions * 100, 1) if total_sessions else 0.0

    session_durations: list[int] = []
    entry_counts: dict[str, int] = {}
    exit_counts: dict[str, int] = {}
    for s in window_sessions:
        first, last = s[0], s[-1]
        if len(s) > 1:
            dur = int(
                datetime.fromisoformat(last["ts"].replace("Z", "+00:00")).timestamp()
                - datetime.fromisoformat(first["ts"].replace("Z", "+00:00")).timestamp()
            )
            session_durations.append(dur)
        elif first["duration_sec"] and first["duration_sec"] > 0:
            session_durations.append(first["duration_sec"])
        entry_counts[first["url"]] = entry_counts.get(first["url"], 0) + 1
        exit_counts[last["url"]] = exit_counts.get(last["url"], 0) + 1

    avg_session_dur = int(sum(session_durations) / len(session_durations)) if session_durations else 0
    if avg_session_dur > 60:
        avg_session_str = f"{avg_session_dur // 60}分{avg_session_dur % 60}秒"
    else:
        avg_session_str = f"{avg_session_dur}秒"
    bounce_str = f"{bounce_rate:g}%"
    top_entries = sorted(entry_counts.items(), key=lambda x: -x[1])[:10]
    top_exits = sorted(exit_counts.items(), key=lambda x: -x[1])[:10]

    top_browsers = sorted(browser_counts.items(), key=lambda x: -x[1])[:10]
    top_os = sorted(os_counts.items(), key=lambda x: -x[1])[:10]

    top_ips = sorted(ip_views.items(), key=lambda x: -x[1])[:15]
    top_ips_out = [(ip, views, len(ip_visitors.get(ip, set()))) for ip, views in top_ips]

    # 时序数据
    all_buckets = sorted(set(bucket_humans.keys()) | set(bucket_bots.keys()))
    human_values = [len(bucket_humans.get(b, set())) for b in all_buckets]
    bot_values = [len(bucket_bots.get(b, set())) for b in all_buckets]

    top_countries = sorted(country_counts.items(), key=lambda x: -x[1])[:10]
    country_labels = [COUNTRY_NAMES.get(c, c) for c, _ in top_countries]
    country_values = [v for _, v in top_countries]

    if interval == "1d":
        time_labels = all_buckets
    else:
        time_labels = [b.split(" ")[1] if " " in b else b for b in all_buckets]

    top_pages = sorted(page_stats.items(), key=lambda x: -x[1]["views"])[:10]
    top_pages_out = []
    for url, ps in top_pages:
        avgd = int(sum(ps["durations"]) / len(ps["durations"])) if ps["durations"] else 0
        avgd_str = f"{avgd // 60}分{avgd % 60}秒" if avgd > 60 else f"{avgd}秒"
        top_pages_out.append({
            "url": url,
            "url_short": (url[:60] + "…") if len(url) > 60 else url,
            "views": ps["views"],
            "visitors": len(ps["visitors"]),
            "avg_dur": avgd_str,
        })

    top_referrers = sorted(referrer_counts.items(), key=lambda x: -x[1])[:10]
    top_keywords = sorted(keyword_counts.items(), key=lambda x: -x[1])[:10]

    top_utm_source = sorted(utm_source_counts.items(), key=lambda x: -x[1])[:10]
    top_utm_medium = sorted(utm_medium_counts.items(), key=lambda x: -x[1])[:10]
    top_utm_campaign = sorted(utm_campaign_counts.items(), key=lambda x: -x[1])[:10]

    hour_labels = [f"{h}时" for h in range(24)]
    weekday_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    if avg_duration > 60:
        duration_str = f"{avg_duration // 60}分{avg_duration % 60}秒"
    else:
        duration_str = f"{avg_duration}秒"

    chart_data = {
        "timeLabels": time_labels,
        "humanValues": human_values,
        "botValues": bot_values,
        "countryLabels": country_labels,
        "countryValues": country_values,
        "devices": device_counts,
        "hourLabels": hour_labels,
        "hourValues": hour_counts,
        "weekdayLabels": weekday_labels,
        "weekdayValues": weekday_counts,
        "newVisitors": new_visitors,
        "returningVisitors": returning_visitors,
    }

    return {
        "hours": hours,
        "interval": interval,
        "total_uniques": total_uniques,
        "total_views": total_views,
        "duration_str": duration_str,
        "device_counts": device_counts,
        "deltas": deltas,
        "online_now": online_now,
        "new_visitors": new_visitors,
        "returning_visitors": returning_visitors,
        "top_pages": top_pages_out,
        "top_referrers": top_referrers,
        "top_keywords": top_keywords,
        "top_utm_source": top_utm_source,
        "top_utm_medium": top_utm_medium,
        "top_utm_campaign": top_utm_campaign,
        "bounce_rate": bounce_str,
        "avg_session_str": avg_session_str,
        "total_sessions": total_sessions,
        "top_entries": top_entries,
        "top_exits": top_exits,
        "top_browsers": top_browsers,
        "top_os": top_os,
        "top_ips": top_ips_out,
        "chart_data": chart_data,
    }


# ---------------------------------------------------------------------------
# 访问日志（强制 site_id 隔离）
# ---------------------------------------------------------------------------

def get_logs(conn, site_id: int, limit: int, offset: int, filter_type: str = "all"):
    """返回 (processed_rows, total)，均限定 site_id。"""
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM pageviews WHERE site_id = ?", (site_id,)
    ).fetchone()["cnt"]
    rows = conn.execute("""
        SELECT id, ts, url, referrer, visitor_hash, user_agent, country, device, duration_sec, ip
        FROM pageviews WHERE site_id = ? ORDER BY ts DESC LIMIT ? OFFSET ?
    """, (site_id, limit, offset)).fetchall()

    processed_rows = []
    for r in rows:
        ua = r["user_agent"] or ""
        is_bot_hit = is_bot(ua)

        if filter_type == "humans" and is_bot_hit:
            continue
        if filter_type == "bots" and not is_bot_hit:
            continue

        processed_rows.append({
            "ts_short": r["ts"][:19].replace("T", " "),
            "url": r["url"],
            "url_short": (r["url"][:50] + "...") if len(r["url"]) > 50 else r["url"],
            "ref_short": (r["referrer"] or "—")[:30],
            "ip": r["ip"] or "—",
            "country": COUNTRY_NAMES.get(r["country"], r["country"]) if r["country"] else "—",
            "device": DEVICE_NAMES.get(r["device"], r["device"]) if r["device"] else "—",
            "duration": f"{r['duration_sec']}秒" if r["duration_sec"] else "—",
            "is_bot": is_bot_hit,
        })

    return processed_rows, total
