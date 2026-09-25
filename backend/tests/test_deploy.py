"""第 4 子阶段测试：测试工序、部署工序、状态机、闸门。"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, StageEvent
from app.services import deploy, engine, testing
from app.services.stages import NEXT_STAGE, Stage

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def _code_dir(run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    d = (DATA_ROOT / "code" / safe)
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_run(session) -> FactoryRun:
    run = FactoryRun(id=str(uuid.uuid4()), idea="x", status="running", current_stage=Stage.IDEA_SUBMITTED.value)
    session.add(run)
    session.commit()
    return run


def answer_all(session, run_id: str) -> None:
    for d in session.query(Decision).filter(Decision.run_id == run_id).all():
        d.answer = "按推荐"
        d.status = "answered"
    session.commit()


# --- 测试工序 ---
FASTAPI_APP = 'from fastapi import FastAPI\napp = FastAPI()\n@app.post("/generate")\ndef g():\n    return {"result": "ok"}\n'
REQS = "fastapi\nuvicorn\nopenai\n"


def _write_app(run_id: str, app: str, reqs: str = REQS) -> None:
    d = _code_dir(run_id)
    (d / "app.py").write_text(app, encoding="utf-8")
    (d / "requirements.txt").write_text(reqs, encoding="utf-8")


def test_testing_pass_on_valid_fastapi_app():
    run_id = str(uuid.uuid4())
    _write_app(run_id, FASTAPI_APP)
    ok, msg = testing.run_tests(run_id)
    assert ok, msg


def test_testing_fail_on_syntax_error():
    run_id = str(uuid.uuid4())
    _write_app(run_id, "def broken(:\n")
    ok, msg = testing.run_tests(run_id)
    assert not ok
    assert "语法错误" in msg


def test_testing_fail_on_missing_requirements():
    run_id = str(uuid.uuid4())
    d = _code_dir(run_id)
    (d / "app.py").write_text(FASTAPI_APP, encoding="utf-8")
    ok, msg = testing.run_tests(run_id)
    assert not ok
    assert "requirements" in msg


def test_testing_fail_on_missing_fastapi():
    run_id = str(uuid.uuid4())
    _write_app(run_id, FASTAPI_APP, reqs="requests\n")
    ok, msg = testing.run_tests(run_id)
    assert not ok
    assert "fastapi" in msg


# --- 部署工序 ---
def test_deploy_generates_files():
    run_id = str(uuid.uuid4())
    result = deploy.generate_deploy(run_id, "测试产品")
    assert Path(result["start_sh"]).is_file()
    assert Path(result["checklist"]).is_file()
    assert Path(result["start_sh"]).read_text(encoding="utf-8").strip() != ""
    assert Path(result["checklist"]).read_text(encoding="utf-8").strip() != ""


# --- 状态机顺序 ---
def test_deploying_after_testing():
    assert NEXT_STAGE[Stage.TESTING] == Stage.DEPLOYING
    assert NEXT_STAGE[Stage.DEPLOYING] == Stage.EVIDENCE_READY


# --- 完整流程含部署 ---
def test_full_pipeline_generates_deploy(session):
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    assert run.current_stage in {Stage.GATE_PASSED.value, Stage.AWAITING_ACCEPTANCE.value, Stage.DELIVERED.value}
    # 完整流水线至少应走到自动闸门之后的验收等待
    assert run.current_stage == Stage.AWAITING_ACCEPTANCE.value
    # 部署证据存在
    deploy_item = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id, EvidenceItem.stage == "deploy").first()
    assert deploy_item is not None


# --- 闸门：测试失败则不过 ---
def test_gate_fails_when_test_fails(session, monkeypatch):
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    # 让测试工序失败
    monkeypatch.setattr(testing, "run_tests", lambda run_id, idea="": (False, "语法错误"))
    engine.advance(session, run)
    assert run.current_stage == Stage.GATE_FAILED.value


# --- 第十刀：readme 产物 + deploy 全文 ---
def test_building_writes_readme_evidence(session):
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    readme = (
        session.query(EvidenceItem)
        .filter(EvidenceItem.run_id == run.id, EvidenceItem.stage == "readme")
        .first()
    )
    assert readme is not None
    assert readme.kind == "readme"
    assert readme.title == "运行说明"
    body = Path(readme.content_path).read_text(encoding="utf-8")
    assert body.strip() != ""
    # mock LLM 给出完整 README
    assert "启动" in body or "uvicorn" in body


def test_deploy_evidence_contains_start_and_checklist(session):
    run = make_run(session)
    engine.advance(session, run)
    answer_all(session, run.id)
    engine.advance(session, run)
    session.add(Confirmation(run_id=run.id, kind="prd", status="confirmed"))
    session.commit()
    engine.advance(session, run)
    deploy_item = (
        session.query(EvidenceItem)
        .filter(EvidenceItem.run_id == run.id, EvidenceItem.stage == "deploy")
        .first()
    )
    assert deploy_item is not None
    assert deploy_item.kind == "deploy"
    body = Path(deploy_item.content_path).read_text(encoding="utf-8")
    assert "start.sh" in body or "uvicorn" in body
    assert "验收" in body or "checklist" in body.lower() or "上线" in body
    assert "已生成" not in body or "uvicorn" in body  # 不再只有一句摘要
