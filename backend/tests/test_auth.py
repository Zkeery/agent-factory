"""登录/账号：手机号验证码（mock 短信）、会话 token、多用户隔离。"""
from __future__ import annotations

import time

from app.core.errors import AppError


def wait_stage(client, run_id: str, stage: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/runs/{run_id}")
        data = r.json()
        if data.get("current_stage") == stage:
            return data
        time.sleep(0.05)
    raise AssertionError(f"等待阶段 {stage} 超时，当前：{data}")


def login_phone(client, phone: str) -> str:
    r = client.post("/api/v1/auth/request-code", json={"phone": phone})
    code = r.json()["mock_code"]
    r = client.post("/api/v1/auth/login", json={"phone": phone, "code": code})
    assert r.status_code == 200
    return r.json()["token"]


def test_request_code_returns_mock_code(client):
    r = client.post("/api/v1/auth/request-code", json={"phone": "13800138000"})
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] == "13800138000"
    assert body["mock_code"] and len(body["mock_code"]) == 6


def test_login_and_me(client):
    token = login_phone(client, "13900139000")
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["phone"] == "13900139000"


def test_login_wrong_code_fails(client):
    client.post("/api/v1/auth/request-code", json={"phone": "13700137000"})
    r = client.post("/api/v1/auth/login", json={"phone": "13700137000", "code": "000000"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "code_invalid"


def test_unauthorized_requires_login(client):
    r = client.get("/api/v1/runs", headers={"Authorization": ""})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_preview_not_ready(client):
    """成品尚未生成完成时不能预览。"""
    r = client.post("/api/v1/runs", json={"idea": "x"})
    run_id = r.json()["id"]
    r2 = client.post(f"/api/v1/runs/{run_id}/start")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "not_ready"


def test_user_isolation(client):
    # 用户 A（client 默认）创建一个 run
    r = client.post("/api/v1/runs", json={"idea": "A 的想法"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    wait_stage(client, run_id, "awaiting_answers")

    # 用户 B 登录，看不到 A 的 run
    token_b = login_phone(client, "13600136000")
    hb = {"Authorization": f"Bearer {token_b}"}
    assert client.get("/api/v1/runs", headers=hb).json()["runs"] == []
    assert client.get(f"/api/v1/runs/{run_id}", headers=hb).status_code == 404
    assert client.post(f"/api/v1/runs/{run_id}/cancel", headers=hb).status_code == 404
