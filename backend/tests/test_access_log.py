"""访问日志不得留下可用的登录令牌或接口密钥。"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from uvicorn.config import LOGGING_CONFIG, Config
from uvicorn.logging import AccessFormatter

from app.core.access_log import (
    AccessCredentialFilter,
    QueryCredentialRedactionMiddleware,
    install_access_log_redaction,
    redact_credential_text,
)

SECRET = "sess" + "ab" * 30
API_KEY = "service-key-value"
BACKEND = Path(__file__).resolve().parents[1]


def test_redact_credential_text_keeps_other_query_values():
    raw = f"/api/v1/runs/abc/events?token={SECRET}&api_key={API_KEY}&x=1"
    cleaned = redact_credential_text(raw)
    assert SECRET not in cleaned
    assert API_KEY not in cleaned
    assert cleaned == "/api/v1/runs/abc/events?token=***&api_key=***&x=1"
    assert redact_credential_text("/health") == "/health"
    assert redact_credential_text("token=***") == "token=***"


def test_uvicorn_access_formatter_hides_query_credentials():
    config = Config(app="app.main:app", host="127.0.0.1", port=8010, log_config=LOGGING_CONFIG, access_log=True)
    assert config.access_log is True
    install_access_log_redaction()
    logger = logging.getLogger("uvicorn.access")
    assert any(isinstance(item, AccessCredentialFilter) for item in logger.filters)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter(LOGGING_CONFIG["formatters"]["access"]["fmt"], use_colors=False))
    logger.addHandler(handler)
    path = f"/api/v1/runs/abc/events?token={SECRET}&api_key={API_KEY}"
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:9", "GET", path, "1.1", 401)
    finally:
        logger.removeHandler(handler)
    text = stream.getvalue()
    assert SECRET not in text
    assert API_KEY not in text
    assert "GET /api/v1/runs/abc/events?token=***&api_key=*** HTTP/1.1" in text
    assert "401" in text


def test_middleware_redacts_query_before_outer_send_sees_it():
    seen: dict[str, bytes] = {}

    async def app(scope, receive, send):
        assert SECRET.encode() in scope["query_string"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            seen["query"] = bytes(scope["query_string"])

    scope = {
        "type": "http",
        "query_string": f"token={SECRET}&api_key={API_KEY}&x=1".encode(),
    }
    asyncio.run(QueryCredentialRedactionMiddleware(app)(scope, receive, send))
    assert SECRET.encode() not in seen["query"]
    assert API_KEY.encode() not in seen["query"]
    assert seen["query"] == b"token=***&api_key=***&x=1"


def test_events_query_token_still_authenticates(client):
    from fastapi.testclient import TestClient

    from app.main import app

    created = client.post("/api/v1/runs", json={"idea": "进度流仍可用查询令牌"})
    assert created.status_code == 201
    run_id = created.json()["id"]
    token = client.headers["Authorization"].split(" ", 1)[1]
    with TestClient(app) as fresh:
        me = fresh.get("/api/v1/auth/me", params={"token": token})
        assert me.status_code == 200
        denied = fresh.get("/api/v1/auth/me")
        assert denied.status_code == 401
        with fresh.stream("GET", f"/api/v1/runs/{run_id}/events", params={"token": token}) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_ensure_backend_uvicorn_access_log_omits_token(tmp_path):
    """与 scripts/ensure-backend.sh 相同的 uvicorn 启动方式：reload + 默认访问日志。"""
    port = _free_port()
    log_path = tmp_path / "uvicorn.log"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'access-log.db'}"
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--reload",
        "--reload-dir",
        "app",
        "--timeout-graceful-shutdown",
        "1",
    ]
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            command,
            cwd=BACKEND,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    try:
        deadline = time.time() + 25
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/docs", timeout=1) as resp:
                    ready = resp.status == 200
                    if ready:
                        break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(0.3)
        assert ready, log_path.read_text(encoding="utf-8")[-2000:]
        url = f"http://127.0.0.1:{port}/api/v1/runs/missing/events?token={SECRET}&api_key={API_KEY}"
        try:
            urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code in {401, 404}
        found = False
        wait_until = time.time() + 5
        while time.time() < wait_until:
            text = log_path.read_text(encoding="utf-8")
            if "/api/v1/runs/missing/events" in text:
                found = True
                break
            time.sleep(0.1)
        text = log_path.read_text(encoding="utf-8")
        assert found, text[-2000:]
        assert SECRET not in text
        assert API_KEY not in text
        assert "token=***" in text
        assert "api_key=***" in text
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
