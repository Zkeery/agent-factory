"""第十三刀：gate_failed 就地重测（续跑 testing），与整段 retry 区分。"""
from __future__ import annotations

import time
from pathlib import Path

from app.models import FactoryRun, SessionLocal, StageEvent
from app.services.stages import Stage

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"

FASTAPI_APP = (
    'from fastapi import FastAPI\n'
    "app = FastAPI()\n"
    '@app.post("/generate")\n'
    "def g():\n"
    '    return {"result": "ok"}\n'
)
REQS = "fastapi\nuvicorn\nopenai\n"


def wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        data = r.json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前：{data}")


def _write_code(run_id: str) -> None:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")
    d = DATA_ROOT / "code" / safe
    d.mkdir(parents=True, exist_ok=True)
    (d / "app.py").write_text(FASTAPI_APP, encoding="utf-8")
    (d / "requirements.txt").write_text(REQS, encoding="utf-8")


def _mark_gate_failed(run_id: str, reason: str = "代码测试未通过：模拟") -> None:
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        run.current_stage = Stage.GATE_FAILED.value
        run.status = "done"
        run.failure_reason = reason
        session.commit()
    finally:
        session.close()


def test_retest_gate_failed_with_code_same_id(client):
    r = client.post("/api/v1/runs", json={"idea": "就地重测有代码"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    _write_code(run_id)
    _mark_gate_failed(run_id)

    r = client.post(f"/api/v1/runs/{run_id}/retest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == run_id
    # 刚拨回时同 id，且已离开原失败终态（或已进入 testing）
    assert body["current_stage"] != "gate_failed" or body.get("failure_reason") is None

    # 续跑证据：出现 testing 阶段事件，或失败原因被重测改写
    deadline = time.time() + 15.0
    saw = False
    while time.time() < deadline:
        session = SessionLocal()
        try:
            ev = (
                session.query(StageEvent)
                .filter(StageEvent.run_id == run_id, StageEvent.stage == "testing")
                .order_by(StageEvent.id.desc())
                .first()
            )
            run = session.get(FactoryRun, run_id)
            if ev is not None:
                saw = True
                break
            if run and run.failure_reason and run.failure_reason != "代码测试未通过：模拟":
                saw = True
                break
            if run and run.current_stage not in {Stage.GATE_FAILED.value, Stage.FAILED.value}:
                saw = True
                break
        finally:
            session.close()
        time.sleep(0.05)
    assert saw, "重测后未见 testing 事件或阶段推进"


def test_retest_without_code_409(client):
    r = client.post("/api/v1/runs", json={"idea": "无代码不可仅重测"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    _mark_gate_failed(run_id)

    r = client.post(f"/api/v1/runs/{run_id}/retest")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "no_code_to_retest"
    assert "整段重跑" in err["message"]


def test_retest_rejects_awaiting_acceptance(client):
    r = client.post("/api/v1/runs", json={"idea": "待验收不可仅重测"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    session = SessionLocal()
    try:
        run = session.get(FactoryRun, run_id)
        run.current_stage = Stage.AWAITING_ACCEPTANCE.value
        run.status = "running"
        session.commit()
    finally:
        session.close()
    _write_code(run_id)

    r = client.post(f"/api/v1/runs/{run_id}/retest")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_retestable"


def test_retest_differs_from_retry(client):
    r = client.post("/api/v1/runs", json={"idea": "重试仍新开"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    _write_code(run_id)
    _mark_gate_failed(run_id)

    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != run_id
    assert new["idea"] == "重试仍新开"

    old = client.get(f"/api/v1/runs/{run_id}").json()
    assert old["current_stage"] == "gate_failed"
