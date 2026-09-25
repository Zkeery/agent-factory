"""第十五刀：LLM profiles 不回显 Key。"""
from __future__ import annotations


def test_profiles_include_mock_and_hide_key(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.llm_api_key", "")
    monkeypatch.setattr("app.core.config.settings.llm_provider", "mock")
    r = client.get("/api/v1/llm/profiles")
    assert r.status_code == 200
    data = r.json()
    body = r.text.lower()
    assert "sk-" not in body
    assert "api_key" not in body
    ids = {p["id"] for p in data["profiles"]}
    assert "mock" in ids
    assert "deepseek" in ids
    deepseek = next(p for p in data["profiles"] if p["id"] == "deepseek")
    assert deepseek["available"] is False


def test_profiles_deepseek_available_with_key(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.llm_api_key", "test-key-not-real")
    monkeypatch.setattr("app.core.config.settings.llm_provider", "deepseek")
    monkeypatch.setattr("app.core.config.settings.llm_model", "deepseek-chat")
    r = client.get("/api/v1/llm/profiles")
    assert r.status_code == 200
    data = r.json()
    assert data["default_provider"] == "deepseek"
    deepseek = next(p for p in data["profiles"] if p["id"] == "deepseek")
    assert deepseek["available"] is True
    assert deepseek["model"] == "deepseek-chat"
    assert "test-key-not-real" not in r.text
