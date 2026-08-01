#!/usr/bin/env python3
"""下载离线 GeoIP 国家库（DB-IP 免费版，CC-BY 4.0，无需 license key）。

用法:
    python scripts/fetch_geoip.py                 # 写到 ./data/GeoIP.mmdb
    python scripts/fetch_geoip.py --out /path/GeoIP.mmdb

下载后应用会在 SMART_ANALYTICS_DB_PATH 同目录（或本脚本默认 data/）下
寻找 GeoIP.mmdb 并自动启用国家识别。
"""
from __future__ import annotations

import argparse
import gzip
import io
import os
import sys
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "..", "data", "GeoIP.mmdb")


def candidate_urls() -> list[str]:
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    prev = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    # city-lite 含国家/省份/城市（CC-BY 4.0，无需 license key）
    base = "https://download.db-ip.com/free/dbip-city-lite-{}.mmdb.gz"
    return [base.format(ym), base.format(prev)]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=DEFAULT_OUT, help="输出 .mmdb 路径")
    args = p.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    last_err = ""
    for url in candidate_urls():
        print(f"下载: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "smart-analytics/geoip-fetch"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
                data = gz.read()
            with open(out, "wb") as f:
                f.write(data)
            print(f"OK -> {out} ({len(data)/1024/1024:.1f} MB)")
            return 0
        except Exception as e:  # noqa: BLE001
            last_err = f"{url} 失败: {e}"
            print(f"  {last_err}")

    print("所有下载源均失败，最后错误：", last_err, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
