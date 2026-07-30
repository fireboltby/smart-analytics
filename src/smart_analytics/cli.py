"""CLI for smart-analytics."""

import os
import secrets


def main():
    """Run the smart-analytics server."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        description="smart-analytics - Minimal, privacy-focused web analytics"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("TINY_ANALYTICS_HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("TINY_ANALYTICS_PORT", "8000")),
        help="Port to listen on (default: 8000)",
    )
    args = parser.parse_args()

    # Handle password
    password = os.environ.get("TINY_ANALYTICS_PASSWORD")
    generated = False
    if not password:
        password = secrets.token_urlsafe(16)
        os.environ["TINY_ANALYTICS_PASSWORD"] = password
        generated = True

    # Generate secret key if not set
    if not os.environ.get("TINY_ANALYTICS_SECRET_KEY"):
        os.environ["TINY_ANALYTICS_SECRET_KEY"] = secrets.token_hex(32)

    # Startup banner（中文）
    print("\n  ╭─────────────────────────────────────────╮")
    print("  │           smart-analytics                │")
    print("  ╰─────────────────────────────────────────╯")
    print()
    print(f"  仪表盘地址：  http://{args.host}:{args.port}/")
    print(f"  登录密码：    {password}", end="")
    if generated:
        print("  （已自动生成）")
    else:
        print()
    print()
    if generated:
        print("  设置环境变量 TINY_ANALYTICS_PASSWORD 即可自定义密码。")
        print()
    
    import sys
    sys.stdout.flush()

    uvicorn.run("smart_analytics.app:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
