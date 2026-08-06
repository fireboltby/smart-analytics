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
        default=os.environ.get("SMART_ANALYTICS_HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SMART_ANALYTICS_PORT", "8000")),
        help="Port to listen on (default: 8000)",
    )
    args = parser.parse_args()

    # Generate secret key if not set
    if not os.environ.get("SMART_ANALYTICS_SECRET_KEY"):
        os.environ["SMART_ANALYTICS_SECRET_KEY"] = secrets.token_hex(32)

    env_pw = os.environ.get("SMART_ANALYTICS_PASSWORD")

    # Startup banner（中文）
    print("\n  ╭─────────────────────────────────────────╮")
    print("  │           smart-analytics                │")
    print("  ╰─────────────────────────────────────────╯")
    print()
    print(f"  仪表盘地址：  http://{args.host}:{args.port}/")
    if env_pw:
        print("  管理员密码：  由环境变量 SMART_ANALYTICS_PASSWORD 提供")
        print("                首次启动会据此自动创建管理员账户。")
    else:
        print("  首次使用：    请访问 /register 注册首个管理员账户")
        print("                （注册者自动成为默认站点 owner）")
    print()
    
    import sys
    sys.stdout.flush()

    uvicorn.run("smart_analytics.app:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
