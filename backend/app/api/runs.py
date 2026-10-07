"""runs / decisions / evidence API 路由。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_api_key
from app.core.config import settings
from app.core.errors import AppError
from app.services.decision_context import normalize_decision_answer
from app.services.project_lifecycle import active_run_filter
from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, ProductProject, RunMetric, SessionLocal, StageEvent, User
from app.schemas import (
    AcceptRunRequest,
    AcceptanceRejectRequest,
    AcceptanceResultsRequest,
    AcceptanceScenariosRequest,
    AnswerDecisionRequest,
    AppRunOut,
    ArtifactDetailOut,
    ArtifactOut,
    ConfirmPrdRequest,
    CreateRunRequest,
    DecisionOut,
    EvidenceOut,
    MetricsOut,
    RequirementFeedbackRequest,
    ReviseRunRequest,
    RunListOut,
    RunMetricOut,
    RunOut,
    RunSummary,
    ScoreRequest,
    WorkspaceAuthorizeRequest,
    WorkspaceSyncOut,
)
from app.services import engine, llm, gates, iteration, metrics, runner, workspace
from app.services.stages import TERMINAL_STAGES, Stage

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _run_or_404(session: Session, run_id: str, user: User | None = None) -> FactoryRun:
    run = session.get(FactoryRun, run_id)
    if run is None or (user is not None and run.user_id != user.id):
        raise AppError("run_not_found", "运行不存在", 404)
    project = session.get(ProductProject, run.project_id) if run.project_id else None
    if project is not None and project.deleted_at is not None:
        raise AppError("run_not_found", "运行不存在", 404)
    return run


def _read_content(path: str) -> str:
    try:
        from pathlib import Path

        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _evidence_out(item: EvidenceItem) -> EvidenceOut:
    content = _read_content(item.content_path)
    # 证据文件格式 "# 标题\n\n正文"；正文不该再带标题（标题由 title 字段承载），剥掉首行标题
    parts = content.split("\n\n", 1)
    if len(parts) > 1 and parts[0].lstrip().startswith("# "):
        content = parts[1].strip()
    return EvidenceOut(id=item.id, stage=item.stage, title=item.title, content_path=item.content_path, content=content)


def _run_out(session: Session, run: FactoryRun) -> RunOut:
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    evidence = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id).order_by(EvidenceItem.id.desc()).all()
    metric = session.query(RunMetric).filter(RunMetric.run_id == run.id).first()
    return RunOut(
        id=run.id,
        idea=run.idea,
        status=run.status,
        current_stage=run.current_stage,
        failure_reason=run.failure_reason,
        failure_code=(getattr(run, 'failure_code', None) or '') or '',
        project_id=run.project_id,
        workspace_write_authorized=bool(getattr(run, 'workspace_write_authorized', False)),
        workspace_exec_authorized=bool(getattr(run, 'workspace_exec_authorized', False)),
        workspace_always_allow=bool(getattr(run, 'workspace_always_allow', False)),
        llm_provider=(getattr(run, 'llm_provider', None) or '') or '',
        llm_model=(getattr(run, 'llm_model_snapshot', None) or '') or '',
        execution_mode=run.execution_mode or "workflow",
        parent_run_id=run.parent_run_id,
        change_request=run.change_request or "",
        requirement_feedback=iteration.json_list(run.requirement_feedback),
        prd_revision=run.prd_revision or 0,
        acceptance_mode=run.acceptance_mode or "basic",
        acceptance_scenarios=iteration.json_list(run.acceptance_scenarios),
        acceptance_results=iteration.json_list(run.acceptance_results),
        acceptance_checklist=iteration.json_list(run.acceptance_checklist),
        acceptance_note=run.acceptance_note or "",
        accepted_at=run.accepted_at,
        decisions=[
            DecisionOut(
                code=d.code, question=d.question, options=d.options,
                recommendation=d.recommendation, consequence=d.consequence,
                answer=d.answer, status=d.status, is_critical=d.is_critical,
            )
            for d in decisions
        ],
        evidence=[_evidence_out(e) for e in evidence],
        metric=RunMetricOut(
            duration_seconds=metric.duration_seconds,
            cost_estimate=metric.cost_estimate,
            prompt_tokens=metric.prompt_tokens,
            completion_tokens=metric.completion_tokens,
        ) if metric else None,
    )


@router.post("/runs", response_model=RunOut, status_code=201)
def create_run(body: CreateRunRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    project_id = body.project_id
    if project_id:
        project = session.get(ProductProject, project_id)
        if project is None or project.user_id != user.id or project.deleted_at is not None:
            raise AppError("project_not_found", "项目不存在", 404)
        if body.workspace_path is not None:
            project.workspace_path = body.workspace_path.strip()
            session.commit()
    else:
        name = (body.project_name or body.idea.strip()[:32] or "未命名项目").strip()
        project = ProductProject(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name=name,
            idea_summary=body.idea.strip()[:500],
            workspace_path=(body.workspace_path or "").strip(),
        )
        session.add(project)
        session.commit()
        project_id = project.id

    # Run 级模型：空=跟随全局；deepseek 无 Key 拒建
    raw_provider = (body.llm_provider or "").strip().lower()
    if raw_provider and raw_provider not in ("mock", "deepseek"):
        raise AppError("unknown_llm_provider", f"未知模型提供商：{raw_provider}", 400)
    if raw_provider == "deepseek" and not settings.llm_api_key.strip():
        raise AppError("llm_key_missing", "未配置 LLM_API_KEY，无法使用 deepseek", 400)
    stored_provider = raw_provider  # '' = follow global
    model_snap = ""
    if stored_provider:
        model_snap = llm.provider_model_label(stored_provider)

    run = FactoryRun(
        id=str(uuid.uuid4()),
        idea=body.idea,
        status="running",
        current_stage=Stage.IDEA_SUBMITTED.value,
        user_id=user.id,
        project_id=project_id,
        llm_provider=stored_provider,
        llm_model_snapshot=model_snap,
        acceptance_mode=body.acceptance_mode,
        execution_mode=body.execution_mode,
    )
    session.add(run)
    session.commit()
    engine.start_run_async(run.id)
    return _run_out(session, run)


@router.get("/runs", response_model=RunListOut)
def list_runs(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    runs = session.query(FactoryRun).filter(FactoryRun.user_id == user.id, active_run_filter()).order_by(FactoryRun.created_at.desc()).all()
    return RunListOut(runs=[RunSummary(id=r.id, idea=r.idea, current_stage=r.current_stage, status=r.status, created_at=r.created_at, project_id=r.project_id, auto_schedule_id=getattr(r, 'auto_schedule_id', None), parent_run_id=r.parent_run_id, execution_mode=r.execution_mode or "workflow") for r in runs])


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    return _run_out(session, run)


EDITABLE_REQUIREMENT_STAGES = {Stage.AWAITING_ANSWERS.value, Stage.AWAITING_PRD_CONFIRM.value}


@router.post("/runs/{run_id}/requirements", response_model=RunOut)
def update_requirements(run_id: str, body: RequirementFeedbackRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        run = _run_or_404(session, run_id, user)
        session.refresh(run)
        if run.current_stage not in EDITABLE_REQUIREMENT_STAGES:
            raise AppError("requirements_locked", "请在回答问题或确认 PRD 前补充需求；成品修改请创建新版本", 409)
        entry = {"id": str(uuid.uuid4()), "feedback": body.feedback, "created_at": datetime.now(timezone.utc).isoformat()}
        run.requirement_feedback = iteration.dump(iteration.json_list(run.requirement_feedback) + [entry])
        session.add(StageEvent(
            run_id=run.id, stage=run.current_stage, event_type="requirements_updated", payload=iteration.dump(entry),
        ))
        session.commit()
        engine.regenerate_prd(session, run)
        return _run_out(session, run)


@router.put("/runs/{run_id}/acceptance-scenarios", response_model=RunOut)
def update_acceptance_scenarios(run_id: str, body: AcceptanceScenariosRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        run = _run_or_404(session, run_id, user)
        session.refresh(run)
        if run.current_stage not in EDITABLE_REQUIREMENT_STAGES:
            raise AppError("scenarios_locked", "验收场景须在确认 PRD 前编辑", 409)
        if run.acceptance_mode != "scenario":
            raise AppError("scenario_mode_required", "该运行使用基础验收模式", 409)
        scenarios = [item.model_dump() for item in body.scenarios]
        run.acceptance_scenarios = iteration.dump(scenarios)
        run.prd_revision = (run.prd_revision or 0) + 1
        run.acceptance_results = "[]"
        session.add(StageEvent(
            run_id=run.id, stage=run.current_stage, event_type="acceptance_scenarios_updated", payload=iteration.dump(scenarios),
        ))
        session.commit()
        return _run_out(session, run)


@router.put("/runs/{run_id}/acceptance-results", response_model=RunOut)
def save_acceptance_results(run_id: str, body: AcceptanceResultsRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        run = _run_or_404(session, run_id, user)
        session.refresh(run)
        if run.current_stage != Stage.AWAITING_ACCEPTANCE.value or run.acceptance_mode != "scenario":
            raise AppError("results_locked", "业务试用记录只能在场景模式的待验收阶段保存", 409)
        expected = {item["id"] for item in iteration.json_list(run.acceptance_scenarios)}
        actual = [item.scenario_id for item in body.scenario_results]
        if len(actual) != len(set(actual)) or not set(actual).issubset(expected):
            raise AppError("invalid_scenario_results", "试用记录包含重复或不属于本版本的场景", 400)
        results = [item.model_dump() for item in body.scenario_results]
        run.acceptance_results = iteration.dump(results)
        session.add(StageEvent(
            run_id=run.id, stage=run.current_stage, event_type="acceptance_results_saved", payload=iteration.dump(results),
        ))
        session.commit()
        return _run_out(session, run)


@router.post("/runs/{run_id}/revise", response_model=RunOut, status_code=201)
def revise_run(run_id: str, body: ReviseRunRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        parent = _run_or_404(session, run_id, user)
        execution_mode = body.execution_mode or parent.execution_mode or "workflow"
        if body.request_id:
            existing = session.query(FactoryRun).filter(
                FactoryRun.parent_run_id == run_id, FactoryRun.revision_request_id == body.request_id,
            ).first()
            if existing:
                if existing.change_request != body.change_request or existing.acceptance_mode != body.acceptance_mode or (existing.execution_mode or "workflow") != execution_mode:
                    raise AppError("revision_request_conflict", "同一提交标识已用于不同修改要求", 409)
                return _run_out(session, existing)
        allowed = {s.value for s in TERMINAL_STAGES} | {Stage.AWAITING_ACCEPTANCE.value}
        if parent.current_stage not in allowed:
            raise AppError("revision_not_ready", "请先完成当前版本生成，再基于成品修改", 409)
        context = engine.snapshot_parent_context(session, parent)
        child = FactoryRun(
            id=str(uuid.uuid4()), idea=parent.idea, status="running", current_stage=Stage.IDEA_SUBMITTED.value,
            user_id=user.id, project_id=parent.project_id, parent_run_id=parent.id,
            revision_request_id=body.request_id, change_request=body.change_request,
            parent_context=iteration.dump(context),
            llm_provider=parent.llm_provider, llm_model_snapshot=parent.llm_model_snapshot,
            acceptance_mode=body.acceptance_mode,
            execution_mode=execution_mode,
        )
        session.add(child)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.query(FactoryRun).filter(
                FactoryRun.parent_run_id == run_id, FactoryRun.revision_request_id == body.request_id,
            ).first() if body.request_id else None
            if existing and existing.change_request == body.change_request and existing.acceptance_mode == body.acceptance_mode and (existing.execution_mode or "workflow") == execution_mode:
                return _run_out(session, existing)
            raise AppError("revision_request_conflict", "修改版本创建冲突，请刷新后重试", 409)
        engine.start_run_async(child.id)
        return _run_out(session, child)


@router.post("/runs/{run_id}/decisions/{code}/answer", response_model=RunOut)
def answer_decision(run_id: str, code: str, body: AnswerDecisionRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        return _answer_decision(run_id, code, body, session, user)


def _answer_decision(run_id: str, code: str, body: AnswerDecisionRequest, session: Session, user: User):
    run = _run_or_404(session, run_id, user)
    # 非关键决策可在「等待回答」或「等待确认 PRD」阶段改；其它阶段幂等返回
    editable_stages = {Stage.AWAITING_ANSWERS.value, Stage.AWAITING_PRD_CONFIRM.value}
    if run.current_stage not in editable_stages:
        return _run_out(session, run)
    decision = session.query(Decision).filter(Decision.run_id == run_id, Decision.code == code).first()
    if decision is None:
        raise AppError("decision_not_found", "决策卡不存在", 404)
    # 关键决策幂等不可改；非关键决策允许改（PRD 生成前或确认前）
    if decision.status == "answered" and decision.is_critical:
        return _run_out(session, run)
    decision.answer = normalize_decision_answer(body.answer, options=decision.options, recommendation=decision.recommendation)
    decision.status = "answered"
    session.commit()
    if run.current_stage == Stage.AWAITING_PRD_CONFIRM.value:
        # PRD 已生成：改非关键决策 → 重新生成 PRD，保持在待确认
        engine.regenerate_prd(session, run)
        return _run_out(session, run)
    if gates.all_decisions_answered(session, run):
        engine.start_run_async(run_id)
    return _run_out(session, run)


@router.post("/runs/{run_id}/confirm-prd", response_model=RunOut)
def confirm_prd(run_id: str, body: ConfirmPrdRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    with engine.run_lock(run_id):
        return _confirm_prd(run_id, body, session, user)


def _confirm_prd(run_id: str, body: ConfirmPrdRequest, session: Session, user: User):
    run = _run_or_404(session, run_id, user)
    # 幂等：不在等待确认阶段（已确认/已推进/已拒绝）时，直接返回当前状态，不报错
    if run.current_stage != Stage.AWAITING_PRD_CONFIRM.value:
        return _run_out(session, run)
    if (run.acceptance_mode == "scenario" or body.prd_revision is not None) and body.prd_revision != (run.prd_revision or 0):
        raise AppError("prd_revision_conflict", "PRD 或验收场景已更新，请刷新并确认最新版本", 409)
    if body.confirmed and run.acceptance_mode == "scenario":
        try:
            iteration.validate_scenarios(iteration.json_list(run.acceptance_scenarios))
        except ValueError:
            raise AppError("acceptance_scenarios_incomplete", "请先准备至少三条完整业务验收场景", 400)
    confirmation = (
        session.query(Confirmation)
        .filter(Confirmation.run_id == run_id, Confirmation.kind == "prd")
        .first()
    )
    if confirmation is None:
        confirmation = Confirmation(run_id=run_id, kind="prd", status="pending")
        session.add(confirmation)
    if not body.confirmed:
        confirmation.status = "rejected"
        session.commit()
        engine.cancel_run(run_id, reason="prd_rejected")
        session.refresh(run)
        return _run_out(session, run)
    confirmation.status = "confirmed"
    session.commit()
    engine.start_run_async(run_id)
    return _run_out(session, run)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    engine.cancel_run(run_id, reason="user_cancelled")
    session.refresh(run)
    return _run_out(session, run)


RETRYABLE_STAGES = {
    Stage.FAILED.value,
    Stage.GATE_FAILED.value,
    Stage.CANCELLED.value,
}


@router.post("/runs/{run_id}/retry", response_model=RunOut, status_code=201)
def retry_run(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """失败 / 闸门失败 / 已取消 后，用同一想法与项目再开一条新 Run。"""
    old = _run_or_404(session, run_id, user)
    if old.current_stage not in RETRYABLE_STAGES:
        raise AppError("not_retryable", "当前状态不能重试，仅失败、闸门失败或已取消可重试", 409)
    new = FactoryRun(
        id=str(uuid.uuid4()),
        idea=old.idea,
        status="running",
        current_stage=Stage.IDEA_SUBMITTED.value,
        user_id=user.id,
        project_id=old.project_id,
        llm_provider=getattr(old, "llm_provider", "") or "",
        llm_model_snapshot=getattr(old, "llm_model_snapshot", "") or "",
        execution_mode=getattr(old, "execution_mode", "workflow") or "workflow",
        parent_run_id=old.parent_run_id,
        change_request=old.change_request or "",
        parent_context=old.parent_context or "{}",
        requirement_feedback=old.requirement_feedback or "[]",
        acceptance_mode=old.acceptance_mode or "basic",
    )
    session.add(new)
    session.commit()
    engine.start_run_async(new.id)
    return _run_out(session, new)







@router.post("/runs/{run_id}/retest", response_model=RunOut)
def retest_run(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """闸门失败（或失败且已有代码）时就地重测：同 Run id，从 testing 续跑，不删 PRD/决策/代码。"""
    run = _run_or_404(session, run_id, user)
    engine.retest_run(run_id)
    session.expire_all()
    run = session.get(FactoryRun, run_id)
    return _run_out(session, run)

@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceOut])
def get_evidence(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    items = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id).all()
    return [_evidence_out(e) for e in items]


@router.post("/runs/{run_id}/score", response_model=RunOut)
def score_run(run_id: str, body: ScoreRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    if run.current_stage not in [s.value for s in TERMINAL_STAGES]:
        raise AppError("not_terminal", "运行尚未结束，不能打分", 409)
    metrics.score_run(session, run_id, body.decision, body.prd, body.code)
    return _run_out(session, run)


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    return metrics.summarize(session, user.id)


@router.post("/runs/{run_id}/start", response_model=AppRunOut)
def start_run_app(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    if run.current_stage not in {
        Stage.GATE_PASSED.value,
        Stage.AWAITING_ACCEPTANCE.value,
        Stage.DELIVERED.value,
    }:
        raise AppError("not_ready", "成品尚未生成完成，不能预览", 409)
    workspace.ensure_exec_authorized(run)
    return runner.start_app(run_id)


@router.post("/runs/{run_id}/workspace/authorize", response_model=RunOut)
def authorize_workspace(
    run_id: str,
    body: WorkspaceAuthorizeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    run = _run_or_404(session, run_id, user)
    run = workspace.authorize(
        session,
        run,
        scopes=body.scopes,
        always_for_run=body.always_for_run,
        role=body.role,
    )
    return _run_out(session, run)


@router.post("/runs/{run_id}/workspace/sync", response_model=WorkspaceSyncOut)
def sync_workspace(
    run_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    run = _run_or_404(session, run_id, user)
    result = workspace.sync_to_workspace(session, run)
    return WorkspaceSyncOut(**result)


@router.post("/runs/{run_id}/stop", response_model=AppRunOut)
def stop_run_app(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    _run_or_404(session, run_id, user)
    runner.stop_app(run_id)
    return AppRunOut(running=False)


@router.get("/runs/{run_id}/app-status", response_model=AppRunOut)
def get_app_status(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    _run_or_404(session, run_id, user)
    return runner.app_status(run_id)


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request, user: User = Depends(get_current_user)):
    """SSE：先回放历史事件，再轮询新事件直到终态。事件序列以 done/error 收尾。"""
    session = SessionLocal()

    def fetch_since(last_id: int) -> list[StageEvent]:
        return (
            session.query(StageEvent)
            .filter(StageEvent.run_id == run_id, StageEvent.id > last_id)
            .order_by(StageEvent.id)
            .all()
        )

    async def event_generator():
        try:
            # 浏览器重连会带 Last-Event-ID，避免整段重放刷屏
            raw_last = request.headers.get("Last-Event-ID") or "0"
            try:
                last_id = max(0, int(raw_last))
            except ValueError:
                last_id = 0
            run = session.get(FactoryRun, run_id)
            if run is None or run.user_id != user.id:
                yield "event: error\ndata: " + json.dumps({"error": {"code": "run_not_found", "message": "运行不存在"}}) + "\n\n"
                return
            for ev in fetch_since(last_id):
                last_id = ev.id
                yield f"id: {ev.id}\nevent: chunk\ndata: " + json.dumps(
                    {"id": ev.id, "stage": ev.stage, "event_type": ev.event_type, "payload": ev.payload}
                ) + "\n\n"
            while True:
                if await request.is_disconnected():
                    return
                session.expire_all()
                run = session.get(FactoryRun, run_id)
                if run is None:
                    yield "event: error\ndata: " + json.dumps({"error": {"code": "run_not_found", "message": "运行不存在"}}) + "\n\n"
                    return
                if run.status == "paused":
                    yield "event: done\ndata: " + json.dumps({"stage": run.current_stage, "status": "paused"}) + "\n\n"
                    return
                if run.current_stage == Stage.FAILED.value:
                    err = (
                        session.query(StageEvent)
                        .filter(StageEvent.run_id == run_id, StageEvent.event_type == "error")
                        .order_by(StageEvent.id.desc())
                        .first()
                    )
                    payload = err.payload if err else json.dumps({"error": {"code": "failed", "message": "运行失败"}})
                    yield "event: error\ndata: " + payload + "\n\n"
                    return
                if run.current_stage in [s.value for s in TERMINAL_STAGES]:
                    yield "event: done\ndata: " + json.dumps({"stage": run.current_stage}) + "\n\n"
                    return
                new_events = fetch_since(last_id)
                for ev in new_events:
                    last_id = ev.id
                    yield f"id: {ev.id}\nevent: chunk\ndata: " + json.dumps(
                        {"id": ev.id, "stage": ev.stage, "event_type": ev.event_type, "payload": ev.payload}
                    ) + "\n\n"
                run = session.get(FactoryRun, run_id)
                await asyncio.sleep(0.4)
        except Exception:
            yield "event: error\ndata: " + json.dumps({"error": {"code": "stream_error", "message": "进度流异常"}}) + "\n\n"
        finally:
            session.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    items = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id).order_by(EvidenceItem.id.asc()).all()
    return [
        ArtifactOut(
            id=e.id,
            kind=getattr(e, "kind", None) or e.stage or "other",
            stage=e.stage,
            title=e.title,
            previewable=True,
        )
        for e in items
    ]


@router.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=ArtifactDetailOut)
def get_artifact(run_id: str, artifact_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    item = session.get(EvidenceItem, artifact_id)
    if item is None or item.run_id != run.id:
        raise AppError("artifact_not_found", "产物不存在", 404)
    base = ArtifactOut(
        id=item.id,
        kind=getattr(item, "kind", None) or item.stage or "other",
        stage=item.stage,
        title=item.title,
        previewable=True,
    )
    return ArtifactDetailOut(**base.model_dump(), content=_read_content(item.content_path))


@router.post("/runs/{run_id}/reject", response_model=RunOut)
def reject_run(run_id: str, body: AcceptanceRejectRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """保存人工验收未通过原因，保留当前成品供后续修改和复验。"""
    with engine.run_lock(run_id):
        run = _run_or_404(session, run_id, user)
        session.refresh(run)
        if run.current_stage != Stage.AWAITING_ACCEPTANCE.value:
            raise AppError("acceptance_not_reviewable", "只有待人工验收的版本可以记录未通过，请先打开待验收版本", 409)
        note = body.note.strip()
        latest = session.query(StageEvent).filter(
            StageEvent.run_id == run_id, StageEvent.event_type == "human_acceptance_rejected",
        ).order_by(StageEvent.id.desc()).first()
        repeated = run.acceptance_note == note and latest is not None and iteration.json_dict(latest.payload).get("note") == note
        run.acceptance_note = note
        confirmation = session.query(Confirmation).filter(
            Confirmation.run_id == run_id, Confirmation.kind == "acceptance",
        ).first()
        if confirmation is not None:
            confirmation.status = "pending"
        if not repeated:
            session.add(StageEvent(
                run_id=run.id, stage=run.current_stage, event_type="human_acceptance_rejected",
                payload=iteration.dump({"note": note}),
            ))
        session.commit()
        return _run_out(session, run)


@router.post("/runs/{run_id}/accept", response_model=RunOut)
def accept_run(run_id: str, body: AcceptRunRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """人验收闸门：自动闸门通过后，须产品经理/开发者勾选验收才算交付。"""
    with engine.run_lock(run_id):
        run = _run_or_404(session, run_id, user)
        if run.current_stage != Stage.AWAITING_ACCEPTANCE.value:
            # 已交付幂等返回，不改写已有观察和验收时间。
            return _run_out(session, run)
        from app.services.acceptance import validate_acceptance_checklist

        try:
            validate_acceptance_checklist(body.checklist)
            if run.acceptance_mode == "scenario":
                iteration.validate_scenario_results(
                    iteration.json_list(run.acceptance_scenarios), body.scenario_results,
                )
        except ValueError as e:
            raise AppError("acceptance_incomplete", str(e), 400) from e
        confirmation = (
            session.query(Confirmation)
            .filter(Confirmation.run_id == run_id, Confirmation.kind == "acceptance")
            .first()
        )
        if confirmation is None:
            confirmation = Confirmation(run_id=run_id, kind="acceptance", status="pending")
            session.add(confirmation)
        confirmation.status = "confirmed"
        run.acceptance_checklist = iteration.dump([item.model_dump() for item in body.checklist])
        run.acceptance_results = iteration.dump([item.model_dump() for item in body.scenario_results])
        run.acceptance_note = body.note
        run.accepted_at = datetime.now(timezone.utc)
        session.add(StageEvent(
            run_id=run.id, stage=run.current_stage, event_type="delivery_accepted",
            payload=iteration.dump({
                "checklist": iteration.json_list(run.acceptance_checklist),
                "scenario_results": iteration.json_list(run.acceptance_results),
                "accepted_at": run.accepted_at.isoformat(), "note": body.note,
            }),
        ))
        session.commit()
    engine.start_run_async(run_id)
    # 给后台线程一点时间推进到 delivered
    import time
    for _ in range(30):
        session.refresh(run)
        if run.current_stage == Stage.DELIVERED.value or run.current_stage in {s.value for s in TERMINAL_STAGES}:
            break
        time.sleep(0.05)
        session.expire_all()
        run = session.get(FactoryRun, run_id)
    return _run_out(session, run)
