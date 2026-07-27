import hashlib
import json
import re
import sqlite3
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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# Bot detection
# ---------------------------------------------------------------------------

BOT_PATTERNS = re.compile(
    r"bot|crawler|spider|scraper|curl|wget|python-requests|httpx|aiohttp|"
    r"googlebot|bingbot|yandex|baidu|duckduckbot|slurp|facebookexternalhit|"
    r"twitterbot|linkedinbot|embedly|quora|pinterest|redditbot|applebot|"
    r"semrushbot|ahrefsbot|mj12bot|dotbot|petalbot|bytespider|gptbot|"
    r"claudebot|anthropic|openai|headless|phantom|selenium|puppeteer|playwright",
    re.IGNORECASE,
)


def is_bot(user_agent: str) -> bool:
    """Return True if user-agent looks like a bot."""
    if not user_agent:
        return True
    return bool(BOT_PATTERNS.search(user_agent))


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

MOBILE_PATTERNS = re.compile(
    r"Mobile|Android.*Mobile|iPhone|iPod|BlackBerry|IEMobile|Opera Mini|"
    r"Windows Phone|webOS|Symbian|Nokia|Samsung.*Mobile",
    re.IGNORECASE,
)

TABLET_PATTERNS = re.compile(
    r"iPad|Android(?!.*Mobile)|Tablet|PlayBook|Silk|Kindle",
    re.IGNORECASE,
)


def detect_device(user_agent: str) -> str:
    """Detect device type from user agent."""
    if not user_agent:
        return "unknown"
    if TABLET_PATTERNS.search(user_agent):
        return "tablet"
    if MOBILE_PATTERNS.search(user_agent):
        return "mobile"
    return "desktop"


# ---------------------------------------------------------------------------
# Geo lookup (Cloudflare)
# ---------------------------------------------------------------------------

def get_country(request: Request) -> str | None:
    """Get country code from Cloudflare header."""
    cf_country = request.headers.get("cf-ipcountry")
    if cf_country and cf_country != "XX":
        return cf_country
    return None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TINY_ANALYTICS_", extra="ignore")
    password: str = "changeme"
    secret_key: str = "change-this-to-a-random-string"
    allowed_origins: list[str] = []
    db_path: str = str(BASE_DIR / "tiny_analytics.db")


