#!/usr/bin/env bash
#
# smart-analytics 生产部署脚本（Linux）
# ===========================================================================
# 设计原则：对 HabitHero 零侵入。
#   - 独立系统用户        smartanalytics
#   - 独立虚拟环境        /opt/smart-analytics/venv
#   - 独立数据库          /opt/smart-analytics/data/smart_analytics.db
#   - 独立 systemd 单元    smart-analytics.service
#   - 独立 nginx server 块（新增文件，不改动 HabitHero 配置）
#   - 独立端口            8001（HabitHero 用 9999，互不冲突）
# 本脚本不会读取、修改、停止 HabitHero 的任何文件或进程。
# ===========================================================================
set -euo pipefail

PROJECT_DIR="${1:-/opt/smart-analytics}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="smartanalytics"
PORT=8001
DATA_DIR="$PROJECT_DIR/data"

echo "==> smart-analytics 部署到 $PROJECT_DIR (端口 $PORT)"

# 0) 应用代码应已就位（git clone 或复制整个仓库到 PROJECT_DIR）
if [ ! -d "$PROJECT_DIR/src/smart_analytics" ]; then
  echo "错误：未在 $PROJECT_DIR/src/smart_analytics 找到应用代码。" >&2
  echo "请先将 smart-analytics 仓库放置/克隆到 $PROJECT_DIR，再运行本脚本。" >&2
  exit 1
fi

# 1) 专用系统用户（无登录、无家目录）
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "已创建系统用户 $SERVICE_USER"
fi

# 2) 数据目录
mkdir -p "$DATA_DIR"

# 3) 虚拟环境 + 依赖（隔离在专属 venv，不污染系统/其他项目）
python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install --quiet --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install --quiet -e "$PROJECT_DIR"

# 4) .env（仅首次生成，含【固定】SECRET_KEY，这是生产必需项）
if [ ! -f "$PROJECT_DIR/.env" ]; then
  SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  ADMIN_PW="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  cat > "$PROJECT_DIR/.env" <<EOF
SMART_ANALYTICS_SECRET_KEY=$SECRET
SMART_ANALYTICS_PASSWORD=$ADMIN_PW
SMART_ANALYTICS_ADMIN_EMAIL=admin@localhost
SMART_ANALYTICS_PORT=$PORT
SMART_ANALYTICS_DB_PATH=$DATA_DIR/smart_analytics.db
SMART_ANALYTICS_OPEN_REGISTER=false
EOF
  chmod 600 "$PROJECT_DIR/.env"          # 仅 root 可读，systemd 以 root 读取后注入进程
  chown root:root "$PROJECT_DIR/.env"
  echo "已生成 $PROJECT_DIR/.env（root:root, 600）"
  echo "  ⚠ 管理员初始密码（请妥善保存，页面不可再修改）： $ADMIN_PW"
else
  echo "已存在 .env，跳过生成（保留原有密钥与密码）"
fi

# 5) systemd 单元
install -m 0644 "$SCRIPT_DIR/smart-analytics.service" /etc/systemd/system/smart-analytics.service
systemctl daemon-reload
systemctl enable --now smart-analytics.service
echo "smart-analytics.service 已启用并启动"

# 6) nginx 配置（新增文件，不改动 HabitHero）
if command -v nginx >/dev/null 2>&1; then
  install -m 0644 "$SCRIPT_DIR/nginx-smart-analytics.conf" /etc/nginx/conf.d/smart-analytics.conf
  echo "已写入 /etc/nginx/conf.d/smart-analytics.conf"
  echo "请编辑其中的 server_name，然后执行："
  echo "  sudo nginx -t && sudo systemctl reload nginx"
else
  echo "未检测到 nginx，跳过。请参考 DEPLOY.md 手动配置反向代理。"
fi

# 7) 数据目录归属服务用户
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"

echo
echo "✅ 部署完成。"
echo "  - 应用监听 127.0.0.1:$PORT（systemd 托管，崩溃自动重启）"
echo "  - 数据库：$DATA_DIR/smart_analytics.db"
echo "  - 运行日志：journalctl -u smart-analytics.service -f"
echo "  - 访问前请配置 nginx 反代，并建议用 certbot 申请 HTTPS。"
