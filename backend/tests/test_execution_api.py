from __future__ import annotations

import json
import uuid

import pytest

from app.models import Confirmation, FactoryRun, User
from app.services import agent_harness as harness
from app.services import engine


def stored_run(session, user_id, *, mode="agent_team", state_status="interrupted", stage="building", turns=2, confirmed=True):
    state = harness._new_state()
    state["status"] = state_status
    state["turns"]["builder:0"] = turns
    state["messages"] = {"builder:0": [{"role": "system", "content": "PRIVATE_SYSTEM_PROMPT"}]}
    state["raw_source"] = "PRIVATE_SOURCE"
    run = FactoryRun(id=str(uuid.uuid4()), idea="接口样例", user_id=user_id, execution_mode=mode, execution_state=json.dumps(state), current_stage=stage, status="paused")
    session.add(run)
    if confirmed:
        session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    return run


def test_execution_view_ownership_and_private_fields(client, session):
    owner = session.query(User).first()
    mine = stored_run(session, owner.id)
    other = stored_run(session, "other-owner")
    response = client.get(f"/api/v1/runs/{mine.id}/execution")
    assert response.status_code == 200
    view = response.json()
    assert view["limits"] == {"max_turns_per_agent": harness.MAX_TURNS, "max_repair_rounds": harness.MAX_REPAIRS}
    assert view["resumable"]
    assert all(isinstance(view[k], list) for k in ("tasks", "steps", "checks", "handoffs"))
    assert "PRIVATE_" not in response.text and "messages" not in response.text and "raw_source" not in response.text
    assert client.get(f"/api/v1/runs/{other.id}/execution").status_code == 404
    assert client.post(f"/api/v1/runs/{other.id}/execution/resume").status_code == 404


def test_resume_claims_checkpoint_once_without_budget_reset(client, session, monkeypatch):
    run = stored_run(session, session.query(User).first().id)
    started = []
    monkeypatch.setattr(engine, "start_run_async", started.append)
    response = client.post(f"/api/v1/runs/{run.id}/execution/resume")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    session.refresh(run)
    assert harness.load_state(run)["turns"] == {"builder:0": 2}
    assert started == [run.id]
    assert client.post(f"/api/v1/runs/{run.id}/execution/resume").status_code == 409
    assert started == [run.id]


@pytest.mark.parametrize("options", [
    {"state_status": "failed"}, {"state_status": "cancelled"}, {"state_status": "completed"},
    {"mode": "workflow"}, {"stage": "awaiting_prd_confirm"}, {"turns": harness.MAX_TURNS}, {"confirmed": False},
])
def test_resume_does_not_bypass_budget_terminal_or_human_gate(client, session, monkeypatch, options):
    run = stored_run(session, session.query(User).first().id, **options)
    started = []
    monkeypatch.setattr(engine, "start_run_async", started.append)
    assert client.post(f"/api/v1/runs/{run.id}/execution/resume").status_code == 409
    assert not started
