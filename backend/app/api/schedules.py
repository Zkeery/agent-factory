"""定时任务 API（§5.3 定时无人值守）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_api_key
from app.core.errors import AppError
from app.models import FactoryRun, ProductProject, Schedule, SessionLocal, User
from app.schemas import CreateScheduleRequest, ScheduleOut, UpdateScheduleRequest
from app.services.stages import TERMINAL_STAGES

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _schedule_or_404(session: Session, schedule_id: str, user: User) -> Schedule:
    s = session.get(Schedule, schedule_id)
    if s is None or s.user_id != user.id:
        raise AppError("schedule_not_found", "定时任务不存在", 404)
    return s


def _pending_runs(session: Session, user_id: str) -> dict[str, FactoryRun]:
    terminal = [stage.value for stage in TERMINAL_STAGES]
    runs = (
        session.query(FactoryRun)
        .filter(
            FactoryRun.user_id == user_id,
            FactoryRun.auto_schedule_id.is_not(None),
            FactoryRun.current_stage.not_in(terminal),
        )
        .order_by(FactoryRun.created_at.desc())
        .all()
    )
    found: dict[str, FactoryRun] = {}
    for run in runs:
        if run.auto_schedule_id and run.auto_schedule_id not in found:
            found[run.auto_schedule_id] = run
    return found


def _out(s: Schedule, pending: FactoryRun | None = None) -> ScheduleOut:
    return ScheduleOut(
        id=s.id,
        idea=s.idea,
        trigger_time=s.trigger_time,
        enabled=s.enabled,
        project_id=s.project_id,
        last_run_at=s.last_run_at,
        last_skipped_at=s.last_skipped_at,
        last_skip_reason=s.last_skip_reason or "",
        pending_run_id=pending.id if pending else None,
        pending_run_stage=pending.current_stage if pending else None,
        created_at=s.created_at,
    )


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    items = (
        session.query(Schedule)
        .filter(Schedule.user_id == user.id)
        .order_by(Schedule.created_at.desc())
        .all()
    )
    pending = _pending_runs(session, user.id)
    return [_out(x, pending.get(x.id)) for x in items]


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(body: CreateScheduleRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    if body.project_id:
        project = session.get(ProductProject, body.project_id)
        if project is None or project.user_id != user.id or project.deleted_at is not None:
            raise AppError("project_not_found", "项目不存在", 404)
    item = Schedule(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=body.project_id,
        idea=body.idea.strip(),
        trigger_time=body.trigger_time,
        enabled=True,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _out(item)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: str, body: UpdateScheduleRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    item = _schedule_or_404(session, schedule_id, user)
    if body.enabled is True and item.project_id:
        project = session.get(ProductProject, item.project_id)
        if project is None or project.user_id != user.id or project.deleted_at is not None:
            raise AppError("project_not_found", "项目不存在", 404)
    if body.idea is not None:
        item.idea = body.idea.strip()
    if body.trigger_time is not None:
        item.trigger_time = body.trigger_time
    if body.enabled is not None:
        item.enabled = body.enabled
    session.commit()
    session.refresh(item)
    return _out(item)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    item = _schedule_or_404(session, schedule_id, user)
    session.delete(item)
    session.commit()
    return {"ok": True}
