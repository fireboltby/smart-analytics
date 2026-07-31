"""smart-analytics —— 多租户 SaaS 版（C 方案）。

核心防御点：所有对 pageviews 的读取都经 analytics 层并按 site_id 隔离；
采集端用每站随机 token 标识站点，visitor_hash 纳入 site_id 防跨站污染。
零新依赖（仅标准库 + 现有依赖）。
"""

import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from smart_analytics.analytics import (
    BEIJING,
    detect_device,
    get_country,
    compute_dashboard,
    get_logs,
)

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SMART_ANALYTICS_", extra="ignore")
    password: str = "changeme"
    secret_key: str = "change-this-to-a-random-string"
    allowed_origins: list[str] = []
    db_path: str = str(BASE_DIR / "smart_analytics.db")
    admin_email: str = "admin@localhost"
    # 注册开关：自托管默认开放；设为 false 可关闭公开注册（仅引导管理员可用）
    open_register: bool = True


settings = Settings()
signer = URLSafeSerializer(settings.secret_key, salt="smart_analytics")

# ---------------------------------------------------------------------------
# 密码哈希（与旧版 _pw_hash 一致，便于从 app_settings.password_hash 迁移；零新依赖）
# ---------------------------------------------------------------------------

def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------

def get_db() -> "sqlite3.Connection":  # noqa: F821
    import sqlite3
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    import sqlite3
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 多租户核心表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                domain TEXT,
                token TEXT UNIQUE NOT NULL,
                allowed_origins TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memberships (
                user_id INTEGER NOT NULL,
                site_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner',
                PRIMARY KEY (user_id, site_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(site_id) REFERENCES sites(id) ON DELETE CASCADE
            )
        """)

        # pageviews：先确保默认站点(id=1)存在，再加 site_id 列（NOT NULL DEFAULT 1 才安全）
        _ensure_default_site(conn)

        # 全新部署时 pageviews 表尚不存在（历史升级场景已有），先建表再 ALTER
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pageviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                url TEXT NOT NULL,
                referrer TEXT,
                visitor_hash TEXT NOT NULL,
                user_agent TEXT,
                country TEXT,
                device TEXT,
                duration_sec INTEGER
            )
        """)

        cursor = conn.execute("PRAGMA table_info(pageviews)")
        columns = [row[1] for row in cursor.fetchall()]
        if "site_id" not in columns:
            conn.execute("ALTER TABLE pageviews ADD COLUMN site_id INTEGER NOT NULL DEFAULT 1")

        # 历史列迁移
        if "country" not in columns:
            conn.execute("ALTER TABLE pageviews ADD COLUMN country TEXT")
        if "device" not in columns:
            conn.execute("ALTER TABLE pageviews ADD COLUMN device TEXT")
        if "duration_sec" not in columns:
            conn.execute("ALTER TABLE pageviews ADD COLUMN duration_sec INTEGER")
        if "ip" not in columns:
            conn.execute("ALTER TABLE pageviews ADD COLUMN ip TEXT")

        # 索引（含复合索引以支撑按站点查询）
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON pageviews(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_visitor ON pageviews(visitor_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON pageviews(country)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_device ON pageviews(device)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ip ON pageviews(ip)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_site_ts ON pageviews(site_id, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_site_visitor ON pageviews(site_id, visitor_hash)")

        # 应用配置键值表（保留以兼容旧密码哈希迁移）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

        # WAL 提升并发写入能力（采集端高频 INSERT）
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
    finally:
        conn.close()


def _ensure_default_site(conn):
    """确保默认站点存在（id=1），存量 pageviews 全部归属于此，零数据丢失。"""
    row = conn.execute("SELECT id FROM sites WHERE id=1").fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO sites(id, name, domain, token, allowed_origins, created_at) VALUES (1, ?, NULL, ?, '', ?)",
        ("默认站点", secrets.token_hex(16), datetime.now(BEIJING).isoformat()),
    )
    conn.commit()


def bootstrap_instance():
    """首次启动引导：创建默认站点 + 管理员账户（零破坏性迁移）。

    - 若 users 为空且设置了 SMART_ANALYTICS_PASSWORD：用该密码创建管理员（邮箱来自
      SMART_ANALYTICS_ADMIN_EMAIL），并设为默认站点 owner。
    - 否则若旧版 app_settings 存有 password_hash：用该哈希创建管理员，兼容历史部署。
    - 否则留空，等待首个用户通过 /register 注册（注册者自动成为默认站点 owner）。
    """
    conn = get_db()
    try:
        users_cnt = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if users_cnt > 0:
            # 已存在用户：仅保证默认站点有 owner
            _ensure_default_site_owner(conn)
            return

        env_pw = os.environ.get("SMART_ANALYTICS_PASSWORD")
        pw_hash = None
        if env_pw:
            pw_hash = _hash_pw(env_pw)
        else:
            row = conn.execute("SELECT value FROM app_settings WHERE key='password_hash'").fetchone()
            if row:
                pw_hash = row["value"]

        if not pw_hash:
            return  # 等待注册

        email = settings.admin_email
        conn.execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, pw_hash, datetime.now(BEIJING).isoformat()),
        )
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO memberships(user_id, site_id, role) VALUES (?, 1, 'owner')",
            (uid,),
        )
        conn.commit()
        print(f"  [引导] 已创建管理员账户：{email}（默认站点 owner）")
    finally:
        conn.close()


