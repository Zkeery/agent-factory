"""第十五刀：compare-prd 至少返回 mock 分支。"""
from __future__ import annotations


def test_compare_prd_returns_mock(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.llm_api_key", "")
    r = client.post(
        "/api/v1/llm/compare-prd",
        json={"idea": "做一个老人用药提醒小应用", "decisions": []},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "variants" in data
    assert any(v["provider"] == "mock" for v in data["variants"])
    mock = next(v for v in data["variants"] if v["provider"] == "mock")
    assert mock["error"] is None
    assert mock["prd"] is not None
    # 无 Key 时不应强行出 deepseek 成功分支（可无、或带 error）
    deepseek = [v for v in data["variants"] if v["provider"] == "deepseek"]
    assert len(deepseek) == 0
