"""大需求下开发输出被截断时的预算、空文件和失败原因。"""
from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models import Confirmation, FactoryRun
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
FORTUNE_IDEA = "算命小程序，包含塔罗、星座、付费、海报和隐私说明"
FORTUNE_PRD = {
    "output_type": "text",
    "goal_users": "想算塔罗和星座、付费解锁海报并阅读隐私说明的用户",
    "input_process_output": "输入生日或问题，返回塔罗解读、星座运势、付费海报和隐私说明",
    "main_loop": "先完成可运行的占卜主路径，再考虑塔罗、星座、付费、海报和隐私增强",
}


@pytest.fixture(autouse=True)
def isolated_code(tmp_path, monkeypatch):
    for module in (testing, runner, engine, deploy, evidence):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(settings, "sandbox_mode", "process")
    monkeypatch.setattr(settings, "llm_api_key", "")
    return tmp_path


def make_run(session, **overrides):
    fields = dict(
        id=str(uuid.uuid4()), idea=FORTUNE_IDEA, current_stage="building", status="running",
        execution_mode="agent_team", llm_provider="", prd_snapshot=json.dumps(FORTUNE_PRD, ensure_ascii=False), prd_revision=1,
    )
    fields.update(overrides)
    run = FactoryRun(**fields)
    session.add(run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    return run


def truncated_write(ident="cut"):
    return {
        "content": "",
        "finish_reason": "length",
        "truncated": True,
        "tool_calls": [{"id": ident, "name": "write_files", "arguments": None}],
    }


class LengthLimitedBuilder:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0
        self.seen = []

    def agent_turn(self, role, messages, tools, context):
        self.calls += 1
        self.completion_tokens += 8000
        self.seen.append({"role": role, "messages": messages, "context": context})
        if self.calls > harness.MAX_TURNS + harness.MAX_TRUNCATION_RETRIES + 2:
            raise RuntimeError("调用次数超过硬上限")
        return truncated_write(f"cut-{self.calls}")


def test_large_requirement_truncation_does_not_exhaust_turn_budget(session, caplog):
    run = make_run(session)
    client = LengthLimitedBuilder()
    with caplog.at_level(logging.WARNING, logger="factory.agent"):
        assert harness.execute(session, run, client, FORTUNE_PRD) is False
    state = harness.load_state(run)
    assert client.calls == harness.MAX_TRUNCATION_RETRIES
    assert state["turns"] == {"builder:0": 0}
    assert state["truncation_retries"]["builder:0"] == harness.MAX_TRUNCATION_RETRIES
    assert run.failure_reason.startswith("模型输出被截断")
    assert "六次模型调用上限" not in (run.failure_reason or "")
    assert harness.read_files(run.id) == {}
    assert "塔罗" in client.seen[0]["context"]["idea"]
    guides = [item for item in state["messages"]["builder:0"] if item.get("role") == "user" and "截断" in item.get("content", "")]
    assert len(guides) == harness.MAX_TRUNCATION_RETRIES
    assert "不计入本轮调用上限" in guides[-1]["content"]
    assert "app.py 单独" in guides[-1]["content"]
    assert "不要调用 read_file" in state["messages"]["builder:0"][0]["content"]
    assert not any(item.get("role") == "assistant" for item in state["messages"]["builder:0"])
    assert "模型输出被截断" in caplog.text
    assert harness.execution_view(run)["stop_reason"].startswith("模型输出被截断")


class BlankFileBuilder:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.seen = []

    def agent_turn(self, role, messages, tools, context):
        self.seen.append(messages)
        return {
            "content": "",
            "finish_reason": "stop",
            "truncated": False,
            "tool_calls": [{"id": "blank", "name": "write_files", "arguments": {"files": {
                "app.py": "", "requirements.txt": " ", "README.md": "",
            }}}],
        }


def test_blank_files_are_rejected_and_still_consume_a_real_turn(session):
    run = make_run(session)
    client = BlankFileBuilder()
    assert harness.execute(session, run, client, FORTUNE_PRD) is False
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == harness.MAX_TURNS
    assert "模型输出被截断" not in (run.failure_reason or "")
    assert f"每轮{harness.MAX_TURNS}次模型调用上限" in (run.failure_reason or "")
    assert "还没有可检查的源码" in (run.failure_reason or "")
    assert harness.read_files(run.id) == {}
    assert any("拒绝写入空文件" in (item.get("content") or "") for item in client.seen[-1] if item.get("role") == "tool")


class RecoveringBuilder:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = []

    def agent_turn(self, role, messages, tools, context):
        self.calls.append(role)
        guided = any("输出被截断" in (item.get("content") or "") for item in messages if item.get("role") == "user")
        results = [item for item in messages if item.get("role") == "tool"]
        if role == "builder" and not guided and not results:
            self.completion_tokens += 8000
            return truncated_write()
        if role == "builder":
            if not results:
                return {"tool_calls": [{"id": "write", "name": "write_files", "arguments": {"files": FILES}}]}
            if len(results) == 1:
                return {"tool_calls": [{"id": "check", "name": "run_checks", "arguments": {}}]}
            return {"tool_calls": [{"id": "hand", "name": "handoff", "arguments": {"reason": "主路径已提交，交给独立验证"}}]}
        if not results:
            return {"tool_calls": [{"id": "read", "name": "read_file", "arguments": {"path": "app.py"}}]}
        if len(results) == 1:
            return {"tool_calls": [{"id": "vcheck", "name": "run_checks", "arguments": {}}]}
        return {"tool_calls": [{"id": "done", "name": "conclude", "arguments": {"passed": True, "summary": "自动技术检查通过，业务效果仍待人工验收"}}]}


def test_one_truncated_call_is_refunded_before_a_complete_write(session):
    run = make_run(session)
    client = RecoveringBuilder()
    assert harness.execute(session, run, client, FORTUNE_PRD) is True
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 3
    assert state["truncation_retries"]["builder:0"] == 1
    assert client.calls.count("builder") == 4
    assert harness.read_files(run.id)["app.py"] == SAFE_APP
    assert any("不计入本轮调用上限" in (item.get("content") or "") for item in state["messages"]["builder:0"])


def test_length_limited_tool_arguments_are_logged_without_body(caplog):
    class SDK:
        def with_options(self, **kwargs):
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))

        def create(self, **kwargs):
            tool = SimpleNamespace(id="cut", function=SimpleNamespace(name="write_files", arguments='{"files": {"app.py": "def incomplete('))
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=8000),
                choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="", tool_calls=[tool]))],
            )

    client = object.__new__(llm.RealLLM)
    client.client, client.model = SDK(), "deepseek-chat"
    client.prompt_tokens = client.completion_tokens = 0
    with caplog.at_level(logging.WARNING, logger="factory.llm"):
        result = client.agent_turn("builder", [{"role": "user", "content": FORTUNE_IDEA}], harness.role_tools("builder"), {})
    assert result["truncated"] is True
    assert result["finish_reason"] == "length"
    assert result["tool_calls"][0]["arguments"] is None
    assert "模型输出被截断" in caplog.text
    assert "def incomplete" not in caplog.text
    assert "json_invalid=True" in caplog.text