def _ensure_default_site_owner(conn):
    cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM memberships WHERE site_id=1"
    ).fetchone()["c"]
    if cnt > 0:
        return
    row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if row:
        conn.execute(
            "INSERT OR IGNORE INTO memberships(user_id, site_id, role) VALUES (?, 1, 'owner')",
            (row["id"],),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 应用生命周期
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_instance()
    yield


app = FastAPI(title="smart-analytics", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR, follow_symlink=True), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# 轻量内存限流：每 token 每 60s 最多 N 次采集，闭「刷量」坑
_RATE_LIMIT: dict[str, list[float]] = {}
_RATE_WINDOW = 60.0
_RATE_MAX = 2000


def _rate_ok(key: str) -> bool:
    now = datetime.now().timestamp()
    hits = _RATE_LIMIT.get(key, [])
    hits = [t for t in hits if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_MAX:
        _RATE_LIMIT[key] = hits
        return False
    hits.append(now)
    _RATE_LIMIT[key] = hits
    return True


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class Hit(BaseModel):
    url: str
    referrer: str | None = None
    sid: str | None = None


# ---------------------------------------------------------------------------
# 认证依赖
# ---------------------------------------------------------------------------

def require_user(session: Annotated[str | None, Cookie(alias="sa_session")] = None) -> int:
    """页面依赖：校验登录，未登录重定向到 /login。返回 user_id。"""
    if not session:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    try:
        uid = signer.loads(session)
    except BadSignature:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return int(uid)


def get_user_id_optional(session: Annotated[str | None, Cookie(alias="sa_session")] = None) -> int | None:
    if not session:
        return None
    try:
        return int(signer.loads(session))
    except BadSignature:
        return None


def user_has_site(user_id: int, site_id: int) -> bool:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM memberships WHERE user_id=? AND site_id=?", (user_id, site_id)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def user_is_admin(user_id: int) -> bool:
    """任一站点拥有 owner 角色即视为管理员（可创建普通账户）。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM memberships WHERE user_id=? AND role='owner'", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _public_register_open() -> bool:
    """公开注册仅在：部署者未显式关闭 且 当前还没有任何用户时开放。
    一旦存在账户（bootstrap 建的管理员或首个注册者），公开 /register 自动关闭，
    之后仅能由管理员在「设置」页创建账户。判断依据为数据库，重启后依然生效。"""
    if not settings.open_register:
        return False
    conn = get_db()
    try:
        cnt = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    finally:
        conn.close()
    return cnt == 0


def resolve_current_site(request: Request, user_id: int):
    """返回 (current_site_dict | None, sites_list)。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT s.id, s.name, s.token, s.domain FROM sites s "
            "JOIN memberships m ON m.site_id=s.id WHERE m.user_id=? ORDER BY s.id",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    sites = [dict(r) for r in rows]
    if not sites:
        return None, []
    cookie_site = request.cookies.get("sa_site")
    if cookie_site:
        try:
            cid = int(cookie_site)
            for s in sites:
                if s["id"] == cid:
                    return s, sites
        except ValueError:
            pass
    return sites[0], sites


# ---------------------------------------------------------------------------
# 站点切换
# ---------------------------------------------------------------------------

@app.get("/switch-site")
async def switch_site(site: int, request: Request, user_id: int = Depends(require_user)):
    if not user_has_site(user_id, site):
        raise HTTPException(status_code=403, detail="无权访问该站点")
    resp = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    resp.set_cookie("sa_site", str(site), httponly=True, samesite="lax", max_age=86400 * 30)
    return resp


# ---------------------------------------------------------------------------
# 注册 / 登录 / 登出
# ---------------------------------------------------------------------------

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if not _public_register_open():
        return templates.TemplateResponse(request, "register.html", {"closed": True})
    return templates.TemplateResponse(request, "register.html", {"closed": False})


@app.post("/register")
async def register(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()] = "",
):
    if not _public_register_open():
        return templates.TemplateResponse(request, "register.html", {"closed": True})
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return templates.TemplateResponse(
            request, "register.html", {"error": "邮箱格式不正确", "email": email}
        )
    if not password or len(password) < 6:
        return templates.TemplateResponse(
            request, "register.html", {"error": "密码至少 6 位", "email": email}
        )
    if password != password_confirm:
        return templates.TemplateResponse(
            request, "register.html", {"error": "两次输入的密码不一致", "email": email}
        )

    conn = get_db()
    try:
        exists = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            return templates.TemplateResponse(
                request, "register.html", {"error": "该邮箱已注册", "email": email}
            )
        conn.execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, _hash_pw(password), datetime.now(BEIJING).isoformat()),
        )
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        # 首个注册用户成为默认站点 owner；其余新用户暂不自动建站（走 /sites 创建）
        is_first = conn.execute("SELECT COUNT(*) AS c FROM memberships").fetchone()["c"] == 0
        if is_first:
            conn.execute(
                "INSERT OR IGNORE INTO memberships(user_id, site_id, role) VALUES (?, 1, 'owner')",
                (uid,),
            )
        conn.commit()
    finally:
        conn.close()

    token = signer.dumps(uid)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("sa_session", token, httponly=True, samesite="lax", max_age=86400 * 30)
    return resp


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(email: Annotated[str, Form()], password: Annotated[str, Form()]):
    email = (email or "").strip().lower()
    conn = get_db()
    try:
        row = conn.execute("SELECT id, password_hash FROM users WHERE email=?", (email,)).fetchone()
    finally:
        conn.close()
    if not row or _hash_pw(password) != row["password_hash"]:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    token = signer.dumps(row["id"])
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("sa_session", token, httponly=True, samesite="lax", max_age=86400 * 30)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("sa_session")
    return resp


