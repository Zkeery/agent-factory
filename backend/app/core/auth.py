"""鉴权：可选 API Key（服务级）+ 登录态（用户级，手机号验证码）。"""
from __future__ import annotations

from fastapi import Depends, Header, Query
from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError
from app.models import Session, SessionLocal, User


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key: str | None = Query(default=None, description="SSE 等无法自定义头时的备用"),
) -> None:
    expected = (settings.api_key or "").strip()
    if not expected:
        return
    provided = (x_api_key or api_key or "").strip()
    if provided != expected:
        raise AppError("unauthorized", "缺少或错误的 API Key", 401)


def _extract_token(authorization: str | None, token: str | None) -> str:
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw or (token or "").strip()


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    token: str | None = Query(default=None, description="SSE 等无法自定义头时的备用"),
) -> User:
    """从 Bearer token 解析当前用户；未登录或会话失效则 401。"""
    raw = _extract_token(authorization, token)
    if not raw:
        raise AppError("unauthorized", "请先登录", 401)
    session = SessionLocal()
    try:
        sess = session.get(Session, raw)
        if sess is None:
            raise AppError("unauthorized", "登录已失效，请重新登录", 401)
        user = session.get(User, sess.user_id)
        if user is None:
            raise AppError("unauthorized", "用户不存在", 401)
        return user
    finally:
        session.close()
