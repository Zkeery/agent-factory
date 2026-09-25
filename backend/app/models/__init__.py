"""SQLAlchemy 模型与数据库会话。schema v1，用于工厂内核的持久化。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProductProject(Base):
    """产品项目：工作台心智下的一等对象，可绑定本地工作区。"""

    __tablename__ = "product_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    idea_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FactoryRun(Base):
    __tablename__ = "factory_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="idea_submitted")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # 机器码，前端据此给人话
    auto_schedule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 由定时任务创建时记录
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    workspace_write_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    workspace_exec_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    workspace_always_allow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    llm_model_snapshot: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StageEvent(Base):
    __tablename__ = "stage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, default="stage")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON 字符串
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consequence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open/answered
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Confirmation(Base):
    __tablename__ = "confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # prd
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending/confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other")  # prd|code|deploy|readme|gate|other
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunMetric(Base):
    __tablename__ = "run_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_decision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_prd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Schedule(Base):
    """定时任务：每天 HH:MM 自动生成一条产品草稿（跑到人工闸门停）。"""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_schema(engine)


def _migrate_schema(engine) -> None:
    """轻量迁移：create_all 不更新已有表，这里给老库补列（幂等）。"""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    with engine.begin() as conn:
        fr_cols = {c["name"] for c in inspector.get_columns("factory_runs")}
        if "failure_reason" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN failure_reason TEXT"))
        d_cols = {c["name"] for c in inspector.get_columns("decisions")}
        if "is_critical" not in d_cols:
            conn.execute(text("ALTER TABLE decisions ADD COLUMN is_critical BOOLEAN DEFAULT 1"))
        if "user_id" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN user_id VARCHAR(36)"))
        if "project_id" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN project_id VARCHAR(36)"))
        if "workspace_write_authorized" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN workspace_write_authorized BOOLEAN DEFAULT 0"))
        if "workspace_exec_authorized" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN workspace_exec_authorized BOOLEAN DEFAULT 0"))
        if "workspace_always_allow" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN workspace_always_allow BOOLEAN DEFAULT 0"))
        if "llm_provider" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN llm_provider VARCHAR(32) DEFAULT ''"))
        if "llm_model_snapshot" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN llm_model_snapshot VARCHAR(64) DEFAULT ''"))
        if "failure_code" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN failure_code VARCHAR(32) DEFAULT ''"))
        if "auto_schedule_id" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN auto_schedule_id VARCHAR(36)"))
        # product_projects 由 create_all 建表
        if "evidence_items" in inspector.get_table_names():
            ev_cols = {c["name"] for c in inspector.get_columns("evidence_items")}
            if "kind" not in ev_cols:
                conn.execute(text("ALTER TABLE evidence_items ADD COLUMN kind VARCHAR(32) DEFAULT 'other'"))
        # schedules（第十九刀）：老库可能建成了缺列版本，补齐
        if "schedules" in inspector.get_table_names():
            sch_cols = {c["name"] for c in inspector.get_columns("schedules")}
            if "enabled" not in sch_cols:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN enabled BOOLEAN DEFAULT 1"))
            if "last_run_at" not in sch_cols:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN last_run_at DATETIME"))
            if "created_at" not in sch_cols:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN created_at DATETIME"))