# ---------------------------------------------------------------------------
# 采集端点（每站 token 隔离）
# ---------------------------------------------------------------------------

def get_real_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _resolve_site_by_token(token: str | None):
    if not token:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, allowed_origins FROM sites WHERE token=?", (token,)
        ).fetchone()
    finally:
        conn.close()
    return row


@app.post("/t", status_code=204)
async def track(hit: Hit, request: Request):
    token = request.query_params.get("t") or request.headers.get("X-Site-Token")
    site = _resolve_site_by_token(token)
    if not site:
        return Response(status_code=204)  # 静默拒绝无效 token

    # 每站 allowed_origins 校验（防跨站刷量；空 = 不限制）
    allowed = (site["allowed_origins"] or "").strip()
    if allowed:
        origin = request.headers.get("origin") or request.headers.get("referer", "")
        parsed = urlparse(origin)
        request_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else ""
        hosts = [o.strip() for o in allowed.split(",") if o.strip()]
        if request_origin and request_origin not in hosts:
            return Response(status_code=204)

    if not _rate_ok(token):
        return Response(status_code=204)

    site_id = site["id"]
    ip = get_real_ip(request)
    ua = request.headers.get("user-agent", "")
    # 关键：visitor_hash 纳入 site_id，杜绝跨站同人误并（闭坑）
    visitor_hash = hashlib.sha256(f"{site_id}:{ip}:{ua}".encode()).hexdigest()[:32]
    country = get_country(request, ip)
    device = detect_device(ua)

    sid = hit.sid or hashlib.sha256(
        f"{visitor_hash}:{datetime.now(BEIJING).isoformat()}".encode()
    ).hexdigest()[:12]

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO pageviews (site_id, ts, url, referrer, visitor_hash, user_agent, country, device, duration_sec, ip)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
            (site_id, datetime.now(BEIJING).isoformat(), hit.url, hit.referrer, visitor_hash, ua, country, device, ip),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    return Response(
        content=json.dumps({"sid": sid, "rid": row_id}),
        status_code=200,
        media_type="application/json",
    )


