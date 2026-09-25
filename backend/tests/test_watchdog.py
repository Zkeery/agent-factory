"""运行看门狗测试：卡死熔断、等待态不误判、终态不扫描。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models import FactoryRun, StageEvent
from app.services import watchdog
from app.services.stages import Stage


def _make_run(session, stage: str, status: str = "running", age_seconds: int = 0) -> str:
    run = FactoryRun(id=str(uuid.uuid4()), idea="x", status=status, current_stage=stage)
    session.add(run)
    session.commit()
    if age_seconds:
        session.query(FactoryRun).filter(FactoryRun.id == run.id).update(
            {"updated_at": datetime.now(timezone.utc) - timedelta(seconds=age_seconds)}
        )
        session.commit()
    return run.id


def test_stuck_run_marked_failed(session):
    rid = _make_run(session, Stage.CLARIFYING.value, age_seconds=600)
    marked = watchdog.check_stuck_runs()
    assert marked >= 1
    session.expire_all()
    run = session.get(FactoryRun, rid)
    assert run.current_stage == Stage.FAILED.value
    assert run.status == "done"
    ev = session.query(StageEvent).filter(StageEvent.run_id == rid, StageEvent.event_type == "error").first()
    assert ev is not None and "run_stuck" in ev.payload


def test_wait_stage_not_marked(session):
    rid = _make_run(session, Stage.AWAITING_ANSWERS.value, age_seconds=600)
    assert watchdog.check_stuck_runs() == 0
    session.expire_all()
    assert session.get(FactoryRun, rid).current_stage == Stage.AWAITING_ANSWERS.value


def test_prd_wait_stage_not_marked(session):
    rid = _make_run(session, Stage.AWAITING_PRD_CONFIRM.value, age_seconds=600)
    assert watchdog.check_stuck_runs() == 0
    session.expire_all()
    assert session.get(FactoryRun, rid).current_stage == Stage.AWAITING_PRD_CONFIRM.value


def test_acceptance_wait_stage_not_marked(session):
    rid = _make_run(session, Stage.AWAITING_ACCEPTANCE.value, age_seconds=600)
    assert watchdog.check_stuck_runs() == 0
    session.expire_all()
    assert session.get(FactoryRun, rid).current_stage == Stage.AWAITING_ACCEPTANCE.value


def test_fresh_run_not_marked(session):
    _make_run(session, Stage.CLARIFYING.value, age_seconds=0)
    assert watchdog.check_stuck_runs() == 0


def test_terminal_not_scanned(session):
    _make_run(session, Stage.GATE_PASSED.value, status="done", age_seconds=600)
    assert watchdog.check_stuck_runs() == 0
