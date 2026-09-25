"""运行生成的应用：拉起/停止子进程，给前端「一键预览成品」；并提供启动探测与主路径烟测。"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

# run_id -> {"proc": subprocess.Popen, "port": int}
_RUNNING: dict[str, dict] = {}

# 预览运行态落盘，后端重启后仍能恢复追踪/停止（避免孤儿进程占用端口）
PREVIEW_DIR = DATA_ROOT / "preview"


def _state_path(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    return PREVIEW_DIR / f"{safe}.json"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _read_state(run_id: str) -> dict | None:
    try:
        data = json.loads(_state_path(run_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(run_id: str, pid: int, port: int) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(run_id).write_text(json.dumps({"pid": pid, "port": port}), encoding="utf-8")


def _remove_state(run_id: str) -> None:
    try:
        _state_path(run_id).unlink()
    except OSError:
        pass


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, 15)  # SIGTERM
    except OSError:
        return
    for _ in range(30):
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, 9)  # SIGKILL
    except OSError:
        pass


READY_TIMEOUT_S = 8.0
PROBE_PORT_START = 8100
PROBE_PORT_END = 8190


def _code_dir(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    return DATA_ROOT / "code" / safe


def _free_port(start: int = 8000, end: int = 8090) -> int | None:
    for p in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return None


def _child_env() -> dict[str, str]:
    return {
        **os.environ,
        "DEEPSEEK_API_KEY": settings.llm_api_key or "",
        "DEEPSEEK_BASE_URL": settings.llm_base_url,
        "DEEPSEEK_MODEL": settings.llm_model,
    }


def _spawn_uvicorn(code_dir: Path, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(code_dir),
        env=_child_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def prefer_open_url(base_url: str) -> str:
    """浏览器可打开的入口：优先 HTML 首页，其次 FastAPI /docs，否则退回根地址。

    纯 API 成品根路径常为 404 JSON；直接打开 base 会让用户误以为预览坏了。
    """
    base = base_url.rstrip("/")
    candidates = [
        (base + "/", "html"),
        (base + "/docs", "docs"),
        (base + "/redoc", "docs"),
    ]
    for url, kind in candidates:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if not (200 <= resp.status < 300):
                    continue
                ctype = (resp.headers.get("content-type") or "").lower()
                body = resp.read(64)
                if kind == "html":
                    if "text/html" in ctype or body.lstrip().startswith(b"<"):
                        return base
                    continue
                return url
        except Exception:  # noqa: BLE001 — 探测失败则试下一个
            continue
    return base


def wait_http_ready(base_url: str, timeout: float = READY_TIMEOUT_S) -> tuple[bool, str]:
    """等到 OpenAPI 可访问，证明进程已真正起来。"""
    deadline = time.monotonic() + timeout
    last = "尚未响应"
    url = base_url.rstrip("/") + "/openapi.json"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if 200 <= resp.status < 300:
                    return True, "服务已就绪"
        except Exception as exc:  # noqa: BLE001 — 探测阶段吞掉连接拒绝等
            last = str(exc)
        time.sleep(0.15)
    return False, f"启动超时（{timeout:.0f}s）：{last}"


def _try_json(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def http_main_smoke(base_url: str) -> tuple[bool, str, dict | None]:
    """主路径烟测：POST /generate。不要求真 LLM，只要路由可达且非 5xx。返回 (ok, msg, 响应JSON)。"""
    url = base_url.rstrip("/") + "/generate"
    body = json.dumps({"input": "ping"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = _try_json(raw)
            if resp.status >= 500:
                return False, f"主路径返回 {resp.status}: {raw[:200]}", None
            return True, "主路径烟测通过", parsed
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        if exc.code == 404:
            return False, "主路径 /generate 不存在", None
        if exc.code < 500:
            return True, f"主路径可达（HTTP {exc.code}）", None
        return False, f"主路径失败 {exc.code}: {raw[:200]}", None
    except Exception as exc:  # noqa: BLE001
        return False, f"主路径请求失败: {exc}", None


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def probe_runnable(
    run_id: str,
    *,
    ready_timeout: float = READY_TIMEOUT_S,
    require_video: bool = False,
) -> tuple[bool, str]:
    """短暂拉起成品做启动探测 + 主路径烟测，测完必杀进程；不写入长驻 _RUNNING。

    require_video=True 时额外校验 /generate 响应必须带非空 video_url（视频类不得回退纯文案）。
    """
    d = _code_dir(run_id)
    if not (d / "app.py").is_file():
        return False, "app.py 不存在"

    port = _free_port(PROBE_PORT_START, PROBE_PORT_END)
    if port is None:
        return False, "没有可用探测端口（8100-8190）"

    proc = _spawn_uvicorn(d, port)
    base = f"http://127.0.0.1:{port}"
    try:
        if proc.poll() is not None:
            return False, f"进程启动即退出（code={proc.returncode}）"
        ok, msg = wait_http_ready(base, timeout=ready_timeout)
        if not ok:
            return False, msg
        ok2, msg2, body = http_main_smoke(base)
        if not ok2:
            return False, msg2
        if require_video:
            video_url = (body or {}).get("video_url") or ""
            if not video_url:
                return False, "视频类成品未产出可播放视频（/generate 无 video_url 或为空）"
        return True, msg2
    finally:
        _terminate(proc)


def start_app(run_id: str) -> dict:
    """拉起 run 生成的成品（若已在运行则直接返回其地址）；启动后等到 HTTP 就绪。

    运行态除内存 _RUNNING 外也落盘 data/preview/<run_id>.json，
    后端重启后能恢复对预览进程的追踪与停止。
    """
    if run_id in _RUNNING:
        port = _RUNNING[run_id]["port"]
        return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}

    # 重启后恢复：状态文件在且进程还活着，直接复用
    st = _read_state(run_id)
    if st and _pid_alive(int(st.get("pid", 0))) and _port_in_use(int(st.get("port", 0))):
        port = int(st["port"])
        return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}
    _remove_state(run_id)

    d = _code_dir(run_id)
    if not (d / "app.py").is_file():
        raise AppError("app_not_found", "成品代码不存在", 404)

    port = _free_port()
    if port is None:
        raise AppError("no_port", "没有可用端口（8000-8090）", 500)

    proc = _spawn_uvicorn(d, port)
    base = f"http://127.0.0.1:{port}"
    ok, msg = wait_http_ready(base)
    if not ok:
        _terminate(proc)
        raise AppError("start_failed", f"成品启动失败：{msg}", 500)

    _RUNNING[run_id] = {"proc": proc, "port": port}
    _write_state(run_id, proc.pid, port)
    return {"running": True, "url": prefer_open_url(base), "port": port}


def stop_app(run_id: str) -> bool:
    item = _RUNNING.pop(run_id, None)
    if item is not None:
        _terminate(item["proc"])
        _remove_state(run_id)
        return True
    # 重启后 _RUNNING 为空，但状态文件还在：按 pid 杀掉残留进程
    st = _read_state(run_id)
    if st and _pid_alive(int(st.get("pid", 0))):
        _kill_pid(int(st["pid"]))
        _remove_state(run_id)
        return True
    _remove_state(run_id)
    return False


def app_status(run_id: str) -> dict:
    if run_id in _RUNNING:
        port = _RUNNING[run_id]["port"]
        return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}
    st = _read_state(run_id)
    if st and _pid_alive(int(st.get("pid", 0))) and _port_in_use(int(st.get("port", 0))):
        port = int(st["port"])
        return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}
    return {"running": False, "url": None, "port": None}
