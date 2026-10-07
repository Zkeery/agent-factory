"""流水线引擎：按固定工序推进状态机，动作由确定性代码执行，模型只产出内容。"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, SessionLocal, StageEvent, init_db
from app.services import agent_harness, deploy, evidence, failure_reasons, gates, iteration, llm, metrics, testing
from app.services.prd_normalize import normalize_prd_fields
from app.services.decision_context import decision_model_context
from app.services.stages import NEXT_STAGE, TERMINAL_STAGES, Stage

logger = logging.getLogger("factory.engine")

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
_run_locks: dict[str, threading.RLock] = {}
_run_locks_guard = threading.Lock()
_background_runs: set[threading.Thread] = set()
_background_runs_guard = threading.Lock()
_active_advances: set[str] = set()


@contextmanager
def run_lock(run_id: str):
    """本地单服务内串行化同一 Run 的人工修改与阶段推进。"""
    with _run_locks_guard:
        lock = _run_locks.setdefault(run_id, threading.RLock())
    with lock:
        yield


def _emit(session: Session, run: FactoryRun, stage: Stage, event_type: str = "stage", payload: str = "") -> None:
    session.add(StageEvent(run_id=run.id, stage=stage.value, event_type=event_type, payload=payload))
    session.commit()


def _transition(session: Session, run: FactoryRun, stage: Stage) -> None:
    run.current_stage = stage.value
    _emit(session, run, stage)


def _write_code(run: FactoryRun, code: dict[str, str]) -> str:
    safe = "".join(c for c in run.id if c.isalnum() or c in "-_")
    d = (DATA_ROOT / "code" / safe).resolve()
    if not d.is_relative_to(DATA_ROOT.resolve()):
        raise AppError("invalid_run_dir", "非法运行目录", 500)
    d.mkdir(parents=True, exist_ok=True)
    (d / "app.py").write_text(code.get("app", ""), encoding="utf-8")
    (d / "requirements.txt").write_text(code.get("requirements", ""), encoding="utf-8")
    (d / "README.md").write_text(code.get("readme", ""), encoding="utf-8")
    return str(d / "app.py")


def _py_syntax_ok(app_path: str) -> bool:
    """app.py 能否通过 py_compile；语法错误返回 False。"""
    import py_compile

    try:
        py_compile.compile(app_path, doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def prd_to_markdown(prd: dict) -> str:
    """九键合同转为 Markdown；保留字段内的小节、规则表和验收编号。"""
    fields = [
        ("用户问题、使用场景与产品目标", prd.get("goal_users", "")),
        ("输入、过程和产物", prd.get("input_process_output", "")),
        ("功能、页面与主流程", prd.get("main_loop", "")),
        ("什么算生成得好", prd.get("quality", "")),
        ("交付阶段与优先级", prd.get("delivery", "")),
        ("模型与成本约束", prd.get("model_cost", "")),
        ("数据与非功能要求", prd.get("data_nonfunc", "")),
        ("上线与账号", prd.get("launch", "")),
    ]
    lines: list[str] = []
    for title, content in fields:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(content or "待定")
        lines.append("")
    if prd.get("output_type"):
        labels = {"text": "文本", "image": "图片", "video": "可播放视频", "other": "交互工具或其他"}
        lines.extend(["## 主路径产物类型", "", labels.get(prd["output_type"], prd["output_type"]), ""])
    return "\n".join(lines).strip()


def _run_tests(session: Session, run: FactoryRun) -> bool:
    """对生成的代码骨架做真实语法检查 + smoke 运行，不依赖模型。"""
    prd = _load_prd(session, run)
    output_type = prd.get("output_type")
    # 新 PRD 以确认后的结构化产物类型约束烟测；历史 PRD 保持原行为。
    test_idea = ("生成可播放视频" if output_type == "video" else "本地小应用") if output_type else run.idea
    ok, reason = testing.run_tests(run.id, idea=test_idea, output_type=output_type)
    _emit(session, run, Stage.TESTING, event_type="test_result", payload=("passed" if ok else f"failed: {reason}"))
    if not ok:
        run.failure_reason = f"代码测试未通过：{reason}"
        run.failure_code = failure_reasons.classify_test_reason(reason)
        session.commit()
    return ok


def _load_prd(session: Session, run: FactoryRun) -> dict:
    """从证据包读取已确认的 PRD JSON；缺失时返回空字典。"""
    snapshot = iteration.json_dict(run.prd_snapshot)
    if snapshot:
        return snapshot
    item = (
        session.query(EvidenceItem)
        .filter(EvidenceItem.run_id == run.id, EvidenceItem.stage == "prd")
        .order_by(EvidenceItem.id.desc())
        .first()
    )
    if item is None or not getattr(item, "content_path", None):
        return {}
    try:
        raw = Path(item.content_path).read_text(encoding="utf-8")
    except OSError:
        return {}
    # evidence 文件格式：# 标题 + 空行 + JSON 正文
    sep = chr(10) + chr(10)
    parts = raw.split(sep, 1)
    body = parts[1].strip() if len(parts) > 1 else raw.strip()
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else {"raw": data}
    except json.JSONDecodeError:
        return {"raw": body}


def regenerate_prd(session: Session, run: FactoryRun) -> None:
    """重写当前草稿并重建场景，保留所有旧 PRD 与反馈的审计历史。"""
    previous_stage = Stage(run.current_stage)
    run.acceptance_scenarios = "[]"
    run.acceptance_results = "[]"
    run.acceptance_checklist = "[]"
    run.accepted_at = None
    _transition(session, run, Stage.PRD_DRAFTING)
    client = None
    start = time.monotonic()
    outcome = "completed"
    try:
        client = llm.get_llm((getattr(run, "llm_provider", None) or "").strip() or None)
        _draft_prd(session, run, client)
        for confirmation in session.query(Confirmation).filter(
            Confirmation.run_id == run.id, Confirmation.kind == "prd",
        ).all():
            confirmation.status = "pending"
        session.commit()
        _transition(session, run, previous_stage)
        _emit(session, run, previous_stage, "prd_updated")
    except AppError as exc:
        outcome = "failed"
        session.rollback()
        _mark_failed(session, run.id, exc.code, exc.message)
        raise
    except Exception:
        outcome = "failed"
        logger.exception("PRD 修订失败 run=%s", run.id)
        session.rollback()
        _mark_failed(session, run.id, "prd_revision_failed", "PRD 更新失败，已保留补充内容，请重试")
        raise AppError("prd_revision_failed", "PRD 更新失败，已保留补充内容，请重试", 502)
    finally:
        metrics.record_metric(session, run, client, start, outcome=outcome)


def snapshot_parent_context(session: Session, run: FactoryRun) -> dict:
    """只取明确的三个源文件，不扫描工作区、密钥或用户运行数据。"""
    prd = _load_prd(session, run)
    if not prd:
        raise AppError("revision_source_missing", "当前版本还没有可引用的 PRD", 409)
    root = (DATA_ROOT / "code" / run.id).resolve()
    if not root.is_relative_to((DATA_ROOT / "code").resolve()):
        raise AppError("invalid_run_dir", "非法运行目录", 400)
    files = {}
    for name in ("app.py", "requirements.txt", "README.md"):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise AppError("revision_source_missing", f"父版本缺少 {name}，无法基于它修改", 409)
        if path.stat().st_size > 200_000:
            raise AppError("revision_source_too_large", "父版本源文件过大，请先缩小本次修改范围", 400)
        files[name] = path.read_text(encoding="utf-8")
    if not files["app.py"].strip():
        raise AppError("revision_source_missing", "父版本代码为空", 409)
    return {
        "parent_run_id": run.id,
        "prd": prd,
        "files": files,
        "acceptance_scenarios": iteration.json_list(run.acceptance_scenarios),
        "acceptance_results": iteration.json_list(run.acceptance_results),
        "acceptance_note": run.acceptance_note or "",
        "requirement_feedback": iteration.json_list(run.requirement_feedback),
    }


def _draft_prd(session: Session, run: FactoryRun, client) -> None:
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    context = iteration.json_dict(run.parent_context)
    kwargs = {"source_context": context} if context else {}
    idea = iteration.effective_idea(run)
    prd = client.generate_prd(
        idea, [decision_model_context(d) for d in decisions], **kwargs,
    )
    prd = normalize_prd_fields(prd)
    if run.acceptance_mode == "scenario":
        scenarios = iteration.validate_scenarios(client.generate_acceptance_scenarios(idea, prd))
        run.acceptance_scenarios = iteration.dump(scenarios)
        # 新需求的场景必须重新核对，不能复用旧观察或通过结果。
        run.acceptance_results = "[]"
        run.acceptance_checklist = "[]"
        run.accepted_at = None
        session.add(StageEvent(
            run_id=run.id, stage=Stage.PRD_DRAFTING.value,
            event_type="acceptance_scenarios", payload=iteration.dump(scenarios),
        ))
    run.prd_snapshot = iteration.dump(prd)
    run.prd_revision = (run.prd_revision or 0) + 1
    evidence.add_evidence(session, run, "prd", "PRD 草稿", prd_to_markdown(prd))


def _action(session: Session, run: FactoryRun, stage: Stage, client) -> Stage | None:
    if stage == Stage.CLARIFYING:
        for card in client.generate_clarify(iteration.effective_idea(run)):
            is_critical = bool(card.get("critical", True))
            recommendation = card.get("recommendation", "")
            session.add(
                Decision(
                    run_id=run.id,
                    code=card["code"],
                    question=card["question"],
                    options=card["options"],
                    recommendation=recommendation,
                    consequence=card.get("consequence", ""),
                    is_critical=is_critical,
                    # 非关键决策：AI 自动按推荐回答，事后可改
                    answer=recommendation if not is_critical else None,
                    status="answered" if not is_critical else "open",
                )
            )
        session.commit()
    elif stage == Stage.PRD_DRAFTING:
        _draft_prd(session, run, client)
    elif stage == Stage.BUILDING:
        prd = _load_prd(session, run)
        if run.acceptance_mode == "scenario":
            prd["acceptance_scenarios"] = iteration.json_list(run.acceptance_scenarios)
        if getattr(run, "execution_mode", "workflow") == "agent_team":
            if not agent_harness.execute(session, run, client, prd):
                return Stage.GATE_FAILED
            files = agent_harness.read_files(run.id)
            evidence.add_evidence(session, run, "code", "代码产物", files.get("app.py", ""))
            evidence.add_evidence(session, run, "readme", "运行说明", files.get("README.md", ""))
            return None
        context = iteration.json_dict(run.parent_context)
        kwargs = {"source_context": context} if context else {}
        idea = iteration.effective_idea(run)
        code = client.generate_code(idea, prd, **kwargs)
        app_path = _write_code(run, code)
        # 语法错误（常见于模型夹带非代码文字）：带修正提示重生成一次
        if not _py_syntax_ok(app_path):
            code = client.generate_code(
                idea + "（务必只输出语法正确的 Python 代码，禁止夹带任何非代码文字）",
                prd, **kwargs,
            )
            _write_code(run, code)
        evidence.add_evidence(session, run, "code", "代码产物", code.get("app", ""))
        readme_text = (code.get("readme") or "").strip() or "（模型未给出 README，请查看代码目录。）"
        evidence.add_evidence(session, run, "readme", "运行说明", readme_text)
    elif stage == Stage.TESTING:
        if getattr(run, "execution_mode", "workflow") == "agent_team":
            state = agent_harness.load_state(run)
            if state.get("status") == "completed" and state.get("validated_source_hash") == agent_harness.source_hash(run.id):
                # 双角色已执行真实检查并写 test_result；不伪造或重复一次检查事件。
                return None
            agent_harness._fail(
                session, run, state or agent_harness._new_state(),
                "当前源码没有匹配的独立验证记录，请创建修改版本重新协作验证",
            )
            return Stage.GATE_FAILED
        ok = _run_tests(session, run)
        if not ok:
            # 测试失败立即失败终态，跳过部署/证据，避免无效产物
            return Stage.GATE_FAILED
    elif stage == Stage.DEPLOYING:
        paths = deploy.generate_deploy(run.id, run.idea)
        start_body = Path(paths["start_sh"]).read_text(encoding="utf-8")
        checklist_body = Path(paths["checklist"]).read_text(encoding="utf-8")
        deploy_content = (
            "## start.sh\n\n"
            f"```bash\n{start_body.rstrip()}\n```\n\n"
            f"{checklist_body.strip()}\n"
        )
        evidence.add_evidence(session, run, "deploy", "部署产物", deploy_content)
    elif stage == Stage.EVIDENCE_READY:
        evidence.build_evidence(session, run)
    # 等待点与终态无动作
    return None


def advance(session: Session, run: FactoryRun) -> None:
    """推进流水线，直到人工等待点或终态。"""
    session.refresh(run)
    if Stage(run.current_stage) in TERMINAL_STAGES:
        return
    start = time.monotonic()
    client = None
    outcome = "completed"
    with _background_runs_guard:
        _active_advances.add(run.id)
    try:
        effective = (getattr(run, "llm_provider", None) or "").strip() or None
        client = llm.get_llm(effective)
        if not (getattr(run, "llm_model_snapshot", None) or "").strip():
            run.llm_model_snapshot = llm.provider_model_label(effective)
            run.llm_provider = llm.resolve_provider(effective)
            session.commit()
        if hasattr(client, "model") and run.llm_model_snapshot != "mock":
            client.model = run.llm_model_snapshot
        while True:
            session.refresh(run)
            stage = Stage(run.current_stage)
            if stage in TERMINAL_STAGES:
                return
            if stage == Stage.AWAITING_ANSWERS and not gates.all_decisions_answered(session, run):
                return
            if stage == Stage.AWAITING_PRD_CONFIRM and not gates.prd_confirmed(session, run):
                return
            if stage == Stage.AWAITING_ACCEPTANCE and not gates.acceptance_confirmed(session, run):
                return
            override = _action(session, run, stage, client)
            session.refresh(run, ["current_stage", "status"])
            if Stage(run.current_stage) in TERMINAL_STAGES:
                return
            if override is not None:
                next_stage = override
            else:
                next_stage = NEXT_STAGE[stage]
                if next_stage == Stage.GATE_PASSED and not gates.final_gate(session, run):
                    next_stage = Stage.GATE_FAILED
                    run.failure_reason = "闸门检查未通过（测试或部署产物缺失）"
                    run.failure_code = "gate_failed"
            _transition(session, run, next_stage)
            run.status = "done" if next_stage in TERMINAL_STAGES else "running"
            session.commit()
    except agent_harness.ExecutionStopped:
        session.rollback()
        return
    except Exception:
        outcome = "failed"
        session.rollback()
        raise
    finally:
        try:
            session.refresh(run)
            if run.current_stage == Stage.CANCELLED.value:
                outcome = "cancelled"
            elif run.current_stage in {Stage.FAILED.value, Stage.GATE_FAILED.value}:
                outcome = "failed"
            metrics.record_metric(session, run, client, start, outcome=outcome)
        finally:
            with _background_runs_guard:
                _active_advances.discard(run.id)


def _mark_failed(session: Session, run_id: str, code: str, message: str) -> None:
    """把运行标记为失败终态，并落一条 error 事件供 SSE 与前端透出。"""
    run = session.get(FactoryRun, run_id)
    if run is None:
        return
    run.current_stage = Stage.FAILED.value
    run.status = "done"
    run.failure_reason = message
    run.failure_code = code
    agent_harness.mark_failed(run, message)
    _emit(session, run, Stage.FAILED, event_type="error",
          payload=json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False))


def advance_run(run_id: str) -> None:
    with run_lock(run_id):
        _advance_run_locked(run_id)


def _advance_run_locked(run_id: str) -> None:
    """独立会话推进；供后台线程与测试同步调用。"""
    init_db()
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        if run is None:
            raise AppError("run_not_found", "运行不存在", 404)
        advance(session, run)
    except agent_harness.ExecutionInterrupted:
        logger.info("协作执行中断，保留检查点 run=%s", run_id)
    except AppError as exc:
        logger.warning("运行失败 run=%s code=%s", run_id, exc.code)
        # flush/commit 失败会让 Session 进入待回滚态；失败记录必须用可用事务写入。
        session.rollback()
        _mark_failed(session, run_id, exc.code, exc.message)
    except Exception:
        logger.exception("运行失败 run=%s 未预期异常", run_id)
        session.rollback()
        _mark_failed(session, run_id, "internal_error", "流水线执行失败，请稍后重试")
    finally:
        session.close()




def cancel_run(run_id: str, reason: str = "cancelled") -> None:
    """取消未终态运行；若后台线程仍在推进，下一轮循环会看到终态并退出。"""
    init_db()
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        if run is None:
            raise AppError("run_not_found", "运行不存在", 404)
        stage = Stage(run.current_stage)
        if stage in TERMINAL_STAGES:
            raise AppError("already_terminal", "运行已结束，无法取消", 409)
        run.current_stage = Stage.CANCELLED.value
        run.status = "done"
        agent_harness.mark_cancelled(session, run)
        _emit(
            session,
            run,
            Stage.CANCELLED,
            event_type="cancelled",
            payload=json.dumps({"reason": reason}, ensure_ascii=False),
        )
        session.commit()
        with _background_runs_guard:
            active = run.id in _active_advances
        if not active:
            metrics.record_metric(session, run, None, time.monotonic(), outcome="cancelled")
    finally:
        session.close()




def retest_run(run_id: str) -> None:
    """就地重测；协作预算边界误判只恢复原开发检查点，仍需独立验证。"""
    with run_lock(run_id):
        _retest_run_locked(run_id)


def _retest_run_locked(run_id: str) -> None:
    init_db()
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        if run is None:
            raise AppError("run_not_found", "运行不存在", 404)
        stage = Stage(run.current_stage)
        state = agent_harness.load_state(run)
        recover_checked_builder = agent_harness.can_recover_builder_budget(run, state)
        if getattr(run, "execution_mode", "workflow") == "agent_team" and state.get("status") in {"failed", "cancelled", "interrupted"} and not recover_checked_builder:
            raise AppError("agent_retest_not_allowed", "协作预算和检查点不能通过重测重置；中断请继续执行，失败请创建修改版本", 409)
        allowed = {Stage.GATE_FAILED, Stage.FAILED}
        if stage not in allowed:
            raise AppError(
                "not_retestable",
                "当前状态不能仅重测，仅闸门失败（或失败且已有代码）可续跑测试",
                409,
            )
        if not testing.has_app_code(run_id):
            raise AppError(
                "no_code_to_retest",
                "磁盘上没有该运行的生成代码，请使用「整段重跑」",
                409,
            )
        if recover_checked_builder and not gates.prd_confirmed(session, run):
            raise AppError("prd_not_confirmed", "请先完成人工需求确认", 409)
        run.failure_reason = None
        run.failure_code = ""
        run.status = "running"
        if recover_checked_builder:
            state["status"], state["stop_reason"] = "running", ""
            run.execution_state = iteration.dump(state)
            session.add(StageEvent(
                run_id=run.id, stage=Stage.BUILDING.value, event_type="agent_execution",
                payload="恢复已通过检查的开发检查点；六次调用预算保持不变，仍须独立验证与人工验收",
            ))
            _transition(session, run, Stage.BUILDING)
        else:
            _transition(session, run, Stage.TESTING)
        session.commit()
    finally:
        session.close()
    start_run_async(run_id)


def recover_interrupted_executions() -> int:
    """服务启动时只标记遗留协作任务，不自动重放工具或越过人审。"""
    count = 0
    with SessionLocal() as session:
        runs = session.query(FactoryRun).filter(FactoryRun.execution_mode == "agent_team").all()
        for run in runs:
            if agent_harness.load_state(run).get("status") == "running" and run.current_stage in {"building", "testing"}:
                agent_harness.mark_interrupted(session, run, "服务已重启，可从已保存检查点继续")
                count += 1
    return count


def prepare_execution_resume(session: Session, run: FactoryRun) -> None:
    """调用者持有 run_lock；只消费中断检查点，不重置任何调用或修复预算。"""
    session.refresh(run)
    state = agent_harness.load_state(run)
    if getattr(run, "execution_mode", "workflow") != "agent_team" or not agent_harness._can_resume(run, state):
        raise AppError("execution_not_resumable", "当前执行没有可恢复的中断检查点", 409)
    if not gates.prd_confirmed(session, run):
        raise AppError("prd_not_confirmed", "请先完成人工需求确认", 409)
    state["status"], state["stop_reason"] = "running", ""
    run.execution_state = iteration.dump(state)
    run.status, run.failure_code, run.failure_reason = "running", "", None
    session.add(StageEvent(run_id=run.id, stage=run.current_stage, event_type="agent_execution", payload="继续已保存的协作检查点；预算保持不变"))
    session.commit()

def start_run_async(run_id: str) -> None:
    def worker():
        try:
            advance_run(run_id)
        finally:
            with _background_runs_guard:
                _background_runs.discard(threading.current_thread())

    thread = threading.Thread(target=worker, daemon=True, name=f"factory-run-{run_id[:8]}")
    with _background_runs_guard:
        _background_runs.add(thread)
        thread.start()


def wait_for_background_runs(timeout: float = 30.0) -> None:
    """等待已启动的阶段推进收尾；用于关闭/测试清理，不自动重放任何任务。"""
    deadline = time.monotonic() + timeout
    while True:
        with _background_runs_guard:
            threads = [thread for thread in _background_runs if thread is not threading.current_thread()]
        if not threads:
            return
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("后台流水线尚未结束，拒绝在运行中清理数据库")
            thread.join(remaining)
