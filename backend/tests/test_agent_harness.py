"""工具权限、真实检查闭环、有限预算与持久化恢复回归。"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.models import Confirmation, FactoryRun, RunMetric, StageEvent
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


@pytest.fixture(autouse=True)
def isolated_code(tmp_path, monkeypatch):
    for module in (testing, runner, engine, deploy, evidence):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(settings, "sandbox_mode", "process")
    monkeypatch.setattr(settings, "llm_api_key", "")
    return tmp_path


def make_run(session, **overrides):
    fields = dict(id=str(uuid.uuid4()), idea="文本检查样例", current_stage="building", status="running", execution_mode="agent_team", llm_provider="mock", prd_snapshot=json.dumps(PRD), prd_revision=1)
    fields.update(overrides)
    run = FactoryRun(**fields)
    session.add(run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    return run


def call(name, args=None, ident="call"):
    return {"tool_calls": [{"id": ident, "name": name, "arguments": args or {}}]}


class SafeMock(llm.MockLLM):
    def generate_code(self, idea, prd, source_context=None):
        return {"app": FILES["app.py"], "requirements": FILES["requirements.txt"], "readme": FILES["README.md"]}


def test_mock_uses_actual_tools_and_independent_verifier(session):
    run = make_run(session)
    assert harness.execute(session, run, SafeMock(), PRD)
    state = harness.load_state(run)
    assert state["status"] == "completed"
    assert state["turns"] == {"builder:0": 3, "verifier:0": 3}
    assert [t["role"] for t in state["tasks"]] == ["builder", "verifier"]
    assert [c["role"] for c in state["checks"]] == ["builder", "verifier"]
    assert all(c["passed"] for c in state["checks"])
    assert harness.read_files(run.id) == FILES
    assert session.query(StageEvent).filter_by(run_id=run.id, event_type="test_result", payload="passed").count() == 2
    assert state["messages"]["builder:0"] is not state["messages"]["verifier:0"]
    public = json.dumps(harness.execution_view(run), ensure_ascii=False)
    assert "from fastapi" not in public and "messages" not in public and "pending" not in public
    assert "人工" in public


class LastTurnCheckMock(SafeMock):
    """开发者直到第六次调用才完成检查，没有额外调用可主动 handoff。"""

    def __init__(self, *, bad_code=False, change_after_pass=False, fail_after_pass=False):
        super().__init__()
        self.calls = []
        self.bad_code = bad_code
        self.change_after_pass = change_after_pass
        self.fail_after_pass = fail_after_pass

    def agent_turn(self, role, messages, tools, context):
        self.calls.append(role)
        if role != "builder":
            return super().agent_turn(role, messages, tools, context)
        turn = sum(item["role"] == "assistant" for item in messages) + 1
        if turn == 1:
            files = dict(FILES)
            if self.bad_code:
                files["app.py"] = "def broken(:\n"
            return call("write_files", {"files": files})
        if turn == 6 and self.change_after_pass:
            return call("write_files", {"files": {"app.py": SAFE_APP + "\n# 检查后的修改\n"}})
        if turn == 6 and self.fail_after_pass:
            return {"tool_calls": [
                {"id": "check", "name": "run_checks", "arguments": {}},
                {"id": "bad-read", "name": "read_file", "arguments": {"path": "../private"}},
            ]}
        if turn == (5 if self.change_after_pass else 6):
            return call("run_checks")
        return call("read_file", {"path": "app.py"})


def legacy_budget_failure(session, run, monkeypatch):
    # 重现旧实现的失败记录，不伪造 checks：源码检查仍由真实受限运行器执行。
    with monkeypatch.context() as patch:
        patch.setattr(harness, "_handoff_checked_builder_budget", lambda *_: False)
        assert not harness.execute(session, run, LastTurnCheckMock(), PRD)
    run.current_stage, run.status = "gate_failed", "done"
    session.commit()
    assert harness.load_state(run)["last_check"]["passed"] is True


def test_sixth_builder_call_passes_and_executor_hands_to_independent_verifier(session):
    run = make_run(session)
    client = LastTurnCheckMock()
    assert harness.execute(session, run, client, PRD)
    state = harness.load_state(run)
    assert state["turns"] == {"builder:0": 6, "verifier:0": 3}
    assert client.calls.count("builder") == 6
    assert [check["role"] for check in state["checks"]] == ["builder", "verifier"]
    assert state["validated_source_hash"] == harness.source_hash(run.id)
    automatic = [step for step in state["steps"] if step["tool"] == "budget_handoff"]
    assert len(automatic) == 1 and "执行器自动交接" in automatic[0]["summary"]
    assert "未生成模型结论" in state["handoffs"][0]["reason"]
    assert run.accepted_at is None


@pytest.mark.parametrize("option", ["bad_code", "change_after_pass", "fail_after_pass"])
def test_builder_budget_cannot_hide_failed_checks_changed_source_or_failed_actions(session, option):
    run = make_run(session)
    client = LastTurnCheckMock(**{option: True})
    assert not harness.execute(session, run, client, PRD)
    state = harness.load_state(run)
    assert state["turns"] == {"builder:0": 6}
    assert state["status"] == "failed" and not state["handoffs"]
    assert "budget_handoff" not in [step["tool"] for step in state["steps"]]
    run.current_stage, run.status = "gate_failed", "done"
    session.commit()
    assert not harness.can_recover_builder_budget(run)
    with pytest.raises(AppError, match="不能通过重测重置"):
        engine.retest_run(run.id)
    assert harness.load_state(run)["turns"] == {"builder:0": 6}


def test_builder_budget_handoff_never_substitutes_for_verifier_check(session):
    class UncheckedVerifier(LastTurnCheckMock):
        def agent_turn(self, role, *args):
            if role == "verifier":
                return call("conclude", {"passed": True, "summary": "沿用开发检查"})
            return super().agent_turn(role, *args)
    run = make_run(session)
    assert not harness.execute(session, run, UncheckedVerifier(), PRD)
    state = harness.load_state(run)
    assert state["turns"] == {"builder:0": 6, "verifier:0": 6}
    assert state["status"] == "failed" and "validated_source_hash" not in state
    assert [check["role"] for check in state["checks"]] == ["builder"]


def test_legacy_builder_budget_failure_retest_preserves_run_and_enters_verifier(session, monkeypatch):
    run = make_run(session)
    from app.models import Decision
    session.add(Decision(run_id=run.id, code="Q1", question="谁用", options="个人", recommendation="个人", answer="个人", status="answered"))
    session.commit()
    legacy_budget_failure(session, run, monkeypatch)
    saved = harness.load_state(run)
    calls = []
    monkeypatch.setattr(engine, "start_run_async", lambda ident: calls.append(ident))
    engine.retest_run(run.id)
    session.refresh(run)
    state = harness.load_state(run)
    assert calls == [run.id] and run.current_stage == "building"
    assert state["turns"] == saved["turns"] == {"builder:0": 6}
    assert state["checks"] == saved["checks"] and state["messages"] == saved["messages"]
    assert run.failure_code == "" and run.failure_reason is None
    class VerifierOnly(SafeMock):
        def agent_turn(self, role, *args):
            assert role == "verifier", "恢复不得增加开发者模型调用"
            return super().agent_turn(role, *args)
    monkeypatch.setattr(llm, "get_llm", lambda *_: VerifierOnly())
    engine.advance(session, run)
    assert run.current_stage == "awaiting_acceptance" and run.accepted_at is None
    state = harness.load_state(run)
    assert state["turns"] == {"builder:0": 6, "verifier:0": 3}
    assert len(state["checks"]) == 2 and state["checks"][-1]["role"] == "verifier"


def test_concurrent_budget_recovery_only_starts_original_checkpoint_once(session, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    run = make_run(session)
    legacy_budget_failure(session, run, monkeypatch)
    run_id = run.id
    starts = []
    monkeypatch.setattr(engine, "start_run_async", lambda ident: starts.append(ident))
    barrier = Barrier(2)
    def recover():
        barrier.wait(timeout=5)
        try:
            engine.retest_run(run_id)
            return "started"
        except AppError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(recover), pool.submit(recover)]
        assert sorted(future.result(timeout=10) for future in futures) == ["not_retestable", "started"]
    session.refresh(run)
    assert starts == [run_id] and run.current_stage == "building"
    assert harness.load_state(run)["turns"] == {"builder:0": 6}
    events = session.query(StageEvent).filter_by(run_id=run_id, event_type="agent_execution").all()
    assert sum("恢复已通过检查" in event.payload for event in events) == 1


@pytest.mark.parametrize("block", ["source_changed", "pending_tool", "unfinished_task", "wrong_failure", "prd_unconfirmed"])
def test_legacy_budget_recovery_requires_unchanged_check_and_confirmed_prd(session, monkeypatch, block):
    run = make_run(session)
    legacy_budget_failure(session, run, monkeypatch)
    state = harness.load_state(run)
    if block == "source_changed":
        harness._path(run.id, "app.py").write_text(SAFE_APP + "\n# 外部改动\n", encoding="utf-8")
    elif block == "pending_tool":
        state["pending"] = {"calls": [{"name": "write_files"}], "index": 0}
    elif block == "unfinished_task":
        state["tasks"].append({"id": "verifier:0", "status": "interrupted"})
    elif block == "wrong_failure":
        run.failure_code = "run_stuck"
    else:
        session.query(Confirmation).filter_by(run_id=run.id, kind="prd").one().status = "pending"
    run.execution_state = json.dumps(state)
    session.commit()
    starts = []
    monkeypatch.setattr(engine, "start_run_async", lambda *_: starts.append(True))
    with pytest.raises(AppError):
        engine.retest_run(run.id)
    session.refresh(run)
    assert run.current_stage == "gate_failed" and harness.load_state(run)["turns"] == {"builder:0": 6}
    assert not starts


def test_interruption_after_sixth_check_can_resume_without_refunding_builder_budget(session, monkeypatch):
    run = make_run(session)
    original = harness._persist
    did_interrupt = []
    def interrupt_after_committed_check(db, current, state, event=None):
        original(db, current, state, event)
        if state.get("turns", {}).get("builder:0") == 6 and (state.get("last_check") or {}).get("passed") is True and not state.get("pending") and not did_interrupt:
            did_interrupt.append(True)
            raise RuntimeError("提交最后检查后进程中断")
    monkeypatch.setattr(harness, "_persist", interrupt_after_committed_check)
    with pytest.raises(harness.ExecutionInterrupted):
        harness.execute(session, run, LastTurnCheckMock(), PRD)
    assert run.status == "paused" and harness.execution_view(run)["resumable"]
    assert harness.load_state(run)["turns"] == {"builder:0": 6}
    engine.prepare_execution_resume(session, run)
    assert harness.execute(session, run, SafeMock(), PRD)
    assert harness.load_state(run)["turns"] == {"builder:0": 6, "verifier:0": 3}


class FixingMock(SafeMock):
    def __init__(self, always_bad=False):
        super().__init__()
        self.feedback = []
        self.always_bad = always_bad

    def agent_turn(self, role, messages, tools, context):
        response = super().agent_turn(role, messages, tools, context)
        current = response["tool_calls"][0]
        if role == "builder" and current["name"] == "write_files":
            if context["repair_round"]:
                self.feedback.append(context["verification_feedback"])
            if self.always_bad or context["repair_round"] == 0:
                current["arguments"]["files"]["app.py"] = "def broken(:\n"
        return response


def test_real_syntax_failure_reaches_repair_context_and_passes(session):
    run = make_run(session)
    client = FixingMock()
    assert harness.execute(session, run, client, PRD)
    state = harness.load_state(run)
    assert state["repair_rounds"] == 1
    assert [c["passed"] for c in state["checks"]] == [False, False, True, True]
    assert any("SyntaxError" in item for item in client.feedback)
    assert [(h["from_role"], h["to_role"]) for h in state["handoffs"]] == [("builder", "verifier"), ("verifier", "builder"), ("builder", "verifier")]
    assert "def broken" not in json.dumps(harness.execution_view(run))


def test_repair_budget_exhaustion_cannot_resume_or_retest(session):
    run = make_run(session)
    assert not harness.execute(session, run, FixingMock(always_bad=True), PRD)
    state = harness.load_state(run)
    assert state["repair_rounds"] == 2 and state["status"] == "failed"
    assert len(state["tasks"]) == 6 and len(state["checks"]) == 6
    assert all(n == 3 for n in state["turns"].values())
    assert not harness.execution_view(run)["resumable"]
    with pytest.raises(AppError, match="中断检查点"):
        engine.prepare_execution_resume(session, run)
    run.current_stage, run.status = "gate_failed", "done"
    session.commit()
    with pytest.raises(AppError, match="不能通过重测重置"):
        engine.retest_run(run.id)


@pytest.mark.parametrize("mode", ["empty", "unknown", "path_escape", "invalid_args"])
def test_invalid_tool_or_missing_calls_consumes_persistent_budget(session, isolated_code, mode):
    class BadMock(SafeMock):
        def agent_turn(self, role, messages, tools, context):
            if mode == "empty":
                return {"content": "测试已通过"}
            if mode == "unknown":
                return call("shell", {"command": "touch escaped"})
            if mode == "path_escape":
                return call("write_files", {"files": {"../escaped.py": "bad"}})
            return call("run_checks", {"shell": "bad"})
    run = make_run(session)
    assert not harness.execute(session, run, BadMock(), PRD)
    state = harness.load_state(run)
    assert state["turns"] == {"builder:0": 6}
    assert state["status"] == "failed" and not state["checks"]
    assert not list(isolated_code.rglob("escaped*"))
    assert not harness.execute(session, run, SafeMock(), PRD)
    assert harness.load_state(run)["turns"] == {"builder:0": 6}


def test_verifier_cannot_write_or_pass_without_own_check(session):
    class BadVerifier(SafeMock):
        def agent_turn(self, role, messages, tools, context):
            if role == "builder":
                return super().agent_turn(role, messages, tools, context)
            assert "write_files" not in {t["function"]["name"] for t in tools}
            used = len([m for m in messages if m["role"] == "tool"])
            if used == 0:
                return call("write_files", {"files": {"app.py": "bad"}})
            return call("conclude", {"passed": True, "summary": "通过"})
    run = make_run(session)
    assert not harness.execute(session, run, BadVerifier(), PRD)
    state = harness.load_state(run)
    assert state["turns"]["verifier:0"] == 6
    assert harness.read_files(run.id)["app.py"] == SAFE_APP
    assert not any(c["role"] == "verifier" for c in state["checks"])


def test_model_interruption_resumes_same_task_without_resetting_budget(session):
    class Interrupted(SafeMock):
        def agent_turn(self, *args):
            self.prompt_tokens += 7
            raise RuntimeError("network dropped")
    run = make_run(session)
    with pytest.raises(harness.ExecutionInterrupted):
        harness.execute(session, run, Interrupted(), PRD)
    state = harness.load_state(run)
    assert state["turns"] == {"builder:0": 1}
    assert state["accounting_incomplete"] is True
    assert state["steps"][0]["input_tokens"] == 7
    assert run.status == "paused" and harness.execution_view(run)["resumable"]
    original_task = state["tasks"][0]["id"]
    engine.prepare_execution_resume(session, run)
    assert harness.execute(session, run, SafeMock(), PRD)
    state = harness.load_state(run)
    assert state["tasks"][0]["id"] == original_task
    assert state["turns"][original_task] == 4
    assert state["accounting_incomplete"] is True


def test_pending_tool_replayed_without_new_model_call(session, monkeypatch):
    run = make_run(session)
    original = testing.run_tests
    attempts = []
    def transient(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("worker interrupted before check result")
        return original(*args, **kwargs)
    monkeypatch.setattr(testing, "run_tests", transient)
    with pytest.raises(harness.ExecutionInterrupted):
        harness.execute(session, run, SafeMock(), PRD)
    state = harness.load_state(run)
    assert state["pending"]["calls"][0]["name"] == "run_checks"
    assert state["turns"]["builder:0"] == 2
    engine.prepare_execution_resume(session, run)
    assert harness.execute(session, run, SafeMock(), PRD)
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 3
    assert len(state["checks"]) == 2 and len(attempts) == 3


def test_interrupted_file_commit_replays_same_payload_idempotently(session, monkeypatch):
    run = make_run(session)
    original_replace = harness.os.replace
    did_interrupt = []
    def interrupt_after_first_replace(source, target):
        original_replace(source, target)
        if not did_interrupt:
            did_interrupt.append(True)
            raise RuntimeError("process stopped after one committed file")
    monkeypatch.setattr(harness.os, "replace", interrupt_after_first_replace)
    with pytest.raises(harness.ExecutionInterrupted):
        harness.execute(session, run, SafeMock(), PRD)
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 1
    assert state["pending"]["calls"][0]["name"] == "write_files"
    original_step_id = state["pending"]["step_id"]
    engine.prepare_execution_resume(session, run)
    assert harness.execute(session, run, SafeMock(), PRD)
    state = harness.load_state(run)
    assert state["turns"]["builder:0"] == 3
    assert harness.read_files(run.id) == FILES
    writes = [step for step in state["steps"] if step["tool"] == "write_files"]
    assert len(writes) == 1 and writes[0]["id"] == original_step_id


def test_cancel_after_checks_does_not_run_followup_tools(session, monkeypatch):
    run = make_run(session)
    original = testing.run_tests
    def cancel_after_actual_check(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.cancel_run(run.id)
        return result
    monkeypatch.setattr(testing, "run_tests", cancel_after_actual_check)
    assert not harness.execute(session, run, SafeMock(), PRD)
    session.refresh(run)
    state = harness.load_state(run)
    assert run.current_stage == "cancelled" and state["status"] == "cancelled"
    assert not state["handoffs"] and len(state["tasks"]) == 1
    assert not session.query(StageEvent).filter_by(run_id=run.id, event_type="test_result").all()


def test_startup_recovery_preserves_budget_and_exhausted_call_is_terminal(session):
    resumable = make_run(session)
    exhausted = make_run(session)
    for run, count in ((resumable, 2), (exhausted, 6)):
        state = harness._new_state()
        state["turns"]["builder:0"] = count
        run.execution_state = json.dumps(state)
    session.commit()
    assert engine.recover_interrupted_executions() == 2
    session.refresh(resumable)
    session.refresh(exhausted)
    assert resumable.status == "paused" and harness.execution_view(resumable)["resumable"]
    assert harness.load_state(resumable)["turns"]["builder:0"] == 2
    assert exhausted.current_stage == "gate_failed" and not harness.execution_view(exhausted)["resumable"]


def test_outer_failure_closes_active_execution_instead_of_exposing_running(session):
    run = make_run(session)
    state = harness._new_state()
    harness._ensure_task(session, run, state, PRD)
    engine._mark_failed(session, run.id, "run_stuck", "运行超时")
    view = harness.execution_view(run)
    assert view["status"] == "failed" and not view["resumable"]
    assert view["tasks"][0]["status"] == "failed"


def test_changed_source_in_testing_cannot_fall_back_to_workflow_checks(session, monkeypatch):
    run = make_run(session)
    assert harness.execute(session, run, SafeMock(), PRD)
    run.current_stage = "testing"
    session.commit()
    app_path = harness._path(run.id, "app.py")
    app_path.write_text(SAFE_APP + "\n# 外部修改：必须重新协作验证\n", encoding="utf-8")
    old_checks = []
    deployments = []
    monkeypatch.setattr(engine, "_run_tests", lambda *args: old_checks.append(True) or True)
    monkeypatch.setattr(deploy, "generate_deploy", lambda *args: deployments.append(True))
    engine.advance(session, run)
    session.refresh(run)
    assert run.current_stage == "gate_failed"
    assert harness.load_state(run)["status"] == "failed"
    assert not old_checks and not deployments
    assert "独立验证记录" in run.failure_reason


def test_cancel_committed_before_budget_failure_remains_authoritative(session, monkeypatch):
    run = make_run(session)
    state = harness._new_state()
    harness._ensure_task(session, run, state, PRD)
    state["turns"]["builder:0"] = 6
    run.execution_state = json.dumps(state)
    session.commit()
    original_fail = harness._fail
    def cancel_then_fail(*args, **kwargs):
        engine.cancel_run(run.id)
        return original_fail(*args, **kwargs)
    monkeypatch.setattr(harness, "_fail", cancel_then_fail)
    assert not harness.execute(session, run, SafeMock(), PRD)
    session.refresh(run)
    assert run.current_stage == "cancelled" and run.status == "done"
    assert harness.load_state(run)["status"] == "cancelled"
    assert run.failure_code == "" and run.failure_reason is None
    assert not harness.execution_view(run)["resumable"]


def test_cancel_during_model_call_keeps_terminal_state_and_accounts_once(session, monkeypatch):
    run = make_run(session)
    class Cancelling(SafeMock):
        def agent_turn(self, *args):
            self.prompt_tokens += 9
            engine.cancel_run(run.id)
            return super().agent_turn(*args)
    monkeypatch.setattr(llm, "get_llm", lambda *_: Cancelling())
    engine.advance(session, run)
    session.refresh(run)
    assert run.current_stage == "cancelled" and run.status == "done"
    assert harness.load_state(run)["status"] == "cancelled"
    metric = session.query(RunMetric).filter_by(run_id=run.id).one()
    assert metric.prompt_tokens == 9
    entries = json.loads(metric.pricing_snapshots)
    assert len(entries) == 1 and entries[0]["outcome"] == "cancelled"
    assert not harness.read_files(run.id)


def test_agent_reaches_human_acceptance_and_workflow_keeps_old_path(session, monkeypatch):
    monkeypatch.setattr(llm, "get_llm", lambda *_: SafeMock())
    for mode in ("agent_team", "workflow"):
        run = make_run(session, execution_mode=mode)
        from app.models import Decision
        session.add(Decision(run_id=run.id, code="Q1", question="谁用", options="个人", recommendation="个人", answer="个人", status="answered"))
        session.commit()
        engine.advance(session, run)
        assert run.current_stage == "awaiting_acceptance"
        assert harness.load_state(run).get("status") == ("completed" if mode == "agent_team" else None)


def test_runtime_env_keeps_configured_model_only(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "private-db")
    monkeypatch.setenv("OTHER_SERVICE_TOKEN", "private-token")
    monkeypatch.setattr(settings, "llm_api_key", "allowed-model-key")
    env = runner._child_env()
    assert env["DEEPSEEK_API_KEY"] == "allowed-model-key"
    assert "DATABASE_URL" not in env and "OTHER_SERVICE_TOKEN" not in env


def test_native_tools_have_no_sdk_retry_and_usage_is_recorded():
    request = {}
    class SDK:
        def with_options(self, **kwargs):
            request["options"] = kwargs
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))
        def create(self, **kwargs):
            request.update(kwargs)
            tool = SimpleNamespace(id="native", function=SimpleNamespace(name="run_checks", arguments="{}"))
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3), choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool]))])
    client = object.__new__(llm.RealLLM)
    client.client, client.model = SDK(), "test-model"
    client.prompt_tokens = client.completion_tokens = 0
    result = client.agent_turn("verifier", [{"role": "user", "content": "fixture"}], harness.role_tools("verifier"), {})
    assert request["options"] == {"max_retries": 0} and request["tool_choice"] == "required"
    assert result["tool_calls"][0]["name"] == "run_checks"
    assert (client.prompt_tokens, client.completion_tokens) == (11, 3)
