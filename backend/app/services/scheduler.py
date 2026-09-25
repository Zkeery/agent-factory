"""定时无人值守：每天 HH:MM 到点自动生成产品草稿（跑到人工闸门停）。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from app.models import FactoryRun, Schedule, SessionLocal, init_db
from app.services.stages import Stage

logger = logging.getLogger("factory.scheduler")

SCAN_INTERVAL = 30  # 秒


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _fire(schedule: Schedule, session) -> FactoryRun:
    run = FactoryRun(
        id=str(uuid.uuid4()),
        idea=schedule.idea,
        status="running",
        current_stage=Stage.IDEA_SUBMITTED.value,
        user_id=schedule.user_id,
        project_id=schedule.project_id,
        llm_provider="",
        llm_model_snapshot="",
        auto_schedule_id=schedule.id,
    )
    session.add(run)
    return run


def check_due_schedules() -> int:
    """扫描到点的定时任务并建 Run，返回触发数量。"""
    from app.services import engine

    now = _local_now()
    hhmm = now.strftime("%H:%M")
    today = now.date()

    session = SessionLocal()
    fired = 0
    try:
        schedules = session.query(Schedule).filter(Schedule.enabled.is_(True)).all()
        for s in schedules:
            if s.trigger_time != hhmm:
                continue
            if s.last_run_at is not None:
                last = s.last_run_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last.astimezone().date() == today:
                    continue
            run = _fire(s, session)
            s.last_run_at = datetime.now(timezone.utc)
            session.commit()
            engine.start_run_async(run.id)
            logger.info("定时任务触发 schedule=%s idea=%.20s", s.id, s.idea)
            fired += 1
        return fired
    finally:
        session.close()


def _loop() -> None:
    while True:
        try:
            check_due_schedules()
        except Exception:
            logger.exception("定时调度扫描异常")
        time.sleep(SCAN_INTERVAL)


def start_scheduler() -> None:
    init_db()
    threading.Thread(target=_loop, daemon=True, name="schedule-runner").start()
    logger.info("定时调度已启动 interval=%ds", SCAN_INTERVAL)
