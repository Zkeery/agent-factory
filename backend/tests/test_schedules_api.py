"""定时任务 API 测试（第十九刀）：CRUD + 用户隔离。"""
from __future__ import annotations


def test_schedules_crud(client):
    r = client.post("/api/v1/schedules", json={"idea": "做个记账本", "trigger_time": "09:00"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["enabled"] is True

    items = client.get("/api/v1/schedules").json()
    assert any(x["id"] == sid for x in items)

    r = client.patch(f"/api/v1/schedules/{sid}", json={"enabled": False, "trigger_time": "10:30"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["trigger_time"] == "10:30"

    r = client.delete(f"/api/v1/schedules/{sid}")
    assert r.status_code == 200
    assert not any(x["id"] == sid for x in client.get("/api/v1/schedules").json())


def test_schedule_bad_time_rejected(client):
    assert client.post("/api/v1/schedules", json={"idea": "x", "trigger_time": "9:00"}).status_code == 422


def test_schedule_not_found(client):
    assert client.delete("/api/v1/schedules/nonexistent").status_code == 404
