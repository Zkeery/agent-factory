"""第一刀：项目绑定、产物列表、验收闸门。"""
from __future__ import annotations


def test_create_run_auto_creates_project(client):
    r = client.post("/api/v1/runs", json={"idea": "做一个记账小工具"})
    assert r.status_code == 201
    body = r.json()
    assert body.get("project_id")
    pid = body["project_id"]
    pr = client.get("/api/v1/projects")
    assert pr.status_code == 200
    ids = [p["id"] for p in pr.json()["projects"]]
    assert pid in ids


def test_artifacts_and_accept_gate(client):
    r = client.post("/api/v1/runs", json={"idea": "做一个待办清单"})
    run_id = r.json()["id"]

    # wait awaiting_answers
    import time
    stage = None
    for _ in range(80):
        data = client.get(f"/api/v1/runs/{run_id}").json()
        stage = data["current_stage"]
        if stage == "awaiting_answers":
            break
        time.sleep(0.05)
    assert stage == "awaiting_answers"
    for d in data["decisions"]:
        if d["status"] != "answered":
            client.post(f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer", json={"answer": "按推荐"})
    for _ in range(80):
        data = client.get(f"/api/v1/runs/{run_id}").json()
        if data["current_stage"] == "awaiting_prd_confirm":
            break
        time.sleep(0.05)
    assert data["current_stage"] == "awaiting_prd_confirm"
    client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True})
    for _ in range(120):
        data = client.get(f"/api/v1/runs/{run_id}").json()
        if data["current_stage"] == "awaiting_acceptance":
            break
        time.sleep(0.05)
    assert data["current_stage"] == "awaiting_acceptance"

    arts = client.get(f"/api/v1/runs/{run_id}/artifacts")
    assert arts.status_code == 200
    assert len(arts.json()) >= 1
    aid = arts.json()[0]["id"]
    detail = client.get(f"/api/v1/runs/{run_id}/artifacts/{aid}")
    assert detail.status_code == 200
    assert "content" in detail.json()

    # 未验收不能算交付
    assert data["current_stage"] != "delivered"
    acc = client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": [{"id": "local_run", "label": "主路径能按说明在本地跑起来", "passed": True},{"id": "prd_match", "label": "PRD 与实现大体一致", "passed": True},{"id": "no_blockers", "label": "没有明显阻断性错误", "passed": True}], "note": "通过"})
    assert acc.status_code == 200
    for _ in range(80):
        data = client.get(f"/api/v1/runs/{run_id}").json()
        if data["current_stage"] == "delivered":
            break
        time.sleep(0.05)
    assert data["current_stage"] == "delivered"
