"""整段重跑后隐藏被替代的失败版本，序号继续递增，复盘仍计入。"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import FactoryRun, Schedule, SessionLocal
from app.services import insights, metrics
from app.services.stages import Stage
from app.services.version_visibility import assign_missing_version_numbers, backfill_replaced_failures

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
APP_SOURCE = (
    "from fastapi import FastAPI\n"
    "app = FastAPI()\n"
    "@app.post('/generate')\n"
    "def generate():\n"
    "    return {'result': 'ok'}\n"
)


def wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        data = client.get(f"/api/v1/runs/{run_id}").json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前：{data}")


def listed_ids(client) -> list[str]:
    return [item["id"] for item in client.get("/api/v1/runs").json()["runs"]]


def mark_stage(run_id: str, stage: str) -> None:
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        run.current_stage = stage
        run.status = "done"
        run.failure_reason = "安装依赖时停止"
        session.commit()
    finally:
        session.close()


def test_backfill_hides_only_retried_failures_and_keeps_numbers(session):
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def add(run_id: str, minute: int, stage: str, **kwargs) -> FactoryRun:
        run = FactoryRun(
            id=run_id,
            idea=kwargs.pop("idea", "同一想法"),
            user_id="owner",
            project_id=kwargs.pop("project_id", "project"),
            current_stage=stage,
            status=kwargs.pop("status", "done"),
            created_at=start + timedelta(minutes=minute),
            version_no=kwargs.pop("version_no", minute),
            **kwargs,
        )
        session.add(run)
        return run

    replaced = add("replaced", 1, "gate_failed", version_no=1)
    successor = add("successor", 2, "awaiting_answers", status="running", version_no=2)
    untouched = add("untouched", 3, "failed", idea="没有重跑的失败", version_no=3)
    add("revise-shape", 4, "awaiting_answers", status="running", version_no=4, idea="谱系乙", parent_run_id="parent", revision_request_id="keep-parent")
    same_line_failure = add("same-line-failure", 5, "failed", version_no=5, idea="谱系乙", parent_run_id="parent")
    add("scheduled", 6, "awaiting_answers", status="running", version_no=6, idea="谱系乙", parent_run_id="parent", auto_schedule_id="schedule-1")
    unnumbered = add("unnumbered", 7, "delivered", version_no=0, project_id="project")
    session.commit()

    assert backfill_replaced_failures(session) == 1
    assign_missing_version_numbers(session)
    session.commit()
    session.refresh(replaced)
    session.refresh(same_line_failure)
    session.refresh(untouched)
    session.refresh(unnumbered)
    assert replaced.superseded_by_run_id == successor.id
    assert same_line_failure.superseded_by_run_id is None
    assert untouched.superseded_by_run_id is None
    assert unnumbered.version_no == 7
    assert session.get(FactoryRun, "successor").version_no == 2


@pytest.mark.parametrize("stage", ["failed", "gate_failed"])
def test_retry_hides_replaced_failure_and_keeps_lineage(client, stage):
    created = client.post("/api/v1/runs", json={"idea": "需要整段重跑的记账工具"}).json()
    parent_id = created["id"]
    project_id = created["project_id"]
    wait_stage(client, parent_id, "awaiting_answers")
    mark_stage(parent_id, "awaiting_acceptance")
    revised = client.post(
        f"/api/v1/runs/{parent_id}/revise",
        json={"change_request": "保留现有记账，修正余额", "request_id": f"revise-{stage}"},
    )
    assert revised.status_code == 201, revised.text
    child_id = revised.json()["id"]
    wait_stage(client, child_id, "awaiting_answers")
    mark_stage(child_id, stage)

    retried = client.post(f"/api/v1/runs/{child_id}/retry")
    assert retried.status_code == 201, retried.text
    new = retried.json()
    hidden = client.get(f"/api/v1/runs/{child_id}")
    assert hidden.status_code == 200
    body = hidden.json()
    assert body["superseded_by_run_id"] == new["id"]
    assert body["parent_run_id"] == parent_id
    assert new["parent_run_id"] == parent_id
    assert new["version_no"] == body["version_no"] + 1
    assert new["version_no"] != body["version_no"]

    visible = listed_ids(client)
    assert parent_id in visible
    assert new["id"] in visible
    assert child_id not in visible
    project_runs = [item["id"] for item in client.get(f"/api/v1/projects/{project_id}/runs").json()["runs"]]
    assert child_id not in project_runs
    assert client.get("/api/v1/projects").json()["projects"][0]["run_count"] == 2

    session = SessionLocal()
    try:
        user_id = session.get(FactoryRun, parent_id).user_id
        assert metrics.summarize(session, user_id)["total_runs"] == 3
        review = insights.build_review(session, user_id, source="all")
        assert review["counts"]["total"] == 3
        assert review["counts"]["failed"] >= 1
    finally:
        session.close()


def test_cancelled_retry_retest_and_schedule_stay_visible(client):
    created = client.post("/api/v1/runs", json={"idea": "取消后重跑仍要留在列表"}).json()
    run_id = created["id"]
    wait_stage(client, run_id, "awaiting_answers")
    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
    retried = client.post(f"/api/v1/runs/{run_id}/retry")
    assert retried.status_code == 201, retried.text
    assert client.get(f"/api/v1/runs/{run_id}").json()["superseded_by_run_id"] is None
    assert run_id in listed_ids(client)
    assert retried.json()["id"] in listed_ids(client)

    gated = client.post("/api/v1/runs", json={"idea": "就地重测不隐藏"}).json()["id"]
    wait_stage(client, gated, "awaiting_answers")
    code_dir = DATA_ROOT / "code" / gated
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    mark_stage(gated, Stage.GATE_FAILED.value)
    retested = client.post(f"/api/v1/runs/{gated}/retest")
    assert retested.status_code == 200, retested.text
    assert retested.json()["id"] == gated
    assert client.get(f"/api/v1/runs/{gated}").json()["superseded_by_run_id"] is None
    assert gated in listed_ids(client)

    parked = client.post("/api/v1/runs", json={"idea": "定时创建不替代失败版本"}).json()
    wait_stage(client, parked["id"], "awaiting_answers")
    mark_stage(parked["id"], Stage.FAILED.value)
    session = SessionLocal()
    try:
        old = session.get(FactoryRun, parked["id"])
        schedule = Schedule(
            id=str(uuid.uuid4()),
            user_id=old.user_id,
            project_id=old.project_id,
            idea=old.idea,
            trigger_time="09:00",
        )
        session.add(schedule)
        session.commit()
        from app.services.scheduler import _fire

        fired = _fire(schedule, session)
        session.commit()
        fired_id = fired.id
        assert old.superseded_by_run_id is None
    finally:
        session.close()
    visible = listed_ids(client)
    assert parked["id"] in visible
    assert fired_id in visible
