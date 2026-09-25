"""第八刀：工作区写盘 / 本地执行授权。"""
from __future__ import annotations

import time
from pathlib import Path

from app.models import FactoryRun, ProductProject, SessionLocal
from app.services.runner import _code_dir
from app.services.stages import Stage


def wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        data = r.json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前：{data}")


def _prepare_gate_passed(client, *, workspace_path: str | None = None) -> str:
    r = client.post("/api/v1/runs", json={"idea": "工作区授权测试"})
    assert r.status_code == 201, r.text
    body = r.json()
    run_id = body["id"]
    project_id = body.get("project_id")
    wait_stage(client, run_id, "awaiting_answers")

    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        assert run is not None
        run.current_stage = Stage.GATE_PASSED.value
        run.status = "done"
        if workspace_path and project_id:
            project = session.get(ProductProject, project_id)
            assert project is not None
            project.workspace_path = workspace_path
        session.commit()
    finally:
        session.close()

    code = _code_dir(run_id)
    code.mkdir(parents=True, exist_ok=True)
    (code / "app.py").write_text("# fake app\nprint('ok')\n", encoding="utf-8")
    return run_id


def test_start_without_exec_auth_403(client):
    run_id = _prepare_gate_passed(client)
    r = client.post(f"/api/v1/runs/{run_id}/start")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "workspace_exec_required"


def test_authorize_exec_then_start_ok(client, monkeypatch):
    run_id = _prepare_gate_passed(client)
    monkeypatch.setattr(
        "app.api.runs.runner.start_app",
        lambda _rid: {"running": True, "url": "http://127.0.0.1:9999", "port": 9999},
    )
    auth = client.post(
        f"/api/v1/runs/{run_id}/workspace/authorize",
        json={"scopes": ["exec"], "always_for_run": False, "role": "pm"},
    )
    assert auth.status_code == 200, auth.text
    body = auth.json()
    assert body["workspace_exec_authorized"] is True
    assert body["workspace_always_allow"] is False

    r = client.post(f"/api/v1/runs/{run_id}/start")
    assert r.status_code == 200, r.text
    assert r.json()["running"] is True


def test_pm_always_for_run_rejected(client):
    run_id = _prepare_gate_passed(client)
    r = client.post(
        f"/api/v1/runs/{run_id}/workspace/authorize",
        json={"scopes": ["exec"], "always_for_run": True, "role": "pm"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "always_not_allowed_for_pm"


def test_dev_always_allows_exec_without_reauth(client, monkeypatch):
    run_id = _prepare_gate_passed(client)
    monkeypatch.setattr(
        "app.api.runs.runner.start_app",
        lambda _rid: {"running": True, "url": "http://127.0.0.1:9998", "port": 9998},
    )
    auth = client.post(
        f"/api/v1/runs/{run_id}/workspace/authorize",
        json={"scopes": ["exec"], "always_for_run": True, "role": "dev"},
    )
    assert auth.status_code == 200, auth.text
    body = auth.json()
    assert body["workspace_always_allow"] is True
    assert body["workspace_exec_authorized"] is True
    assert body["workspace_write_authorized"] is True

    r = client.post(f"/api/v1/runs/{run_id}/start")
    assert r.status_code == 200, r.text
    assert r.status_code != 403


def test_sync_requires_write_then_copies(client, tmp_path: Path):
    target = tmp_path / "ws"
    target.mkdir()
    run_id = _prepare_gate_passed(client, workspace_path=str(target))

    denied = client.post(f"/api/v1/runs/{run_id}/workspace/sync")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "workspace_write_required"

    auth = client.post(
        f"/api/v1/runs/{run_id}/workspace/authorize",
        json={"scopes": ["write"], "always_for_run": False, "role": "pm"},
    )
    assert auth.status_code == 200, auth.text
    assert auth.json()["workspace_write_authorized"] is True

    synced = client.post(f"/api/v1/runs/{run_id}/workspace/sync")
    assert synced.status_code == 200, synced.text
    body = synced.json()
    assert body["ok"] is True
    assert body["files_copied"] >= 1
    assert (target / "app.py").is_file()
    assert "print" in (target / "app.py").read_text(encoding="utf-8")


def test_app_status_and_stop(client, monkeypatch):
    """第九刀：status / stop 与 start 返回体一致。"""
    run_id = _prepare_gate_passed(client)
    monkeypatch.setattr(
        "app.api.runs.runner.start_app",
        lambda _rid: {"running": True, "url": "http://127.0.0.1:9999", "port": 9999},
    )
    monkeypatch.setattr(
        "app.api.runs.runner.app_status",
        lambda _rid: {"running": True, "url": "http://127.0.0.1:9999", "port": 9999},
    )
    stopped = {"n": 0}

    def _stop(_rid):
        stopped["n"] += 1
        return True

    monkeypatch.setattr("app.api.runs.runner.stop_app", _stop)

    auth = client.post(
        f"/api/v1/runs/{run_id}/workspace/authorize",
        json={"scopes": ["exec"], "always_for_run": False, "role": "dev"},
    )
    assert auth.status_code == 200, auth.text
    assert client.post(f"/api/v1/runs/{run_id}/start").status_code == 200

    st = client.get(f"/api/v1/runs/{run_id}/app-status")
    assert st.status_code == 200, st.text
    assert st.json()["running"] is True
    assert st.json()["port"] == 9999

    sp = client.post(f"/api/v1/runs/{run_id}/stop")
    assert sp.status_code == 200, sp.text
    assert sp.json()["running"] is False
    assert stopped["n"] == 1
