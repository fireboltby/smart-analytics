import os

import pytest

# 必须在导入 smart_analytics.app 之前设置隔离数据库路径，避免落到真实 dev 库。
# 每个测试的具体文件路径由 client fixture 再覆盖为独立临时文件。
os.environ["SMART_ANALYTICS_DB_PATH"] = ":memory:"  # 占位；client fixture 会覆盖为临时文件
os.environ.setdefault("SMART_ANALYTICS_SECRET_KEY", "test-secret-key-not-for-prod")


@pytest.fixture
def client(tmp_path):
    """每个测试使用独立临时 SQLite 文件，完全隔离，不污染真实开发库。

    - 不设置 SMART_ANALYTICS_PASSWORD，保证 bootstrap 不自动建管理员，
      公开注册保持开放（与首个用户注册后自动关闭的逻辑一致）。
    - 通过覆盖 settings.db_path 指向临时文件，init_db / get_db 均使用该文件。
    """
    import smart_analytics.app as appmod

    db_file = tmp_path / "test.db"
    appmod.settings.db_path = str(db_file)
    os.environ.pop("SMART_ANALYTICS_PASSWORD", None)

    from fastapi.testclient import TestClient

    with TestClient(appmod.app) as c:
        yield c


@pytest.fixture
def admin_client(tmp_path):
    """自动建管理员的隔离客户端：设 SMART_ANALYTICS_PASSWORD 后启动，

    bootstrap 会用该密码创建 admin@localhost 并设为默认站点 owner，
    公开注册因此自动关闭。专用于「环境变量固定密码 / bootstrap」相关测试。
    """
    import smart_analytics.app as appmod

    db_file = tmp_path / "admin.db"
    appmod.settings.db_path = str(db_file)
    os.environ["SMART_ANALYTICS_PASSWORD"] = "boot123"
    os.environ["SMART_ANALYTICS_ADMIN_EMAIL"] = "admin@localhost"

    from fastapi.testclient import TestClient

    with TestClient(appmod.app) as c:
        yield c

    os.environ.pop("SMART_ANALYTICS_PASSWORD", None)
    os.environ.pop("SMART_ANALYTICS_ADMIN_EMAIL", None)