settings = Settings()
signer = URLSafeSerializer(settings.secret_key, salt="tiny_analytics")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
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
    # Migrations for existing tables
    cursor = conn.execute("PRAGMA table_info(pageviews)")
    columns = [row[1] for row in cursor.fetchall()]
    if "country" not in columns:
        conn.execute("ALTER TABLE pageviews ADD COLUMN country TEXT")
    if "device" not in columns:
        conn.execute("ALTER TABLE pageviews ADD COLUMN device TEXT")
    if "duration_sec" not in columns:
        conn.execute("ALTER TABLE pageviews ADD COLUMN duration_sec INTEGER")
    conn.commit()
    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON pageviews(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_visitor ON pageviews(visitor_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON pageviews(country)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_device ON pageviews(device)")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="tiny-analytics", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins or ["*"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR, follow_symlink=True), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Hit(BaseModel):
    url: str
    referrer: str | None = None
    sid: str | None = None  # Session ID for duration tracking


class Duration(BaseModel):
    sid: str
    duration: int  # Seconds spent on page


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def require_auth(session: Annotated[str | None, Cookie(alias="tt_session")] = None):
    if not session:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    try:
        signer.loads(session)
    except BadSignature:
        raise HTTPException(status_code=303, headers={"Location": "/login"})


# ---------------------------------------------------------------------------
# Tracking endpoints
# ---------------------------------------------------------------------------

def get_real_ip(request: Request) -> str:
    """Extract real client IP, handling Cloudflare/proxy headers."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/t", status_code=204)
async def track(hit: Hit, request: Request):
    if settings.allowed_origins:
        origin = request.headers.get("origin") or request.headers.get("referer", "")
        parsed = urlparse(origin)
        request_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else ""
        if request_origin not in settings.allowed_origins:
            return Response(status_code=403)

    ip = get_real_ip(request)
    ua = request.headers.get("user-agent", "")
    visitor_hash = hashlib.sha256(f"{ip}:{ua}".encode()).hexdigest()[:16]
    country = get_country(request)
    device = detect_device(ua)

    # Use provided session ID or generate one
    sid = hit.sid or hashlib.sha256(f"{visitor_hash}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:12]

    conn = get_db()
    conn.execute(
        """INSERT INTO pageviews (ts, url, referrer, visitor_hash, user_agent, country, device, duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
        (datetime.now(timezone.utc).isoformat(), hit.url, hit.referrer, visitor_hash, ua, country, device),
    )
    # Get the row ID for duration updates
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    
    # Return session info for duration tracking
    return Response(
        content=json.dumps({"sid": sid, "rid": row_id}),
        status_code=200,
        media_type="application/json",
    )


@app.post("/d", status_code=204)
async def duration(request: Request):
    """Update duration for a pageview (called on page unload)."""
    try:
        body = await request.body()
        data = json.loads(body)
        rid = data.get("rid")
        duration_sec = data.get("d", 0)
        
        if rid and duration_sec and duration_sec > 0 and duration_sec < 7200:  # Cap at 2 hours
            conn = get_db()
            conn.execute("UPDATE pageviews SET duration_sec = ? WHERE id = ?", (duration_sec, rid))
            conn.commit()
            conn.close()
    except Exception:
        pass  # Silently fail for beacon requests
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Snippet endpoint
# ---------------------------------------------------------------------------

@app.get("/snippet.js")
async def snippet(request: Request):
    origin = f"{request.url.scheme}://{request.url.netloc}"
    js = f"""\
(function(){{
  var start=Date.now(),rid=null;
  fetch("{origin}/t",{{
    method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{url:location.href,referrer:document.referrer||null}})
  }}).then(r=>r.json()).then(d=>{{rid=d.rid}}).catch(()=>{{}});
  function send(){{
    if(!rid)return;
    var d=Math.round((Date.now()-start)/1000);
    navigator.sendBeacon("{origin}/d",JSON.stringify({{rid:rid,d:d}}));
  }}
  document.addEventListener("visibilitychange",function(){{if(document.hidden)send()}});
  window.addEventListener("pagehide",send);
}})();"""
    return Response(content=js, media_type="application/javascript")


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(password: Annotated[str, Form()]):
    if password != settings.password:
        raise HTTPException(status_code=401, detail="Wrong password")
    token = signer.dumps("authenticated")
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("tt_session", token, httponly=True, samesite="lax", max_age=86400 * 30)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("tt_session")
    return resp


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def bucket_timestamp(ts_str: str, interval: str) -> str:
    """Bucket a timestamp string into the specified interval."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if interval == "15m":
        minute = (dt.minute // 15) * 15
        return dt.strftime(f"%Y-%m-%d %H:{minute:02d}")
    elif interval == "1h":
        return dt.strftime("%Y-%m-%d %H:00")
    else:
        return dt.strftime("%Y-%m-%d")


# Country name mapping for display
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany", "FR": "France",
    "CA": "Canada", "AU": "Australia", "JP": "Japan", "CN": "China", "IN": "India",
    "BR": "Brazil", "NL": "Netherlands", "IT": "Italy", "ES": "Spain", "SE": "Sweden",
    "CH": "Switzerland", "PL": "Poland", "RU": "Russia", "KR": "South Korea",
    "MX": "Mexico", "SG": "Singapore", "HK": "Hong Kong", "TW": "Taiwan",
    "IE": "Ireland", "IL": "Israel", "AT": "Austria", "BE": "Belgium", "DK": "Denmark",
    "NO": "Norway", "FI": "Finland", "NZ": "New Zealand", "PT": "Portugal",
}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def dashboard(request: Request, hours: int = 24, interval: str = "1h"):
    if interval not in ("15m", "1h", "1d"):
        interval = "1h"

    conn = get_db()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # Aggregate stats
    stats = conn.execute("""
        SELECT 
            COUNT(DISTINCT visitor_hash) as uniques,
            COUNT(*) as views,
            AVG(CASE WHEN duration_sec IS NOT NULL AND duration_sec > 0 THEN duration_sec END) as avg_duration
        FROM pageviews WHERE ts >= ?
    """, (since,)).fetchone()
    
    total_uniques = stats["uniques"]
    total_views = stats["views"]
    avg_duration = int(stats["avg_duration"] or 0)

    # Get all pageviews
    rows = conn.execute("""
        SELECT ts, visitor_hash, user_agent, country, device, duration_sec
        FROM pageviews WHERE ts >= ?
    """, (since,)).fetchall()
    conn.close()

    # Process data for charts
    bucket_humans: dict[str, set[str]] = {}
    bucket_bots: dict[str, set[str]] = {}
    country_counts: dict[str, int] = {}
    device_counts = {"desktop": 0, "mobile": 0, "tablet": 0, "unknown": 0}
    duration_buckets: dict[str, list[int]] = {}

    for r in rows:
        bucket = bucket_timestamp(r["ts"], interval)
        vh = r["visitor_hash"]
        ua = r["user_agent"] or ""
        country = r["country"] or "Unknown"
        device = r["device"] or "unknown"
        duration = r["duration_sec"]

        if is_bot(ua):
            bucket_bots.setdefault(bucket, set()).add(vh)
        else:
            bucket_humans.setdefault(bucket, set()).add(vh)
            country_counts[country] = country_counts.get(country, 0) + 1
            device_counts[device] = device_counts.get(device, 0) + 1
            if duration and duration > 0:
                duration_buckets.setdefault(bucket, []).append(duration)

    # Time series data
    all_buckets = sorted(set(bucket_humans.keys()) | set(bucket_bots.keys()))
    human_values = [len(bucket_humans.get(b, set())) for b in all_buckets]
    bot_values = [len(bucket_bots.get(b, set())) for b in all_buckets]

    # Top countries for chart (with full names)
    top_countries = sorted(country_counts.items(), key=lambda x: -x[1])[:10]
    country_labels = [COUNTRY_NAMES.get(c, c) for c, _ in top_countries]
    country_values = [v for _, v in top_countries]

    # Format time labels
    if interval == "1d":
        time_labels = all_buckets
    else:
        time_labels = [b.split(" ")[1] if " " in b else b for b in all_buckets]

    origin = f"{request.url.scheme}://{request.url.netloc}"

    # Format average duration
    if avg_duration > 60:
        duration_str = f"{avg_duration // 60}m {avg_duration % 60}s"
    else:
        duration_str = f"{avg_duration}s"

    # Prepare chart data for JS
    chart_data = {
        "timeLabels": time_labels,
        "humanValues": human_values,
        "botValues": bot_values,
        "countryLabels": country_labels,
        "countryValues": country_values,
        "devices": device_counts,
    }

    return templates.TemplateResponse(request, "dashboard.html", {
        "hours": hours,
        "interval": interval,
        "total_uniques": total_uniques,
        "total_views": total_views,
        "duration_str": duration_str,
        "device_counts": type("DeviceCounts", (), device_counts)(),  # Object-like access
        "origin": origin,
        "chart_data": chart_data,
    })


# ---------------------------------------------------------------------------
# Logs page
# ---------------------------------------------------------------------------

@app.get("/logs", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def logs_page(request: Request, limit: int = 100, offset: int = 0, filter: str = "all"):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as cnt FROM pageviews").fetchone()["cnt"]
    rows = conn.execute("""
        SELECT id, ts, url, referrer, visitor_hash, user_agent, country, device, duration_sec
        FROM pageviews ORDER BY ts DESC LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()
    conn.close()

    processed_rows = []
    for r in rows:
        ua = r["user_agent"] or ""
        is_bot_hit = is_bot(ua)

        if filter == "humans" and is_bot_hit:
            continue
        if filter == "bots" and not is_bot_hit:
            continue

        processed_rows.append({
            "ts_short": r["ts"][:19].replace("T", " "),
            "url": r["url"],
            "url_short": r["url"][:50] + "..." if len(r["url"]) > 50 else r["url"],
            "ref_short": (r["referrer"] or "—")[:30],
            "country": r["country"] or "—",
            "device": r["device"] or "—",
            "duration": f"{r['duration_sec']}s" if r["duration_sec"] else "—",
            "is_bot": is_bot_hit,
        })

    return templates.TemplateResponse(request, "logs.html", {
        "rows": processed_rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filter": filter,
        "prev_offset": max(0, offset - limit),
        "next_offset": offset + limit,
    })
