"""统计核心单测：直接调用 analytics 层纯函数与 dashboard / logs 计算。

重点验证：
- 设备/浏览器/OS 识别、Bot 判定、时间分桶
- 会话重建（按 visitor 分组 + 30 分钟超时切分）
- compute_dashboard 强制 site_id 隔离、实时在线、环比
- get_logs 的 humans / bots 过滤与总数
"""
from datetime import datetime, timedelta, timezone

from smart_analytics.analytics import (
    BEIJING,
    bucket_timestamp,
    compute_dashboard,
    detect_browser,
    detect_device,
    detect_os,
    get_logs,
    is_bot,
    reconstruct_sessions,
)
from smart_analytics.app import get_db

import helpers


# ---------------------------------------------------------------------------
# Bot / 设备 / 浏览器 / OS 识别
# ---------------------------------------------------------------------------

def test_is_bot():
    assert is_bot("") is True                      # 空 UA 视为 bot
    assert is_bot(helpers.CHROME_UA) is False
    assert is_bot(helpers.BOT_UA) is True
    assert is_bot("Mozilla/5.0 (compatible; bingbot/2.0)") is True


def test_detect_device():
    assert detect_device("") == "unknown"
    assert detect_device(helpers.IPHONE_UA) == "mobile"
    assert detect_device(helpers.IPAD_UA) == "tablet"
    assert detect_device(helpers.CHROME_UA) == "desktop"


def test_detect_browser():
    assert detect_browser("") == "未知"
    assert detect_browser(helpers.CHROME_UA) == "Chrome"
    assert detect_browser(helpers.FIREFOX_UA) == "Firefox"
    assert detect_browser(helpers.BOT_UA) == "其他"   # 无特定分支
    assert detect_browser(helpers.IPHONE_UA) == "Safari"


def test_detect_os():
    assert detect_os("") == "未知"
    assert detect_os(helpers.CHROME_UA) == "Windows"
    assert detect_os(helpers.FIREFOX_UA) == "Windows"
    assert detect_os(helpers.IPHONE_UA) == "iOS"
    assert detect_os(helpers.IPAD_UA) == "iOS"


# ---------------------------------------------------------------------------
# 时间分桶
# ---------------------------------------------------------------------------

def test_bucket_timestamp_intervals():
    ts = "2026-01-01T12:37:00"
    assert bucket_timestamp(ts, "15m") == "2026-01-01 12:30"
    assert bucket_timestamp(ts, "1h") == "2026-01-01 12:00"
    assert bucket_timestamp(ts, "1d") == "2026-01-01"
    # 非法 interval 退化为 1d 格式（%Y-%m-%d）
    assert bucket_timestamp(ts, "bogus") == "2026-01-01"


# ---------------------------------------------------------------------------
# 会话重建
# ---------------------------------------------------------------------------

def test_reconstruct_sessions_groups_and_splits():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=BEIJING)
    t0 = base.isoformat()
    t1 = (base + timedelta(minutes=1)).isoformat()    # 同会话
    t2 = (base + timedelta(minutes=40)).isoformat()   # >30min → 新会话
    rows = [
        {"visitor_hash": "v", "ts": t0, "url": "/a", "duration_sec": 5},
        {"visitor_hash": "v", "ts": t1, "url": "/b", "duration_sec": 5},
        {"visitor_hash": "v", "ts": t2, "url": "/c", "duration_sec": 5},
    ]
    sessions = reconstruct_sessions(rows)
    assert len(sessions) == 2
    assert len(sessions[0]) == 2
    assert len(sessions[1]) == 1


def test_reconstruct_sessions_separates_visitors():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=BEIJING)
    rows = [
        {"visitor_hash": "v1", "ts": base.isoformat(), "url": "/a", "duration_sec": 1},
        {"visitor_hash": "v2", "ts": base.isoformat(), "url": "/a", "duration_sec": 1},
    ]
    sessions = reconstruct_sessions(rows)
    assert len(sessions) == 2


# ---------------------------------------------------------------------------
# compute_dashboard
# ---------------------------------------------------------------------------

def test_compute_dashboard_basic(client):
    helpers.add_pageview(1, url="/home", ua=helpers.CHROME_UA, visitor_hash="u1")
    helpers.add_pageview(1, url="/home", ua=helpers.CHROME_UA, visitor_hash="u1")  # 同访客
    helpers.add_pageview(1, url="/about", ua=helpers.CHROME_UA, visitor_hash="u2")
    conn = get_db()
    try:
        d = compute_dashboard(conn, 1, 24, "1h")
    finally:
        conn.close()
    assert d["total_views"] == 3
    assert d["total_uniques"] == 2
    assert d["online_now"] == 2               # 近 5 分钟去重在线
    assert d["total_sessions"] >= 1
    assert d["avg_session_str"]                 # 生成了会话时长字符串
    assert d["bounce_rate"]                     # 生成了跳出率字符串


def test_compute_dashboard_site_isolation(client):
    helpers.add_site("Site B", "tokB", owner_user_id=1)   # site id = 2
    helpers.add_pageview(1, url="/a", ua=helpers.CHROME_UA, visitor_hash="x")
    helpers.add_pageview(2, url="/b", ua=helpers.CHROME_UA, visitor_hash="y")
    conn = get_db()
    try:
        d1 = compute_dashboard(conn, 1, 24, "1h")
        d2 = compute_dashboard(conn, 2, 24, "1h")
    finally:
        conn.close()
    assert d1["total_views"] == 1
    assert d1["total_uniques"] == 1
    assert d2["total_views"] == 1
    assert d2["total_uniques"] == 1


def test_compute_dashboard_no_data_safe(client):
    conn = get_db()
    try:
        d = compute_dashboard(conn, 1, 24, "1h")
    finally:
        conn.close()
    assert d["total_views"] == 0
    assert d["total_uniques"] == 0
    assert d["online_now"] == 0
    assert d["deltas"]["uniques"] is None      # 无环比基准 → None


# ---------------------------------------------------------------------------
# get_logs
# ---------------------------------------------------------------------------

def test_get_logs_filters_and_total(client):
    helpers.add_pageview(1, url="/human", ua=helpers.CHROME_UA, visitor_hash="h1")
    helpers.add_pageview(1, url="/bot", ua=helpers.BOT_UA, visitor_hash="b1")
    conn = get_db()
    try:
        rows_all, total = get_logs(conn, 1, 100, 0, "all")
        rows_h, _ = get_logs(conn, 1, 100, 0, "humans")
        rows_b, _ = get_logs(conn, 1, 100, 0, "bots")
    finally:
        conn.close()
    assert total == 2
    assert len(rows_all) == 2
    assert len(rows_h) == 1 and rows_h[0]["is_bot"] is False
    assert len(rows_b) == 1 and rows_b[0]["is_bot"] is True
    # 国家/设备映射生效
    assert rows_h[0]["country"] == "中国"
    assert rows_h[0]["device"] == "桌面端"
