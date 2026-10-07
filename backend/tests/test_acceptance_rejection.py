"""人工验收未通过持久化；测试不执行模型、生成应用或预览。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import runs
from app.core.errors import register_error_handlers
from app.models import Base, Confirmation, FactoryRun, ProductProject, StageEvent, User
from app.services import engine, iteration


@pytest.fixture(autouse=True)
def clean_db():
    """覆盖共享 fixture：本文件仅使用下面创建的临时数据库。"""
    yield


@pytest.fixture
def review(tmp_path, monkeypatch):
    db_engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(db_engine)
    sessions = sessionmaker(bind=db_engine, expire_on_commit=False)
    user = User(id="reviewer", phone="reviewer")
    with sessions() as session:
        session.add(user)
        session.commit()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(runs.router)

    def get_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[runs.get_session] = get_session
    app.dependency_overrides[runs.get_current_user] = lambda: user
    app.dependency_overrides[runs.require_api_key] = lambda: None
    starts = []
    monkeypatch.setattr(engine, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(engine, "start_run_async", lambda run_id: starts.append(run_id))
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, sessions=sessions, starts=starts, root=tmp_path)
    db_engine.dispose()


def create_review(review, **overrides):
    values = dict(
        id="review-run", user_id="reviewer", idea="五子棋", status="running",
        current_stage="awaiting_acceptance", acceptance_mode="basic",
        prd_snapshot=iteration.dump({"goal_users": "五子棋玩家"}),
    )
    values.update(overrides)
    with review.sessions() as session:
        session.add(FactoryRun(**values))
        session.commit()
    return values["id"]


@pytest.mark.parametrize("mode", ["basic", "scenario"])
def test_rejection_persists_failure_without_changing_review_or_observations(review, mode):
    results = [{"scenario_id": "ai", "passed": False, "observation": "落子后 AI 没有行动"}]
    checklist = [{"id": "main_path", "passed": False, "label": "主路径能运行"}]
    run_id = create_review(
        review, acceptance_mode=mode,
        acceptance_results=iteration.dump(results), acceptance_checklist=iteration.dump(checklist),
    )
    with review.sessions() as session:
        session.add(Confirmation(run_id=run_id, kind="acceptance", status="pending"))
        session.commit()
    response = review.client.post(f"/api/v1/runs/{run_id}/reject", json={"note": "  人机对战：玩家落子后 AI 不落子  "})
    assert response.status_code == 200, response.text
    data = review.client.get(f"/api/v1/runs/{run_id}").json()
    assert data["acceptance_note"] == "人机对战：玩家落子后 AI 不落子"
    assert data["current_stage"] == "awaiting_acceptance" and data["status"] == "running"
    assert data["accepted_at"] is None
    assert data["acceptance_results"] == results and data["acceptance_checklist"] == checklist
    with review.sessions() as session:
        assert session.query(FactoryRun).count() == 1
        saved = session.get(FactoryRun, run_id)
        assert iteration.json_list(saved.acceptance_results) == results
        assert iteration.json_list(saved.acceptance_checklist) == checklist
        assert session.query(Confirmation).one().status == "pending"
        event = session.query(StageEvent).one()
        assert event.event_type == "human_acceptance_rejected" and event.stage == "awaiting_acceptance"
        assert iteration.json_dict(event.payload) == {"note": data["acceptance_note"]}
        assert session.query(StageEvent).filter_by(event_type="delivery_accepted").count() == 0
    assert review.starts == []


def test_repeated_rejection_is_idempotent_but_changed_note_is_recorded(review):
    run_id = create_review(review)
    url = f"/api/v1/runs/{run_id}/reject"
    for note in ("AI 不落子", " AI 不落子 ", "AI 连续两局都不落子", "AI 不落子"):
        assert review.client.post(url, json={"note": note}).status_code == 200
    with review.sessions() as session:
        assert session.query(StageEvent).count() == 3
        assert session.get(FactoryRun, run_id).acceptance_note == "AI 不落子"
        assert session.query(Confirmation).count() == 0
    assert review.starts == []


@pytest.mark.parametrize("note", ["", " \n\t ", "x" * 4001])
def test_rejection_requires_a_bounded_nonempty_note(review, note):
    run_id = create_review(review)
    response = review.client.post(f"/api/v1/runs/{run_id}/reject", json={"note": note})
    assert response.status_code == 422
    with review.sessions() as session:
        assert session.query(StageEvent).count() == 0
        assert session.get(FactoryRun, run_id).acceptance_note == ""


@pytest.mark.parametrize("stage", ["idea_submitted", "awaiting_answers", "awaiting_prd_confirm", "building", "testing", "delivered", "failed", "gate_failed", "cancelled"])
def test_rejection_only_allows_pending_review_and_preserves_prior_acceptance(review, stage):
    accepted_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    run_id = create_review(review, current_stage=stage, acceptance_note="历史验收", accepted_at=accepted_at)
    with review.sessions() as session:
        session.add(Confirmation(run_id=run_id, kind="acceptance", status="confirmed"))
        session.commit()
    response = review.client.post(f"/api/v1/runs/{run_id}/reject", json={"note": "覆盖历史"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "acceptance_not_reviewable"
    with review.sessions() as session:
        run = session.get(FactoryRun, run_id)
        assert run.current_stage == stage and run.acceptance_note == "历史验收"
        assert run.accepted_at is not None
        assert session.query(Confirmation).one().status == "confirmed"
        assert session.query(StageEvent).count() == 0
    assert review.starts == []


def test_rejection_removes_unfinished_acceptance_confirmation(review):
    run_id = create_review(review)
    with review.sessions() as session:
        session.add(Confirmation(run_id=run_id, kind="acceptance", status="confirmed"))
        session.commit()
    assert review.client.post(f"/api/v1/runs/{run_id}/reject", json={"note": "主链路未通过"}).status_code == 200
    with review.sessions() as session:
        assert session.query(Confirmation).one().status == "pending"


@pytest.mark.parametrize("hidden", ["missing", "other_owner", "deleted_project"])
def test_rejection_respects_run_ownership_and_recycle_bin(review, hidden):
    run_id = "missing"
    if hidden != "missing":
        run_id = create_review(review, user_id="someone-else" if hidden == "other_owner" else "reviewer")
    if hidden == "deleted_project":
        with review.sessions() as session:
            session.add(ProductProject(id="deleted", user_id="reviewer", name="回收站项目", deleted_at=datetime.now(timezone.utc)))
            session.get(FactoryRun, run_id).project_id = "deleted"
            session.commit()
    response = review.client.post(f"/api/v1/runs/{run_id}/reject", json={"note": "不能越过归属"})
    assert response.status_code == 404 and response.json()["error"]["code"] == "run_not_found"
    with review.sessions() as session:
        assert session.query(StageEvent).count() == 0


def test_rejection_note_and_observations_are_frozen_into_revision_context(review):
    run_id = create_review(review, acceptance_results=iteration.dump([{"scenario_id": "ai", "passed": False, "observation": "AI 没响应"}]))
    root = review.root / "code" / run_id
    root.mkdir(parents=True)
    for name, content in {"app.py": "# parent source", "requirements.txt": "fastapi", "README.md": "父版本"}.items():
        (root / name).write_text(content, encoding="utf-8")
    assert review.client.post(f"/api/v1/runs/{run_id}/reject", json={"note": "AI 不落子，主链路失败"}).status_code == 200
    response = review.client.post(f"/api/v1/runs/{run_id}/revise", json={"change_request": "修复 AI 回合", "request_id": "repair-ai"})
    assert response.status_code == 201, response.text
    child_id = response.json()["id"]
    with review.sessions() as session:
        child = session.get(FactoryRun, child_id)
        context = iteration.json_dict(child.parent_context)
        assert context["acceptance_note"] == "AI 不落子，主链路失败"
        assert context["acceptance_results"][0]["observation"] == "AI 没响应"
        assert context["files"]["app.py"] == "# parent source"
        assert child.parent_run_id == run_id and child.accepted_at is None and child.acceptance_note == ""
        session.get(FactoryRun, run_id).acceptance_note = "后续编辑"
        session.commit()
    with review.sessions() as session:
        assert iteration.json_dict(session.get(FactoryRun, child_id).parent_context)["acceptance_note"] == "AI 不落子，主链路失败"
    assert review.starts == [child_id]
