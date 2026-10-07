"""双角色工具执行器：持久化预算和检查点，模型只能选择白名单工具。

外层状态机与人审闸门仍由 engine 控制。本模块的成功仅表示自动技术检查通过。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models import FactoryRun, StageEvent
from app.services import iteration, testing

MAX_TURNS = 6
MAX_REPAIRS = 2
ALLOWED_FILES = {"app.py", "requirements.txt", "README.md"}
MAX_FILE_BYTES = 300_000
PROMPTS = Path(__file__).resolve().parent / "prompts"
TERMINAL = {"failed", "gate_failed", "cancelled", "delivered"}


class ExecutionInterrupted(AppError):
    def __init__(self, message: str = "执行已中断，可从保存的检查点继续"):
        super().__init__("execution_interrupted", message, 409)


class ExecutionStopped(Exception):
    """取消或外层终态阻止继续执行；不是可绕过的恢复入口。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_text(value: object, limit: int = 360) -> str:
    text = str(value).replace("```", "").replace("\x00", "")
    for secret in (settings.llm_api_key, settings.api_key):
        if secret:
            text = text.replace(secret, "[已隐藏]")
    return " ".join(text.split())[:limit]


def load_state(run: FactoryRun) -> dict:
    state = iteration.json_dict(getattr(run, "execution_state", "{}"))
    return state if state.get("version") == 1 else {}


def _new_state() -> dict:
    return {
        "version": 1, "status": "running", "active_role": "builder", "repair_rounds": 0,
        "stop_reason": "", "tasks": [], "steps": [], "handoffs": [], "checks": [],
        "messages": {}, "turns": {}, "pending": None, "last_check": None,
    }


def _task_id(role: str, round_number: int) -> str:
    return f"{role}:{round_number}"


def _builder_budget_reason() -> str:
    return "开发与修复已达到每轮六次模型调用上限"


def _checked_builder_budget_ready(run: FactoryRun, state: dict) -> bool:
    """只允许已完成真实检查的开发者在预算边界交接，不产生模型结论。"""
    round_number = state.get("repair_rounds", 0)
    task_id = _task_id("builder", round_number)
    if (state.get("active_role") != "builder" or round_number > MAX_REPAIRS
            or state.get("turns", {}).get(task_id) != MAX_TURNS or state.get("pending")):
        return False
    task = next((item for item in state.get("tasks", []) if item.get("id") == task_id), None)
    if not task or task.get("role") != "builder" or task.get("round") != round_number:
        return False
    if any(item.get("id") != task_id and item.get("status") != "completed" for item in state.get("tasks", [])):
        return False
    checked = state.get("last_check") or {}
    checks = state.get("checks", [])
    if not (checked.get("passed") is True and checked.get("role") == "builder"
            and checked.get("round") == round_number and checks and checks[-1] == checked):
        return False
    steps = state.get("steps", [])
    check_index = next((i for i, step in enumerate(steps) if step.get("id") == checked.get("id")), None)
    if check_index is None:
        return False
    check_step = steps[check_index]
    if check_step.get("task_id") != task_id or check_step.get("tool") != "run_checks":
        return False
    # 已提交检查及其后的动作必须全部结束；失败/未提交的后续动作不能被预算收束掩盖。
    if any(step.get("status") != "completed" for step in steps[check_index:]):
        return False
    if any(step.get("status") == "running" for step in steps[:check_index]):
        return False
    try:
        return set(read_files(run.id)) == ALLOWED_FILES and checked.get("source_hash") == source_hash(run.id)
    except (OSError, UnicodeError, ValueError):
        return False


def can_recover_builder_budget(run: FactoryRun, state: dict | None = None) -> bool:
    """识别旧执行器在检查通过后因缺少 handoff 调用而误报的唯一失败类型。"""
    state = load_state(run) if state is None else state
    return bool(
        getattr(run, "execution_mode", "workflow") == "agent_team"
        and run.current_stage == "gate_failed" and state.get("status") == "failed"
        and run.failure_code == "agent_execution_failed"
        and run.failure_reason == state.get("stop_reason") == _builder_budget_reason()
        and _checked_builder_budget_ready(run, state)
    )


