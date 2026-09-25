"""定时无人值守测试（第十九刀）：到点触发、防重复、开关。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import FactoryRun, Schedule
from app.services import scheduler


def _hhmm() -> str:
    return datetime.now().astimezone().strftime("%H:%M")


def _make_schedule(session, *, enabled=True, last_run_at=None, user_id="u1") -> Schedule:
    s = Schedule(
        id=str(uuid.uuid4()),
        user_id=user_id,
        idea="做个每日待办清单",
        trigger_time=_hhmm(),
        enabled=enabled,
        last_run_at=last_run_at,
    )
    session.add(s)
    session.commit()
    return s


def test_due_schedule_fires_run(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    s = _make_schedule(session)
    fired = scheduler.check_due_schedules()
    assert fired == 1
    runs = session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == s.id).all()
    assert len(runs) == 1
    assert runs[0].idea == "做个每日待办清单"


def test_not_due_does_not_fire(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    s = Schedule(
        id=str(uuid.uuid4()),
        user_id="u1",
        idea="x",
        trigger_time="03:33",  # 几乎不会命中的固定时间
        enabled=True,
    )
    session.add(s)
    session.commit()
    # 若当前恰好 03:33（极低概率），改成一个不合法时间避免误判
    if _hhmm() == "03:33":
        s.trigger_time = "03:34"
        session.commit()
    assert scheduler.check_due_schedules() == 0


def test_same_day_no_repeat(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    _make_schedule(session, last_run_at=datetime.now(timezone.utc))
    assert scheduler.check_due_schedules() == 0


def test_disabled_does_not_fire(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    _make_schedule(session, enabled=False)
    assert scheduler.check_due_schedules() == 0
