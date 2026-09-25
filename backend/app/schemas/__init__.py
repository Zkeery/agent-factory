"""API 输入输出结构。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    workspace_path: str | None = None
    project_name: str | None = None
    llm_provider: str | None = None  # mock | deepseek | 空=跟随全局


class CreateScheduleRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)
    trigger_time: str = Field(pattern=r"^\d{2}:\d{2}$")  # "HH:MM"
    project_id: str | None = None


class UpdateScheduleRequest(BaseModel):
    idea: str | None = Field(default=None, max_length=2000)
    trigger_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    id: str
    idea: str
    trigger_time: str
    enabled: bool
    project_id: str | None = None
    last_run_at: datetime | None = None
    created_at: datetime


class RequestCodeRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class RequestCodeResponse(BaseModel):
    phone: str
    mock_code: str | None = None  # 仅 sms_mock=True 时返回，方便本地登录


class LoginRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=4, max_length=8)


class AuthResponse(BaseModel):
    token: str
    phone: str


class AnswerDecisionRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


class ConfirmPrdRequest(BaseModel):
    confirmed: bool = True


class DecisionOut(BaseModel):
    code: str
    question: str
    options: str
    recommendation: str
    consequence: str
    answer: str | None
    status: str
    is_critical: bool = True


class EvidenceOut(BaseModel):
    stage: str
    title: str
    content_path: str
    content: str = ""


class ScoreRequest(BaseModel):
    decision: int = Field(ge=1, le=3)
    prd: int = Field(ge=1, le=3)
    code: int = Field(ge=1, le=3)


class MetricsOut(BaseModel):
    total_runs: int
    ship_rate: float
    avg_duration: float
    avg_cost: float
    quality_rate: float | None
    scored_runs: int


class RunSummary(BaseModel):
    id: str
    idea: str
    current_stage: str
    status: str
    created_at: datetime
    project_id: str | None = None
    auto_schedule_id: str | None = None


class RunListOut(BaseModel):
    runs: list[RunSummary]


class RunMetricOut(BaseModel):
    duration_seconds: float = 0.0
    cost_estimate: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class AppRunOut(BaseModel):
    running: bool
    url: str | None = None
    port: int | None = None


class RunOut(BaseModel):
    id: str
    idea: str
    status: str
    current_stage: str
    failure_reason: str | None = None
    failure_code: str = ""
    project_id: str | None = None
    workspace_write_authorized: bool = False
    workspace_exec_authorized: bool = False
    workspace_always_allow: bool = False
    llm_provider: str = ""
    llm_model: str = ""
    decisions: list[DecisionOut] = []
    evidence: list[EvidenceOut] = []
    metric: RunMetricOut | None = None


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    idea_summary: str = Field(default="", max_length=2000)
    workspace_path: str = Field(default="", max_length=2000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    idea_summary: str | None = None
    workspace_path: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    id: str
    name: str
    idea_summary: str
    workspace_path: str
    created_at: datetime
    updated_at: datetime
    run_count: int = 0


class ProjectListOut(BaseModel):
    projects: list[ProjectOut]


class ArtifactOut(BaseModel):
    id: int
    kind: str
    stage: str
    title: str
    previewable: bool = True


class ArtifactDetailOut(ArtifactOut):
    content: str = ""


class AcceptChecklistItem(BaseModel):
    id: str
    passed: bool
    label: str = ""


class AcceptRunRequest(BaseModel):
    checklist: list[AcceptChecklistItem] = []
    note: str = ""


class WorkspaceAuthorizeRequest(BaseModel):
    scopes: list[str]
    always_for_run: bool = False
    role: str = "pm"  # pm | dev


class WorkspaceSyncOut(BaseModel):
    ok: bool = True
    target: str
    files_copied: int


class LlmProfileOut(BaseModel):
    id: str
    label: str
    available: bool
    model: str


class LlmProfilesOut(BaseModel):
    default_provider: str
    profiles: list[LlmProfileOut]


class ComparePrdDecisionIn(BaseModel):
    code: str = ""
    question: str = ""
    answer: str = ""


class ComparePrdRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)
    decisions: list[ComparePrdDecisionIn] = []


class ComparePrdVariantOut(BaseModel):
    provider: str
    model: str
    prd: dict | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


class ComparePrdOut(BaseModel):
    variants: list[ComparePrdVariantOut]
