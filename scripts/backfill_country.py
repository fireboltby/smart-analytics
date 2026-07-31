#!/usr/bin/env python3
"""回填历史访问记录的国家/地区字段。

仅在 country 为 NULL 且已记录 ip 的行上执行。需要 GeoIP.mmdb 已就位
（见 scripts/fetch_geoip.py）。

用法:
    python scripts/backfill_country.py
    SMART_ANALYTICS_DB_PATH=/www/wwwroot/smart-analytics/data/smart_analytics.db \
        python scripts/backfill_country.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

from smart_analytics.geoip import ip_to_country

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "smart_analytics.db")


def main() -> int:
    db_path = os.environ.get("SMART_ANALYTICS_DB_PATH") or DEFAULT_DB
    if not os.path.exists(db_path):
        print(f"找不到数据库: {db_path}", file=sys.stderr)
        return 1

    from smart_analytics.geoip import is_available

    if not is_available():
        print("GeoIP 数据库未就绪，请先运行 scripts/fetch_geoip.py", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ip FROM pageviews WHERE country IS NULL AND ip IS NOT NULL"
        ).fetchall()
        total = len(rows)
        updated = 0
        for row_id, ip in rows:
            country = ip_to_country(ip)
            if country:
                conn.execute("UPDATE pageviews SET country = ? WHERE id = ?", (country, row_id))
                updated += 1
        conn.commit()
        print(f"待回填 {total} 行，成功写入国家 {updated} 行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
