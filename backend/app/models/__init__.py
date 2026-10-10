"""SQLAlchemy 模型与数据库会话。schema v1，用于工厂内核的持久化。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """数据库不保存时区。写入和读出都按 UTC，接口才能带上偏移。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


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
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class FactoryRun(Base):
    __tablename__ = "factory_runs"
    __table_args__ = (Index("uq_run_revision_request", "parent_run_id", "revision_request_id", unique=True),)

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
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="workflow")
    # Harness 私有检查点；对外仅返回脱敏后的任务、工具与交接摘要。
    execution_state: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    parent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    change_request: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 父 PRD/源文件在创建子版本时快照，后续不依赖父文件是否被手工修改。
    parent_context: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    requirement_feedback: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    prd_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prd_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    acceptance_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="basic")
    acceptance_scenarios: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    acceptance_results: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    acceptance_checklist: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    acceptance_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # 内部创建计数。用户看到的序号按可见版本的创建顺序连号计算，不直接使用本列。
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 用户整段重跑失败版本并创建新版本后写入。用户界面不展示，统计仍计入，不进回收站。
    superseded_by_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class StageEvent(Base):
    __tablename__ = "stage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, default="stage")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other")  # prd|code|deploy|readme|gate|other
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RunMetric(Base):
    __tablename__ = "run_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("factory_runs.id"), index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pricing_snapshots: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    accounting_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_segments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_segments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_decision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_prd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Schedule(Base):
    """定时任务：每天 HH:MM 自动生成一条产品草稿（跑到人工闸门停）。"""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_skipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_skip_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


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
    link_historical_retries = False
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
        iteration_columns = {
            "execution_mode": "VARCHAR(32) NOT NULL DEFAULT 'workflow'",
            "execution_state": "TEXT NOT NULL DEFAULT '{}'",
            "parent_run_id": "VARCHAR(36)",
            "revision_request_id": "VARCHAR(128)",
            "change_request": "TEXT NOT NULL DEFAULT ''",
            "parent_context": "TEXT NOT NULL DEFAULT '{}'",
            "requirement_feedback": "TEXT NOT NULL DEFAULT '[]'",
            "prd_revision": "INTEGER NOT NULL DEFAULT 0",
            "prd_snapshot": "TEXT NOT NULL DEFAULT '{}'",
            "acceptance_mode": "VARCHAR(16) NOT NULL DEFAULT 'basic'",
            "acceptance_scenarios": "TEXT NOT NULL DEFAULT '[]'",
            "acceptance_results": "TEXT NOT NULL DEFAULT '[]'",
            "acceptance_checklist": "TEXT NOT NULL DEFAULT '[]'",
            "acceptance_note": "TEXT NOT NULL DEFAULT ''",
            "accepted_at": "DATETIME",
        }
        for name, definition in iteration_columns.items():
            if name not in fr_cols:
                conn.execute(text(f"ALTER TABLE factory_runs ADD COLUMN {name} {definition}"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_run_revision_request "
            "ON factory_runs (parent_run_id, revision_request_id)"
        ))
        metric_cols = {c["name"] for c in inspector.get_columns("run_metrics")}
        for name, definition in {
            "pricing_snapshots": "TEXT NOT NULL DEFAULT '[]'",
            "accounting_version": "INTEGER NOT NULL DEFAULT 0",
            "recorded_segments": "INTEGER NOT NULL DEFAULT 0",
            "failed_segments": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in metric_cols:
                conn.execute(text(f"ALTER TABLE run_metrics ADD COLUMN {name} {definition}"))
        project_cols = {c["name"] for c in inspector.get_columns("product_projects")}
        if "deleted_at" not in project_cols:
            conn.execute(text("ALTER TABLE product_projects ADD COLUMN deleted_at DATETIME"))
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
            if "last_skipped_at" not in sch_cols:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN last_skipped_at DATETIME"))
            if "last_skip_reason" not in sch_cols:
                conn.execute(text("ALTER TABLE schedules ADD COLUMN last_skip_reason TEXT DEFAULT ''"))
        if "version_no" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN version_no INTEGER NOT NULL DEFAULT 0"))
        if "superseded_by_run_id" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN superseded_by_run_id VARCHAR(36)"))
            link_historical_retries = True
        if "superseded_at" not in fr_cols:
            conn.execute(text("ALTER TABLE factory_runs ADD COLUMN superseded_at DATETIME"))
    if link_historical_retries:
        from sqlalchemy.orm import Session

        from app.services.version_visibility import assign_missing_version_numbers, backfill_replaced_failures

        with Session(engine) as session:
            assign_missing_version_numbers(session)
            backfill_replaced_failures(session)
            session.commit()
