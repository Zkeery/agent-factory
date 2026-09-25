"""第六刀：验收清单必须人工勾选齐全才能交付。"""
from __future__ import annotations

import time

from app.services.acceptance import DEFAULT_ACCEPTANCE_CHECKLIST, REQUIRED_IDS


def wait_stage(client, run_id: str, stage: str, timeout: float = 12.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        data = r.json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前：{data}")


def full_checklist(all_passed: bool = True) -> list[dict]:
    return [
        {"id": item.id, "label": item.label, "passed": all_passed}
        for item in DEFAULT_ACCEPTANCE_CHECKLIST
    ]


def drive_to_acceptance(client) -> str:
    r = client.post("/api/v1/runs", json={"idea": "验收清单闭环样例"})
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    data = wait_stage(client, run_id, "awaiting_answers")
    for d in data["decisions"]:
        assert client.post(
            f"/api/v1/runs/{run_id}/decisions/{d['code']}/answer",
            json={"answer": "按推荐"},
        ).status_code == 200
    wait_stage(client, run_id, "awaiting_prd_confirm")
    assert client.post(f"/api/v1/runs/{run_id}/confirm-prd", json={"confirmed": True}).status_code == 200
    wait_stage(client, run_id, "awaiting_acceptance", timeout=20.0)
    return run_id


def test_accept_rejects_empty_checklist(client):
    run_id = drive_to_acceptance(client)
    r = client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": [], "note": "ok"})
    assert r.status_code == 400
    body = r.json()
    code = body.get("error", {}).get("code") or body.get("detail", {}).get("code")
    assert code == "acceptance_incomplete"
    assert client.get(f"/api/v1/runs/{run_id}").json()["current_stage"] == "awaiting_acceptance"


def test_accept_rejects_partial_fail(client):
    run_id = drive_to_acceptance(client)
    items = full_checklist(True)
    items[0]["passed"] = False
    r = client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": items, "note": "缺一项"})
    assert r.status_code == 400
    body = r.json()
    code = body.get("error", {}).get("code") or body.get("detail", {}).get("code")
    assert code == "acceptance_incomplete"


def test_accept_rejects_missing_required_id(client):
    run_id = drive_to_acceptance(client)
    items = full_checklist(True)[1:]
    r = client.post(f"/api/v1/runs/{run_id}/accept", json={"checklist": items})
    assert r.status_code == 400
    body = r.json()
    code = body.get("error", {}).get("code") or body.get("detail", {}).get("code")
    assert code == "acceptance_incomplete"


def test_accept_with_full_checklist_delivers(client):
    run_id = drive_to_acceptance(client)
    r = client.post(
        f"/api/v1/runs/{run_id}/accept",
        json={"checklist": full_checklist(True), "note": "全部通过"},
    )
    assert r.status_code == 200, r.text
    data = wait_stage(client, run_id, "delivered", timeout=8.0)
    assert data["current_stage"] == "delivered"
    assert REQUIRED_IDS == frozenset(i.id for i in DEFAULT_ACCEPTANCE_CHECKLIST)
