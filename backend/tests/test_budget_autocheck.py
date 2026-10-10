"""预算用尽后的真实检查、初次构建空读，以及截断与预算的交互。"""
from __future__ import annotations

import json
import uuid

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.models import Confirmation, Decision, FactoryRun
from app.services import agent_harness as harness
from app.services import deploy, engine, evidence, llm, runner, testing

SAFE_APP = '''from fastapi import FastAPI
from pydantic import BaseModel
app = FastAPI()
class Request(BaseModel):
    input: str = ""
@app.get("/")
def home():
    return {"ready": True}
@app.post("/generate")
def generate(data: Request):
    return {"output": data.input}
'''
FILES = {"app.py": SAFE_APP, "requirements.txt": "fastapi\nuvicorn\n", "README.md": "本地检查样例；业务效果待人工验证。"}
PRD = {"output_type": "text", "goal_users": "个人用户", "input_process_output": "输入文本返回文本"}


def _isolated(tmp_path, monkeypatch):
    for module in (testing, runner, engine, deploy, evidence):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(settings, "sandbox_mode", "process")
    monkeypatch.setattr(settings, "llm_api_key", "")


def make_run(session, **overrides):
    fields = dict(
        id=str(uuid.uuid4()), idea="文本检查样例", current_stage="building", status="running",
        execution_mode="agent_team", llm_provider="", prd_snapshot=json.dumps(PRD), prd_revision=1,
    )
    fields.update(overrides)
    run = FactoryRun(**fields)
    session.add(run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    return run


def call(name, args=None, ident="call"):
    return {"tool_calls": [{"id": ident, "name": name, "arguments": args or {}}]}


def verifier_turn(messages):
    results = [item for item in messages if item.get("role") == "tool"]
    if not results:
        return call("read_file", {"path": "app.py"}, "v-read")
    if len(results) == 1:
        return call("run_checks", {}, "v-check")
    return call("conclude", {"passed": True, "summary": "自动技术检查通过，业务效果仍待人工验收"}, "v-done")


class WriteThenRead:
    """写出可运行源码后只读文件，把本轮调用用完，自己不跑检查。"""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def agent_turn(self, role, messages, tools, context):
        if role != "builder":
            return verifier_turn(messages)
        results = [item for item in messages if item.get("role") == "tool"]
        if not results:
            return call("write_files", {"files": FILES}, "write")
        return call("read_file", {"path": "app.py"}, f"read-{len(results)}")


class SyntaxThenRepair:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.feedback = []

    def agent_turn(self, role, messages, tools, context):
        if role != "builder":
            return verifier_turn(messages)
        if context.get("repair_round"):
            self.feedback.append(context.get("verification_feedback") or "")
            results = [item for item in messages if item.get("role") == "tool"]
            if not results:
                return call("write_files", {"files": FILES}, "fix")
            if len(results) == 1:
                return call("run_checks", {}, "fix-check")
            return call("handoff", {"reason": "已按检查报错修好主路径"}, "fix-hand")
        results = [item for item in messages if item.get("role") == "tool"]
        if not results:
            broken = dict(FILES)
            broken["app.py"] = "def broken(:\n"
            return call("write_files", {"files": broken}, "bad")
        return call("read_file", {"path": "app.py"}, f"bad-read-{len(results)}")


class ReadBeforeWrite:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seen = []

    def agent_turn(self, role, messages, tools, context):
        self.seen.append(messages)
        if role != "builder":
            return verifier_turn(messages)
        text = json.dumps(messages, ensure_ascii=False)
        names = [
            call["function"]["name"]
            for message in messages if message.get("role") == "assistant"
            for call in (message.get("tool_calls") or [])
        ]
        if "write_files" not in names:
            if "read_file" not in names and "不要再 read_file" not in text:
                return call("read_file", {"path": "app.py"}, "empty-read")
            return call("write_files", {"files": FILES}, "write")
        if "run_checks" not in names:
            return call("run_checks", {}, "check")
        return call("handoff", {"reason": "主路径已提交"}, "hand")


class SmallFilesTogether:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def agent_turn(self, role, messages, tools, context):
        if role != "builder":
            return verifier_turn(messages)
        results = [item for item in messages if item.get("role") == "tool"]
        if not results:
            return call("write_files", {"files": {"app.py": SAFE_APP}}, "app")
        if len(results) == 1:
            return call("write_files", {"files": {"requirements.txt": FILES["requirements.txt"], "README.md": FILES["README.md"]}}, "meta")
        if len(results) == 2:
            return call("run_checks", {}, "check")
        return call("handoff", {"reason": "主路径和说明已提交"}, "hand")


class TruncateThenIdle(WriteThenRead):
    def __init__(self):
        super().__init__()
        self.truncated = False

    def agent_turn(self, role, messages, tools, context):
        if role == "builder" and not self.truncated:
            self.truncated = True
            self.completion_tokens += 8000
            return {"content": "", "finish_reason": "length", "truncated": True, "tool_calls": [
                {"id": "cut", "name": "write_files", "arguments": None},
            ]}
        return super().agent_turn(role, messages, tools, context)


def test_budget_exhaustion_runs_real_check_and_hands_off(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session)
    assert harness.execute(session, run, WriteThenRead(), PRD)
    state = harness.load_state(run)
    assert state["status"] == "completed"
    assert state["turns"]["builder:0"] == harness.MAX_TURNS
    assert not any(
        step["tool"] == "model_call" and "run_checks" in step["summary"]
        for step in state["steps"]
    )
    names = [
        call["function"]["name"]
        for message in state["messages"]["builder:0"]
        for call in (message.get("tool_calls") or [])
    ]
    assert "run_checks" not in names
    automatic = [step for step in state["steps"] if step["summary"].startswith("执行器自动检查")]
    assert automatic and state["checks"][0]["passed"] is True and state["checks"][0]["role"] == "builder"
    assert any(step["tool"] == "budget_handoff" for step in state["steps"])
    assert state["validated_source_hash"] == harness.source_hash(run.id)


def test_failed_check_at_budget_enters_repair_with_diagnosis(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session)
    client = SyntaxThenRepair()
    assert harness.execute(session, run, client, PRD)
    state = harness.load_state(run)
    assert state["status"] == "completed"
    assert state["turns"]["builder:0"] == harness.MAX_TURNS
    assert state["repair_rounds"] >= 1
    assert state["checks"][0]["passed"] is False
    assert any(step["tool"] == "budget_repair" for step in state["steps"])
    assert any("语法" in item or "SyntaxError" in item for item in client.feedback)
    assert state["handoffs"][0]["from_role"] == "builder" and state["handoffs"][0]["to_role"] == "builder"


def test_initial_build_does_not_spend_a_turn_reading_missing_file(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session)
    client = ReadBeforeWrite()
    assert harness.execute(session, run, client, PRD)
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 3
    assert state["empty_read_retries"]["builder:0"] == 1
    assert any("读取空文件不计入调用上限" in step["summary"] for step in state["steps"])
    first = json.dumps(client.seen[0], ensure_ascii=False)
    assert "【本轮预算】" in first and "还剩" in first
    assert "不要调用 read_file" in state["messages"]["builder:0"][0]["content"]
    assert "build_contract" in state["messages"]["builder:0"][1]["content"]
    assert harness.read_files(run.id)["app.py"] == SAFE_APP


def test_parent_source_read_still_consumes_a_turn(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session, parent_context=json.dumps({"files": {"app.py": "print('parent')\n"}}, ensure_ascii=False))
    assert harness.execute(session, run, ReadBeforeWrite(), PRD)
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 4
    assert "empty_read_retries" not in state or "builder:0" not in state.get("empty_read_retries", {})


def test_requirements_and_readme_share_one_write(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session)
    assert harness.execute(session, run, SmallFilesTogether(), PRD)
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 4
    written = [step for step in state["steps"] if step["tool"] == "write_files"]
    assert len(written) == 2
    assert "requirements.txt" in written[1]["summary"] and "README.md" in written[1]["summary"]
    description = next(item["function"]["description"] for item in harness.role_tools("builder") if item["function"]["name"] == "write_files")
    assert "同一次" in description


def test_truncated_call_does_not_block_budget_autocheck(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session)
    client = TruncateThenIdle()
    assert harness.execute(session, run, client, PRD)
    state = harness.load_state(run)
    assert state["truncation_retries"]["builder:0"] == 1
    assert state["turns"]["builder:0"] == harness.MAX_TURNS
    assert client.truncated is True
    assert state["checks"][0]["passed"] is True
    assert any(step["summary"].startswith("执行器自动检查") for step in state["steps"])
    assert any("不计入本轮调用上限" in (item.get("content") or "") for item in state["messages"]["builder:0"])


class LastCheckOnly:
    """把真实检查留到本轮最后一次调用。"""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def agent_turn(self, role, messages, tools, context):
        if role != "builder":
            return verifier_turn(messages)
        turn = sum(item.get("role") == "assistant" for item in messages) + 1
        if turn == 1:
            return call("write_files", {"files": FILES}, "write")
        if turn == harness.MAX_TURNS:
            return call("run_checks", {}, "check")
        return call("read_file", {"path": "app.py"}, f"read-{turn}")


def test_historical_six_call_checkpoint_still_retests_without_extra_builder_calls(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    run = make_run(session)
    session.add(Decision(run_id=run.id, code="Q1", question="谁用", options="个人", recommendation="个人", answer="个人", status="answered"))
    session.commit()
    original_handoff = harness._handoff_checked_builder_budget
    monkeypatch.setattr(harness, "_handoff_checked_builder_budget", lambda *_args, **_kwargs: False)
    assert harness.execute(session, run, LastCheckOnly(), PRD) is False
    state = harness.load_state(run)
    assert state["last_check"]["passed"] is True
    state.pop("turn_cap", None)
    state.pop("repair_cap", None)
    state["turns"]["builder:0"] = harness.LEGACY_BUILDER_TURNS
    state["stop_reason"] = harness.LEGACY_BUILDER_BUDGET_REASON
    run.failure_code = "agent_execution_failed"
    run.failure_reason = harness.LEGACY_BUILDER_BUDGET_REASON
    run.execution_state = json.dumps(state)
    run.current_stage, run.status = "gate_failed", "done"
    session.commit()
    assert harness.can_recover_builder_budget(run) is True
    calls = []
    monkeypatch.setattr(engine, "start_run_async", lambda ident: calls.append(ident))
    engine.retest_run(run.id)
    session.refresh(run)
    assert calls == [run.id]
    monkeypatch.setattr(harness, "_handoff_checked_builder_budget", original_handoff)

    class VerifierOnly:
        def __init__(self):
            self.prompt_tokens = 0
            self.completion_tokens = 0

        def agent_turn(self, role, messages, tools, context):
            assert role == "verifier"
            return verifier_turn(messages)

    monkeypatch.setattr(llm, "get_llm", lambda *_args: VerifierOnly())
    engine.advance(session, run)
    session.refresh(run)
    state = harness.load_state(run)
    assert run.current_stage == "awaiting_acceptance"
    assert state["turns"]["builder:0"] == harness.LEGACY_BUILDER_TURNS
    assert state["turns"]["verifier:0"] == 3
    assert state["checks"][-1]["role"] == "verifier"


def test_retest_refusal_still_blocks_budget_failure_without_a_passing_check(session, tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    failed = make_run(session)
    state = harness._new_state()
    state["status"] = "failed"
    state["stop_reason"] = harness._builder_budget_reason_for(state)
    state["turns"]["builder:0"] = harness.MAX_TURNS
    failed.execution_state = json.dumps(state)
    failed.current_stage, failed.status = "gate_failed", "done"
    failed.failure_code = "agent_execution_failed"
    failed.failure_reason = state["stop_reason"]
    session.commit()
    assert harness.can_recover_builder_budget(failed) is False
    with pytest.raises(AppError, match="不能通过重测重置"):
        engine.retest_run(failed.id)
