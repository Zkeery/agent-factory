"""检查和预览使用系统分配端口，并在结束后回收子进程。"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import runner, testing

CHOICE_APP = '''from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    input: str = ""

@app.get("/")
def home():
    return {"ready": True}

@app.post("/generate")
def generate(req: Req):
    if "塔罗" not in req.input and "星座" not in req.input:
        raise HTTPException(status_code=400, detail="请先选择塔罗抽牌或星座运势")
    return {"result": req.input}
'''

MARKED_APP = '''from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Req(BaseModel):
    input: str = ""

@app.post("/generate")
def generate(req: Req):
    return {"result": "MARKER", "echo": req.input}
'''


def _write(root: Path, run_id: str, source: str) -> None:
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "app.py").write_text(source, encoding="utf-8")
    (directory / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")


def test_kill_group_returns_once_leader_is_zombie():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        os.kill(proc.pid, signal.SIGTERM)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = runner._proc_state(proc.pid)
            if state in {"Z", "X", None}:
                break
            time.sleep(0.02)
        started = time.monotonic()
        runner._kill_group(proc.pid)
        assert time.monotonic() - started < 1.0
        assert proc.wait(timeout=1) is not None
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait(timeout=1)


def test_bound_socket_stays_occupied_until_closed():
    sock = runner._bind_loopback()
    port = sock.getsockname()[1]
    try:
        other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            try:
                other.bind(("127.0.0.1", port))
                bound = True
            except OSError:
                bound = False
            assert bound is False
        finally:
            other.close()
    finally:
        sock.close()


def test_choice_app_passes_when_smoke_body_matches_main_flow(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(testing, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "PREVIEW_DIR", root / "preview")
    _write(root / "code", "tarot", CHOICE_APP)
    ok, message = testing.run_tests(
        "tarot",
        idea="算命",
        prd={"main_loop": "塔罗或星座"},
        scenarios=[{"id": "main-flow", "title": "主流程", "input": "选择塔罗抽牌，问今天运势", "expected_output": "一张牌"}],
    )
    assert ok, message
    assert not list((root / "preview").glob("probe-*.json"))


def test_choice_app_400_names_request_and_fix(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(testing, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "PREVIEW_DIR", root / "preview")
    _write(root / "code", "reject", CHOICE_APP)
    ok, message = testing.run_tests("reject", idea="随便写一句不够具体的需求")
    assert ok is False
    assert "POST /generate" in message
    assert "请先选择塔罗抽牌或星座运势" in message
    assert "改法" in message
    assert "ping" not in message
    assert not list((root / "preview").glob("probe-*.json"))


def test_probe_rejects_response_from_other_process(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "PREVIEW_DIR", root / "preview")
    _write(root / "code", "owned", MARKED_APP.replace("MARKER", "owned"))
    monkeypatch.setattr(runner, "_process_owns_listen", lambda pid, port: False)
    ok, message = runner.probe_runnable("owned", smoke_body={"input": "塔罗"})
    assert ok is False
    assert "本次" in message


def test_parallel_probes_do_not_share_results(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "PREVIEW_DIR", root / "preview")
    seen: dict[str, dict] = {}
    original = runner.http_main_smoke

    def capture(base, body=None):
        ok, message, payload = original(base, body)
        seen[base] = payload or {}
        return ok, message, payload

    monkeypatch.setattr(runner, "http_main_smoke", capture)
    ids = []
    for index in range(4):
        run_id = f"mark-{index}"
        ids.append(run_id)
        _write(root / "code", run_id, MARKED_APP.replace("MARKER", run_id))

    def once(run_id: str):
        return run_id, runner.probe_runnable(run_id, smoke_body={"input": run_id})

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(once, ids))
    assert all(ok for _, (ok, _message) in results), results
    payloads = list(seen.values())
    assert {item.get("result") for item in payloads} == set(ids)
    assert not list((root / "preview").glob("probe-*.json"))


def test_reap_kills_recorded_probe_and_skips_unrelated(monkeypatch, tmp_path: Path):
    code_root = tmp_path / "data" / "code" / "old-run"
    code_root.mkdir(parents=True)
    monkeypatch.setattr(runner, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(runner, "PREVIEW_DIR", tmp_path / "data" / "preview")
    orphan = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=str(code_root),
        start_new_session=True,
    )
    outsider = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=str(tmp_path),
        start_new_session=True,
    )
    try:
        runner._write_probe_record(orphan.pid, 1)
        runner.PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        (runner.PREVIEW_DIR / f"probe-{outsider.pid}.json").write_text(
            '{"pid": %d, "pgid": %d, "port": 1, "kind": "probe"}' % (outsider.pid, outsider.pid),
            encoding="utf-8",
        )
        runner.reap_orphan_probes()
        orphan.wait(timeout=3)
        assert orphan.returncode is not None
        assert outsider.poll() is None
    finally:
        if outsider.poll() is None:
            os.killpg(outsider.pid, 15)
            outsider.wait(timeout=3)


def test_stop_app_reaps_preview_process_group(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "PREVIEW_DIR", root / "preview")
    _write(root / "code", "preview-run", MARKED_APP)
    started = runner.start_app("preview-run")
    proc = runner._RUNNING["preview-run"]["proc"]
    assert runner._process_owns_listen(proc.pid, started["port"])
    pid = proc.pid
    try:
        assert runner.stop_app("preview-run") is True
    finally:
        if runner._pid_alive(pid):
            runner._kill_group(pid)
    assert "preview-run" not in runner._RUNNING
    assert runner._read_state("preview-run") is None
    assert runner._pid_alive(pid) is False


def _hide_procfs(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_procfs_usable", lambda: False)


def test_pid_cwd_and_group_without_procfs(monkeypatch):
    _hide_procfs(monkeypatch)
    assert runner._pid_alive(os.getpid()) is True
    assert runner._pid_alive(0) is False
    assert runner._pid_alive(99999999) is False
    cwd = runner._proc_cwd(os.getpid())
    assert cwd is not None and cwd.is_dir()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert runner._pid_alive(proc.pid) is True
        assert runner._group_has_running_member(proc.pid) is True
        assert runner._proc_cwd(proc.pid) is not None
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait(timeout=2)
    assert runner._pid_alive(proc.pid) is False
    assert runner._group_has_running_member(proc.pid) is False


def test_unknown_listen_owner_does_not_reject_live_process(monkeypatch):
    _hide_procfs(monkeypatch)
    monkeypatch.setattr(runner, "_process_owns_listen", lambda pid, port: None)
    assert runner._wait_owns_listen(os.getpid(), 9, timeout=0.2) is True


def test_foreign_listen_owner_is_still_rejected(monkeypatch):
    monkeypatch.setattr(runner, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(runner, "_process_owns_listen", lambda pid, port: False)
    assert runner._wait_owns_listen(os.getpid(), 9, timeout=0.25) is False


def test_probe_and_preview_without_procfs(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    (root / "code").mkdir(parents=True)
    _hide_procfs(monkeypatch)
    monkeypatch.setattr(runner, "DATA_ROOT", root)
    monkeypatch.setattr(runner, "PREVIEW_DIR", root / "preview")
    _write(root / "code", "portable", MARKED_APP.replace("MARKER", "portable"))
    ok, message = runner.probe_runnable("portable", smoke_body={"input": "主路径"})
    assert ok, message
    started = runner.start_app("portable")
    proc = runner._RUNNING["portable"]["proc"]
    try:
        assert runner._process_owns_listen(proc.pid, started["port"]) is True
        assert runner._proc_cwd(proc.pid) is not None
        assert runner.stop_app("portable") is True
    finally:
        if runner._pid_alive(proc.pid):
            runner._kill_group(proc.pid)
    assert runner._pid_alive(proc.pid) is False
    assert runner._read_state("portable") is None
