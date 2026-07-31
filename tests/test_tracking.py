"""埋点接口测试：/t 采集、/d 时长上报、/s/{token}.js 片段。

覆盖：无效 token 静默拒绝、有效采集入库、allowed_origins 校验、
跨站时长越权防护、时长上报边界、脚本片段下发。
"""
from smart_analytics.app import get_db

import helpers


def test_track_invalid_token_204(client):
    r = client.post("/t?t=badtok", json={"url": "/x"})
    assert r.status_code == 204


def test_track_valid_inserts(client):
    helpers.add_site("S", "tok123", owner_user_id=1)
    r = client.post("/t?t=tok123", json={"url": "/home", "referrer": "https://google.com"})
    assert r.status_code == 200
    body = r.json()
    assert "sid" in body and "rid" in body
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT site_id, url, referrer FROM pageviews WHERE site_id=2"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["url"] == "/home"
    assert row["referrer"] == "https://google.com"


def test_track_allowed_origins_blocks(client):
    helpers.add_site("S", "tokO", owner_user_id=1, allowed_origins="https://good.com")
    r = client.post("/t?t=tokO", json={"url": "/x"}, headers={"origin": "https://evil.com"})
    assert r.status_code == 204
    conn = get_db()
    try:
        cnt = conn.execute("SELECT COUNT(*) c FROM pageviews WHERE site_id=2").fetchone()["c"]
    finally:
        conn.close()
    assert cnt == 0


def test_track_allowed_origins_allows(client):
    helpers.add_site("S", "tokO2", owner_user_id=1, allowed_origins="https://good.com")
    r = client.post("/t?t=tokO2", json={"url": "/x"}, headers={"origin": "https://good.com"})
    assert r.status_code == 200


def test_duration_updates_own_record(client):
    helpers.add_site("S", "tokD", owner_user_id=1)
    r = client.post("/t?t=tokD", json={"url": "/x"})
    rid = r.json()["rid"]
    r2 = client.post("/d?t=tokD", json={"rid": rid, "d": 30})
    assert r2.status_code == 204
    conn = get_db()
    try:
        dur = conn.execute(
            "SELECT duration_sec FROM pageviews WHERE id=?", (rid,)
        ).fetchone()["duration_sec"]
    finally:
        conn.close()
    assert dur == 30


def test_duration_invalid_token_204(client):
    r = client.post("/d?t=badtok", json={"rid": 1, "d": 30})
    assert r.status_code == 204


def test_duration_out_of_range_ignored(client):
    helpers.add_site("S", "tokD2", owner_user_id=1)
    r = client.post("/t?t=tokD2", json={"url": "/x"})
    rid = r.json()["rid"]
    client.post("/d?t=tokD2", json={"rid": rid, "d": 99999})  # >7200 忽略
    conn = get_db()
    try:
        dur = conn.execute(
            "SELECT duration_sec FROM pageviews WHERE id=?", (rid,)
        ).fetchone()["duration_sec"]
    finally:
        conn.close()
    assert dur is None


def test_duration_cannot_update_other_site(client):
    # 两个站点；rid 属于 site A，却用 site B 的 token 尝试改写
    helpers.add_site("A", "tokDA", owner_user_id=1)   # site 2
    helpers.add_site("B", "tokDB", owner_user_id=1)   # site 3
    r = client.post("/t?t=tokDA", json={"url": "/x"})
    rid = r.json()["rid"]
    client.post("/d?t=tokDB", json={"rid": rid, "d": 30})
    conn = get_db()
    try:
        dur = conn.execute(
            "SELECT duration_sec FROM pageviews WHERE id=?", (rid,)
        ).fetchone()["duration_sec"]
    finally:
        conn.close()
    assert dur is None


def test_snippet_invalid_token_404(client):
    r = client.get("/s/badtok.js")
    assert r.status_code == 404


def test_snippet_valid(client):
    helpers.add_site("S", "tokJS", owner_user_id=1)
    r = client.get("/s/tokJS.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers.get("content-type", "")
    assert "tokJS" in r.text
    assert "/t?t=tokJS" in r.text