def _can_resume(run: FactoryRun, state: dict) -> bool:
    if state.get("status") != "interrupted" or run.current_stage not in {"building", "testing"}:
        return False
    if state.get("repair_rounds", 0) > MAX_REPAIRS:
        return False
    task_id = _task_id(state.get("active_role", "builder"), state.get("repair_rounds", 0))
    return (bool(state.get("pending")) or state.get("turns", {}).get(task_id, 0) < MAX_TURNS
            or _checked_builder_budget_ready(run, state))


def execution_view(run: FactoryRun) -> dict:
    """只投影可公开的摘要，私有消息、工具参数与源码绝不出现在 API 中。"""
    state = load_state(run)
    mode = getattr(run, "execution_mode", "workflow") or "workflow"
    keys = {
        "tasks": ("id", "role", "title", "status", "round", "started_at", "finished_at", "input_summary", "output_summary"),
        "steps": ("id", "task_id", "role", "round", "sequence", "tool", "status", "summary", "created_at", "duration_ms", "input_tokens", "output_tokens"),
        "handoffs": ("id", "from_role", "to_role", "round", "reason", "created_at"),
        "checks": ("id", "round", "passed", "summary", "created_at"),
    }
    result = {
        "run_id": run.id, "execution_mode": mode, "status": state.get("status", "pending" if mode == "agent_team" else "not_enabled"),
        "active_role": state.get("active_role"),
        "limits": {"max_turns_per_agent": MAX_TURNS, "max_repair_rounds": MAX_REPAIRS},
        "repair_rounds": state.get("repair_rounds", 0), "resumable": _can_resume(run, state),
        "stop_reason": state.get("stop_reason", ""),
    }
    for collection, fields in keys.items():
        result[collection] = [{key: item.get(key) for key in fields} for item in state.get(collection, [])]
    return result


def _persist(session: Session, run: FactoryRun, state: dict, event: str | None = None) -> None:
    # 取消可由另一数据库会话发生；不能用旧实例覆盖已提交的终态。
    payload = iteration.dump(state)
    with session.no_autoflush:
        # 条件更新使检查与写入属于同一数据库动作，也挡住 refresh 后才提交的取消。
        persisted = session.execute(
            update(FactoryRun).where(FactoryRun.id == run.id, FactoryRun.current_stage.not_in(TERMINAL))
            .values(execution_state=payload).execution_options(synchronize_session=False)
        ).rowcount
    if persisted != 1:
        # 丢弃 _fail 尚未提交的 failure_code/reason 和工具事件，重新采用数据库终态。
        session.rollback()
        session.refresh(run)
        raise ExecutionStopped()
    run.execution_state = payload
    if event:
        session.add(StageEvent(run_id=run.id, stage=run.current_stage, event_type="agent_execution", payload=_public_text(event)))
    session.commit()


def mark_interrupted(session: Session, run: FactoryRun, reason: str) -> None:
    state = load_state(run)
    if not state or state.get("status") != "running" or run.current_stage not in {"building", "testing"}:
        return
    state["status"] = "interrupted"
    state["stop_reason"] = _public_text(reason)
    # 硬中断可能来不及执行 finally；恢复不能假定缺失的用量和耗时已完整记账。
    state["accounting_incomplete"] = True
    for task in state["tasks"]:
        if task["status"] == "running":
            task["status"] = "interrupted"
    for step in state["steps"]:
        if step["status"] == "running" and step["tool"] == "model_call":
            step["status"] = "interrupted"
            step["summary"] = "模型返回未提交；该次调用预算已消耗"
    # 最后一次模型调用若未提交任何可重放工具，已没有可恢复预算。
    if not _can_resume(run, state):
        state["status"] = "failed"
        state["stop_reason"] = "角色调用预算已耗尽"
        run.current_stage, run.status = "gate_failed", "done"
        run.failure_code, run.failure_reason = "agent_budget_exhausted", state["stop_reason"]
    else:
        run.status = "paused"
    run.execution_state = iteration.dump(state)
    session.add(StageEvent(run_id=run.id, stage=run.current_stage, event_type="agent_execution", payload=state["stop_reason"]))
    session.commit()


