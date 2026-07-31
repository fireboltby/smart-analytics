"""引导（bootstrap）测试：环境变量建管理员、无配置等待注册、旧 password_hash 迁移。
"""
import smart_analytics.app as appmod
from smart_analytics.app import get_db, user_is_admin

import helpers


def test_bootstrap_env_creates_admin(admin_client):
    # bootstrap 用环境变量密码创建了 admin@localhost，并设为默认站点 owner
    assert user_is_admin(1) is True
    # 公开注册因此关闭
    r = admin_client.get("/register")
    assert r.status_code == 200
    assert "注册已关闭" in r.text
    # 用引导密码可登录
    lr = admin_client.post(
        "/login",
        data={"email": "admin@localhost", "password": "boot123"},
        follow_redirects=False,
    )
    assert lr.status_code == 303
    assert lr.cookies.get("sa_session")


def test_bootstrap_no_users_no_admin(client):
    # 无环境变量密码、无 app_settings 哈希 → 不建管理员，注册开放
    assert user_is_admin(1) is False
    r = client.get("/register")
    assert r.status_code == 200
    assert "创建账户" in r.text


def test_bootstrap_migration_password_hash(client):
    # 模拟历史部署：app_settings 存有 password_hash，未设环境变量
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings(key, value) VALUES ('password_hash', ?)",
            (appmod._hash_pw("legacy123"),),
        )
        conn.commit()
    finally:
        conn.close()
    appmod.bootstrap_instance()   # 手动触发迁移路径
    assert user_is_admin(1) is True
    lr = client.post(
        "/login",
        data={"email": "admin@localhost", "password": "legacy123"},
        follow_redirects=False,
    )
    assert lr.status_code == 303
    assert lr.cookies.get("sa_session")
