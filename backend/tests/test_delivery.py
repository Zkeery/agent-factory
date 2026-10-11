"""交付包验证：所有权、完整内容、真实验收记录与受控文件边界。"""
from __future__ import annotations

import io
import json
import stat
import zipfile
from datetime import datetime, timezone

import pytest

from app.models import Decision, EvidenceItem, FactoryRun, StageEvent, User
from app.services import delivery


@pytest.fixture()
def bundle_run(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(delivery, "DATA_ROOT", tmp_path / "data")
    owner = session.query(User).filter(User.phone == "13800138000").one()
    run = FactoryRun(
        id="delivery-test-run", user_id=owner.id, idea="记录真实开支的小应用",
        current_stage="awaiting_acceptance", status="running", llm_provider="mock",
        llm_model_snapshot="mock", acceptance_mode="scenario",
        acceptance_scenarios=json.dumps([
            {"id": "main", "title": "记录开支", "input": "填写午餐 25 元", "expected_output": "列表新增一条 25 元开支"},
        ], ensure_ascii=False),
    )
    session.add(run)
    session.commit()
    code = delivery.DATA_ROOT / "code" / run.id
    code.joinpath("deploy").mkdir(parents=True)
    files = {
        "app.py": 'import os\nfrom fastapi import FastAPI\napp = FastAPI()\napi_key = os.getenv("LLM_API_KEY", "")\n',
        "requirements.txt": "fastapi\nuvicorn\n",
        "README.md": "# 应用运行说明\n运行 bash deploy/start.sh\n",
        "deploy/start.sh": '#!/usr/bin/env bash\ncd "$(dirname "$0")/.."\nuvicorn app:app --port 8000\n',
        "deploy/上线验收清单.md": "# 验收\n完成一条真实开支录入。\n",
    }
    for name, content in files.items():
        code.joinpath(name).write_text(content, encoding="utf-8")
    code.joinpath("deploy/start.sh").chmod(0o755)
    evidence_dir = delivery.DATA_ROOT / "evidence" / run.id
    evidence_dir.mkdir(parents=True)
    prd = evidence_dir / "01-prd.md"
    prd.write_text("# PRD\n\n支持记录开支并查看结果。\n", encoding="utf-8")
    session.add(EvidenceItem(run_id=run.id, stage="prd", kind="prd", title="PRD", content_path=str(prd)))
    session.add(Decision(run_id=run.id, code="D1", question="数据放在哪里？", options="本地 / 云端", recommendation="本地", answer="本地", status="answered"))
    session.add(StageEvent(run_id=run.id, stage="testing", event_type="test_result", payload="passed"))
    session.commit()
    return run, code, evidence_dir


def _archive(response):
    assert response.status_code == 200, response.text if response.status_code != 200 else ""
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_bundle_contains_complete_local_application_and_documents(client, bundle_run):
    run, _, _ = bundle_run
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == f'attachment; filename="agent-factory-{run.id}-review.zip"'
    with _archive(response) as archive:
        assert {
            "app/app.py", "app/requirements.txt", "app/README.md", "app/.env.example",
            "app/deploy/start.sh", "app/deploy/上线验收清单.md", "README.md", "docs/PRD.md",
            "docs/decisions.md", "docs/acceptance.md", "docs/acceptance.json", "docs/tests.json", "docs/run.json",
        }.issubset(archive.namelist())
        assert archive.read("app/deploy/start.sh").startswith(b"#!/usr/bin/env bash")
        assert (archive.getinfo("app/deploy/start.sh").external_attr >> 16) & stat.S_IXUSR
        assert "LLM_API_KEY=\n" in archive.read("app/.env.example").decode()
        assert "最终回答：本地" in archive.read("docs/decisions.md").decode()
        assert "人工验收尚未通过" in archive.read("docs/acceptance.md").decode()
        assert json.loads(archive.read("docs/tests.json"))[0]["result"] == "passed"


def test_rejected_bundle_names_the_failed_acceptance_and_is_not_delivered(client, session, bundle_run):
    run, _, _ = bundle_run
    run.acceptance_results = json.dumps(
        [{"scenario_id": "main", "passed": False, "observation": "字体都是歪的，都是反的。"}],
        ensure_ascii=False,
    )
    run.acceptance_note = "字体都是歪的，都是反的。"
    session.commit()
    with _archive(client.get(f"/api/v1/runs/{run.id}/bundle")) as archive:
        readme = archive.read("README.md").decode()
        acceptance = archive.read("docs/acceptance.md").decode()
        record = json.loads(archive.read("docs/acceptance.json"))
        assert "状态：验收未通过" in readme
        assert "人工验收已通过" not in readme
        assert "主流程验收未通过" in acceptance
        assert "不得标为已交付" in acceptance
        assert record["outcome"] == "rejected" and record["stage"] == "awaiting_acceptance"


def test_agent_bundle_exports_public_execution_without_private_context(client, session, bundle_run):
    run, _, _ = bundle_run
    run.execution_mode = "agent_team"
    run.execution_state = json.dumps({
        "status": "completed", "active_role": "verifier", "repair_rounds": 0,
        "contexts": {"builder": [{"role": "system", "content": "private-system-context"}]},
        "private_payload": "private-code-content", "steps": [], "tasks": [], "checks": [], "handoffs": [],
    })
    session.commit()
    with _archive(client.get(f"/api/v1/runs/{run.id}/bundle")) as archive:
        trace = archive.read("docs/execution.json").decode()
        assert json.loads(trace)["execution_mode"] == "agent_team"
        assert "private-system-context" not in trace
        assert "private-code-content" not in trace
        assert json.loads(archive.read("docs/run.json"))["execution_mode"] == "agent_team"


def test_delivered_bundle_has_actual_scenarios_observations_and_latest_prd(client, session, bundle_run):
    run, _, evidence_dir = bundle_run
    run.current_stage = "delivered"
    run.status = "done"
    run.accepted_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    run.acceptance_results = json.dumps([{"scenario_id": "main", "passed": True, "observation": "午餐记录已显示，金额是 25 元。"}], ensure_ascii=False)
    run.acceptance_checklist = json.dumps([{"id": "local_run", "label": "本地启动通过", "passed": True}], ensure_ascii=False)
    run.acceptance_note = "已用本周真实账单复验；下轮再增加导出功能。"
    run.requirement_feedback = json.dumps([{"id": "f1", "feedback": "补上金额单位", "created_at": "2026-10-05"}], ensure_ascii=False)
    run.parent_run_id = "previous-run"
    run.change_request = "补上金额单位"
    prd = evidence_dir / "02-prd.md"
    prd.write_text("# 最新 PRD\n\n金额单位显示为元。\n", encoding="utf-8")
    session.add(EvidenceItem(run_id=run.id, stage="prd", kind="prd", title="修订 PRD", content_path=str(prd)))
    session.commit()
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    with _archive(response) as archive:
        assert response.headers["content-disposition"].endswith('-delivered.zip"')
        assert "金额单位显示为元" in archive.read("docs/PRD.md").decode()
        assert len([name for name in archive.namelist() if name.startswith("docs/evidence/")]) == 2
        result = json.loads(archive.read("docs/acceptance.json"))
        assert result["accepted_at"].startswith("2026-10-05")
        assert result["results"][0]["observation"] == "午餐记录已显示，金额是 25 元。"
        assert result["note"] == "已用本周真实账单复验；下轮再增加导出功能。"
        assert "验收备注：已用本周真实账单复验；下轮再增加导出功能。" in archive.read("docs/acceptance.md").decode()
        assert "真实观察：午餐记录已显示" in archive.read("docs/acceptance.md").decode()
        assert "补上金额单位" in archive.read("docs/decisions.md").decode()
        assert json.loads(archive.read("docs/run.json"))["parent_run_id"] == "previous-run"


def test_bundle_requires_login_and_owner(client, bundle_run):
    run, _, _ = bundle_run
    url = f"/api/v1/runs/{run.id}/bundle"
    assert client.get(url, headers={"Authorization": ""}).status_code == 401
    phone = "13900139000"
    code = client.post("/api/v1/auth/request-code", json={"phone": phone}).json()["mock_code"]
    token = client.post("/api/v1/auth/login", json={"phone": phone, "code": code}).json()["token"]
    response = client.get(url, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"
    assert client.get("/api/v1/runs/missing-run/bundle").status_code == 404


@pytest.mark.parametrize("stage", ["failed", "gate_failed", "cancelled", "building", "testing", "awaiting_prd_confirm"])
def test_bundle_does_not_turn_failed_or_unfinished_runs_into_deliverables(client, session, bundle_run, stage):
    run, _, _ = bundle_run
    run.current_stage = stage
    session.commit()
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bundle_not_ready"


def test_bundle_omits_runtime_files_and_redacts_credentials(client, bundle_run, monkeypatch):
    run, code, evidence_dir = bundle_run
    secret = "fixture-only-configured-credential"
    monkeypatch.setattr(delivery.settings, "llm_api_key", secret)
    for name in [".env", ".env.example", "database.db", "run.log", ".venv/private.py", "__pycache__/app.pyc", "deploy/.env", "deploy/start.log"]:
        file = code / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(secret, encoding="utf-8")
    source = code / "app.py"
    source.write_text(source.read_text() + '\nCUSTOM_API_KEY = "fixture-only-hardcoded-credential"\n', encoding="utf-8")
    prd = evidence_dir / "01-prd.md"
    prd.write_text(prd.read_text() + "\n" + secret, encoding="utf-8")
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    with _archive(response) as archive:
        names = set(archive.namelist())
        assert "app/.env" not in names
        assert not any(name.endswith((".db", ".log", ".pyc")) or ".venv/" in name for name in names)
        contents = b"\n".join(archive.read(name) for name in names)
        assert secret.encode() not in contents
        assert b"fixture-only-hardcoded-credential" not in contents
        assert b"[REDACTED]" in archive.read("app/app.py")
        assert secret.encode() not in archive.read("app/.env.example")


@pytest.mark.parametrize("target", ["app.py", "deploy", "run_directory", "evidence"])
def test_bundle_rejects_symlinks(client, bundle_run, tmp_path, target):
    run, code, evidence_dir = bundle_run
    if target == "run_directory":
        moved = tmp_path / "moved-source"
        code.rename(moved)
        code.symlink_to(moved, target_is_directory=True)
    elif target == "evidence":
        original = evidence_dir / "01-prd.md"
        moved = tmp_path / "external-prd.md"
        original.rename(moved)
        original.symlink_to(moved)
    else:
        original = code / target
        moved = tmp_path / ("moved-" + target.replace("/", "-"))
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=moved.is_dir())
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.status_code == 409


def test_bundle_rejects_evidence_path_outside_run(client, session, bundle_run, tmp_path):
    run, _, evidence_dir = bundle_run
    external = tmp_path / "unrelated-document.md"
    external.write_text("private document outside this run", encoding="utf-8")
    item = session.query(EvidenceItem).filter(EvidenceItem.run_id == run.id).one()
    item.content_path = str(evidence_dir / ".." / ".." / ".." / external.name)
    session.commit()
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.status_code == 409
    assert "private document" not in response.text


@pytest.mark.parametrize("name", ["app.py", "requirements.txt", "deploy/start.sh"])
def test_bundle_refuses_incomplete_application(client, bundle_run, name):
    run, code, _ = bundle_run
    (code / name).unlink()
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bundle_incomplete"


def test_bundle_limits_file_size(client, bundle_run, monkeypatch):
    run, code, _ = bundle_run
    monkeypatch.setattr(delivery, "MAX_FILE_BYTES", 1024)
    (code / "README.md").write_text("a" * 1025, encoding="utf-8")
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "bundle_too_large"


def test_bundle_limits_evidence_count(client, session, bundle_run, monkeypatch):
    run, _, evidence_dir = bundle_run
    monkeypatch.setattr(delivery, "MAX_EVIDENCE_FILES", 1)
    session.add(EvidenceItem(run_id=run.id, stage="gate", kind="gate", title="闸门", content_path=str(evidence_dir / "01-prd.md")))
    session.commit()
    response = client.get(f"/api/v1/runs/{run.id}/bundle")
    assert response.status_code == 413
