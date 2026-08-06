"""测试辅助：在隔离临时库上播种数据，并生成登录态 cookie。

所有辅助都读写 smart_analytics.app.settings.db_path 指向的库，
与 conftest 的 client / admin_client fixture 共用同一临时文件，零污染真实 dev 库。
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import smart_analytics.app as appmod

BEIJING = timezone(timedelta(hours=8))

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
BOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
IPAD_UA = "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"


def db_path() -> str:
    return appmod.settings.db_path


def raw_conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    return c


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def add_user(email: str, password: str, site_id: int = 1, role: str = "owner") -> int:
    c = raw_conn()
    c.execute(
        "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
        (email, hash_pw(password), datetime.now(BEIJING).isoformat()),
    )
    uid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute(
        "INSERT OR IGNORE INTO memberships(user_id, site_id, role) VALUES (?, ?, ?)",
        (uid, site_id, role),
    )
    c.commit()
    c.close()
    return uid


def add_user_no_site(email: str, password: str) -> int:
    """插入一个没有任何站点归属的用户（用于 no_site 空态测试）。"""
    c = raw_conn()
    c.execute(
        "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
        (email, hash_pw(password), datetime.now(BEIJING).isoformat()),
    )
    uid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit()
    c.close()
    return uid


def add_site(name: str, token: str, owner_user_id: int, domain=None,
             allowed_origins: str = "") -> int:
    c = raw_conn()
    c.execute(
        "INSERT INTO sites(name, domain, token, allowed_origins, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, domain, token, allowed_origins, datetime.now(BEIJING).isoformat()),
    )
    sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute(
        "INSERT INTO memberships(user_id, site_id, role) VALUES (?, ?, 'owner')",
        (owner_user_id, sid),
    )
    c.commit()
    c.close()
    return sid


def add_pageview(site_id: int, ts=None, url: str = "/page", referrer=None,
                 visitor_hash: str = "v1", ua: str = CHROME_UA, country: str = "CN",
                 device: str = "desktop", duration=None):
    if ts is None:
        ts = datetime.now(BEIJING).isoformat()
    c = raw_conn()
    c.execute(
        """INSERT INTO pageviews(site_id, ts, url, referrer, visitor_hash,
           user_agent, country, device, duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (site_id, ts, url, referrer, visitor_hash, ua, country, device, duration),
    )
    c.commit()
    c.close()


def session_cookie(user_id: int) -> dict:
    return {"sa_session": appmod.signer.dumps(user_id)}


def site_cookie(site_id: int) -> dict:
    return {"sa_site": str(site_id)}


def recent_ts(minutes: int = 1) -> str:
    """返回距今 minutes 分钟的北京时间 ISO 字符串（落在实时/窗口内）。"""
    return (datetime.now(BEIJING) - timedelta(minutes=minutes)).isoformat()


def login_cookie(client, email: str, password: str) -> dict:
    """用 TestClient 登录并返回 sa_session cookie 字典，便于带鉴权请求。"""
    r = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    return {"sa_session": r.cookies.get("sa_session")}
