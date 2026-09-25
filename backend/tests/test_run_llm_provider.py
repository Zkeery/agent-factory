"""第十五刀：Run 级 llm_provider。"""
from __future__ import annotations


def test_create_run_with_mock_provider(client):
    r = client.post("/api/v1/runs", json={"idea": "做一个待办清单", "llm_provider": "mock"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["llm_provider"] == "mock"
    assert data.get("llm_model") in ("mock", "")


def test_create_run_deepseek_without_key_rejected(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.llm_api_key", "")
    r = client.post("/api/v1/runs", json={"idea": "做一个待办清单", "llm_provider": "deepseek"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] in ("llm_key_missing", "llm_api_key_missing")


def test_create_run_invalid_provider(client):
    r = client.post("/api/v1/runs", json={"idea": "做一个待办清单", "llm_provider": "openai"})
    assert r.status_code == 400
