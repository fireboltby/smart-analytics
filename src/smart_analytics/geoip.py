"""离线 GeoIP 国家识别（不依赖 Cloudflare 头）。

数据库文件（.mmdb）不随仓库分发，需自行下载：
    scripts/fetch_geoip.py
默认从 DB-IP 免费库（CC-BY 4.0，无需 license key）拉取。

读取逻辑：
- 优先用 Cloudflare 的 CF-IPCountry 头（若部署在 CF 后）；
- 否则用已采集的访客 IP 查本地 .mmdb，返回 ISO 3166-1 alpha-2 国家码。
- 数据库缺失/不可用时优雅降级为 None（与历史行为一致）。
"""

from __future__ import annotations

import os
import threading

try:
    import geoip2.database

    _GEOIP_AVAILABLE = True
except Exception:  # pragma: no cover - 依赖缺失时降级
    _GEOIP_AVAILABLE = False

_reader = None
_lock = threading.Lock()


def _open_reader() -> "geoip2.database.Reader | None":
    """按优先级解析 .mmdb 路径并打开（带缓存）。"""
    global _reader
    if not _GEOIP_AVAILABLE:
        return None
    with _lock:
        if _reader is not None:
            return _reader
        path = _resolve_db_path()
        if path and os.path.exists(path):
            try:
                _reader = geoip2.database.Reader(path)
            except Exception:
                _reader = None
        return _reader


def _resolve_db_path() -> str | None:
    """解析 .mmdb 路径：环境变量优先，其次与 sqlite 库同目录下的 GeoIP.mmdb。"""
    env = os.environ.get("SMART_ANALYTICS_GEOIP_DB")
    if env:
        return env
    db_path = os.environ.get("SMART_ANALYTICS_DB_PATH")
    base_dir = (
        os.path.dirname(db_path)
        if db_path
        else os.path.join(os.path.dirname(__file__), "..", "..", "data")
    )
    candidate = os.path.join(base_dir, "GeoIP.mmdb")
    return candidate if os.path.exists(candidate) else None


def ip_to_country(ip: str | None) -> str | None:
    """根据 IP 返回 ISO 3166-1 alpha-2 国家码，失败/未知返回 None。"""
    if not ip:
        return None
    reader = _open_reader()
    if reader is None:
        return None
    try:
        code = reader.country(ip).country.iso_code
        return code if code and code != "XX" else None
    except Exception:
        return None


def is_available() -> bool:
    """GeoIP 数据库是否就绪（用于前端提示/管理页）。"""
    return _open_reader() is not None
