"""双角色执行记录与受控恢复；不返回模型私有对话。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.runs import _run_or_404, get_session
from app.core.auth import get_current_user, require_api_key
from app.models import User
from app.services import agent_harness, engine

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.get("/runs/{run_id}/execution")
def get_execution(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    return agent_harness.execution_view(_run_or_404(session, run_id, user))


@router.post("/runs/{run_id}/execution/resume")
def resume_execution(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        run = _run_or_404(session, run_id, user)
        engine.prepare_execution_resume(session, run)
        view = agent_harness.execution_view(run)
    engine.start_run_async(run_id)
    return view
