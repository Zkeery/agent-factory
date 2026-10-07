"""推荐和选项简写须携带真实决策含义；不调用真实模型、不改历史回答。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models import Decision, FactoryRun, SessionLocal
from app.services import deploy, engine, evidence, llm, runner, testing
from app.services.decision_context import decision_model_context, normalize_decision_answer

OPTIONS = "A 完全零基础个人小白 / B 企业内容运营团队 / C 有经验的个人创作者"
RECOMMENDATION = "A 完全零基础个人小白"


@pytest.fixture(autouse=True)
def isolated_pipeline(tmp_path, monkeypatch):
    for module in (engine, deploy, evidence, runner, testing):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(engine, "start_run_async", lambda *_: None)


@pytest.mark.parametrize(("answer", "options", "recommendation", "expected"), [
    ("按推荐", OPTIONS, RECOMMENDATION, RECOMMENDATION),
    ("按推荐", OPTIONS, "B", "B 企业内容运营团队"),
    ("A", OPTIONS, "", RECOMMENDATION),
    (" b ", OPTIONS, "", "B 企业内容运营团队"),
    ("C", "A：个人 / B. 团队 / C、有经验创作者", "", "C、有经验创作者"),
    ("A", "A完全零基础个人小白 / B企业团队", "", "A完全零基础个人小白"),
    ("B", "A 个人用户 / C 创作者", "", "B"),
    ("B", "B 团队甲 / B 团队乙", "", "B"),
    ("B", "B 团队 / B 团队", "", "B 团队"),
    ("A", "A / B / C", "", "A"),
    ("B", "Bananas / C 创作者", "", "B"),
    ("A 完全零基础个人小白", OPTIONS, "", "A 完全零基础个人小白"),
    (" 先服务个人，后期再扩展团队。 ", OPTIONS, RECOMMENDATION, " 先服务个人，后期再扩展团队。 "),
    ("按照推荐但增加手动筛选", OPTIONS, RECOMMENDATION, "按照推荐但增加手动筛选"),
    ("按推荐", OPTIONS, "", "按推荐"),
    ("按推荐", OPTIONS, "  ", "按推荐"),
    ("按推荐", OPTIONS, "按推荐", "按推荐"),
    (None, OPTIONS, RECOMMENDATION, None),
])
def test_resolve_only_supported_literal_or_unique_option(answer, options, recommendation, expected):
    assert normalize_decision_answer(answer, options=options, recommendation=recommendation) == expected


def test_model_context_preserves_source_fields_and_is_idempotent():
    original = {"code": "Q1", "question": "面向谁？", "options": OPTIONS, "recommendation": RECOMMENDATION, "answer": "按推荐"}
    payload = decision_model_context(original)
    assert payload == {**original, "answer": RECOMMENDATION, "raw_answer": "按推荐"}
    assert original["answer"] == "按推荐"
    assert decision_model_context(payload) == payload
    assert decision_model_context(SimpleNamespace(**original)) == payload


@pytest.mark.parametrize(("answer", "recommendation"), [("按推荐", ""), ("B", "")])
def test_missing_context_has_explicit_gap_and_preserves_expression(answer, recommendation):
    payload = decision_model_context({"code": "Q1", "question": "面向谁？", "options": "A 个人用户", "recommendation": recommendation, "answer": answer})
    assert payload["answer"] == payload["raw_answer"] == answer
    assert "需要补充确认" in payload["answer_gap"]


def create_pending_decision(client, *, recommendation=RECOMMENDATION, answer=None):
    response = client.post("/api/v1/runs", json={"idea": "为新手筛选可参考的视频", "acceptance_mode": "basic"})
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    with SessionLocal() as session:
        run = session.get(FactoryRun, run_id)
        run.current_stage = "awaiting_answers"
        session.add(Decision(
            run_id=run_id, code="Q1", question="面向哪类用户？", options=OPTIONS,
            recommendation=recommendation, is_critical=True,
            answer=answer, status="answered" if answer is not None else "open",
        ))
        session.commit()
    return run_id


@pytest.mark.parametrize(("submitted", "recommendation", "stored"), [
    ("按推荐", RECOMMENDATION, RECOMMENDATION),
    ("B", RECOMMENDATION, "B 企业内容运营团队"),
    ("我想先服务小店店主", RECOMMENDATION, "我想先服务小店店主"),
    ("按推荐", "", "按推荐"),
])
def test_answer_endpoint_stores_meaning_and_keeps_old_response_contract(client, submitted, recommendation, stored):
    run_id = create_pending_decision(client, recommendation=recommendation)
    response = client.post(f"/api/v1/runs/{run_id}/decisions/Q1/answer", json={"answer": submitted})
    assert response.status_code == 200, response.text
    decision = response.json()["decisions"][0]
    assert decision["answer"] == stored and decision["status"] == "answered"
    with SessionLocal() as session:
        assert session.query(Decision).filter_by(run_id=run_id, code="Q1").one().answer == stored


@pytest.mark.parametrize(("historical_answer", "expected"), [
    ("按推荐", RECOMMENDATION),
    ("B", "B 企业内容运营团队"),
    ("只做个人记账，不做视频工具", "只做个人记账，不做视频工具"),
])
def test_prd_generation_resolves_historical_context_without_rewriting_database(client, historical_answer, expected):
    run_id = create_pending_decision(client, answer=historical_answer)
    captured = []
    class CaptureModel:
        def generate_prd(self, idea, decisions, **kwargs):
            captured.extend(decisions)
            return {"goal_users": expected, "input_process_output": "输入筛选条件，输出视频候选清单"}
    with SessionLocal() as session:
        run = session.get(FactoryRun, run_id)
        engine._draft_prd(session, run, CaptureModel())
        payload = captured[0]
        assert payload == {
            "code": "Q1", "question": "面向哪类用户？", "options": OPTIONS,
            "recommendation": RECOMMENDATION, "answer": expected, "raw_answer": historical_answer,
        }
        assert session.query(Decision).filter_by(run_id=run_id, code="Q1").one().answer == historical_answer
        assert json.loads(run.prd_snapshot)["goal_users"] == expected


@pytest.mark.parametrize(("submitted", "recommendation", "expected"), [
    ("按推荐", RECOMMENDATION, RECOMMENDATION),
    ("B", RECOMMENDATION, "B 企业内容运营团队"),
    ("具体对象由我填写", RECOMMENDATION, "具体对象由我填写"),
    ("按推荐", "", "按推荐"),
])
def test_compare_endpoint_carries_decision_context_and_raw_answer_without_runs(client, monkeypatch, submitted, recommendation, expected):
    captured = []
    class CaptureModel:
        prompt_tokens = completion_tokens = 0
        def generate_prd(self, idea, decisions):
            captured.extend(decisions)
            return {"goal_users": str(decisions[0]["answer"])}
    def mock_only(provider):
        assert provider == "mock", "测试不得调用真实模型"
        return CaptureModel()
    monkeypatch.setattr(llm, "get_llm", mock_only)
    response = client.post("/api/v1/llm/compare-prd", json={
        "idea": "为新手筛选视频", "decisions": [{
            "code": "Q1", "question": "面向哪类用户？", "options": OPTIONS,
            "recommendation": recommendation, "answer": submitted,
        }],
    })
    assert response.status_code == 200, response.text
    variants = response.json()["variants"]
    assert len(variants) == 1 and variants[0]["provider"] == "mock"
    assert variants[0]["error"] is None
    assert captured[0]["answer"] == expected and captured[0]["raw_answer"] == submitted
    assert captured[0]["options"] == OPTIONS and captured[0]["recommendation"] == recommendation
    if recommendation == "":
        assert "未提供具体推荐" in captured[0]["answer_gap"]
    with SessionLocal() as session:
        assert session.query(FactoryRun).count() == 0


def test_compare_endpoint_keeps_legacy_input_compatible(client, monkeypatch):
    captured = []
    class CaptureModel:
        def generate_prd(self, idea, decisions):
            captured.extend(decisions)
            return {"goal_users": "具体用户尚待确认"}
    monkeypatch.setattr(llm, "get_llm", lambda *_: CaptureModel())
    response = client.post("/api/v1/llm/compare-prd", json={"idea": "清单工具", "decisions": [{"code": "Q1", "question": "谁用", "answer": "按推荐"}]})
    assert response.status_code == 200, response.text
    assert response.json()["variants"][0]["error"] is None
    assert captured[0]["options"] == captured[0]["recommendation"] == ""
    assert captured[0]["answer"] == "按推荐" and "answer_gap" in captured[0]
