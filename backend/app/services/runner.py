"""运行生成的应用：拉起/停止子进程，给前端「一键预览成品」；并提供启动探测与主路径烟测。"""
from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import threading
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


def _proc_state(pid: int) -> str | None:
    """进程状态。Z/X 表示已退出但尚未被父进程回收，不能再当成正在提供服务。"""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    marker = stat.rfind(")")
    if marker < 0 or marker + 2 >= len(stat):
        return None
    return stat[marker + 2]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    state = _proc_state(pid)
    if state is None or state in {"Z", "X"}:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _group_has_running_member(pgid: int) -> bool:
    """进程组里是否还有未退出的成员。组长已成僵尸时，killpg(0) 仍会成功，不能用来判断。"""
    if pgid <= 0:
        return False
    leader = _proc_state(pgid)
    if leader not in {None, "Z", "X"}:
        return True
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == pgid:
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
        except OSError:
            continue
        marker = raw.rfind(")")
        fields = raw[marker + 2:].split()
        if len(fields) >= 3 and fields[2] == str(pgid) and fields[0] not in {"Z", "X"}:
            return True
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


def _write_state(run_id: str, pid: int, port: int, pgid: int | None = None) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"pid": pid, "port": port}
    if pgid:
        payload["pgid"] = pgid
    _state_path(run_id).write_text(json.dumps(payload), encoding="utf-8")


def _remove_state(run_id: str) -> None:
    try:
        _state_path(run_id).unlink()
    except OSError:
        pass


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(30):
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _kill_group(pgid: int) -> None:
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        _kill_pid(pgid)
        return
    for _ in range(30):
        if not _group_has_running_member(pgid):
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


READY_TIMEOUT_S = 8.0
# 旧检查固定扫描 8100–8190，绑定后立刻释放，再由子进程重新绑定。
# 并行检查会同时看中同一端口；就绪判断又不核对监听进程，可能把别的应用的成功响应当成自己的。
PROBE_PORT_START = 8100
PROBE_PORT_END = 8190
DEFAULT_SMOKE_INPUT = "按主路径完成一次默认处理"
SMOKE_INPUT_LIMIT = 240
_PROCESS_LOCK = threading.Lock()
_ACTIVE_CHILDREN: set[int] = set()