def mark_cancelled(session: Session, run: FactoryRun) -> None:
    state = load_state(run)
    if not state or state.get("status") in {"completed", "failed", "cancelled"}:
        return
    state["status"], state["stop_reason"] = "cancelled", "用户取消执行"
    for task in state["tasks"]:
        if task["status"] in {"running", "interrupted"}:
            task.update(status="cancelled", finished_at=_now(), output_summary="用户取消执行")
    for step in state["steps"]:
        if step["status"] == "running":
            step.update(status="cancelled", summary="用户取消执行")
    run.execution_state = iteration.dump(state)


def mark_failed(run: FactoryRun, reason: str) -> None:
    """外层异常/看门狗失败同步关闭活动角色，不展示仍在执行的旧摘要。"""
    state = load_state(run)
    if not state or state.get("status") in {"completed", "failed", "cancelled"}:
        return
    state["status"], state["stop_reason"] = "failed", _public_text(reason)
    for task in state["tasks"]:
        if task["status"] in {"running", "interrupted"}:
            task.update(status="failed", finished_at=_now(), output_summary=state["stop_reason"])
    for step in state["steps"]:
        if step["status"] == "running":
            step.update(status="failed", summary=state["stop_reason"])
    run.execution_state = iteration.dump(state)


def _path(run_id: str, name: str) -> Path:
    if name not in ALLOWED_FILES:
        raise ValueError("工具只能访问 app.py、requirements.txt、README.md")
    directory = testing._code_dir(run_id)
    unresolved = testing.DATA_ROOT / "code" / "".join(c for c in run_id if c.isalnum() or c in "-_")
    path = directory / name
    if unresolved.is_symlink() or path.is_symlink():
        raise ValueError("拒绝通过符号链接读写源文件")
    return path


def source_hash(run_id: str) -> str:
    digest = hashlib.sha256()
    for name in sorted(ALLOWED_FILES):
        path = _path(run_id, name)
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def read_files(run_id: str) -> dict[str, str]:
    return {name: _path(run_id, name).read_text(encoding="utf-8") for name in sorted(ALLOWED_FILES) if _path(run_id, name).is_file()}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False,
    }}}


def role_tools(role: str) -> list[dict]:
    tools = [
        _tool("read_file", "读取当前产物中的一个源文件", {"path": {"type": "string", "enum": sorted(ALLOWED_FILES)}}, ["path"]),
        _tool("run_checks", "真实运行语法、产物护栏、受限导入、HTTP主路径检查；不代表人工业务验收", {}, []),
        _tool("handoff", "开发者交给验证者；验证者交回开发者修复（最多两轮）", {"reason": {"type": "string"}}, ["reason"]),
    ]
    if role == "builder":
        tools.append(_tool("write_files", "提交完整文件内容，只允许三个指定文件；保留未要求修改的功能", {"files": {
            "type": "object", "properties": {name: {"type": "string"} for name in sorted(ALLOWED_FILES)},
            "additionalProperties": False,
        }}, ["files"]))
    else:
        tools.append(_tool("conclude", "在本角色真实检查后给出技术结论；失败将交回开发者修复", {
            "passed": {"type": "boolean"}, "summary": {"type": "string"},
        }, ["passed", "summary"]))
    return tools


def _context(run: FactoryRun, prd: dict, state: dict) -> dict:
    return {
        "idea": iteration.effective_idea(run), "prd": prd,
        "source_context": iteration.json_dict(run.parent_context),
        "repair_round": state["repair_rounds"],
        "verification_feedback": state.get("repair_feedback", ""),
        "last_check": state.get("last_check"),
        "files": read_files(run.id),
        "automatic_checks_only": True,
    }


def _ensure_task(session: Session, run: FactoryRun, state: dict, prd: dict) -> dict:
    role, round_number = state["active_role"], state["repair_rounds"]
    task_id = _task_id(role, round_number)
    task = next((t for t in state["tasks"] if t["id"] == task_id), None)
    if task is None:
        task = {
            "id": task_id, "role": role, "title": "开发与修复" if role == "builder" else "独立技术验证",
            "status": "running", "round": round_number, "started_at": _now(), "finished_at": None,
            "input_summary": "已确认需求、父版本与验证反馈" if role == "builder" else "已确认需求、验收场景与当前源码",
            "output_summary": "",
        }
        state["tasks"].append(task)
        state["turns"].setdefault(task_id, 0)
        state["messages"][task_id] = [
            {"role": "system", "content": (PROMPTS / f"agent_{role}.md").read_text(encoding="utf-8")},
            {"role": "user", "content": iteration.dump(_context(run, prd, state))},
        ]
    task["status"] = "running"
    _persist(session, run, state)
    return task


