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

# iPadOS 13+ 的 Safari 默认 UA 与 Mac 完全一致（Apple 隐私设计），
# 纯靠 UA 无法 100% 区分。启发式：Mac 形态且只有 Safari（不含 Chrome/Edge
# 等桌面浏览器标识）时，倾向判为平板（iPad 远比 Mac 上 Safari 常见）。
_DESKTOP_BROWSER_PATTERNS = re.compile(
    r"Chrome|Edg|OPR|Firefox|Trident|MSIE", re.IGNORECASE
)
_MAC_PATTERNS = re.compile(r"Macintosh|Mac OS X", re.IGNORECASE)
_SAFARI_PATTERNS = re.compile(r"Safari", re.IGNORECASE)


def detect_device(user_agent: str) -> str:
    """Detect device type from user agent."""
    if not user_agent:
        return "unknown"
    if TABLET_PATTERNS.search(user_agent):
        return "tablet"
    if MOBILE_PATTERNS.search(user_agent):
        return "mobile"
    if (
        _MAC_PATTERNS.search(user_agent)
        and _SAFARI_PATTERNS.search(user_agent)
        and not _DESKTOP_BROWSER_PATTERNS.search(user_agent)
    ):
        return "tablet"
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


def get_location(request: Request, ip: str | None = None) -> dict:
    """返回 {country_code, country, region, city}（均为中文名）。

    国家优先用 Cloudflare 的 CF-IPCountry 头；省份/城市始终用已采集的访客 IP
    查本地 GeoIP 库（CF 头不含省份城市）。
    """
    from .geoip import ip_to_location, COUNTRY_NAMES

    loc = {"country_code": None, "country": None, "region": None, "city": None}
    cf_country = request.headers.get("cf-ipcountry")
    if cf_country and cf_country != "XX":
        loc["country_code"] = cf_country
        loc["country"] = COUNTRY_NAMES.get(cf_country, cf_country)
    geo = ip_to_location(ip) or {}
    if not loc["country_code"]:
        loc["country_code"] = geo.get("country_code")
        loc["country"] = geo.get("country")
    loc["region"] = geo.get("region")
    loc["city"] = geo.get("city")
    return loc


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
# 访问排除（展示层过滤：数据照常入库，仅统计/展示时排除）
# ---------------------------------------------------------------------------

def exclusion_clause(excl: "dict | None") -> str:
    """生成 pageviews 统计查询的排除片段（不含前缀 AND）。

    语义：被排除的访问**已入库**（保留记录），仅在统计/展示时过滤掉。
    excl 结构：{enabled:bool, file:bool, localhost:bool, loopback:bool, custom:[str]}。
    返回空串表示不排除。
    """
    if not excl or not excl.get("enabled"):
        return ""
    parts: list[str] = []
    if excl.get("file"):
        parts.append("LOWER(url) NOT LIKE 'file://%'")
    if excl.get("localhost"):
        parts.append(
            "LOWER(url) NOT LIKE 'http://localhost%' "
            "AND LOWER(url) NOT LIKE 'https://localhost%'"
        )
    if excl.get("loopback"):
        parts.append(
            "LOWER(url) NOT LIKE 'http://127.0.0.1%' AND LOWER(url) NOT LIKE 'https://127.0.0.1%' "
            "AND LOWER(url) NOT LIKE 'http://0.0.0.0%' AND LOWER(url) NOT LIKE 'https://0.0.0.0%' "
            "AND LOWER(url) NOT LIKE 'http://[::1]%' AND LOWER(url) NOT LIKE 'https://[::1]%'"
        )
    for c in (excl.get("custom") or []):
        c = str(c).strip().lower().replace("'", "''")
        if not c:
            continue
        parts.append(
            f"LOWER(url) NOT LIKE 'http://{c}%' AND LOWER(url) NOT LIKE 'https://{c}%' "
            f"AND LOWER(url) NOT LIKE 'http://%.{c}%' AND LOWER(url) NOT LIKE 'https://%.{c}%'"
        )
    if not parts:
        return ""
    return " AND ".join(parts)


# ---------------------------------------------------------------------------
# 展示用映射
# ---------------------------------------------------------------------------

from .geoip import COUNTRY_NAMES


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

