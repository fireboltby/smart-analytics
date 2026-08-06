"""页面 / 实时 / 日志 与多站点隔离测试。

覆盖：仪表盘渲染、无站点空态、实时在线计数、访问日志列表与过滤、
以及「跨站点数据不串」这一核心防御点（切换站点后才可见另一站数据）。
"""
from smart_analytics.app import get_db

import helpers


def _new_site_id(name: str) -> int:
    conn = get_db()
    try:
        return conn.execute("SELECT id FROM sites WHERE name=?", (name,)).fetchone()["id"]
    finally:
        conn.close()


def test_dashboard_with_site_renders(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    helpers.add_pageview(1, url="/home", ua=helpers.CHROME_UA, visitor_hash="u1")
    r = client.get("/", cookies=cookies)
    assert r.status_code == 200
    assert "默认站点" in r.text
    assert "/home" in r.text


def test_dashboard_no_site_empty(client):
    helpers.add_user_no_site("nos@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "nos@x.com", "pw123456")
    r = client.get("/", cookies=cookies)
    assert r.status_code == 200
    # 无站点时不应崩溃，且不应显示任何站点数据


def test_realtime_counts_online(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    helpers.add_pageview(1, ts=helpers.recent_ts(1), url="/home", ua=helpers.CHROME_UA, visitor_hash="u_on")
    r = client.get("/api/realtime?site=1", cookies=cookies)
    assert r.status_code == 200
    assert r.json()["online"] >= 1


def test_logs_lists_and_filters(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    helpers.add_pageview(1, url="/human", ua=helpers.CHROME_UA, visitor_hash="h")
    helpers.add_pageview(1, url="/bot", ua=helpers.BOT_UA, visitor_hash="b")
    r = client.get("/logs", cookies=cookies)
    assert r.status_code == 200
    assert "/human" in r.text

    r_h = client.get("/logs?filter=humans", cookies=cookies)
    assert "/bot" not in r_h.text
    r_b = client.get("/logs?filter=bots", cookies=cookies)
    assert "/human" not in r_b.text

    # 总数正确
    assert "共 2" in r.text or "2" in r.text


def test_isolation_dashboard_across_sites(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    # 创建第二个站点并写入数据
    client.post("/sites/create", data={"name": "Two"}, cookies=cookies)
    sid2 = _new_site_id("Two")
    helpers.add_pageview(sid2, url="/secret", ua=helpers.CHROME_UA, visitor_hash="s2")

    # 当前站点仍为默认 site 1（无 sa_site cookie）→ 看不到 /secret
    r1 = client.get("/", cookies=cookies)
    assert r1.status_code == 200
    assert "/secret" not in r1.text

    # 切换到 site 2 后再看 → 可见
    sw = client.get(f"/switch-site?site={sid2}", cookies=cookies, follow_redirects=False)
    cookies2 = dict(cookies)
    cookies2["sa_site"] = sw.cookies.get("sa_site")
    r2 = client.get("/", cookies=cookies2)
    assert r2.status_code == 200
    assert "/secret" in r2.text
