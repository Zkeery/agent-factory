"""API 层测试：接口、错误路径与 SSE 收尾。"""
from __future__ import annotations

import time


def wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        data = r.json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前状态：{data}")


def test_create_and_await_answers(client):
    r = client.post("/api/v1/runs", json={"idea": "做一个给宠物起名字的小工具"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    assert 0 < len(data["decisions"]) <= 5


def test_full_flow_via_api(client):
    r = client.post("/api/v1/runs", json={"idea": "宠物起名工具"})
    assert r.status_code == 201
    run_id = r.json()["id"]

    data = wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        r = client.post(f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer", json={"answer": "按推荐"})
        assert r.status_code == 200

    data = wait_stage(client, run_id, "awaiting_prd_confirm")
    r = client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True})
    assert r.status_code == 200

    data = wait_stage(client, run_id, "awaiting_acceptance")
    assert data["current_stage"] == "awaiting_acceptance"
    r = client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": [{"id": "local_run", "label": "主路径能按说明在本地跑起来", "passed": True},{"id": "prd_match", "label": "PRD 与实现大体一致", "passed": True},{"id": "no_blockers", "label": "没有明显阻断性错误", "passed": True}], "note": "ok"})
    assert r.status_code == 200
    data = wait_stage(client, run_id, "delivered")
    assert data["status"] == "done"

    ev = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert len(ev) > 0


def test_run_not_found(client):
    assert client.get("/api/v1/runs/nonexistent").status_code == 404


def test_duplicate_answer_idempotent(client):
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    code = data["decisions"][0]["code"]
    assert client.post(f"/api/v1/runs/{run_id}/decisions/{code}/answer", json={"answer": "A"}).status_code == 200
    # 幂等：关键决策重复回答返回 200，但答案不变
    r2 = client.post(f"/api/v1/runs/{run_id}/decisions/{code}/answer", json={"answer": "B"})
    assert r2.status_code == 200
    d = [x for x in r2.json()["decisions"] if x["code"] == code][0]
    assert d["answer"] == "A"


def test_noncritical_can_reanswer(client):
    """非关键决策自动按推荐后可改（决策卡 A+B 的「事后可改」）。"""
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    noncrit = [d for d in data["decisions"] if not d["is_critical"]]
    assert noncrit, "mock 应包含非关键决策"
    code = noncrit[0]["code"]
    r2 = client.post(f"/api/v1/runs/{run_id}/decisions/{code}/answer", json={"answer": "B 活泼俏皮"})
    assert r2.status_code == 200
    d = [x for x in r2.json()["decisions"] if x["code"] == code][0]
    assert d["answer"] == "B 活泼俏皮"


def test_invalid_decision_code(client):
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")
    assert client.post(f"/api/v1/runs/{run_id}/decisions/NOCODE/answer", json={"answer": "A"}).status_code == 404


def test_answer_outside_awaiting_idempotent(client):
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    # 完整走完到终态后，再回答决策卡应幂等返回 200（不报错）
    data = wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        client.post(f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer", json={"answer": "A"})
    wait_stage(client, run_id, "awaiting_prd_confirm")
    client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True})
    wait_stage(client, run_id, "awaiting_acceptance")
    client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": [{"id": "local_run", "label": "主路径能按说明在本地跑起来", "passed": True},{"id": "prd_match", "label": "PRD 与实现大体一致", "passed": True},{"id": "no_blockers", "label": "没有明显阻断性错误", "passed": True}], "note": "ok"})
    wait_stage(client, run_id, "delivered")
    code = data["decisions"][0]["code"]
    r2 = client.post(f"/api/v1/runs/{run_id}/decisions/{code}/answer", json={"answer": "B"})
    assert r2.status_code == 200


def test_sse_terminates_with_done(client):
    r = client.post("/api/v1/runs", json={"idea": "宠物起名"})
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        client.post(f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer", json={"answer": "A"})
    wait_stage(client, run_id, "awaiting_prd_confirm")
    client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True})
    wait_stage(client, run_id, "awaiting_acceptance")
    client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": [{"id": "local_run", "label": "主路径能按说明在本地跑起来", "passed": True},{"id": "prd_match", "label": "PRD 与实现大体一致", "passed": True},{"id": "no_blockers", "label": "没有明显阻断性错误", "passed": True}], "note": "ok"})
    wait_stage(client, run_id, "delivered")

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        text = "".join(resp.iter_text())
    assert "event: done" in text


def test_list_runs(client):
    r1 = client.post("/api/v1/runs", json={"idea": "第一个想法"})
    r2 = client.post("/api/v1/runs", json={"idea": "第二个想法"})
    assert r1.status_code == 201 and r2.status_code == 201
    data = client.get("/api/v1/runs").json()
    runs = data["runs"]
    ids = [r["id"] for r in runs]
    # 倒序：第二个想法在前
    assert r2.json()["id"] in ids
    assert r1.json()["id"] in ids
    assert ids.index(r2.json()["id"]) < ids.index(r1.json()["id"])
    for r in runs:
        assert set(r.keys()) == {"id", "idea", "current_stage", "status", "created_at", "project_id", "auto_schedule_id"}


def test_noncritical_reanswer_at_prd_confirm_regenerates_prd(client):
    """改非关键决策后 PRD 应重新生成，并保持在 awaiting_prd_confirm。"""
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        client.post(f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer", json={"answer": "按推荐"})
    data = wait_stage(client, run_id, "awaiting_prd_confirm")
    noncrit = [d for d in data["decisions"] if not d["is_critical"]]
    assert noncrit, "mock 应包含非关键决策"
    code = noncrit[0]["code"]

    old_paths = {e["content_path"] for e in client.get(f"/api/v1/runs/{run_id}/evidence").json() if e["stage"] == "prd"}
    r2 = client.post(f"/api/v1/runs/{run_id}/decisions/{code}/answer", json={"answer": "B 活泼俏皮"})
    assert r2.status_code == 200
    assert r2.json()["current_stage"] == "awaiting_prd_confirm"
    d = [x for x in r2.json()["decisions"] if x["code"] == code][0]
    assert d["answer"] == "B 活泼俏皮"

    new_paths = {e["content_path"] for e in client.get(f"/api/v1/runs/{run_id}/evidence").json() if e["stage"] == "prd"}
    assert new_paths and new_paths != old_paths  # PRD 已重新生成（新证据文件）
