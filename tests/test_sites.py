"""站点管理测试：/sites 列表、/sites/create 创建、/sites/delete 删除（含级联清理）、
/switch-site 切换与越权防护。

全部基于隔离临时库；创建站点/切换站点需登录态。
"""
from smart_analytics.app import get_db

import helpers


def _new_site_id(name: str) -> int:
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id FROM sites WHERE name=?", (name,)
        ).fetchone()["id"]
    finally:
        conn.close()


def test_create_site_then_listed(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    r = client.post("/sites/create", data={"name": "New Site", "domain": "example.com"}, cookies=cookies, follow_redirects=False)
    assert r.status_code == 303
    r2 = client.get("/sites", cookies=cookies)
    assert r2.status_code == 200
    assert "New Site" in r2.text


def test_create_site_defaults_name_and_domain(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    # 空串名 → 默认值机制直接进函数 → 回退默认名「未命名站点」（验证第1点修复）
    r = client.post("/sites/create", data={"name": "", "domain": ""}, cookies=cookies, follow_redirects=False)
    assert r.status_code == 303
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, domain FROM sites WHERE name='未命名站点'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["domain"] is None


def test_delete_site_cleans_pageviews(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    client.post("/sites/create", data={"name": "Del Site"}, cookies=cookies)
    sid = _new_site_id("Del Site")
    helpers.add_pageview(sid, url="/d", visitor_hash="z")
    r = client.post("/sites/delete", data={"site": sid}, cookies=cookies, follow_redirects=False)
    assert r.status_code == 303
    conn = get_db()
    try:
        pv = conn.execute("SELECT COUNT(*) c FROM pageviews WHERE site_id=?", (sid,)).fetchone()["c"]
        site = conn.execute("SELECT 1 FROM sites WHERE id=?", (sid,)).fetchone()
    finally:
        conn.close()
    assert pv == 0                      # 级联清理本站点数据
    assert site is None                 # 站点已删除


def test_delete_site_no_membership_403(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies1 = helpers.login_cookie(client, "o@x.com", "pw123456")
    client.post("/sites/create", data={"name": "A"}, cookies=cookies1)
    sidA = _new_site_id("A")

    helpers.add_user("other@x.com", "pw123456")
    cookies2 = helpers.login_cookie(client, "other@x.com", "pw123456")
    r = client.post("/sites/delete", data={"site": sidA}, cookies=cookies2)
    assert r.status_code == 403


def test_switch_site_sets_cookie_and_403(client):
    helpers.add_user("o@x.com", "pw123456")
    cookies = helpers.login_cookie(client, "o@x.com", "pw123456")
    client.post("/sites/create", data={"name": "B"}, cookies=cookies)
    sidB = _new_site_id("B")

    r = client.get(f"/switch-site?site={sidB}", cookies=cookies, follow_redirects=False)
    assert r.status_code == 303
    assert r.cookies.get("sa_site") == str(sidB)

    # 切换到无成员关系的站点 → 403
    r2 = client.get("/switch-site?site=999", cookies=cookies, follow_redirects=False)
    assert r2.status_code == 403