@app.post("/d", status_code=204)
async def duration(request: Request):
    token = request.query_params.get("t") or request.headers.get("X-Site-Token")
    site = _resolve_site_by_token(token)
    if not site:
        return Response(status_code=204)
    if not _rate_ok(token):
        return Response(status_code=204)
    try:
        body = await request.body()
        data = json.loads(body)
        rid = data.get("rid")
        duration_sec = data.get("d", 0)
        if rid and duration_sec and 0 < duration_sec < 7200:
            conn = get_db()
            try:
                # 仅允许更新本站点自身的记录（闭越权改他人时长坑）
                conn.execute(
                    "UPDATE pageviews SET duration_sec = ? WHERE id = ? AND site_id = ?",
                    (duration_sec, rid, site["id"]),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 每站追踪脚本
# ---------------------------------------------------------------------------

@app.get("/s/{token}.js")
async def snippet(request: Request, token: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM sites WHERE token=?", (token,)).fetchone()
    finally:
        conn.close()
    if not row:
        return Response(status_code=404, media_type="application/javascript")
    origin = f"{request.url.scheme}://{request.url.netloc}"
    js = f"""\
(function(){{
  var start=Date.now(),rid=null;
  fetch("{origin}/t?t={token}",{{
    method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{url:location.href,referrer:document.referrer||null}})
  }}).then(r=>r.json()).then(d=>{{rid=d.rid}}).catch(()=>{{}});
  function send(){{
    if(!rid)return;
    var d=Math.round((Date.now()-start)/1000);
    navigator.sendBeacon("{origin}/d?t={token}",JSON.stringify({{rid:rid,d:d}}));
  }}
  document.addEventListener("visibilitychange",function(){{if(document.hidden)send()}});
  window.addEventListener("pagehide",send);
}})();"""
    return Response(content=js, media_type="application/javascript")


# ---------------------------------------------------------------------------
# 站点管理
# ---------------------------------------------------------------------------

@app.get("/sites", response_class=HTMLResponse, dependencies=[Depends(require_user)])
async def sites_page(request: Request, user_id: int = Depends(require_user)):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT s.id, s.name, s.domain, s.token, s.created_at FROM sites s "
            "JOIN memberships m ON m.site_id=s.id WHERE m.user_id=? ORDER BY s.id",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    sites = [dict(r) for r in rows]
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return templates.TemplateResponse(request, "sites.html", {"sites": sites, "origin": origin})


@app.post("/sites/create")
async def sites_create(
    name: Annotated[str, Form()] = "",
    domain: Annotated[str, Form()] = "",
    user_id: int = Depends(require_user),
):
    name = (name or "").strip() or "未命名站点"
    domain = (domain or "").strip() or None
    token = secrets.token_hex(16)
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO sites(name, domain, token, allowed_origins, created_at) VALUES (?, ?, ?, '', ?)",
            (name, domain, token, datetime.now(BEIJING).isoformat()),
        )
        site_id = cur.lastrowid
        conn.execute(
            "INSERT INTO memberships(user_id, site_id, role) VALUES (?, ?, 'owner')",
            (user_id, site_id),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/sites", status_code=303)


@app.post("/sites/delete")
async def sites_delete(site: int = Form(...), user_id: int = Depends(require_user)):
    if not user_has_site(user_id, site):
        raise HTTPException(status_code=403, detail="无权删除该站点")
    conn = get_db()
    try:
        # 级联：先清该站 pageviews（闭删站残留坑），再删站点与成员关系
        conn.execute("DELETE FROM pageviews WHERE site_id=?", (site,))
        conn.execute("DELETE FROM memberships WHERE site_id=?", (site,))
        conn.execute("DELETE FROM sites WHERE id=?", (site,))
        conn.commit()
    finally:
        conn.close()
    resp = RedirectResponse("/sites", status_code=303)
    # 清除当前站点 cookie，避免指向已删站点
    resp.delete_cookie("sa_site")
    return resp


# ---------------------------------------------------------------------------
# 仪表盘（按当前站点隔离）
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_user)])
async def dashboard(request: Request, hours: int = 24, interval: str = "1h",
                   user_id: int = Depends(require_user)):
    site, sites = resolve_current_site(request, user_id)
    origin = f"{request.url.scheme}://{request.url.netloc}"

    if not site:
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"no_site": True, "sites": sites, "origin": origin, "hours": hours, "interval": interval},
        )

    conn = get_db()
    try:
        data = compute_dashboard(conn, site["id"], hours, interval)
    finally:
        conn.close()

    ctx = dict(data)
    ctx.update({
        "no_site": False,
        "site": site,
        "sites": sites,
        "origin": origin,
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/api/realtime")
async def api_realtime(request: Request, site: int = 0, user_id: int | None = Depends(get_user_id_optional)):
    if not user_id:
        return {"online": 0}
    if not site or not user_has_site(user_id, site):
        # 回退：取用户首个站点
        _, sites = resolve_current_site(request, user_id)
        site = sites[0]["id"] if sites else 0
    if not site:
        return {"online": 0}
    since = (datetime.now(BEIJING) - timedelta(minutes=5)).isoformat()
    conn = get_db()
    try:
        online = conn.execute(
            "SELECT COUNT(DISTINCT visitor_hash) FROM pageviews WHERE site_id=? AND ts>=?",
            (site, since),
        ).fetchone()[0]
    finally:
        conn.close()
    return {"online": online}


# ---------------------------------------------------------------------------
# 访问日志（按当前站点隔离）
# ---------------------------------------------------------------------------

@app.get("/logs", response_class=HTMLResponse, dependencies=[Depends(require_user)])
async def logs_page(request: Request, limit: int = 100, offset: int = 0,
                    filter: str = "all", user_id: int = Depends(require_user)):
    site, sites = resolve_current_site(request, user_id)
    if not site:
        return templates.TemplateResponse(
            request, "logs.html", {"sites": sites, "rows": [], "total": 0,
                                   "limit": limit, "offset": offset, "filter": filter,
                                   "prev_offset": 0, "next_offset": 0}
        )
    conn = get_db()
    try:
        rows, total = get_logs(conn, site["id"], limit, offset, filter)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "logs.html", {
        "site": site,
        "sites": sites,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filter": filter,
        "prev_offset": max(0, offset - limit),
        "next_offset": offset + limit,
    })


# ---------------------------------------------------------------------------
# 设置 / 修改密码（按当前登录用户）
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(require_user)])
async def settings_page(request: Request, user_id: int = Depends(require_user)):
    env_fixed = bool(os.environ.get("SMART_ANALYTICS_PASSWORD"))
    is_admin = user_is_admin(user_id)
    return templates.TemplateResponse(request, "settings.html", {"env_fixed": env_fixed, "is_admin": is_admin})