def _code_dir(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    return DATA_ROOT / "code" / safe


def _free_port(start: int = 8000, end: int = 8090) -> int | None:
    """保留给仍按端口段探测的调用。新的检查和预览改用系统分配并持有套接字。"""
    for p in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return None


def _bind_loopback() -> socket.socket:
    """绑定 127.0.0.1 上由系统分配的空闲端口，并一直持有到子进程继承。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        sock.set_inheritable(True)
    except OSError:
        sock.close()
        raise
    return sock


def _child_env() -> dict[str, str]:
    # 成品需要已约定的模型配置，但不继承后端数据库、登录及其他服务密钥。
    return {
        **{key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SSL_CERT_FILE") if key in os.environ},
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "DEEPSEEK_API_KEY": settings.llm_api_key or "",
        "DEEPSEEK_BASE_URL": settings.llm_base_url,
        "DEEPSEEK_MODEL": settings.llm_model,
    }


def _spawn_uvicorn(code_dir: Path, sock: socket.socket) -> subprocess.Popen:
    """把已经监听的套接字交给子进程。父进程随后关闭自己的副本。"""
    fd = sock.fileno()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--fd", str(fd)],
        cwd=str(code_dir),
        env=_child_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(fd,),
        start_new_session=True,
    )
    with _PROCESS_LOCK:
        _ACTIVE_CHILDREN.add(proc.pid)
    return proc


def _forget_child(pid: int) -> None:
    with _PROCESS_LOCK:
        _ACTIVE_CHILDREN.discard(pid)


def _terminate(proc: subprocess.Popen) -> None:
    _forget_child(proc.pid)
    if proc.poll() is not None:
        return
    _kill_group(proc.pid)
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _atexit_reap() -> None:
    with _PROCESS_LOCK:
        pids = list(_ACTIVE_CHILDREN)
    for pid in pids:
        _kill_group(pid)
        _forget_child(pid)


atexit.register(_atexit_reap)


def _proc_cwd(pid: int) -> Path | None:
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        return None


def _under_code_root(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        root = (DATA_ROOT / "code").resolve()
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def _listen_inodes(port: int) -> set[str]:
    hex_port = f"{port:04X}"
    inodes: set[str] = set()
    try:
        lines = Path("/proc/net/tcp").read_text(encoding="utf-8").splitlines()
    except OSError:
        return inodes
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 10:
            continue
        local, state, inode = parts[1], parts[3], parts[9]
        if state != "0A" or ":" not in local:
            continue
        _ip, port_hex = local.split(":", 1)
        if port_hex.upper() != hex_port:
            continue
        inodes.add(inode)
    return inodes


def _process_has_socket(pid: int, inodes: set[str]) -> bool:
    if pid <= 0 or not inodes:
        return False
    fd_dir = Path(f"/proc/{pid}/fd")
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return False
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]") and target[8:-1] in inodes:
            return True
    return False


def _descendant_pids(pid: int) -> list[int]:
    try:
        text = Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="utf-8")
    except OSError:
        return []
    found: list[int] = []
    for item in text.split():
        if item.isdigit():
            child = int(item)
            found.append(child)
            found.extend(_descendant_pids(child))
    return found


def _process_owns_listen(pid: int, port: int) -> bool:
    """监听该端口的套接字必须属于本次启动的进程或其子进程。"""
    inodes = _listen_inodes(port)
    if not inodes or pid <= 0:
        return False
    if _process_has_socket(pid, inodes):
        return True
    return any(_process_has_socket(child, inodes) for child in _descendant_pids(pid))


def _wait_owns_listen(pid: int, port: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if not _pid_alive(pid):
            return False
        if _process_owns_listen(pid, port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _probe_record_path(pid: int) -> Path:
    return PREVIEW_DIR / f"probe-{pid}.json"


def _write_probe_record(pid: int, port: int) -> None:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": pid, "pgid": pid, "port": port, "kind": "probe"})
    with _PROCESS_LOCK:
        _probe_record_path(pid).write_text(payload, encoding="utf-8")


def _remove_probe_record(pid: int) -> None:
    try:
        _probe_record_path(pid).unlink()
    except OSError:
        pass


def reap_orphan_probes() -> None:
    """回收上次检查没能在退出时杀掉的子进程。不碰仍在本次进程里跟踪的检查，也不碰工作目录不在本项目代码目录的进程。"""
    if not PREVIEW_DIR.is_dir():
        return
    with _PROCESS_LOCK:
        active = set(_ACTIVE_CHILDREN)
        paths = list(PREVIEW_DIR.glob("probe-*.json"))
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
            continue
        if not isinstance(data, dict):
            path.unlink(missing_ok=True)
            continue
        pid = int(data.get("pid") or 0)
        pgid = int(data.get("pgid") or pid)
        if pid in active:
            continue
        if _pid_alive(pid) and _under_code_root(_proc_cwd(pid)):
            _kill_group(pgid or pid)
        path.unlink(missing_ok=True)


def _clip_smoke_input(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= SMOKE_INPUT_LIMIT:
        return compact
    return compact[:SMOKE_INPUT_LIMIT]


def _first_useful_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("#").strip("*- ").strip()
        if len(stripped) < 4 or stripped in {"待定", "无", "暂无"}:
            continue
        return stripped
    return ""


def main_smoke_body(
    *,
    idea: str = "",
    prd: dict | None = None,
    scenarios: list | None = None,
) -> dict:
    """主路径烟测请求体。优先用主流程场景的 input，其次需求里的主路径说明。"""
    from app.services.iteration import main_flow_scenario

    main = main_flow_scenario(list(scenarios or []))
    if main:
        text = _clip_smoke_input(str(main.get("input") or ""))
        if text:
            return {"input": text}
    fields = prd or {}
    for key in ("main_loop", "input_process_output", "goal_users"):
        text = _clip_smoke_input(_first_useful_line(str(fields.get(key) or "")))
        if text:
            return {"input": text}
    text = _clip_smoke_input(_first_useful_line(idea or ""))
    return {"input": text or DEFAULT_SMOKE_INPUT}


def smoke_contract_note(body: dict) -> str:
    sent = json.dumps(body, ensure_ascii=False)
    return (
        "自动检查会 POST /generate，Content-Type 为 application/json，请求体为 "
        f"{sent}。该请求必须返回 HTTP 2xx 和 JSON。"
        "不要用 4xx 要求检查再传这个请求体里没有的字段。"
        "若业务必须先选择功能，请求没带该字段时按主路径默认选项继续，并在结果里写明所用默认。"
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


def _response_hint(raw: str) -> str:
    parsed = _try_json(raw)
    if not isinstance(parsed, dict):
        return " ".join((raw or "").split())[:180]
    detail = parsed.get("detail", parsed.get("message", parsed.get("error")))
    if isinstance(detail, str) and detail.strip():
        return " ".join(detail.split())[:180]
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict) and item.get("msg"):
                parts.append(str(item["msg"]))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return " ".join(" ".join(parts).split())[:180]
    return " ".join(raw.split())[:180]


def _http_failure_message(status: int, sent: dict, raw: str) -> str:
    if status == 404:
        return "主路径 /generate 不存在"
    hint = _response_hint(raw)
    sent_text = json.dumps(sent, ensure_ascii=False)
    if 400 <= status < 500 and hint:
        return (
            f"主路径失败 {status}: 检查请求 POST /generate，请求体 {sent_text}。"
            f"应用返回：{hint}。"
            "改法：让这个请求体直接走完主路径并返回 HTTP 2xx 的 JSON；"
            "不要再要求检查补传请求体里没有的字段。"
            "若必须先选择功能，缺省时按该请求采用默认选项，并在结果里写明。"
        )
    return f"主路径失败 {status}: 检查请求 POST /generate，请求体 {sent_text}。应用返回：{hint}"


def http_main_smoke(base_url: str, body: dict | None = None) -> tuple[bool, str, dict | None]:
    """主路径烟测：POST /generate 必须对本次请求体返回 2xx。业务效果仍由真实任务验收。"""
    sent = body if isinstance(body, dict) else main_smoke_body()
    url = base_url.rstrip("/") + "/generate"
    req = urllib.request.Request(
        url,
        data=json.dumps(sent, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = _try_json(raw)
            if not 200 <= resp.status < 300:
                return False, _http_failure_message(resp.status, sent, raw), None
            return True, "主路径烟测通过", parsed
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        return False, _http_failure_message(exc.code, sent, raw), None
    except Exception as exc:  # noqa: BLE001
        return False, f"主路径请求失败: {exc}", None


def _launch(code_dir: Path) -> tuple[subprocess.Popen, int]:
    sock = _bind_loopback()
    port = int(sock.getsockname()[1])
    try:
        proc = _spawn_uvicorn(code_dir, sock)
    except Exception:
        sock.close()
        raise
    else:
        sock.close()
    return proc, port


def _confirm_ours(proc: subprocess.Popen, port: int) -> str | None:
    if proc.poll() is not None:
        return f"检查进程已退出（code={proc.returncode}），不能把同一端口上的其他服务当成本次结果"
    if not _wait_owns_listen(proc.pid, port):
        return "端口上的服务不是本次启动的检查进程，结果作废"
    return None


def probe_runnable(
    run_id: str,
    *,
    ready_timeout: float = READY_TIMEOUT_S,
    require_video: bool = False,
    smoke_body: dict | None = None,
) -> tuple[bool, str]:
    """短暂拉起成品做启动探测 + 主路径烟测，测完必杀进程；不写入长驻 _RUNNING。

    端口由系统分配，套接字在子进程继承前一直由本次检查持有。
    请求发出前确认监听者是本次进程。require_video=True 时还要求响应带非空 video_url。
    """
    d = _code_dir(run_id)
    if not (d / "app.py").is_file():
        return False, "app.py 不存在"

    reap_orphan_probes()
    try:
        proc, port = _launch(d)
    except OSError as exc:
        return False, f"没有可用的本机端口: {exc}"
    _write_probe_record(proc.pid, port)
    base = f"http://127.0.0.1:{port}"
    sent = smoke_body if isinstance(smoke_body, dict) else main_smoke_body()
    try:
        if proc.poll() is not None:
            return False, f"进程启动即退出（code={proc.returncode}）"
        ok, msg = wait_http_ready(base, timeout=ready_timeout)
        if not ok:
            return False, msg
        foreign = _confirm_ours(proc, port)
        if foreign:
            return False, foreign
        ok2, msg2, body = http_main_smoke(base, sent)
        foreign = _confirm_ours(proc, port)
        if foreign:
            return False, foreign
        if not ok2:
            return False, msg2
        if require_video:
            video_url = (body or {}).get("video_url") or ""
            if not video_url:
                return False, "视频类成品未产出可播放视频（/generate 无 video_url 或为空）"
        return True, msg2
    finally:
        _remove_probe_record(proc.pid)
        _terminate(proc)


def _recorded_preview(run_id: str) -> dict | None:
    """只读：状态文件里的进程仍在，且确实监听记录中的端口。"""
    st = _read_state(run_id)
    if not st:
        return None
    pid = int(st.get("pid") or 0)
    port = int(st.get("port") or 0)
    if _pid_alive(pid) and port > 0 and _process_owns_listen(pid, port):
        return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}
    return None


def _drop_stale_preview(run_id: str) -> None:
    st = _read_state(run_id)
    if not st:
        return
    pid = int(st.get("pid") or 0)
    port = int(st.get("port") or 0)
    if _pid_alive(pid) and _under_code_root(_proc_cwd(pid)) and not _process_owns_listen(pid, port):
        _kill_group(int(st.get("pgid") or pid))
    _remove_state(run_id)


def start_app(run_id: str) -> dict:
    """拉起 run 生成的成品（若已在运行则直接返回其地址）；启动后等到 HTTP 就绪。

    运行态除内存 _RUNNING 外也落盘 data/preview/<run_id>.json，
    后端重启后能恢复对预览进程的追踪与停止。端口由系统分配。
    """
    reap_orphan_probes()
    if run_id in _RUNNING:
        port = _RUNNING[run_id]["port"]
        proc = _RUNNING[run_id]["proc"]
        if proc.poll() is None and _process_owns_listen(proc.pid, port):
            return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}
        _terminate(proc)
        _RUNNING.pop(run_id, None)
        _remove_state(run_id)

    recorded = _recorded_preview(run_id)
    if recorded:
        return recorded
    _drop_stale_preview(run_id)

    d = _code_dir(run_id)
    if not (d / "app.py").is_file():
        raise AppError("app_not_found", "成品代码不存在", 404)

    try:
        proc, port = _launch(d)
    except OSError as exc:
        raise AppError("no_port", f"没有可用的本机端口: {exc}", 500) from exc
    base = f"http://127.0.0.1:{port}"
    ok, msg = wait_http_ready(base)
    foreign = _confirm_ours(proc, port) if ok else None
    if not ok or foreign:
        _terminate(proc)
        raise AppError("start_failed", f"成品启动失败：{foreign or msg}", 500)

    _RUNNING[run_id] = {"proc": proc, "port": port}
    _write_state(run_id, proc.pid, port, pgid=proc.pid)
    return {"running": True, "url": prefer_open_url(base), "port": port}


def stop_app(run_id: str) -> bool:
    item = _RUNNING.pop(run_id, None)
    if item is not None:
        _terminate(item["proc"])
        _remove_state(run_id)
        return True
    # 重启后 _RUNNING 为空，但状态文件还在：按进程组杀掉残留进程
    st = _read_state(run_id)
    if st and _pid_alive(int(st.get("pid", 0))):
        pid = int(st["pid"])
        port = int(st.get("port") or 0)
        if _under_code_root(_proc_cwd(pid)) or _process_owns_listen(pid, port):
            _kill_group(int(st.get("pgid") or pid))
        _remove_state(run_id)
        return True
    _remove_state(run_id)
    return False


def app_status(run_id: str) -> dict:
    if run_id in _RUNNING:
        port = _RUNNING[run_id]["port"]
        proc = _RUNNING[run_id]["proc"]
        if proc.poll() is None and _process_owns_listen(proc.pid, port):
            return {"running": True, "url": prefer_open_url(f"http://127.0.0.1:{port}"), "port": port}
    recorded = _recorded_preview(run_id)
    if recorded:
        return recorded
    return {"running": False, "url": None, "port": None}
