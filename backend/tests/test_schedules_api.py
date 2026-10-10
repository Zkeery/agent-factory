"""定时任务 API 测试（第十九刀）：CRUD + 用户隔离。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import FactoryRun, Schedule


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


def test_unfinished_schedule_run_is_visible(client, session):
    created = client.post("/api/v1/schedules", json={"idea": "洗澡", "trigger_time": "21:00"}).json()
    schedule = session.get(Schedule, created["id"])
    session.add(FactoryRun(
        id="bath-wait", idea="洗澡", status="running", current_stage="awaiting_answers",
        user_id=schedule.user_id, auto_schedule_id=schedule.id,
    ))
    schedule.last_skipped_at = datetime(2026, 10, 10, 12, 32, tzinfo=timezone.utc)
    schedule.last_skip_reason = "上一次仍在等待回答"
    session.commit()
    item = next(row for row in client.get("/api/v1/schedules").json() if row["id"] == created["id"])
    assert item["pending_run_id"] == "bath-wait"
    assert item["pending_run_stage"] == "awaiting_answers"
    assert item["last_skip_reason"] == "上一次仍在等待回答"
    assert item["last_skipped_at"].startswith("2026-10-10T12:32:00")
    assert item["last_skipped_at"].endswith("+00:00") or item["last_skipped_at"].endswith("Z")
    assert item["created_at"].endswith("+00:00") or item["created_at"].endswith("Z")
