#!/usr/bin/env python3
"""回填历史访问记录的国家/省份/城市字段。

需要 GeoIP.mmdb（city 库，含省份/城市）已就位——见 scripts/fetch_geoip.py。

用法:
    python scripts/backfill_country.py
    python scripts/backfill_country.py --force            # 强制重新解析所有已记录 IP 的行
    SMART_ANALYTICS_DB_PATH=/www/wwwroot/smart-analytics/data/smart_analytics.db \
        python scripts/backfill_country.py
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from smart_analytics.geoip import ip_to_location

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "smart_analytics.db")


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 pageviews 表的国家/省份/城市字段")
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新解析所有带 IP 的记录（默认只填 country/region/city 任一为空者）",
    )
    args = parser.parse_args()

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
        if args.force:
            rows = conn.execute("SELECT id, ip FROM pageviews WHERE ip IS NOT NULL").fetchall()
        else:
            rows = conn.execute(
                "SELECT id, ip FROM pageviews "
                "WHERE ip IS NOT NULL AND (country IS NULL OR region IS NULL OR city IS NULL)"
            ).fetchall()
        total = len(rows)
        updated = 0
        for row_id, ip in rows:
            loc = ip_to_location(ip)
            if not loc:
                continue
            conn.execute(
                "UPDATE pageviews SET country = ?, region = ?, city = ? WHERE id = ?",
                (loc["country_code"], loc["region"], loc["city"], row_id),
            )
            updated += 1
        conn.commit()
        mode = "强制重新解析" if args.force else "回填空值"
        print(f"{mode}: 待处理 {total} 行，成功写入国家/省份/城市 {updated} 行。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
