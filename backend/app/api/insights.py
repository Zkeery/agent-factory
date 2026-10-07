"""项目复盘接口：全量选项也只汇总当前用户数据。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_api_key
from app.models import SessionLocal, User
from app.schemas.insights import ReviewOut
from app.services.insights import build_review

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/metrics/review", response_model=ReviewOut)
def metrics_review(source: str = "real", days: str = "all", project_id: str | None = None,
                   session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    return build_review(session, user.id, source=source, days=days, project_id=project_id)
