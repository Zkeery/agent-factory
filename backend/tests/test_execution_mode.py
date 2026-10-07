"""执行模式向后兼容，以及版本继承和交付包的公开记录边界。"""
import pytest

from app.api import runs
from app.models import FactoryRun


@pytest.mark.parametrize("mode, expected", [(None, "workflow"), ("agent_team", "agent_team")])
def test_create_execution_mode_and_list_contract(client, monkeypatch, mode, expected):
    monkeypatch.setattr(runs.engine, "start_run_async", lambda _: None)
    body = {"idea": "项目复盘的小应用", "llm_provider": "mock"}
    if mode:
        body["execution_mode"] = mode
    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 201
    assert response.json()["execution_mode"] == expected
    run_id = response.json()["id"]
    assert client.get(f"/api/v1/runs/{run_id}").json()["execution_mode"] == expected
    listing = client.get("/api/v1/runs").json()["runs"]
    assert next(row for row in listing if row["id"] == run_id)["execution_mode"] == expected


def test_revision_inherits_mode_and_rejects_conflicting_retry(client, session, monkeypatch):
    monkeypatch.setattr(runs.engine, "start_run_async", lambda _: None)
    monkeypatch.setattr(runs.engine, "snapshot_parent_context", lambda *args: {"prd": "confirmed", "files": {}})
    parent_id = client.post("/api/v1/runs", json={
        "idea": "项目复盘的小应用", "llm_provider": "mock", "execution_mode": "agent_team",
    }).json()["id"]
    parent = session.get(FactoryRun, parent_id)
    parent.current_stage = "failed"
    session.commit()
    body = {"change_request": "修正输入校验", "request_id": "same-mode-retry", "acceptance_mode": "basic"}
    response = client.post(f"/api/v1/runs/{parent_id}/revise", json=body)
    assert response.status_code == 201
    assert response.json()["execution_mode"] == "agent_team"
    retry = client.post(f"/api/v1/runs/{parent_id}/revise", json=body)
    assert retry.json()["id"] == response.json()["id"]
    conflict = client.post(f"/api/v1/runs/{parent_id}/revise", json={**body, "execution_mode": "workflow"})
    assert conflict.status_code == 409


def test_invalid_execution_mode_rejected(client):
    response = client.post("/api/v1/runs", json={"idea": "项目复盘的小应用", "execution_mode": "arbitrary"})
    assert response.status_code == 422
