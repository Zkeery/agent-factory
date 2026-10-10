"""定时无人值守测试（第十九刀）：到点触发、防重复、开关。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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


def _freeze(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(scheduler, "_local_now", lambda: moment)


def test_waiting_run_is_not_created_again(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    moment = datetime(2026, 10, 10, 20, 32, tzinfo=timezone(timedelta(hours=8)))
    _freeze(monkeypatch, moment)
    schedule = Schedule(
        id=str(uuid.uuid4()), user_id="u1", idea="吃饭", trigger_time="20:32", enabled=True,
        last_run_at=datetime(2026, 10, 9, 12, 32, tzinfo=timezone.utc),
    )
    waiting = FactoryRun(
        id=str(uuid.uuid4()), idea="吃饭", status="running", current_stage="awaiting_answers",
        user_id="u1", auto_schedule_id=schedule.id,
    )
    session.add(schedule)
    session.add(waiting)
    session.commit()
    assert scheduler.check_due_schedules() == 0
    session.expire_all()
    assert session.get(Schedule, schedule.id).last_skip_reason == "上一次仍在等待回答"
    assert session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == schedule.id).count() == 1
    assert scheduler.check_due_schedules() == 0
    assert session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == schedule.id).count() == 1


def test_finished_run_can_trigger_again(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    moment = datetime(2026, 10, 11, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    _freeze(monkeypatch, moment)
    schedule = Schedule(
        id=str(uuid.uuid4()), user_id="u1", idea="提醒我吃早餐", trigger_time="08:00", enabled=True,
        last_run_at=datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc),
        last_skip_reason="上一次仍在等待回答",
    )
    done = FactoryRun(
        id=str(uuid.uuid4()), idea="提醒我吃早餐", status="done", current_stage="delivered",
        user_id="u1", auto_schedule_id=schedule.id,
    )
    session.add(schedule)
    session.add(done)
    session.commit()
    assert scheduler.check_due_schedules() == 1
    session.expire_all()
    assert session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == schedule.id).count() == 2
    assert session.get(Schedule, schedule.id).last_skip_reason == ""


def test_trigger_time_follows_server_local_clock(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    moment = datetime(2026, 10, 10, 20, 32, tzinfo=timezone(timedelta(hours=8)))
    _freeze(monkeypatch, moment)
    utc_wall = Schedule(id=str(uuid.uuid4()), user_id="u1", idea="按世界时", trigger_time="12:32", enabled=True)
    local_wall = Schedule(id=str(uuid.uuid4()), user_id="u1", idea="按当地时间", trigger_time="20:32", enabled=True)
    session.add(utc_wall)
    session.add(local_wall)
    session.commit()
    assert scheduler.check_due_schedules() == 1
    session.expire_all()
    assert session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == utc_wall.id).count() == 0
    assert session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == local_wall.id).count() == 1


def test_same_server_day_is_not_repeated_across_utc_midnight(session, monkeypatch):
    from app.services import engine

    monkeypatch.setattr(engine, "start_run_async", lambda run_id: None)
    moment = datetime(2026, 10, 10, 0, 30, tzinfo=timezone(timedelta(hours=8)))
    _freeze(monkeypatch, moment)
    schedule = Schedule(
        id=str(uuid.uuid4()), user_id="u1", idea="洗澡", trigger_time="00:30", enabled=True,
        last_run_at=datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc),
    )
    session.add(schedule)
    session.commit()
    assert scheduler.check_due_schedules() == 0
    assert session.query(FactoryRun).filter(FactoryRun.auto_schedule_id == schedule.id).count() == 0
