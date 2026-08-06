#!/usr/bin/env bash
#
# 生产环境重启脚本（smart-analytics）
#
# 用法（在项目根目录执行）：
#   ./restart.sh
#   bash restart.sh
#
# 行为：
#   1. 杀掉正在运行的 smart_analytics.cli 进程
#   2. 加载项目根目录的 .env 环境变量
#   3. 用 ./venv/bin/python 后台重新启动服务
#   4. 轮询等待服务就绪并做 HTTP 健康检查
#
set -euo pipefail

# 切到脚本所在目录（项目根）
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

HOST="${SMART_ANALYTICS_HOST:-127.0.0.1}"
PORT="${SMART_ANALYTICS_PORT:-8001}"
VENV_PY="./venv/bin/python"

echo "==> 项目根: $ROOT"
echo "==> 停止旧进程 (smart_analytics.cli)"
pkill -f 'smart_analytics.cli' || true
sleep 1

echo "==> 加载 .env"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "警告: 未找到 .env，继续使用当前环境变量" >&2
fi

if [ ! -x "$VENV_PY" ] && [ ! -f "$VENV_PY" ]; then
  echo "错误: 找不到 venv 解释器 $VENV_PY" >&2
  exit 1
fi

echo "==> 启动服务 (host=$HOST port=$PORT)"
nohup "$VENV_PY" -m smart_analytics.cli --host "$HOST" --port "$PORT" > run.log 2>&1 &

echo "==> 等待服务就绪"
code="000"
for i in $(seq 1 15); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://$HOST:$PORT/" 2>/dev/null || true)
  if [ -n "$code" ] && [ "$code" != "000" ]; then
    break
  fi
  sleep 1
done

echo "HTTP $code ($HOST:$PORT)"
if [ "$code" = "000" ]; then
  echo "!! 服务未能响应，请检查 run.log:" >&2
  echo "   tail -n 30 run.log" >&2
  exit 1
fi

echo "==> 重启完成"
