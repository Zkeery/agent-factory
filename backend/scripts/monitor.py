#!/usr/bin/env python3
"""Agent造物坊 左侧终端（8010 后端）看门狗。

检查项：后端 HTTP 可达、后端日志新增错误、卡死/失败运行、蓝图 plan/audit 卡死。
发现异常追加到 .runtime/monitor.log；同一问题 10 分钟内不重复告警。
"""
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # projects/Agent造物坊
RT = ROOT / ".runtime"
MONITOR_LOG = RT / "monitor.log"
DEFAULT_LOG = RT / "backend.log"
DB = ROOT / "backend" / "data" / "factory.db"
STATE = RT / "monitor.state"                        # JSON: {"path": ..., "offset": ...}
PID_FILE = RT / "monitor.pid"
INTERVAL = 30                                       # 秒
DEDUP_SECONDS = 600                                 # 同一告警 10 分钟内不重复

ALERT_PATTERNS = (
    "模型调用失败",
    "llm_call_failed",
    "Traceback",
    "llm_output_invalid",
    "internal_error",
)


def http_ok() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8010/", timeout=6) as r:
            return r.status == 200
    except Exception:
        return False


def _find_backend_log() -> Path:
    """自动定位 8010 后端进程实际写入的日志文件（其 stdout 指向的文件）。"""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "uvicorn app.main:app --port 8010"], text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return DEFAULT_LOG
    for pid in [p for p in out.split() if p.strip()]:
        try:
            fd = subprocess.check_output(["lsof", "-p", pid], text=True)
        except subprocess.CalledProcessError:
            continue
        for line in fd.splitlines():
            parts = line.split()
            # lsof 列：COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
            if len(parts) >= 5 and parts[3] == "1w":
                cand = Path(parts[-1])
                if cand.exists():
                    return cand
    return DEFAULT_LOG


def _load_state() -> tuple[Path, int]:
    try:
        raw = json.loads(STATE.read_text() or "0")
    except Exception:
        raw = 0
    if isinstance(raw, dict):
        return Path(raw.get("path") or DEFAULT_LOG), int(raw.get("offset") or 0)
    return DEFAULT_LOG, int(raw) if str(raw).lstrip("-").isdigit() else 0


def _save_state(path: Path, offset: int) -> None:
    STATE.write_text(json.dumps({"path": str(path), "offset": offset}))


def new_log_errors() -> list[str]:
    log = _find_backend_log()
    if not log.exists():
        return []
    old_path, offset = _load_state()
    size = log.stat().st_size
    if old_path != log:
        offset = size                              # 换了日志文件：从当前位置开始，不回放旧错误
    offset = min(offset, size)
    with open(log, encoding="utf-8", errors="ignore") as f:
        f.seek(offset)
        text = f.read()
        new_offset = f.tell()
    _save_state(log, new_offset)
    if not text:
        return []
    return [l.strip() for l in text.splitlines() if any(p in l for p in ALERT_PATTERNS)]


def stuck_runs(minutes: int = 8) -> list[str]:
    if not DB.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cur = con.execute(
            "SELECT id, current_stage, created_at FROM factory_runs "
            "WHERE status='running' AND current_stage NOT IN ('awaiting_answers','awaiting_prd_confirm') "
            "AND created_at < datetime('now', ?)",
            (f"-{minutes} minutes",),
        )
        rows = cur.fetchall()
        con.close()
        return [f"卡死运行 {r[0][:8]}… 停在 {r[1]}（{r[2]}）" for r in rows]
    except Exception:
        return []


def recent_failed(minutes: int = 60) -> list[str]:
    if not DB.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cur = con.execute(
            "SELECT id, created_at FROM factory_runs WHERE current_stage='failed' "
            "AND created_at > datetime('now', ?)",
            (f"-{minutes} minutes",),
        )
        rows = cur.fetchall()
        con.close()
        return [f"失败运行 {r[0][:8]}…（{r[1]}）" for r in rows]
    except Exception:
        return []


def _parse_etime(etime: str) -> int:
    """把 ps 的 etime（MM:SS / HH:MM:SS / D-HH:MM:SS）转成秒。"""
    etime = etime.strip()
    if "-" in etime:
        days_str, t = etime.split("-", 1)
        d = int(days_str) if days_str.isdigit() else 0
    else:
        d, t = 0, etime
    parts = t.split(":")
    if len(parts) == 2:
        h, m, s = 0, int(parts[0]), int(parts[1])
    elif len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    else:
        return 0
    return d * 86400 + h * 3600 + m * 60 + s


def blueprint_stuck(minutes: int = 5) -> str | None:
    """检测正在跑且长时间未结束的 blueprint plan/audit 进程（疑似 LLM 超时卡住）。"""
    try:
        out = subprocess.check_output(["pgrep", "-f", "blueprint.py"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    pids = [p for p in out.split() if p.strip()]
    max_secs, max_etime = 0, ""
    for pid in pids:
        try:
            etime = subprocess.check_output(["ps", "-o", "etime=", "-p", pid], text=True).strip()
        except subprocess.CalledProcessError:
            continue
        secs = _parse_etime(etime)
        if secs > max_secs:
            max_secs, max_etime = secs, etime
    if max_secs >= minutes * 60:
        return f"蓝图 plan/audit 疑似卡住：已运行 {max_etime}（> {minutes} 分钟）"
    return None


_ALERTED: dict[str, float] = {}


def alert(msg: str, key: str | None = None) -> None:
    """带 10 分钟去重地写告警；key 相同则在窗口内只写一次。"""
    now = time.time()
    k = key or msg
    if k in _ALERTED and now - _ALERTED[k] < DEDUP_SECONDS:
        return
    _ALERTED[k] = now
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with open(MONITOR_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def cycle() -> None:
    if not http_ok():
        alert("后端不可达（HTTP 检查失败，进程可能已挂）", key="backend_down")
    for e in new_log_errors():
        alert("日志错误：" + e[:160], key="log:" + e[:80])
    for s in stuck_runs():
        alert(s, key="stuck:" + s[:40])
    for s in recent_failed():
        alert(s, key="failed:" + s[:40])
    b = blueprint_stuck()
    if b:
        alert(b, key="blueprint_stuck")


def main() -> None:
    RT.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    # 首次把已存在的旧日志标为已读，避免把历史错误重复报警
    if not STATE.exists():
        log = _find_backend_log()
        _save_state(log, log.stat().st_size if log.exists() else 0)
    with open(MONITOR_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 看门狗启动，每 {INTERVAL}s 检查一次（自动定位日志 + 10min 去重）\n")
    while True:
        try:
            cycle()
        except Exception:
            pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