def _step(state: dict, task: dict, tool: str) -> dict:
    step = {
        "id": uuid.uuid4().hex, "task_id": task["id"], "role": task["role"], "round": task["round"],
        "sequence": len(state["steps"]) + 1, "tool": tool, "status": "running", "summary": "执行中",
        "created_at": _now(), "duration_ms": 0, "input_tokens": 0, "output_tokens": 0,
    }
    state["steps"].append(step)
    return step


def _fail(session: Session, run: FactoryRun, state: dict, reason: str) -> bool:
    state["status"], state["stop_reason"] = "failed", _public_text(reason)
    for task in state["tasks"]:
        if task["status"] == "running":
            task.update(status="failed", finished_at=_now(), output_summary=state["stop_reason"])
    run.failure_code, run.failure_reason = "agent_execution_failed", state["stop_reason"]
    _persist(session, run, state, reason)
    return False


def _handoff(state: dict, task: dict, reason: str) -> None:
    role = task["role"]
    target = "verifier" if role == "builder" else "builder"
    state["handoffs"].append({
        "id": uuid.uuid4().hex, "from_role": role, "to_role": target, "round": state["repair_rounds"],
        "reason": _public_text(reason), "created_at": _now(),
    })
    task.update(status="completed", finished_at=_now(), output_summary=_public_text(reason))
    state["active_role"] = target
    if role == "verifier":
        state["repair_rounds"] += 1
        state["repair_feedback"] = reason


def _handoff_checked_builder_budget(session: Session, run: FactoryRun, state: dict, task: dict) -> bool:
    if not _checked_builder_budget_ready(run, state):
        return False
    reason = "执行器自动交接：六次模型调用已用完，当前源码真实检查已通过；继续独立验证，未生成模型结论"
    step = _step(state, task, "budget_handoff")
    step.update(status="completed", summary=reason)
    _handoff(state, task, reason)
    _persist(session, run, state, reason)
    return True


def _validate_arguments(name: str, args: object) -> dict:
    fields = {"read_file": {"path"}, "write_files": {"files"}, "run_checks": set(), "handoff": {"reason"}, "conclude": {"passed", "summary"}}
    if name not in fields or not isinstance(args, dict) or set(args) != fields[name]:
        raise ValueError("工具参数不符合声明")
    if name == "read_file" and not isinstance(args["path"], str):
        raise ValueError("path 必须是文件名")
    if name == "handoff" and (not isinstance(args["reason"], str) or not args["reason"].strip()):
        raise ValueError("交接需要说明原因")
    if name == "conclude" and (type(args["passed"]) is not bool or not isinstance(args["summary"], str)):
        raise ValueError("结论需要布尔 passed 和文字 summary")
    return args


