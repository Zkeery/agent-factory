"""度量采集、打分与汇总测试。"""
from __future__ import annotations

import time
import uuid

import pytest

from app.models import Confirmation, Decision, FactoryRun, RunMetric, SessionLocal
from app.services import engine, metrics
from app.services.stages import Stage


def make_run(session) -> FactoryRun:
    run = FactoryRun(id=str(uuid.uuid4()), idea="x", status="running", current_stage=Stage.IDEA_SUBMITTED.value)
    session.add(run)
    session.commit()
    return run


def answer_all(session, run_id: str) -> None:
    for d in session.query(Decision).filter(Decision.run_id == run_id).all():
        d.answer = "按推荐"
        d.status = "answered"
    session.commit()


def run_to_gate_passed(session) -> FactoryRun:
    """跑完整流水线并完成人工验收，停在 delivered。"""
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="acceptance", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    return run


def test_metric_recorded_on_terminal(session):
    run = run_to_gate_passed(session)
    m = session.query(RunMetric).filter(RunMetric.run_id == run.id).first()
    assert m is not None
    assert m.duration_seconds >= 0
    assert m.prompt_tokens == 0  # mock 无 token
    assert m.completion_tokens == 0
    assert m.cost_estimate == 0.0


def test_metric_accumulates_across_advances(session):
    run = make_run(session)
    engine.advance(session, run)  # 到 awaiting_answers，记录一段
    m1 = session.query(RunMetric).filter(RunMetric.run_id == run.id).first()
    assert m1 is not None
    d1 = m1.duration_seconds
    answer_all(session, run.id)
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    engine.advance(session, run)  # 到终态
    m2 = session.query(RunMetric).filter(RunMetric.run_id == run.id).first()
    assert m2.id == m1.id  # 同一条累加
    assert m2.duration_seconds >= d1


def test_score_and_summarize(session):
    run = run_to_gate_passed(session)
    metrics.score_run(session, run.id, 3, 2, 3)
    summary = metrics.summarize(session)
    assert summary["total_runs"] == 1
    assert summary["ship_rate"] == 1.0
    assert summary["quality_rate"] == 1.0  # min(3,2,3)=2 合格
    assert summary["scored_runs"] == 1


def test_summarize_quality_rate_below_line(session):
    run = run_to_gate_passed(session)
    metrics.score_run(session, run.id, 1, 2, 2)  # min=1 不合格
    summary = metrics.summarize(session)
    assert summary["quality_rate"] == 0.0


def test_score_overwrite(session):
    run = run_to_gate_passed(session)
    metrics.score_run(session, run.id, 1, 1, 1)
    metrics.score_run(session, run.id, 3, 3, 3)
    m = session.query(RunMetric).filter(RunMetric.run_id == run.id).first()
    assert m.score_decision == 3 and m.score_prd == 3 and m.score_code == 3


def test_summarize_empty():
    session = SessionLocal()
    try:
        summary = metrics.summarize(session)
        assert summary["total_runs"] == 0
        assert summary["quality_rate"] is None
    finally:
        session.close()


def _wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/v1/runs/{run_id}").json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时")


def test_score_api_and_metrics(client):
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    data = _wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        client.post(f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer", json={"answer": "A"})
    _wait_stage(client, run_id, "awaiting_prd_confirm")
    client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True})
    _wait_stage(client, run_id, "awaiting_acceptance")
    assert client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": [{"id": "local_run", "label": "主路径能按说明在本地跑起来", "passed": True},{"id": "prd_match", "label": "PRD 与实现大体一致", "passed": True},{"id": "no_blockers", "label": "没有明显阻断性错误", "passed": True}], "note": "ok"}).status_code == 200
    _wait_stage(client, run_id, "delivered")

    # 打分成功
    r = client.post(f"/api/v1/runs/{run_id}/score", json={"decision": 3, "prd": 2, "code": 3})
    assert r.status_code == 200
    # 越界 422
    r = client.post(f"/api/v1/runs/{run_id}/score", json={"decision": 4, "prd": 2, "code": 3})
    assert r.status_code == 422
    # 汇总接口
    m = client.get("/api/v1/metrics").json()
    assert m["total_runs"] >= 1


def test_score_rejected_before_terminal(client):
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    r = client.post(f"/api/v1/runs/{run_id}/score", json={"decision": 3, "prd": 3, "code": 3})
    assert r.status_code == 409
