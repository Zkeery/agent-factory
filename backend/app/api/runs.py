"""runs / decisions / evidence API 路由。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_api_key
from app.core.config import settings
from app.core.errors import AppError
from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, ProductProject, RunMetric, SessionLocal, StageEvent, User
from app.schemas import (
    AcceptRunRequest,
    AnswerDecisionRequest,
    AppRunOut,
    ArtifactDetailOut,
    ArtifactOut,
    ConfirmPrdRequest,
    CreateRunRequest,
    DecisionOut,
    EvidenceOut,
    MetricsOut,
    RunListOut,
    RunMetricOut,
    RunOut,
    RunSummary,
    ScoreRequest,
    WorkspaceAuthorizeRequest,
    WorkspaceSyncOut,
)
from app.services import engine, llm, gates, metrics, runner, workspace
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
    return EvidenceOut(stage=item.stage, title=item.title, content_path=item.content_path, content=content)


def _run_out(session: Session, run: FactoryRun) -> RunOut:
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    evidence = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id).all()
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
        if project is None or project.user_id != user.id:
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
    )
    session.add(run)
    session.commit()
    engine.start_run_async(run.id)
    return _run_out(session, run)


@router.get("/runs", response_model=RunListOut)
def list_runs(session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    runs = session.query(FactoryRun).filter(FactoryRun.user_id == user.id).order_by(FactoryRun.created_at.desc()).all()
    return RunListOut(runs=[RunSummary(id=r.id, idea=r.idea, current_stage=r.current_stage, status=r.status, created_at=r.created_at, project_id=r.project_id, auto_schedule_id=getattr(r, 'auto_schedule_id', None)) for r in runs])


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    run = _run_or_404(session, run_id, user)
    return _run_out(session, run)


@router.post("/runs/{run_id}/decisions/{code}/answer", response_model=RunOut)
def answer_decision(run_id: str, code: str, body: AnswerDecisionRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
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
    decision.answer = body.answer
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
    run = _run_or_404(session, run_id, user)
    # 幂等：不在等待确认阶段（已确认/已推进/已拒绝）时，直接返回当前状态，不报错
    if run.current_stage != Stage.AWAITING_PRD_CONFIRM.value:
        return _run_out(session, run)
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


@router.post("/runs/{run_id}/accept", response_model=RunOut)
def accept_run(run_id: str, body: AcceptRunRequest, session: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """人验收闸门：自动闸门通过后，须产品经理/开发者勾选验收才算交付。"""
    run = _run_or_404(session, run_id, user)
    if run.current_stage != Stage.AWAITING_ACCEPTANCE.value:
        # 幂等：已交付则直接返回
        return _run_out(session, run)
    from app.services.acceptance import validate_acceptance_checklist

    try:
        validate_acceptance_checklist(body.checklist)
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