def _execute_tool(session: Session, run: FactoryRun, state: dict, task: dict, step: dict, call: dict, prd: dict) -> dict:
    name = call["name"]
    allowed = {t["function"]["name"] for t in role_tools(task["role"])}
    if name not in allowed:
        raise ValueError("当前角色没有该工具权限")
    args = _validate_arguments(name, call.get("arguments"))
    if name == "read_file":
        path = _path(run.id, args["path"])
        step["summary"] = f"读取 {args['path']}"
        return {"path": args["path"], "content": path.read_text(encoding="utf-8") if path.is_file() else "", "exists": path.is_file()}
    if name == "write_files":
        files = args["files"]
        if not isinstance(files, dict) or not files or set(files) - ALLOWED_FILES:
            raise ValueError("只能提交白名单中的源文件")
        if any(not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES for content in files.values()):
            raise ValueError("文件必须为文本且不超过 300KB")
        # 先验证全部路径，再写入；每个文件以 replace 提交。中断时可幂等重放同一调用。
        paths = {name: _path(run.id, name) for name in files}
        for name, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{step['id']}.tmp")
            try:
                temp.write_text(files[name], encoding="utf-8")
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        state["last_check"] = None
        step["summary"] = "提交源码：" + "、".join(sorted(files))
        return {"written": sorted(files), "source_hash": source_hash(run.id)}
    if name == "run_checks":
        snapshot = source_hash(run.id)
        passed, diagnosis = testing.run_tests(run.id, idea=run.idea, output_type=prd.get("output_type"))
        if snapshot != source_hash(run.id):
            passed, diagnosis = False, "检查期间源文件发生变化，需要重新检查"
        # Python 编译错误常带源码行；公开记录只呈现最后一行诊断，完整结果留在私有工具会话。
        public_diagnosis = _public_text((str(diagnosis).splitlines() or ["检查未提供诊断"])[-1], 360)
        diagnosis = _public_text(diagnosis, 1200)
        check = {
            "id": step["id"], "round": task["round"], "passed": passed,
            "summary": "自动技术检查通过；业务效果待人工验收" if passed else public_diagnosis, "created_at": _now(),
            "diagnosis": diagnosis,
            "source_hash": snapshot, "role": task["role"],
        }
        state["checks"].append(check)
        state["last_check"] = check
        # 与旧 gates/复盘契约一致：只记录真实运行检查所得结果。
        session.add(StageEvent(run_id=run.id, stage="testing", event_type="test_result", payload="passed" if passed else f"failed: {diagnosis}"))
        step["summary"] = check["summary"]
        return {"passed": passed, "diagnosis": diagnosis, "source_hash": snapshot, "business_acceptance": "pending_human"}
    if name == "handoff" and task["role"] == "builder":
        if set(read_files(run.id)) != ALLOWED_FILES:
            raise ValueError("交接前需提交完整的三个源文件")
        _handoff(state, task, "源码已提交，交给独立验证角色")
        step["summary"] = "开发者 → 验证者"
        return {"next_role": "verifier"}
    if name == "conclude" and args["passed"]:
        checked = state.get("last_check") or {}
        if not (checked.get("passed") is True and checked.get("role") == "verifier" and checked.get("round") == task["round"] and checked.get("source_hash") == source_hash(run.id)):
            raise ValueError("验证角色必须对当前源码亲自运行检查且通过，才能给出通过结论")
        state["status"], state["stop_reason"] = "completed", "自动技术检查通过，等待人工业务验收"
        state["validated_source_hash"] = checked["source_hash"]
        task.update(status="completed", finished_at=_now(), output_summary=state["stop_reason"])
        step["summary"] = state["stop_reason"]
        return {"completed": True, "business_acceptance": "pending_human"}
    # verifier 的否定结论或明确交回都会消耗一轮修复；不允许无限重开任务。
    if state["repair_rounds"] >= MAX_REPAIRS:
        state["status"], state["stop_reason"] = "failed", "已达到两轮自动修复上限"
        task.update(status="failed", finished_at=_now(), output_summary=state["stop_reason"])
        step["summary"] = state["stop_reason"]
        return {"failed": True, "reason": state["stop_reason"]}
    feedback = args.get("reason") or args.get("summary") or "验证未通过"
    checked = state.get("last_check") or {}
    if checked.get("passed") is False:
        feedback += "；真实检查诊断：" + checked.get("diagnosis", checked["summary"])
    _handoff(state, task, _public_text(feedback, 1500))
    state["handoffs"][-1]["reason"] = "验证发现问题，交回开发者修复；详见自动检查记录"
    task["output_summary"] = state["handoffs"][-1]["reason"]
    step["summary"] = "验证者 → 开发者，开始有限修复"
    return {"next_role": "builder", "repair_round": state["repair_rounds"]}


