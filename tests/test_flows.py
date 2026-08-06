"""功能测试（流程层）：用 TestClient 跑端到端接口流程。

覆盖：注册（含确认密码校验、注册后自动关闭）、登录、管理员建普通账户、
改密、受保护页跳转、设置页权限可见性。全部基于 client fixture 的隔离临时库。
"""
from smart_analytics.app import get_db


def _register(client, email, password, confirm=None):
    confirm = password if confirm is None else confirm
    # follow_redirects=False：保留 303 状态码与 Set-Cookie，便于校验跳转与登录态
    return client.post(
        "/register",
        data={"email": email, "password": password, "password_confirm": confirm},
        follow_redirects=False,
    )


def _login(client, email, password):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _token(resp):
    return resp.cookies.get("sa_session")


# ---------------------------------------------------------------------------
# 注册流程
# ---------------------------------------------------------------------------

def test_register_page_open_when_no_users(client):
    r = client.get("/register")
    assert r.status_code == 200
    assert "创建账户" in r.text


def test_register_password_mismatch_inline_error(client):
    r = _register(client, "a@x.com", "secret123", confirm="other123")
    assert r.status_code == 200  # 内联错误重渲染，非重定向
    assert "两次输入的密码不一致" in r.text
    assert 'value="a@x.com"' in r.text  # 邮箱回填


def test_register_success_autologin_and_owner(client):
    reg = _register(client, "admin@x.com", "secret123")
    assert reg.status_code == 303  # 注册成功跳转
    token = _token(reg)
    assert token

    # 自动登录态可访问首页
    r2 = client.get("/", cookies={"sa_session": token})
    assert r2.status_code == 200

    # 首个注册者成为默认站点 owner
    conn = get_db()
    try:
        role = conn.execute(
            "SELECT role FROM memberships WHERE user_id=1 AND site_id=1"
        ).fetchone()["role"]
    finally:
        conn.close()
    assert role == "owner"


def test_register_closes_after_first_user(client):
    _register(client, "admin@x.com", "secret123")  # 首个用户

    # GET /register 现在显示已关闭
    r = client.get("/register")
    assert r.status_code == 200
    assert "注册已关闭" in r.text

    # POST /register 拒绝（关闭态返回注册页 200，含「注册已关闭」）
    r2 = _register(client, "another@x.com", "secret123")
    assert r2.status_code == 200
    assert "注册已关闭" in r2.text


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

def test_login_wrong_password_rejected(client):
    _register(client, "admin@x.com", "secret123")
    r = _login(client, "admin@x.com", "wrongpass")
    assert r.status_code == 401


def test_login_success_returns_token(client):
    _register(client, "admin@x.com", "secret123")
    r = _login(client, "admin@x.com", "secret123")
    assert r.status_code == 303
    assert _token(r)


# ---------------------------------------------------------------------------
# 管理员创建普通账户
# ---------------------------------------------------------------------------

def test_admin_create_user_and_login(client):
    reg = _register(client, "admin@x.com", "secret123")
    token = _token(reg)
    assert token

    r = client.post(
        "/api/create-user",
        data={"email": "mem@x.com", "password": "secret123"},
        cookies={"sa_session": token},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 新成员可登录
    login = _login(client, "mem@x.com", "secret123")
    assert login.status_code == 303

    # 新成员是 member 而非 owner
    conn = get_db()
    try:
        role = conn.execute(
            "SELECT role FROM memberships WHERE user_id=2 AND site_id=1"
        ).fetchone()["role"]
    finally:
        conn.close()
    assert role == "member"


def test_member_cannot_create_user(client):
    reg = _register(client, "admin@x.com", "secret123")
    admin_token = _token(reg)
    # 管理员先建一个普通成员
    client.post(
        "/api/create-user",
        data={"email": "mem@x.com", "password": "secret123"},
        cookies={"sa_session": admin_token},
    )
    # 以普通成员登录
    mem_login = _login(client, "mem@x.com", "secret123")
    mem_token = _token(mem_login)
    assert mem_token

    r = client.post(
        "/api/create-user",
        data={"email": "mem2@x.com", "password": "secret123"},
        cookies={"sa_session": mem_token},
    )
    assert r.status_code == 403


def test_create_user_duplicate_email(client):
    reg = _register(client, "admin@x.com", "secret123")
    token = _token(reg)
    client.post(
        "/api/create-user",
        data={"email": "mem@x.com", "password": "secret123"},
        cookies={"sa_session": token},
    )
    r = client.post(
        "/api/create-user",
        data={"email": "mem@x.com", "password": "secret123"},
        cookies={"sa_session": token},
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# 改密
# ---------------------------------------------------------------------------

def test_change_password_flow(client):
    reg = _register(client, "admin@x.com", "secret123")
    token = _token(reg)

    # 当前密码错误 → 401
    r = client.post(
        "/api/change-password",
        data={"current_password": "wrong", "new_password": "newpass123"},
        cookies={"sa_session": token},
    )
    assert r.status_code == 401

    # 新密码过短 → 400
    r = client.post(
        "/api/change-password",
        data={"current_password": "secret123", "new_password": "123"},
        cookies={"sa_session": token},
    )
    assert r.status_code == 400

    # 成功
    r = client.post(
        "/api/change-password",
        data={"current_password": "secret123", "new_password": "newpass123"},
        cookies={"sa_session": token},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 旧密码失效
    old = _login(client, "admin@x.com", "secret123")
    assert old.status_code == 401

    # 新密码可用
    new = _login(client, "admin@x.com", "newpass123")
    assert new.status_code == 303


# ---------------------------------------------------------------------------
# 受保护页跳转 & 设置页权限可见性
# ---------------------------------------------------------------------------

def test_protected_page_redirects_when_unauthenticated(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in (r.headers.get("location") or "")


def test_settings_admin_sees_create_user(client):
    reg = _register(client, "admin@x.com", "secret123")
    token = _token(reg)
    r = client.get("/settings", cookies={"sa_session": token})
    assert r.status_code == 200
    assert "创建账户" in r.text


def test_settings_member_hides_create_user(client):
    reg = _register(client, "admin@x.com", "secret123")
    admin_token = _token(reg)
    client.post(
        "/api/create-user",
        data={"email": "mem@x.com", "password": "secret123"},
        cookies={"sa_session": admin_token},
    )
    mem_login = _login(client, "mem@x.com", "secret123")
    mem_token = _token(mem_login)
    r = client.get("/settings", cookies={"sa_session": mem_token})
    assert r.status_code == 200
    assert "创建账户" not in r.text
