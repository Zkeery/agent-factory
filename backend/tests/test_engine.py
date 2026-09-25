"""引擎层测试：状态机、闸门、持久化与重启恢复。"""
from __future__ import annotations

import uuid

from app.models import Confirmation, Decision, FactoryRun, SessionLocal, StageEvent
from app.services import engine
from app.services.stages import Stage


def make_run(session) -> FactoryRun:
    run = FactoryRun(
        id=str(uuid.uuid4()), idea="做一个给宠物起名字的小工具",
        status="running", current_stage=Stage.IDEA_SUBMITTED.value,
    )
    session.add(run)
    session.commit()
    return run


def answer_all(session, run_id: str) -> None:
    for d in session.query(Decision).filter(Decision.run_id == run_id).all():
        d.answer = "按推荐"
        d.status = "answered"
    session.commit()


def test_advance_stops_at_awaiting_answers(session):
    run = make_run(session)
    engine.advance(session, run)
    assert run.current_stage == Stage.AWAITING_ANSWERS.value
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    assert 0 < len(decisions) <= 5


def test_clarify_gate_blocks_without_answers(session):
    run = make_run(session)
    engine.advance(session, run)
    assert run.current_stage == Stage.AWAITING_ANSWERS.value
    engine.advance(session, run)  # 未回答，不推进
    assert run.current_stage == Stage.AWAITING_ANSWERS.value


def test_prd_gate_blocks_without_confirm(session):
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    assert run.current_stage == Stage.AWAITING_PRD_CONFIRM.value
    engine.advance(session, run)  # 未确认，不推进
    assert run.current_stage == Stage.AWAITING_PRD_CONFIRM.value


def test_full_pipeline_to_awaiting_acceptance(session):
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    assert run.current_stage == Stage.AWAITING_PRD_CONFIRM.value
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    assert run.current_stage == Stage.AWAITING_ACCEPTANCE.value
    # 人验收后才 delivered
    session.add(Confirmation(run_id=run.id, kind="acceptance", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    session.refresh(run)
    assert run.current_stage == Stage.DELIVERED.value
    assert run.status == "done"


def test_restart_recovery(session):
    run = make_run(session)
    engine.advance(session, run)
    run_id = run.id
    # 新会话模拟进程重启
    s2 = SessionLocal()
    try:
        run2 = s2.get(FactoryRun, run_id)
        assert run2 is not None
        assert run2.current_stage == Stage.AWAITING_ANSWERS.value
        events = s2.query(StageEvent).filter(StageEvent.run_id == run_id).all()
        assert len(events) >= 1
        decisions = s2.query(Decision).filter(Decision.run_id == run_id).all()
        assert len(decisions) == 4
    finally:
        s2.close()


def test_noncritical_auto_answered(session):
    """决策卡 A+B：非关键决策自动按推荐回答，关键决策待点选。"""
    run = make_run(session)
    engine.advance(session, run)
    decisions = session.query(Decision).filter(Decision.run_id == run.id).all()
    critical = [d for d in decisions if d.is_critical]
    noncritical = [d for d in decisions if not d.is_critical]
    assert len(critical) >= 1
    assert len(noncritical) >= 1
    for d in noncritical:
        assert d.status == "answered"
        assert d.answer == d.recommendation
    for d in critical:
        assert d.status == "open"
        assert d.answer is None


def test_illegal_transition_not_possible(session):
    # 状态机由 NEXT_STAGE 固定，引擎不会跳转到等待点之前的阶段
    run = make_run(session)
    engine.advance(session, run)
    first = run.current_stage
    engine.advance(session, run)
    assert run.current_stage == first  # 等待点，无人工操作不前进


class _FakeCodeClient:
    def __init__(self):
        self.calls = 0

    def generate_code(self, idea, prd):
        self.calls += 1
        if self.calls == 1:
            return {"app": "def broken(:\n", "requirements": "fastapi\n", "readme": "x"}
        return {"app": "from fastapi import FastAPI\napp = FastAPI()\n", "requirements": "fastapi\n", "readme": "x"}


def test_building_retries_on_syntax_error(session):
    import py_compile

    from app.services import evidence as ev
    from app.services import runner

    run = make_run(session)
    ev.add_evidence(session, run, "prd", "PRD", "{}")
    fake = _FakeCodeClient()
    engine._action(session, run, Stage.BUILDING, fake)
    assert fake.calls == 2  # 第一次语法错误 → 重试一次
    app_py = runner._code_dir(run.id) / "app.py"
    py_compile.compile(str(app_py), doraise=True)  # 不抛 = 合法