def execute(session: Session, run: FactoryRun, client, prd: dict) -> bool:
    state = load_state(run)
    if state.get("status") == "completed":
        if state.get("validated_source_hash") != source_hash(run.id):
            return _fail(session, run, state, "已验证源码发生变化，需要创建修改版本重新检查")
        return True
    if state.get("status") in {"failed", "cancelled"}:
        return False
    if state.get("status") == "interrupted":
        raise ExecutionInterrupted()
    if not state:
        state = _new_state()
        _persist(session, run, state, "开始开发者与验证者工具协作")
    try:
        while state["status"] == "running":
            session.refresh(run, ["current_stage", "status"])
            if run.current_stage in TERMINAL:
                raise ExecutionStopped()
            task = _ensure_task(session, run, state, prd)
            messages = state["messages"][task["id"]]
            pending = state.get("pending")
            if pending:
                call = pending["calls"][pending["index"]]
                step = next((s for s in state["steps"] if s["id"] == pending.get("step_id")), None)
                if step is None:
                    step = _step(state, task, call["name"])
                    pending["step_id"] = step["id"]
                    _persist(session, run, state)
                started = time.monotonic()
                try:
                    result = _execute_tool(session, run, state, task, step, call, prd)
                    step["status"] = "completed"
                except (ValueError, UnicodeError) as exc:
                    result = {"error": _public_text(exc)}
                    step.update(status="failed", summary=_public_text(exc))
                step["duration_ms"] = round((time.monotonic() - started) * 1000)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": iteration.dump(result)})
                pending["index"] += 1
                pending.pop("step_id", None)
                if pending["index"] >= len(pending["calls"]) or state["active_role"] != task["role"] or state["status"] != "running":
                    # 交接/结束调用必须是本次返回的最后一个工具，校验在模型响应入口完成。
                    state["pending"] = None
                _persist(session, run, state, step["summary"])
                continue
            used = state["turns"].get(task["id"], 0)
            if used >= MAX_TURNS:
                if _handoff_checked_builder_budget(session, run, state, task):
                    continue
                return _fail(session, run, state, f"{task['title']}已达到每轮六次模型调用上限")
            state["turns"][task["id"]] = used + 1
            step = _step(state, task, "model_call")
            _persist(session, run, state)  # 在网络请求前消耗预算，进程中断也不会清零。
            started = time.monotonic()
            before_input, before_output = getattr(client, "prompt_tokens", 0), getattr(client, "completion_tokens", 0)
            try:
                response = client.agent_turn(task["role"], messages, role_tools(task["role"]), _context(run, prd, state))
            finally:
                step["duration_ms"] = round((time.monotonic() - started) * 1000)
                step["input_tokens"] = max(0, getattr(client, "prompt_tokens", 0) - before_input)
                step["output_tokens"] = max(0, getattr(client, "completion_tokens", 0) - before_output)
            calls = response.get("tool_calls") if isinstance(response, dict) else None
            valid = isinstance(calls, list) and 0 < len(calls) <= 3 and all(
                isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("name"), str) for c in calls
            )
            if valid:
                valid = len({c["id"] for c in calls}) == len(calls) and all(c["name"] not in {"handoff", "conclude"} for c in calls[:-1])
            if not valid:
                step.update(status="failed", summary="模型未返回有效工具调用，未执行任何动作")
                messages.append({"role": "user", "content": "必须使用声明的工具；每次最多3项调用，交接或结论仅能出现在最后。请重试，预算不会重置。"})
                _persist(session, run, state, step["summary"])
                continue
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": iteration.dump(c.get("arguments"))}} for c in calls
            ]})
            step.update(status="completed", summary=f"模型选择了 {len(calls)} 项工具动作")
            state["pending"] = {"task_id": task["id"], "calls": calls, "index": 0}
            _persist(session, run, state)
        if state["status"] == "failed":
            return _fail(session, run, state, state["stop_reason"])
        return state["status"] == "completed"
    except ExecutionStopped:
        session.rollback()
        session.refresh(run)
        return False
    except Exception as exc:
        session.rollback()
        session.refresh(run)
        if run.current_stage in TERMINAL:
            return False
        # 尽量保存本次已取得的用量与耗时；网络/工具中断不退款预算。
        _persist(session, run, state)
        # 私有异常仅写服务日志；公开检查点不泄露原始请求/源码。
        mark_interrupted(session, run, "工具或模型调用中断，已保存已用预算与上次提交的检查点")
        raise ExecutionInterrupted() from exc
