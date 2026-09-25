#!/usr/bin/env bash
# 日常一键：先保活后端 8010，再按需后台启动前端 3010。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
HOST="127.0.0.1"
FE_PORT="3010"
FE_LOG_DIR="$FRONTEND/logs"
FE_LOG_FILE="$FE_LOG_DIR/next-3010.log"
FE_PID_FILE="$FRONTEND/.next-3010.pid"
FE_URL="http://${HOST}:${FE_PORT}/"
MAX_WAIT_SEC=30

echo "[dev-up] 确保后端…"
bash "$ROOT/scripts/ensure-backend.sh"

is_fe_up() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 --max-time 2 "$FE_URL" 2>/dev/null || true)"
  case "$code" in
    2*|3*) return 0 ;;
    *) return 1 ;;
  esac
}

if is_fe_up; then
  echo "[dev-up] 前端已在运行：${FE_URL}"
  exit 0
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "[dev-up] 警告：未找到 $FRONTEND/node_modules，请先 cd frontend && npm install" >&2
  exit 1
fi

mkdir -p "$FE_LOG_DIR"

echo "[dev-up] 启动前端 npm run dev → ${HOST}:${FE_PORT} …"
(
  cd "$FRONTEND"
  # predev 会再次 ensure-backend（幂等秒过）
  nohup npm run dev >>"$FE_LOG_FILE" 2>&1 &
  echo $! >"$FE_PID_FILE"
)

deadline=$((SECONDS + MAX_WAIT_SEC))
while (( SECONDS < deadline )); do
  if is_fe_up; then
    echo "[dev-up] 前端已就绪：${FE_URL}（PID $(tr -d '[:space:]' <"$FE_PID_FILE" 2>/dev/null || echo '?')）"
    echo "[dev-up] 后端 http://${HOST}:8010/docs · 前端 ${FE_URL}"
    exit 0
  fi
  sleep 0.5
done

echo "[dev-up] 前端启动超时：${MAX_WAIT_SEC}s 内 ${FE_URL} 仍不通" >&2
echo "—— 日志尾部（$FE_LOG_FILE）——" >&2
tail -n 40 "$FE_LOG_FILE" 2>/dev/null || echo "(无日志)" >&2
exit 1
