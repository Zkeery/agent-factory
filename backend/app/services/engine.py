"""流水线引擎：按固定工序推进状态机，动作由确定性代码执行，模型只产出内容。"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, SessionLocal, StageEvent, init_db
from app.services import deploy, evidence, failure_reasons, gates, llm, metrics, testing
from app.services.prd_normalize import normalize_prd_fields
from app.services.stages import NEXT_STAGE, TERMINAL_STAGES, Stage

logger = logging.getLogger("factory.engine")

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


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
    """把 8 字段 PRD 字典转成可读的 Markdown（不含标题，标题由证据条目承载）。"""
    fields = [
        ("目标用户与核心任务", prd.get("goal_users", "")),
        ("输入、过程和产物", prd.get("input_process_output", "")),
        ("Agent 主链路", prd.get("main_loop", "")),
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
    return "\n".join(lines).strip()


def _run_tests(session: Session, run: FactoryRun) -> bool:
    """对生成的代码骨架做真实语法检查 + smoke 运行，不依赖模型。"""
    ok, reason = testing.run_tests(run.id, idea=run.idea)
    _emit(session, run, Stage.TESTING, event_type="test_result", payload=("passed" if ok else f"failed: {reason}"))
    if not ok:
        run.failure_reason = f"代码测试未通过：{reason}"
        run.failure_code = failure_reasons.classify_test_reason(reason)
        session.commit()
    return ok


def _load_prd(session: Session, run: FactoryRun) -> dict:
    """从证据包读取已确认的 PRD JSON；缺失时返回空字典。"""
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
    """改非关键决策后重新生成 PRD 草稿，覆盖旧 prd 证据（保持 awaiting_prd_confirm）。"""
    old_items = (
        session.query(EvidenceItem)
        .filter(EvidenceItem.run_id == run.id, EvidenceItem.stage == "prd")
        .all()
    )
    for it in old_items:
        session.delete(it)
    session.commit()

    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    client = llm.get_llm((getattr(run, "llm_provider", None) or "").strip() or None)
    prd = client.generate_prd(
        run.idea,
        [{"code": d.code, "question": d.question, "answer": d.answer} for d in decisions],
    )
    prd = normalize_prd_fields(prd)
    evidence.add_evidence(session, run, "prd", "PRD 草稿", prd_to_markdown(prd))


def _action(session: Session, run: FactoryRun, stage: Stage, client) -> Stage | None:
    if stage == Stage.CLARIFYING:
        for card in client.generate_clarify(run.idea):
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
        decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
        prd = client.generate_prd(
            run.idea,
            [
                {"code": d.code, "question": d.question, "answer": d.answer}
                for d in decisions
            ],
        )
        prd = normalize_prd_fields(prd)
        evidence.add_evidence(session, run, "prd", "PRD 草稿", prd_to_markdown(prd))
    elif stage == Stage.BUILDING:
        prd = _load_prd(session, run)
        code = client.generate_code(run.idea, prd)
        app_path = _write_code(run, code)
        # 语法错误（常见于模型夹带非代码文字）：带修正提示重生成一次
        if not _py_syntax_ok(app_path):
            code = client.generate_code(
                run.idea + "（务必只输出语法正确的 Python 代码，禁止夹带任何非代码文字）",
                prd,
            )
            _write_code(run, code)
        evidence.add_evidence(session, run, "code", "代码产物", code.get("app", ""))
        readme_text = (code.get("readme") or "").strip() or "（模型未给出 README，请查看代码目录。）"
        evidence.add_evidence(session, run, "readme", "运行说明", readme_text)
    elif stage == Stage.TESTING:
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
    effective = (getattr(run, "llm_provider", None) or "").strip() or None
    client = llm.get_llm(effective)
    # 首次真正取客户端时固化模型快照，便于复盘（不随后续改 .env 而变）
    if not (getattr(run, "llm_model_snapshot", None) or "").strip():
        run.llm_model_snapshot = llm.provider_model_label(effective)
        session.add(run)
        session.commit()
    start = time.monotonic()
    while True:
        session.refresh(run)
        stage = Stage(run.current_stage)
        if stage in TERMINAL_STAGES:
            return
        if stage == Stage.AWAITING_ANSWERS and not gates.all_decisions_answered(session, run):
            metrics.record_metric(session, run, client, start)
            return
        if stage == Stage.AWAITING_PRD_CONFIRM and not gates.prd_confirmed(session, run):
            metrics.record_metric(session, run, client, start)
            return
        if stage == Stage.AWAITING_ACCEPTANCE and not gates.acceptance_confirmed(session, run):
            # 等人验收；确认记录 kind=acceptance
            metrics.record_metric(session, run, client, start)
            return
        override = _action(session, run, stage, client)
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
        if next_stage in TERMINAL_STAGES:
            metrics.record_metric(session, run, client, start)


def _mark_failed(session: Session, run_id: str, code: str, message: str) -> None:
    """把运行标记为失败终态，并落一条 error 事件供 SSE 与前端透出。"""
    run = session.get(FactoryRun, run_id)
    if run is None:
        return
    run.current_stage = Stage.FAILED.value
    run.status = "done"
    run.failure_reason = message
    run.failure_code = code
    _emit(session, run, Stage.FAILED, event_type="error",
          payload=json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False))


def advance_run(run_id: str) -> None:
    """独立会话推进；供后台线程与测试同步调用。"""
    init_db()
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        if run is None:
            raise AppError("run_not_found", "运行不存在", 404)
        advance(session, run)
    except AppError as exc:
        logger.warning("运行失败 run=%s code=%s", run_id, exc.code)
        _mark_failed(session, run_id, exc.code, exc.message)
    except Exception:
        logger.exception("运行失败 run=%s 未预期异常", run_id)
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
        _emit(
            session,
            run,
            Stage.CANCELLED,
            event_type="cancelled",
            payload=json.dumps({"reason": reason}, ensure_ascii=False),
        )
        session.commit()
    finally:
        session.close()




def retest_run(run_id: str) -> None:
    """闸门失败/有代码的失败：就地拨回 testing 并异步续跑，不新建 Run、不删产物。"""
    init_db()
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        if run is None:
            raise AppError("run_not_found", "运行不存在", 404)
        stage = Stage(run.current_stage)
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
        run.failure_reason = None
        run.failure_code = ""
        run.status = "running"
        _transition(session, run, Stage.TESTING)
        session.commit()
    finally:
        session.close()
    start_run_async(run_id)

def start_run_async(run_id: str) -> None:
    threading.Thread(target=advance_run, args=(run_id,), daemon=True).start()
