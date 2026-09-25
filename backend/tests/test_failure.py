"""失败处理改动测试：FAILED 终态、_mark_failed、advance_run 失败标记、LLM 重试、monitor 纯函数。"""
from __future__ import annotations

import importlib.util
import types
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.models import FactoryRun, SessionLocal, StageEvent
from app.services import engine, llm
from app.services.stages import Stage, TERMINAL_STAGES


def _load_monitor():
    spec = importlib.util.spec_from_file_location(
        "monitor", Path(__file__).resolve().parents[1] / "scripts" / "monitor.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


monitor = _load_monitor()


# --- FAILED 终态 ---
def test_failed_is_terminal():
    assert Stage.FAILED in TERMINAL_STAGES


# --- _mark_failed ---
def test_mark_failed(session):
    run = FactoryRun(id=str(uuid.uuid4()), idea="x", status="running", current_stage=Stage.IDEA_SUBMITTED.value)
    session.add(run)
    session.commit()
    engine._mark_failed(session, run.id, "boom", "模拟失败")
    session.expire_all()
    run2 = session.get(FactoryRun, run.id)
    assert run2.current_stage == Stage.FAILED.value
    assert run2.status == "done"
    assert run2.failure_reason == "模拟失败"
    ev = session.query(StageEvent).filter(StageEvent.run_id == run.id, StageEvent.event_type == "error").first()
    assert ev is not None and "boom" in ev.payload


# --- advance_run 失败标记 ---
def test_advance_run_marks_failed_on_app_error(monkeypatch):
    session = SessionLocal()
    try:
        run = FactoryRun(id=str(uuid.uuid4()), idea="x", status="running", current_stage=Stage.IDEA_SUBMITTED.value)
        session.add(run)
        session.commit()
        run_id = run.id

        def boom():
            raise AppError("boom", "模拟失败", 500)

        monkeypatch.setattr(llm, "get_llm", boom)
        engine.advance_run(run_id)

        session.expire_all()
        run2 = session.get(FactoryRun, run_id)
        assert run2.current_stage == Stage.FAILED.value
        assert run2.status == "done"
    finally:
        session.close()


def test_advance_run_marks_failed_on_unexpected_error(monkeypatch):
    session = SessionLocal()
    try:
        run = FactoryRun(id=str(uuid.uuid4()), idea="x", status="running", current_stage=Stage.IDEA_SUBMITTED.value)
        session.add(run)
        session.commit()
        run_id = run.id

        def boom():
            raise RuntimeError("未预期异常")

        monkeypatch.setattr(llm, "get_llm", boom)
        engine.advance_run(run_id)

        session.expire_all()
        run2 = session.get(FactoryRun, run_id)
        assert run2.current_stage == Stage.FAILED.value
        ev = session.query(StageEvent).filter(StageEvent.run_id == run_id, StageEvent.event_type == "error").first()
        assert ev is not None and "internal_error" in ev.payload
    finally:
        session.close()


# --- LLM 重试 ---
def test_real_llm_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)  # 加速测试
    real = llm.RealLLM()
    calls: list[int] = []

    def create(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("网络抖动")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="OK"))],
            usage=None,
        )

    real.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    assert real._chat("hi") == "OK"
    assert len(calls) == 2


def test_real_llm_retries_exhausted_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    real = llm.RealLLM()

    def create(**kw):
        raise RuntimeError("一直失败")

    real.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    with pytest.raises(AppError) as exc:
        real._chat("hi")
    assert exc.value.code == "llm_call_failed"


# --- monitor 纯函数 ---
def test_monitor_parse_etime():
    assert monitor._parse_etime("00:30") == 30
    assert monitor._parse_etime("01:00:00") == 3600
    assert monitor._parse_etime("2-00:00:00") == 172800
    assert monitor._parse_etime("") == 0
