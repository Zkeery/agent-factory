"""完整本地交付包下载：登录身份与 Run 所有权在后端校验。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_api_key
from app.core.errors import AppError
from app.models import FactoryRun, SessionLocal, User
from app.services.delivery import build_bundle

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/runs/{run_id}/bundle", response_class=Response)
def download_bundle(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = session.get(FactoryRun, run_id)
    if run is None or run.user_id != user.id:
        raise AppError("run_not_found", "运行不存在", 404)
    bundle = build_bundle(session, run)
    return Response(
        content=bundle.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle.filename}"', "Cache-Control": "no-store"},
    )