@app.post("/api/change-password")
async def change_password(
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    user_id: int = Depends(require_user),
):
    if os.environ.get("SMART_ANALYTICS_PASSWORD"):
        raise HTTPException(status_code=400, detail="密码由环境变量 SMART_ANALYTICS_PASSWORD 固定，无法在页面修改。")
    conn = get_db()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
    finally:
        conn.close()
    if not row or _hash_pw(current_password) != row["password_hash"]:
        raise HTTPException(status_code=401, detail="当前密码错误")
    if not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    conn = get_db()
    try:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_pw(new_password), user_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "msg": "密码已更新，请使用新密码重新登录。", "logout": "/logout"}


# ---------------------------------------------------------------------------
# 管理员创建普通账户（默认站点 member 角色）
# ---------------------------------------------------------------------------

@app.post("/api/create-user")
async def create_user(
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    user_id: int = Depends(require_user),
):
    # 仅管理员（任一站点 owner）可创建账户
    if not user_is_admin(user_id):
        raise HTTPException(status_code=403, detail="仅管理员可创建账户")
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")

    conn = get_db()
    try:
        exists = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="该邮箱已注册")
        conn.execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, _hash_pw(password), datetime.now(BEIJING).isoformat()),
        )
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        # 普通成员：加入默认站点（site_id=1），role='member'
        conn.execute(
            "INSERT OR IGNORE INTO memberships(user_id, site_id, role) VALUES (?, 1, 'member')",
            (uid,),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "msg": f"已创建账户 {email}（普通成员）"}