def compute_dashboard(conn, site_id: int, hours: int, interval: str, excl: "dict | None" = None) -> dict:
    """Compute all dashboard metrics for a single site within [now-hours, now].

    所有 SQL 均带 `site_id = ?` 过滤——这是多站点隔离的唯一出口，
    任何新增指标都必须经此函数或复用其查询模式，禁止在别处裸写 pageviews 查询。
    """
    if interval not in ("1m", "5m", "15m", "1h", "1d"):
        interval = "1h"

    # 展示层排除：被排除访问已入库，仅在统计时过滤
    cl = exclusion_clause(excl)
    excl_sql = (" AND " + cl) if cl else ""

    now = datetime.now(BEIJING)
    since = (now - timedelta(hours=hours)).isoformat()

    # 聚合统计
    stats = conn.execute(f"""
        SELECT
            COUNT(DISTINCT visitor_hash) as uniques,
            COUNT(*) as views,
            AVG(CASE WHEN duration_sec IS NOT NULL AND duration_sec > 0 THEN duration_sec END) as avg_duration
        FROM pageviews WHERE site_id = ? AND ts >= ?{excl_sql}
    """, (site_id, since)).fetchone()

    total_uniques = stats["uniques"]
    total_views = stats["views"]
    avg_duration = int(stats["avg_duration"] or 0)

    # 环比：上一等长周期 [since*2, since)
    prev_since = (now - timedelta(hours=hours * 2)).isoformat()
    prev_stats = conn.execute(f"""
        SELECT
            COUNT(DISTINCT visitor_hash) as uniques,
            COUNT(*) as views,
            AVG(CASE WHEN duration_sec IS NOT NULL AND duration_sec > 0 THEN duration_sec END) as avg_duration
        FROM pageviews WHERE site_id = ? AND ts >= ?{excl_sql} AND ts < ?
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
        f"SELECT COUNT(DISTINCT visitor_hash) FROM pageviews WHERE site_id = ? AND ts >= ?{excl_sql}",
        (site_id, online_since),
    ).fetchone()[0]

    # 新/老访客：以 visitor_hash 在该站的首访时间是否在当前窗口内判定
    nr = conn.execute(f"""
        SELECT
            SUM(CASE WHEN first_seen >= ? THEN 1 ELSE 0 END) AS new_v,
            SUM(CASE WHEN first_seen < ? THEN 1 ELSE 0 END) AS ret_v
        FROM (
            SELECT visitor_hash, MIN(ts) AS first_seen
            FROM pageviews
            WHERE site_id = ?{excl_sql}
            GROUP BY visitor_hash
            HAVING MAX(ts) >= ?
        )
    """, (since, since, site_id, since)).fetchone()
    new_visitors = nr["new_v"] or 0
    returning_visitors = nr["ret_v"] or 0

    # 拉取窗口内明细行，单次遍历完成所有拆解
    rows = conn.execute(f"""
        SELECT ts, url, referrer, visitor_hash, user_agent, country, region, city, device, duration_sec, ip
        FROM pageviews WHERE site_id = ? AND ts >= ?{excl_sql}
    """, (site_id, since)).fetchall()

    # 会话重建——向前多取一个超时窗口，减少跨边界会话被截断
    session_since = (now - timedelta(hours=hours, seconds=SESSION_TIMEOUT)).isoformat()
    session_rows = conn.execute(f"""
        SELECT ts, url, visitor_hash, duration_sec
        FROM pageviews WHERE site_id = ? AND ts >= ?{excl_sql}
    """, (site_id, session_since)).fetchall()

    # 累加器
    bucket_humans: dict[str, set[str]] = {}
    bucket_bots: dict[str, set[str]] = {}
    country_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    city_counts: dict[str, int] = {}
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
        region = r["region"] or "未知"
        city = r["city"] or "未知"
        region_counts[region] = region_counts.get(region, 0) + 1
        city_counts[city] = city_counts.get(city, 0) + 1
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
    from .geoip import ip_to_location

    top_ips_out = []
    for ip, views in top_ips:
        visitors_count = len(ip_visitors.get(ip, set()))
        loc = ip_to_location(ip) or {}
        country = loc.get("country") or "—"
        city = loc.get("city") or ""
        location = f"{country} {city}".strip() if city else country
        top_ips_out.append((ip, views, visitors_count, location))

    # 时序数据
    all_buckets = sorted(set(bucket_humans.keys()) | set(bucket_bots.keys()))
    human_values = [len(bucket_humans.get(b, set())) for b in all_buckets]
    bot_values = [len(bucket_bots.get(b, set())) for b in all_buckets]

    top_countries = sorted(country_counts.items(), key=lambda x: -x[1])[:10]
    country_labels = [COUNTRY_NAMES.get(c, c) for c, _ in top_countries]
    country_values = [v for _, v in top_countries]

    top_regions = sorted(region_counts.items(), key=lambda x: -x[1])[:10]
    region_labels = [r for r, _ in top_regions]
    region_values = [v for _, v in top_regions]

    top_cities = sorted(city_counts.items(), key=lambda x: -x[1])[:10]
    city_labels = [c for c, _ in top_cities]
    city_values = [v for _, v in top_cities]

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
        "regionLabels": region_labels,
        "regionValues": region_values,
        "cityLabels": city_labels,
        "cityValues": city_values,
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

def get_logs(conn, site_id: int, limit: int, offset: int, filter_type: str = "all", excl: "dict | None" = None):
    """返回 (processed_rows, total)，均限定 site_id；excl 非空时排除指定访问。"""
    cl = exclusion_clause(excl)
    excl_sql = (" AND " + cl) if cl else ""
    total = conn.execute(
        f"SELECT COUNT(*) as cnt FROM pageviews WHERE site_id = ?{excl_sql}", (site_id,)
    ).fetchone()["cnt"]
    rows = conn.execute(f"""
        SELECT id, ts, url, referrer, visitor_hash, user_agent, country, region, city, device, duration_sec, ip
        FROM pageviews WHERE site_id = ?{excl_sql} ORDER BY ts DESC LIMIT ? OFFSET ?
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
            "referrer": r["referrer"] or "—",
            "ref_short": (r["referrer"] or "—")[:40],
            "ip": r["ip"] or "—",
            "country": COUNTRY_NAMES.get(r["country"], r["country"]) if r["country"] else "—",
            "region": r["region"] or "—",
            "city": r["city"] or "—",
            "device": DEVICE_NAMES.get(r["device"], r["device"]) if r["device"] else "—",
            "duration": f"{r['duration_sec']}秒" if r["duration_sec"] else "—",
            "is_bot": is_bot_hit,
        })

    return processed_rows, total
