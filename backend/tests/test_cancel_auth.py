"""取消、拒绝 PRD、可选 API Key。"""
from __future__ import annotations

import time

import pytest


def wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        data = r.json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前：{data}")


def test_reject_prd_cancels_run(client):
    r = client.post("/api/v1/runs", json={"idea": "一个被拒绝的 PRD 想法"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        assert client.post(
            f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer",
            json={"answer": "按推荐"},
        ).status_code == 200
    wait_stage(client, run_id, "awaiting_prd_confirm")
    r = client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": False})
    assert r.status_code == 200
    body = r.json()
    assert body["current_stage"] == "cancelled"
    assert body["status"] == "done"


def test_cancel_at_awaiting_answers(client):
    r = client.post("/api/v1/runs", json={"idea": "取消测试"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    r = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert r.status_code == 200
    assert r.json()["current_stage"] == "cancelled"
    # 再取消应 409
    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 409


def test_api_key_required_when_configured(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "api_key", "secret-test-key")
    r = client.post("/api/v1/runs", json={"idea": "无 key"})
    assert r.status_code == 401
    r = client.post(
        "/api/v1/runs",
        json={"idea": "有 key"},
        headers={"X-API-Key": "secret-test-key"},
    )
    assert r.status_code == 201
