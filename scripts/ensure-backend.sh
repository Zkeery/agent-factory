#!/usr/bin/env bash
# 幂等保活：确保 Agent造物坊后端在 127.0.0.1:8010 可用（脱离终端）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
HOST="127.0.0.1"
PORT="8010"
PID_FILE="$BACKEND/.uvicorn-8010.pid"
LOG_DIR="$BACKEND/logs"
LOG_FILE="$LOG_DIR/uvicorn-8010.log"
PYTHON="$BACKEND/.venv/bin/python"
HEALTH_URL="http://${HOST}:${PORT}/docs"
MAX_WAIT_SEC=20

is_healthy() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 --max-time 2 "$HEALTH_URL" 2>/dev/null || true)"
  case "$code" in
    2*|3*) return 0 ;;
    *) return 1 ;;
  esac
}

clear_stale_pid() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 0
  fi
  local old_pid
  old_pid="$(tr -d '[:space:]' <"$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    if ! is_healthy; then
      echo "[ensure-backend] PID $old_pid 仍在但 ${PORT} 不通，清理僵死进程…"
      kill "$old_pid" 2>/dev/null || true
      sleep 0.5
      kill -9 "$old_pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE"
}

if is_healthy; then
  echo "[ensure-backend] 后端已在运行：${HEALTH_URL}"
  exit 0
fi

clear_stale_pid

if [[ ! -x "$PYTHON" ]]; then
  echo "[ensure-backend] 错误：找不到 $PYTHON" >&2
  echo "请先创建虚拟环境：" >&2
  echo "  cd \"$BACKEND\" && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

echo "[ensure-backend] 启动 uvicorn → ${HOST}:${PORT} …"
(
  cd "$BACKEND"
  # --reload-dir app：只监听源码，排除 data/（否则流水线生成 data/code/.../app.py
  # 会触发重载，杀掉后台推进线程与 SSE 连接）；nohup 脱离终端，日志落盘
  nohup "$PYTHON" -m uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --reload \
    --reload-dir app \
    --timeout-graceful-shutdown 1 \
    >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
)

deadline=$((SECONDS + MAX_WAIT_SEC))
while (( SECONDS < deadline )); do
  if is_healthy; then
    echo "[ensure-backend] 启动成功：${HEALTH_URL}（PID $(tr -d '[:space:]' <"$PID_FILE" 2>/dev/null || echo '?')）"
    exit 0
  fi
  sleep 0.5
done

echo "[ensure-backend] 启动失败：${MAX_WAIT_SEC}s 内 ${HEALTH_URL} 仍不通" >&2
echo "—— 日志尾部（$LOG_FILE）——" >&2
tail -n 40 "$LOG_FILE" 2>/dev/null || echo "(无日志)" >&2
exit 1
