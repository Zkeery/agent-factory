"""项目回收站保留版本/产物，隔离所有者、自动执行与定时调度。"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, text

from app import models
from app.core.config import settings
from app.models import Confirmation, Decision, EvidenceItem, FactoryRun, ProductProject, Schedule, SessionLocal, StageEvent
from app.services import deploy, engine, evidence, runner, scheduler, testing


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    for module in (engine, deploy, evidence, runner, testing):
        monkeypatch.setattr(module, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(runner, "PREVIEW_DIR", tmp_path / "preview")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(engine, "start_run_async", lambda *_: None)
    monkeypatch.setattr(scheduler, "start_scheduler", lambda: None)


def project_with_run(client, *, stage="awaiting_answers", status="running", project_id=None):
    if project_id is None:
        response = client.post("/api/v1/projects", json={"name": "可恢复项目", "idea_summary": "保留历史版本"})
        assert response.status_code == 201, response.text
        project_id = response.json()["id"]
    response = client.post("/api/v1/runs", json={"idea": "本地待办工具", "project_id": project_id, "llm_provider": "mock"})
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    with SessionLocal() as session:
        run = session.get(FactoryRun, run_id)
        run.current_stage, run.status = stage, status
        session.commit()
    return project_id, run_id


def test_delete_all_versions_hides_project_runs_but_preserves_records_files_and_restores(client, tmp_path):
    project_id, first = project_with_run(client, stage="delivered", status="done")
    _, second = project_with_run(client, project_id=project_id, stage="awaiting_prd_confirm")
    app_path = tmp_path / "code" / first / "app.py"
    app_path.parent.mkdir(parents=True)
    app_path.write_text("# 保留交付版本\n", encoding="utf-8")
    with SessionLocal() as session:
        session.add(Decision(run_id=first, code="Q1", question="谁用", options="A 个人", recommendation="A 个人", answer="A 个人", status="answered"))
        session.add(Confirmation(run_id=first, kind="prd", status="confirmed"))
        session.add(StageEvent(run_id=first, stage="delivered", payload="用户已经验收"))
        session.add(EvidenceItem(run_id=first, stage="code", title="旧代码", content_path=str(app_path)))
        session.commit()
    assert client.get("/api/v1/metrics").json()["total_runs"] == 2
    response = client.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200 and response.json() == {"deleted": True, "project_id": project_id}
    assert client.delete(f"/api/v1/projects/{project_id}").json() == response.json()
    assert client.get("/api/v1/projects").json()["projects"] == []
    trash = client.get("/api/v1/projects?deleted=true").json()["projects"]
    assert [row["id"] for row in trash] == [project_id] and trash[0]["run_count"] == 2
    assert client.get("/api/v1/runs").json()["runs"] == []
    for url in (f"/api/v1/projects/{project_id}", f"/api/v1/projects/{project_id}/runs", f"/api/v1/runs/{first}", f"/api/v1/runs/{second}"):
        assert client.get(url).status_code == 404
    assert client.patch(f"/api/v1/projects/{project_id}", json={"name": "不能改回收站"}).status_code == 404
    assert client.post("/api/v1/runs", json={"idea": "不应生成新版本", "project_id": project_id}).status_code == 404
    assert client.get("/api/v1/metrics").json()["total_runs"] == 0
    assert client.get("/api/v1/metrics/review?source=all").json()["counts"]["total"] == 0
    assert client.get(f"/api/v1/metrics/review?source=all&project_id={project_id}").status_code == 404
    with SessionLocal() as session:
        assert session.query(FactoryRun).filter(FactoryRun.project_id == project_id).count() == 2
        assert session.query(Decision).filter_by(run_id=first).count() == 1
        assert session.query(Confirmation).filter_by(run_id=first).count() == 1
        assert session.query(StageEvent).filter_by(run_id=first).count() == 1
        assert session.query(EvidenceItem).filter_by(run_id=first).count() == 1
        assert session.get(ProductProject, project_id).deleted_at is not None
    assert app_path.read_text(encoding="utf-8") == "# 保留交付版本\n"
    restored = client.post(f"/api/v1/projects/{project_id}/restore")
    assert restored.status_code == 200 and restored.json()["run_count"] == 2
    assert client.post(f"/api/v1/projects/{project_id}/restore").status_code == 200
    assert client.get("/api/v1/projects?deleted=true").json()["projects"] == []
    assert {row["id"] for row in client.get(f"/api/v1/projects/{project_id}/runs").json()["runs"]} == {first, second}
    assert client.get(f"/api/v1/runs/{first}").status_code == 200
    assert client.get("/api/v1/metrics").json()["total_runs"] == 2


@pytest.mark.parametrize("stage", ["idea_submitted", "clarifying", "prd_drafting", "building", "testing", "deploying", "evidence_ready", "gate_passed"])
def test_automatic_execution_rejects_deletion_without_changing_project(client, stage):
    project_id, _ = project_with_run(client, stage=stage)
    response = client.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code == 409 and response.json()["error"]["code"] == "project_busy"
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 200
    with SessionLocal() as session:
        assert session.get(ProductProject, project_id).deleted_at is None


@pytest.mark.parametrize(("stage", "status"), [
    ("awaiting_answers", "running"), ("awaiting_prd_confirm", "running"), ("awaiting_acceptance", "running"),
    ("cancelled", "done"), ("gate_failed", "done"), ("delivered", "done"), ("building", "paused"),
])
def test_human_wait_terminal_and_paused_execution_are_recoverably_deletable(client, stage, status):
    project_id, run_id = project_with_run(client, stage=stage, status=status)
    assert client.delete(f"/api/v1/projects/{project_id}").status_code == 200
    assert client.post(f"/api/v1/projects/{project_id}/restore").status_code == 200
    restored = client.get(f"/api/v1/runs/{run_id}").json()
    assert restored["current_stage"] == stage and restored["status"] == status


def test_deleted_project_schedules_pause_and_require_explicit_reenable_after_restore(client, monkeypatch):
    project_id, run_id = project_with_run(client)
    response = client.post("/api/v1/schedules", json={"idea": "每天生成待办草稿", "trigger_time": "08:00", "project_id": project_id})
    assert response.status_code == 201, response.text
    schedule_id = response.json()["id"]
    assert client.delete(f"/api/v1/projects/{project_id}").status_code == 200
    assert client.get("/api/v1/schedules").json()[0]["enabled"] is False
    assert client.post("/api/v1/schedules", json={"idea": "不能创建", "trigger_time": "08:00", "project_id": project_id}).status_code == 404
    assert client.patch(f"/api/v1/schedules/{schedule_id}", json={"enabled": True}).status_code == 404
    # 遗留的启用标记也不能越过回收站重新运行项目。
    with SessionLocal() as session:
        session.get(Schedule, schedule_id).enabled = True
        session.commit()
    started = []
    monkeypatch.setattr(engine, "start_run_async", lambda ident: started.append(ident))
    monkeypatch.setattr(scheduler, "_local_now", lambda: datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc))
    assert scheduler.check_due_schedules() == 0 and started == []
    with SessionLocal() as session:
        assert session.query(FactoryRun).count() == 1
        assert session.get(FactoryRun, run_id) is not None
        assert session.get(Schedule, schedule_id).enabled is False
    assert client.post(f"/api/v1/projects/{project_id}/restore").status_code == 200
    assert client.get("/api/v1/schedules").json()[0]["enabled"] is False
    assert client.patch(f"/api/v1/schedules/{schedule_id}", json={"enabled": True}).status_code == 200


def test_delete_restore_and_trash_are_owner_isolated(client):
    project_id, run_id = project_with_run(client)
    code = client.post("/api/v1/auth/request-code", json={"phone": "13900139000"}).json()["mock_code"]
    token = client.post("/api/v1/auth/login", json={"phone": "13900139000", "code": code}).json()["token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.delete(f"/api/v1/projects/{project_id}", headers=other).status_code == 404
    assert client.post(f"/api/v1/projects/{project_id}/restore", headers=other).status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/projects/{project_id}").status_code == 200
    assert client.get("/api/v1/projects?deleted=true", headers=other).json()["projects"] == []
    assert client.post(f"/api/v1/projects/{project_id}/restore", headers=other).status_code == 404


def test_old_project_table_migrates_deleted_at_idempotently_without_losing_rows(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy-projects.db'}")
    try:
        with legacy_engine.begin() as connection:
            connection.execute(text("CREATE TABLE product_projects (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, name VARCHAR(128) NOT NULL, idea_summary TEXT NOT NULL DEFAULT '', workspace_path TEXT NOT NULL DEFAULT '', created_at DATETIME, updated_at DATETIME)"))
            connection.execute(text("INSERT INTO product_projects (id,user_id,name) VALUES ('old-project','old-user','原有项目')"))
        models.Base.metadata.create_all(legacy_engine)
        models._migrate_schema(legacy_engine)
        models._migrate_schema(legacy_engine)
        columns = {column["name"] for column in inspect(legacy_engine).get_columns("product_projects")}
        assert "deleted_at" in columns
        with legacy_engine.connect() as connection:
            row = connection.execute(text("SELECT name, deleted_at FROM product_projects WHERE id='old-project'")).one()
            assert row == ("原有项目", None)
    finally:
        legacy_engine.dispose()
