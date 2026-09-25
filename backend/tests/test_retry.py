"""第五刀：失败/取消后可重试。"""
from __future__ import annotations

import time

from app.models import FactoryRun, SessionLocal
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


def test_retry_after_cancel(client):
    r = client.post("/api/v1/runs", json={"idea": "重试用的想法"})
    assert r.status_code == 201
    old_id = r.json()["id"]
    wait_stage(client, old_id, "awaiting_answers")
    assert client.post(f"/api/v1/runs/{old_id}/cancel").status_code == 200

    r = client.post(f"/api/v1/runs/{old_id}/retry")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] != old_id
    assert body["idea"] == "重试用的想法"

    old = client.get(f"/api/v1/runs/{old_id}").json()
    assert old["current_stage"] == "cancelled"


def test_retry_rejects_non_terminal(client):
    r = client.post("/api/v1/runs", json={"idea": "进行中不可重试"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_retryable"


def test_retry_after_failed(client):
    r = client.post("/api/v1/runs", json={"idea": "先建再改失败"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        run.current_stage = Stage.FAILED.value
        run.status = "done"
        run.failure_reason = "模拟流水线失败：依赖安装超时"
        session.commit()
    finally:
        session.close()

    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != run_id
    assert new["idea"] == "先建再改失败"

    old = client.get(f"/api/v1/runs/{run_id}").json()
    assert old["current_stage"] == "failed"
    assert "依赖安装超时" in (old.get("failure_reason") or "")


def test_retry_other_users_run_404(client):
    r = client.post("/api/v1/runs", json={"idea": "别人的失败"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        run.current_stage = Stage.GATE_FAILED.value
        run.status = "done"
        run.failure_reason = "闸门未通过"
        session.commit()
    finally:
        session.close()

    r = client.post("/api/v1/auth/request-code", json={"phone": "13900139000"})
    code = r.json()["mock_code"]
    r = client.post("/api/v1/auth/login", json={"phone": "13900139000", "code": code})
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"

    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 404
