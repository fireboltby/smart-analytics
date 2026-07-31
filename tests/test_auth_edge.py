"""认证边界测试：未登录受保护页 303 跳转、坏签名 cookie、无需登录的接口返回、
环境变量固定密码时禁止页面改密。
"""
from smart_analytics.app import user_is_admin

import helpers


def test_unauth_dashboard_redirect(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in (r.headers.get("location") or "")


def test_unauth_settings_redirect(client):
    r = client.get("/settings", follow_redirects=False)
    assert r.status_code == 303


def test_unauth_sites_redirect(client):
    r = client.get("/sites", follow_redirects=False)
    assert r.status_code == 303


def test_unauth_logs_redirect(client):
    r = client.get("/logs", follow_redirects=False)
    assert r.status_code == 303


def test_bad_signature_redirect(client):
    r = client.get("/", cookies={"sa_session": "garbage.signature"}, follow_redirects=False)
    assert r.status_code == 303


def test_realtime_unauth_returns_zero(client):
    r = client.get("/api/realtime")
    assert r.status_code == 200
    assert r.json()["online"] == 0


def test_change_password_unauth_303(client):
    r = client.post(
        "/api/change-password",
        data={"current_password": "x", "new_password": "y12345"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_create_user_unauth_303(client):
    r = client.post(
        "/api/create-user",
        data={"email": "a@x.com", "password": "pw123456"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_change_password_env_fixed_400(admin_client):
    # admin_client 由 bootstrap 用环境变量密码创建管理员，页面改密应被禁止
    cookies = helpers.session_cookie(1)
    r = admin_client.post(
        "/api/change-password",
        data={"current_password": "boot123", "new_password": "newpw123"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 400
