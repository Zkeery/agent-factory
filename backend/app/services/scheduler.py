"""定时无人值守：每天 HH:MM 到点自动生成产品草稿（跑到人工闸门停）。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from app.models import FactoryRun, ProductProject, Schedule, SessionLocal, init_db
from app.services.stages import TERMINAL_STAGES, Stage
from app.services.version_visibility import next_version_no

logger = logging.getLogger("factory.scheduler")

SCAN_INTERVAL = 30  # 秒


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _as_server_local(value: datetime) -> datetime:
    """触发记录按 UTC 保存，是否同一天要换算到服务器当地日期。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_local_now().tzinfo)


def _handled_today(schedule: Schedule, today) -> bool:
    for stamp in (schedule.last_run_at, schedule.last_skipped_at):
        if stamp is not None and _as_server_local(stamp).date() == today:
            return True
    return False


def _blocking_run(session, schedule_id: str) -> FactoryRun | None:
    terminal = [stage.value for stage in TERMINAL_STAGES]
    return (
        session.query(FactoryRun)
        .filter(FactoryRun.auto_schedule_id == schedule_id, FactoryRun.current_stage.not_in(terminal))
        .order_by(FactoryRun.created_at.desc())
        .first()
    )


def _skip_reason(stage: str) -> str:
    labels = {
        "awaiting_answers": "上一次仍在等待回答",
        "awaiting_prd_confirm": "上一次仍在等待确认需求",
        "awaiting_acceptance": "上一次仍在等待验收",
    }
    return labels.get(stage, "上一次运行尚未完成")


def _fire(schedule: Schedule, session) -> FactoryRun | None:
    if schedule.project_id:
        project = session.get(ProductProject, schedule.project_id)
        if project is not None and project.deleted_at is not None:
            schedule.enabled = False
            return None
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
        version_no=next_version_no(session, schedule.project_id),
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
            if _handled_today(s, today):
                continue
            if s.project_id:
                project = session.get(ProductProject, s.project_id)
                if project is not None and project.deleted_at is not None:
                    s.enabled = False
                    session.commit()
                    continue
            blocking = _blocking_run(session, s.id)
            if blocking is not None:
                s.last_skipped_at = _local_now().astimezone(timezone.utc)
                s.last_skip_reason = _skip_reason(blocking.current_stage)
                session.commit()
                logger.info("定时任务跳过 schedule=%s stage=%s", s.id, blocking.current_stage)
                continue
            run = _fire(s, session)
            if run is None:
                session.commit()
                continue
            s.last_run_at = _local_now().astimezone(timezone.utc)
            s.last_skip_reason = ""
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
