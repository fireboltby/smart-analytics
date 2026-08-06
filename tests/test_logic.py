"""代码测试（单元层）：核心纯逻辑函数。

不依赖网络/服务，直接调用 app 模块内的函数，验证密码哈希与权限/注册开放判定。
每个用例通过 client fixture 获得一个全新的隔离数据库（已由 init_db 建好表结构）。
"""
import hashlib

from smart_analytics.app import (
    _hash_pw,
    _public_register_open,
    get_db,
    settings,
    user_is_admin,
)


def test_hash_pw_deterministic_and_sha256():
    h1 = _hash_pw("smart-analytics")
    h2 = _hash_pw("smart-analytics")
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 十六进制长度
    assert h1 == hashlib.sha256("smart-analytics".encode("utf-8")).hexdigest()


def test_public_register_open_when_no_users(client):
    # 全新数据库、无环境变量密码、open_register 默认 True → 公开注册开放
    assert _public_register_open() is True


def test_public_register_open_after_user_exists(client):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users(email, password_hash, created_at) "
            "VALUES ('a@x.com', 'h', '2026-01-01T00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    # 一旦存在账户，公开注册自动关闭
    assert _public_register_open() is False


def test_public_register_open_respects_setting(client, monkeypatch):
    monkeypatch.setattr(settings, "open_register", False)
    assert _public_register_open() is False


def test_user_is_admin_owner(client):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users(id, email, password_hash, created_at) "
            "VALUES (1, 'a@x.com', 'h', '2026-01-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO memberships(user_id, site_id, role) VALUES (1, 1, 'owner')"
        )
        conn.commit()
    finally:
        conn.close()
    assert user_is_admin(1) is True


def test_user_is_admin_member(client):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users(id, email, password_hash, created_at) "
            "VALUES (2, 'b@x.com', 'h', '2026-01-01T00:00:00')"
        )
        conn.execute(
            "INSERT INTO memberships(user_id, site_id, role) VALUES (2, 1, 'member')"
        )
        conn.commit()
    finally:
        conn.close()
    assert user_is_admin(2) is False


def test_user_is_admin_nonexistent(client):
    # 不存在的用户，任何角色查询都应为 False
    assert user_is_admin(999) is False
