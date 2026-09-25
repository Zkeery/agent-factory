"""登录/账号接口：手机号验证码（mock 短信） + 会话 token。"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.errors import AppError
from app.models import Session, SessionLocal, User, VerificationCode
from app.schemas import AuthResponse, LoginRequest, RequestCodeRequest, RequestCodeResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

CODE_TTL_MINUTES = 5
PHONE_RE = re.compile(r"^\+?\d{5,20}$")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _validate_phone(phone: str) -> str:
    p = (phone or "").strip()
    if not PHONE_RE.match(p):
        raise AppError("invalid_phone", "手机号格式不对", 400)
    return p


def _expire_previous(session: Session, phone: str) -> None:
    """把该手机号之前未使用的验证码全部作废，避免多码并存。"""
    for c in (
        session.query(VerificationCode)
        .filter(VerificationCode.phone == phone, VerificationCode.used.is_(False))
        .all()
    ):
        c.used = True


@router.post("/request-code", response_model=RequestCodeResponse)
def request_code(body: RequestCodeRequest, session: Session = Depends(get_session)):
    phone = _validate_phone(body.phone)
    code = f"{secrets.randbelow(1_000_000):06d}"
    _expire_previous(session, phone)
    session.add(
        VerificationCode(
            phone=phone,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MINUTES),
        )
    )
    session.commit()
    # mock 短信：验证码直接随接口返回，本地零成本；真实短信接入后改走短信服务
    return RequestCodeResponse(phone=phone, mock_code=code if settings.sms_mock else None)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)):
    phone = _validate_phone(body.phone)
    code = (body.code or "").strip()
    now = datetime.now(timezone.utc)
    latest = (
        session.query(VerificationCode)
        .filter(
            VerificationCode.phone == phone,
            VerificationCode.used.is_(False),
            VerificationCode.expires_at > now,
        )
        .order_by(VerificationCode.id.desc())
        .first()
    )
    if latest is None:
        raise AppError("code_invalid", "验证码错误或已过期", 400)
    if latest.code != code:
        raise AppError("code_invalid", "验证码错误", 400)
    latest.used = True
    user = session.query(User).filter(User.phone == phone).first()
    if user is None:
        user = User(id=str(uuid.uuid4()), phone=phone)
        session.add(user)
    token = secrets.token_hex(32)
    session.add(Session(token=token, user_id=user.id))
    session.commit()
    return AuthResponse(token=token, phone=user.phone)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"phone": user.phone}
